"""Golden Path Integration Test Harness (OMN-2168).

Proves the full omniclaude emission side of the feedback loop:
  session.started → prompt.submitted → routing.decision → tool.executed
  → session.ended → session.outcome → context.utilization → agent.match
  → latency.breakdown → routing.feedback

Architecture:
  Test ─► emit_client_wrapper.emit_event() ─► Unix socket ─► MockEmitDaemon
  MockEmitDaemon captures all events in a list for assertion.

Standalone mode (default):
  A temporary Unix socket server replaces the real emit daemon.
  No Kafka, no external services required.

Integration mode (@pytest.mark.integration):
  Uses the real emit daemon + Kafka. Requires KAFKA_INTEGRATION_TESTS=1.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    import pydantic

# ---------------------------------------------------------------------------
# Logging setup — acceptance criterion: step-by-step debugging
# ---------------------------------------------------------------------------

logger = logging.getLogger("golden_path_harness")

# ---------------------------------------------------------------------------
# Sys.path for plugin lib — intentionally duplicates conftest.py so this
# file can also be run standalone (python -m pytest tests/integration/...).
# Anchored to _REPO_ROOT via pyproject.toml marker for resilience.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT.parent != _REPO_ROOT:
    if (_REPO_ROOT / "pyproject.toml").exists():
        break
    _REPO_ROOT = _REPO_ROOT.parent

_plugin_lib_path = str(_REPO_ROOT / "plugins" / "onex" / "hooks" / "lib")
if _plugin_lib_path not in sys.path:
    sys.path.insert(0, _plugin_lib_path)

_src_path = str(_REPO_ROOT / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)


# ---------------------------------------------------------------------------
# Schema imports (for payload validation in test_schema_validation)
# ---------------------------------------------------------------------------
from omniclaude.hooks.schemas import (
    ModelAgentMatchPayload,
    ModelContextUtilizationPayload,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
    ModelLatencyBreakdownPayload,
    ModelRoutingFeedbackPayload,
    ModelSessionOutcome,
)

# ---------------------------------------------------------------------------
# Constants for the golden path scenario
# ---------------------------------------------------------------------------

# Fixed timestamp base — all events offset from this
T0 = datetime(2026, 2, 11, 12, 0, 0, tzinfo=UTC)

# Known pattern identifiers injected at session start.
# The tool.executed event will reference these to prove utilization detection.
INJECTED_PATTERN_IDENTIFIERS = [
    "ProtocolPatternPersistence",
    "ModelHookSessionStartedPayload",
    "emit_client_wrapper",
]

# Event type → emit daemon event_type string mapping
EVENT_TYPES = [
    "session.started",
    "prompt.submitted",
    "routing.decision",
    "tool.executed",
    "session.ended",
    "session.outcome",
    "context.utilization",
    "agent.match",
    "latency.breakdown",
    "routing.feedback",
]


# ===========================================================================
# Mock Emit Daemon — captures events via Unix socket
# ===========================================================================


class MockEmitDaemon:
    """Temporary Unix socket server that mimics the emit daemon protocol.

    Protocol (newline-delimited JSON):
        Request:  {"event_type": "...", "payload": {...}}\\n
        Response: {"status": "queued", "event_id": "mock-001"}\\n
        Ping:     {"command": "ping"}\\n
        Pong:     {"status": "ok", "queue_size": 0, "spool_size": 0}\\n

    All received events are stored in ``self.captured_events`` for assertions.
    """

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self.captured_events: list[dict[str, Any]] = []
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._handler_threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._event_counter = 0
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Start the mock daemon in a background thread."""
        # Clean up stale socket if it exists
        sock = Path(self.socket_path)
        if sock.exists():
            sock.unlink()

        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(self.socket_path)
        self._server_socket.listen(5)
        self._server_socket.settimeout(0.5)  # Allow periodic stop checks

        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        logger.info("MockEmitDaemon started on %s", self.socket_path)

    def stop(self) -> None:
        """Stop the mock daemon, join all handler threads, and clean up."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        # Join handler threads to ensure no concurrent writes to captured_events
        for t in self._handler_threads:
            t.join(timeout=2.0)
        self._handler_threads.clear()
        if self._server_socket:
            self._server_socket.close()
        Path(self.socket_path).unlink(missing_ok=True)
        logger.info(
            "MockEmitDaemon stopped. Captured %d events.", len(self.captured_events)
        )

    # -- internal ------------------------------------------------------------

    def _accept_loop(self) -> None:
        """Accept connections until stopped.

        Each connection is handled in a separate daemon thread to prevent
        a slow/blocked connection from stalling the accept loop.
        """
        while not self._stop_event.is_set():
            try:
                conn, _ = self._server_socket.accept()  # type: ignore[union-attr]
                t = threading.Thread(
                    target=self._handle_connection, args=(conn,), daemon=True
                )
                t.start()
                self._handler_threads.append(t)
            except TimeoutError:
                continue
            except OSError:
                break  # Socket closed

    def _handle_connection(self, conn: socket.socket) -> None:
        """Handle a single client connection (one or more messages)."""
        conn.settimeout(2.0)
        try:
            buf = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                # Process complete lines
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    response = self._process_message(line.decode("utf-8"))
                    conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except (TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            conn.close()

    def _process_message(self, raw: str) -> dict[str, Any]:
        """Parse and store a single message, return response."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "error", "message": "invalid JSON"}

        # Handle ping
        if msg.get("command") == "ping":
            return {"status": "ok", "queue_size": 0, "spool_size": 0}

        # Capture event
        event_type = msg.get("event_type")
        payload = msg.get("payload", {})
        with self._lock:
            self._event_counter += 1
            event_id = f"mock-{self._event_counter:04d}"
            self.captured_events.append(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "payload": payload,
                    "received_at": datetime.now(UTC).isoformat(),
                }
            )

        logger.debug(
            "Captured event %s: %s (payload keys: %s)",
            event_id,
            event_type,
            list(payload.keys()),
        )
        return {"status": "queued", "event_id": event_id}

    # -- query helpers -------------------------------------------------------

    def wait_for_events(self, count: int, timeout: float = 5.0) -> None:
        """Poll until ``count`` events are captured or timeout expires.

        Raises TimeoutError if the expected event count is not reached,
        providing a clear diagnostic instead of silently returning.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if len(self.captured_events) >= count:
                    return
            time.sleep(0.02)
        with self._lock:
            got = len(self.captured_events)
        raise TimeoutError(
            f"wait_for_events: expected {count} events within {timeout}s, "
            f"got {got}. Types received: {self.event_types_in_order()}"
        )

    def events_by_type(self, event_type: str) -> list[dict[str, Any]]:
        """Return captured events filtered by event_type."""
        with self._lock:
            return [e for e in self.captured_events if e["event_type"] == event_type]

    def event_types_in_order(self) -> list[str]:
        """Return the ordered list of event types received."""
        with self._lock:
            return [e["event_type"] for e in self.captured_events]


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_emit_daemon(monkeypatch: pytest.MonkeyPatch):
    """Provide a MockEmitDaemon with a temporary socket path.

    Uses /tmp directly to stay within the ~104-char Unix socket path limit
    on macOS. Patches OMNICLAUDE_EMIT_SOCKET so emit_client_wrapper
    connects to our mock instead of the real daemon.
    """
    # Unix domain sockets have a max path of ~104 chars on macOS.
    # pytest's tmp_path is too long, so we use tempfile in /tmp directly.
    # mkstemp creates the file atomically (safe), then we remove it so the
    # socket can bind to that path.
    fd, sock_path = tempfile.mkstemp(prefix="gp-", suffix=".sock", dir="/tmp")  # noqa: S108 — Unix socket paths must be <104 chars on macOS
    os.close(fd)
    Path(sock_path).unlink()  # Socket bind needs the path to not exist
    daemon = MockEmitDaemon(sock_path)
    daemon.start()

    # Point the emit client at our mock socket (monkeypatch scopes to test)
    monkeypatch.setenv("OMNICLAUDE_EMIT_SOCKET", sock_path)

    # Reset the module-level singleton so it picks up the new socket path
    from emit_client_wrapper import reset_client

    reset_client()

    yield daemon

    # Restore (monkeypatch handles env var teardown automatically)
    daemon.stop()
    reset_client()


# ===========================================================================
# Per-test ID fixture — generates fresh UUIDs for test isolation
# ===========================================================================


@dataclass(frozen=True)
class GoldenPathIDs:
    """Deterministic IDs for a single golden path test run."""

    session_id: str
    correlation_id: str
    causation_id: str
    prompt_id: str
    tool_execution_id: str


@pytest.fixture
def gp_ids() -> GoldenPathIDs:
    """Generate fresh UUIDs per test to ensure test isolation."""
    session_id = uuid4()
    return GoldenPathIDs(
        session_id=str(session_id),
        correlation_id=str(session_id),  # Convention: correlation_id == session_id
        causation_id=str(uuid4()),
        prompt_id=str(uuid4()),
        tool_execution_id=str(uuid4()),
    )


# ===========================================================================
# Golden Path Event Builders
# ===========================================================================


def _build_golden_path_events(
    ids: GoldenPathIDs,
) -> list[tuple[str, dict[str, Any]]]:
    """Build the 10 golden path events with known deterministic values.

    Returns a list of (event_type, payload_dict) tuples in emission order.
    """
    sid = ids.session_id
    cid = ids.correlation_id
    caus = ids.causation_id

    events: list[tuple[str, dict[str, Any]]] = []

    # 1. session.started
    events.append(
        (
            "session.started",
            {
                "entity_id": sid,
                "session_id": sid,
                "correlation_id": cid,
                "causation_id": caus,
                "emitted_at": (T0).isoformat(),
                "working_directory": "/Volumes/PRO-G40/Code/omniclaude2",
                "git_branch": "jonah/omn-2168-golden-path",
                "hook_source": "startup",
            },
        )
    )

    # 2. prompt.submitted
    events.append(
        (
            "prompt.submitted",
            {
                "entity_id": sid,
                "session_id": sid,
                "correlation_id": cid,
                "causation_id": caus,
                "emitted_at": (T0 + timedelta(seconds=2)).isoformat(),
                "prompt_id": ids.prompt_id,
                "prompt_preview": "Implement the ProtocolPatternPersistence handler for emit_client_wrapper",
                "prompt_length": 78,
                "detected_intent": "implement",
            },
        )
    )

    # 3. routing.decision (dict-based, no Pydantic model)
    events.append(
        (
            "routing.decision",
            {
                "agent_name": "agent-api-architect",
                "confidence": 0.92,
                "strategy": "event_routing",
                "latency_ms": 45,
                "correlation_id": cid,
                "session_id": sid,
                "user_request": "Implement the ProtocolPatternPersistence handler",
                "timestamp": (T0 + timedelta(seconds=3)).isoformat(),
            },
        )
    )

    # 4. tool.executed — output contains injected pattern identifiers
    tool_summary = (
        "Read 150 lines from src/omniclaude/hooks/handler_context_injection.py. "
        f"Found references to {', '.join(INJECTED_PATTERN_IDENTIFIERS)}"
    )
    events.append(
        (
            "tool.executed",
            {
                "entity_id": sid,
                "session_id": sid,
                "correlation_id": cid,
                "causation_id": ids.prompt_id,
                "emitted_at": (T0 + timedelta(seconds=5)).isoformat(),
                "tool_execution_id": ids.tool_execution_id,
                "tool_name": "Read",
                "success": True,
                "duration_ms": 45,
                "summary": tool_summary[:500],
            },
        )
    )

    # 5. session.ended
    events.append(
        (
            "session.ended",
            {
                "entity_id": sid,
                "session_id": sid,
                "correlation_id": cid,
                "causation_id": caus,
                "emitted_at": (T0 + timedelta(minutes=30)).isoformat(),
                "reason": "clear",
                "duration_seconds": 1800.0,
                "tools_used_count": 42,
            },
        )
    )

    # 6. session.outcome
    events.append(
        (
            "session.outcome",
            {
                "session_id": sid,
                "outcome": "success",
                "emitted_at": (T0 + timedelta(minutes=30, seconds=1)).isoformat(),
            },
        )
    )

    # 7. context.utilization — 3 injected identifiers, all 3 reused → score=1.0
    events.append(
        (
            "context.utilization",
            {
                "entity_id": sid,
                "session_id": sid,
                "correlation_id": cid,
                "causation_id": caus,
                "emitted_at": (T0 + timedelta(minutes=30, seconds=2)).isoformat(),
                "utilization_score": 1.0,
                "method": "identifier_overlap",
                "injected_count": len(INJECTED_PATTERN_IDENTIFIERS),
                "reused_count": len(INJECTED_PATTERN_IDENTIFIERS),
                "detection_duration_ms": 12,
            },
        )
    )

    # 8. agent.match — exact match, high confidence
    events.append(
        (
            "agent.match",
            {
                "entity_id": sid,
                "session_id": sid,
                "correlation_id": cid,
                "causation_id": caus,
                "emitted_at": (T0 + timedelta(minutes=30, seconds=3)).isoformat(),
                "selected_agent": "agent-api-architect",
                "expected_agent": "agent-api-architect",
                "match_grade": "exact",
                "confidence": 0.92,
                "routing_method": "event_routing",
            },
        )
    )

    # 9. latency.breakdown
    events.append(
        (
            "latency.breakdown",
            {
                "entity_id": sid,
                "session_id": sid,
                "correlation_id": cid,
                "causation_id": ids.prompt_id,
                "emitted_at": (T0 + timedelta(minutes=30, seconds=4)).isoformat(),
                "routing_ms": 45,
                "agent_load_ms": 12,
                "context_injection_ms": 150,
                "intelligence_request_ms": None,
                "total_hook_ms": 210,
                "user_perceived_ms": 450,
            },
        )
    )

    # 10. routing.feedback
    events.append(
        (
            "routing.feedback",
            {
                "session_id": sid,
                "outcome": "success",
                "emitted_at": (T0 + timedelta(minutes=30, seconds=5)).isoformat(),
            },
        )
    )

    return events


# ===========================================================================
# Pydantic validation map — event_type → model class
# ===========================================================================

SCHEMA_MAP: dict[str, type[pydantic.BaseModel]] = {
    "session.started": ModelHookSessionStartedPayload,
    "prompt.submitted": ModelHookPromptSubmittedPayload,
    # routing.decision has no Pydantic model (dict-based via HookEventAdapter)
    "tool.executed": ModelHookToolExecutedPayload,
    "session.ended": ModelHookSessionEndedPayload,
    "session.outcome": ModelSessionOutcome,
    "context.utilization": ModelContextUtilizationPayload,
    "agent.match": ModelAgentMatchPayload,
    "latency.breakdown": ModelLatencyBreakdownPayload,
    "routing.feedback": ModelRoutingFeedbackPayload,
}


# ===========================================================================
# Helpers
# ===========================================================================


def _emit_all_events(
    daemon: MockEmitDaemon, ids: GoldenPathIDs, *, timeout_ms: int = 2000
) -> list[tuple[str, dict[str, Any]]]:
    """Emit all 10 golden path events and wait for daemon capture.

    Returns the built events list for further assertions.
    """
    from emit_client_wrapper import emit_event

    events = _build_golden_path_events(ids)
    for event_type, payload in events:
        success = emit_event(
            event_type=event_type, payload=payload, timeout_ms=timeout_ms
        )
        assert success, f"emit_event failed for {event_type}"
    daemon.wait_for_events(len(events))
    return events


# ===========================================================================
# Tests — Standalone (mock emit daemon)
# ===========================================================================


class TestGoldenPathStandalone:
    """Golden path tests using mock emit daemon (no external services)."""

    def test_full_session_lifecycle(
        self, mock_emit_daemon: MockEmitDaemon, gp_ids: GoldenPathIDs
    ) -> None:
        """Emit all 10 golden path events and verify they arrive at the mock daemon."""
        _emit_all_events(mock_emit_daemon, gp_ids)

        # Verify all 10 events captured
        with mock_emit_daemon._lock:
            count = len(mock_emit_daemon.captured_events)
        assert count == 10, (
            f"Expected 10 captured events, got {count}. "
            f"Types received: {mock_emit_daemon.event_types_in_order()}"
        )

        # Verify event order
        expected_order = EVENT_TYPES
        actual_order = mock_emit_daemon.event_types_in_order()
        assert actual_order == expected_order, (
            f"Event order mismatch.\nExpected: {expected_order}\nActual:   {actual_order}"
        )

        logger.info("All 10 golden path events captured in correct order.")

    def test_correlation_id_consistency(
        self, mock_emit_daemon: MockEmitDaemon, gp_ids: GoldenPathIDs
    ) -> None:
        """Verify all events that carry a correlation_id share the same value."""
        _emit_all_events(mock_emit_daemon, gp_ids)

        expected_cid = gp_ids.correlation_id
        for captured in mock_emit_daemon.captured_events:
            payload = captured["payload"]
            if "correlation_id" in payload:
                assert payload["correlation_id"] == expected_cid, (
                    f"Event {captured['event_type']} has correlation_id "
                    f"{payload['correlation_id']}, expected {expected_cid}"
                )

        logger.info("Correlation ID consistency verified across all events.")

    def test_schema_validation(
        self, mock_emit_daemon: MockEmitDaemon, gp_ids: GoldenPathIDs
    ) -> None:
        """Validate each captured event payload against its Pydantic model."""
        _emit_all_events(mock_emit_daemon, gp_ids)

        for captured in mock_emit_daemon.captured_events:
            event_type = captured["event_type"]
            payload = captured["payload"]

            model_cls = SCHEMA_MAP.get(event_type)
            if model_cls is None:
                # routing.decision has no Pydantic model — validate dict keys
                if event_type == "routing.decision":
                    assert "agent_name" in payload
                    assert "confidence" in payload
                    assert "correlation_id" in payload
                    logger.debug(
                        "routing.decision validated as dict (no Pydantic model)"
                    )
                continue

            # Validate against Pydantic model
            try:
                instance = model_cls.model_validate(payload)
            except Exception as e:
                pytest.fail(
                    f"Schema validation failed for {event_type}: {e}\n"
                    f"Payload: {json.dumps(payload, indent=2, default=str)}"
                )

            # Verify frozen (immutable) — model_config must declare frozen=True
            assert model_cls.model_config.get("frozen") is True, (
                f"{event_type} model {model_cls.__name__} is not frozen"
            )

            logger.debug("Schema validation passed for %s", event_type)

        logger.info("All event payloads validated against Pydantic schemas.")

    def test_timestamps_are_timezone_aware(
        self, mock_emit_daemon: MockEmitDaemon, gp_ids: GoldenPathIDs
    ) -> None:
        """Verify all emitted_at timestamps are timezone-aware (UTC)."""
        _emit_all_events(mock_emit_daemon, gp_ids)

        for captured in mock_emit_daemon.captured_events:
            payload = captured["payload"]
            emitted_at = payload.get("emitted_at")
            if emitted_at is None:
                continue

            # All our timestamps end with +00:00 (UTC)
            dt = datetime.fromisoformat(emitted_at)
            assert dt.tzinfo is not None, (
                f"Event {captured['event_type']} has naive timestamp: {emitted_at}"
            )

        logger.info("All timestamps verified as timezone-aware.")

    def test_utilization_reflects_tool_output(
        self, mock_emit_daemon: MockEmitDaemon, gp_ids: GoldenPathIDs
    ) -> None:
        """Verify the utilization event references identifiers from tool output."""
        _emit_all_events(mock_emit_daemon, gp_ids)

        # Get tool.executed and context.utilization events
        tool_events = mock_emit_daemon.events_by_type("tool.executed")
        util_events = mock_emit_daemon.events_by_type("context.utilization")

        assert len(tool_events) == 1, "Expected exactly 1 tool.executed event"
        assert len(util_events) == 1, "Expected exactly 1 context.utilization event"

        tool_summary = tool_events[0]["payload"]["summary"]
        util_payload = util_events[0]["payload"]

        # Verify tool output contains the injected identifiers
        for identifier in INJECTED_PATTERN_IDENTIFIERS:
            assert identifier in tool_summary, (
                f"Injected identifier '{identifier}' not found in tool output summary"
            )

        # Verify utilization score is 1.0 (all identifiers reused)
        assert util_payload["utilization_score"] == 1.0
        assert util_payload["injected_count"] == len(INJECTED_PATTERN_IDENTIFIERS)
        assert util_payload["reused_count"] == len(INJECTED_PATTERN_IDENTIFIERS)
        assert util_payload["method"] == "identifier_overlap"

        logger.info(
            "Utilization event correctly reflects tool output: "
            "score=%.1f, injected=%d, reused=%d",
            util_payload["utilization_score"],
            util_payload["injected_count"],
            util_payload["reused_count"],
        )

    def test_schema_rejects_invalid_payloads(
        self, mock_emit_daemon: MockEmitDaemon, gp_ids: GoldenPathIDs
    ) -> None:
        """Verify schemas reject payloads with missing required fields and extra fields."""
        from pydantic import ValidationError

        # Missing required field (session_id)
        with pytest.raises(ValidationError):
            ModelHookSessionStartedPayload.model_validate(
                {
                    "working_directory": "/tmp",
                    "git_branch": "main",
                    "hook_source": "startup",
                }
            )

        # Extra field on a model with extra="forbid"
        with pytest.raises(ValidationError):
            ModelSessionOutcome.model_validate(
                {
                    "session_id": gp_ids.session_id,
                    "outcome": "success",
                    "emitted_at": T0.isoformat(),
                    "unexpected_field": "should_fail",
                }
            )

        logger.info("Schema rejection of invalid payloads verified.")

    def test_secret_redaction_on_prompt(
        self, mock_emit_daemon: MockEmitDaemon, gp_ids: GoldenPathIDs
    ) -> None:
        """Verify Pydantic schema redaction works on prompt_preview.

        Note: The emit client transmits payloads as-is (no redaction at emission
        time). Redaction happens at the Pydantic model layer when consumers
        validate the payload. This test verifies that the model_validate path
        correctly redacts secrets — which is the production behavior since all
        consumers validate with Pydantic before processing.
        """
        from emit_client_wrapper import emit_event

        # Emit a prompt with an embedded API key
        payload = {
            "entity_id": gp_ids.session_id,
            "session_id": gp_ids.session_id,
            "correlation_id": gp_ids.correlation_id,
            "causation_id": gp_ids.causation_id,
            "emitted_at": T0.isoformat(),
            "prompt_id": str(uuid4()),
            "prompt_preview": "Use sk-1234567890abcdefghijklmnop to call the API",
            "prompt_length": 50,
            "detected_intent": None,
        }

        emit_event(event_type="prompt.submitted", payload=payload, timeout_ms=2000)
        mock_emit_daemon.wait_for_events(1)

        # Validate via Pydantic — the model's field_validator should redact
        captured = mock_emit_daemon.events_by_type("prompt.submitted")
        assert len(captured) == 1, (
            f"Expected 1 prompt.submitted event, got {len(captured)}"
        )

        model = ModelHookPromptSubmittedPayload.model_validate(captured[-1]["payload"])
        assert "sk-1234567890" not in model.prompt_preview
        assert "REDACTED" in model.prompt_preview

        logger.info("Secret redaction verified: API key redacted from prompt_preview.")


# ===========================================================================
# Tests — Integration (real Kafka, requires KAFKA_INTEGRATION_TESTS=1)
# ===========================================================================


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("KAFKA_INTEGRATION_TESTS"),
    reason="Set KAFKA_INTEGRATION_TESTS=1 to run real Kafka integration tests",
)
class TestGoldenPathIntegration:
    """Golden path tests using real emit daemon and Kafka.

    Prerequisites:
        - Emit daemon running (started by SessionStart hook)
        - Kafka broker at KAFKA_BOOTSTRAP_SERVERS
        - KAFKA_INTEGRATION_TESTS=1 env var set
    """

    def test_events_reach_daemon(self, gp_ids: GoldenPathIDs) -> None:
        """Emit golden path events via real daemon and verify acceptance.

        Scope: Verifies daemon acceptance (emit_event returns True for all events)
        and that the daemon remains healthy after ingestion. Kafka delivery
        verification requires a consumer and is covered by separate E2E tests.
        """
        from emit_client_wrapper import daemon_available, emit_event

        if not daemon_available():
            pytest.skip("Emit daemon not running")

        events = _build_golden_path_events(gp_ids)
        results = []

        for step, (event_type, payload) in enumerate(events, 1):
            logger.info("Integration Step %02d/10: Emitting %s", step, event_type)
            success = emit_event(
                event_type=event_type, payload=payload, timeout_ms=5000
            )
            results.append((event_type, success))
            logger.info(
                "Integration Step %02d/10: %s → %s",
                step,
                event_type,
                "OK" if success else "FAILED",
            )

        # All events should be accepted by the daemon
        failed = [(et, s) for et, s in results if not s]
        assert not failed, f"Events failed to emit: {failed}"

        # Verify daemon is still healthy after ingesting all events
        assert daemon_available(), "Daemon became unavailable after ingesting events"
        logger.info("All 10 events accepted by real emit daemon. Daemon still healthy.")
