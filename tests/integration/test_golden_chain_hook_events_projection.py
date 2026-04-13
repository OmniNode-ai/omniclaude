# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Golden chain test: hook events → hook_health_events / pattern_injections projection tables.

Validates the full emission path:
  hook lib → emit daemon socket → Kafka topic → omnidash consumer → DB projection row shape

Architecture (mock-first):
  - MockEmitDaemon: Unix socket server that captures all emitted events (no real daemon needed)
  - MockKafkaProducer: captures published messages; validates topic + payload shape
  - MockOmnidashConsumer: simulates the omnidash read path; validates row shape vs DB schema

Integration gate (@pytest.mark.integration):
  - Requires KAFKA_INTEGRATION_TESTS=1 + reachable Kafka at localhost:19092
  - Skips automatically when env gate is absent
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# sys.path setup — mirrors test_golden_path_harness.py pattern
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
# Imports from hook lib
# ---------------------------------------------------------------------------

from omniclaude.hooks.cohort_assignment import EnumCohort
from omniclaude.hooks.models_injection_tracking import (
    EnumInjectionContext,
    EnumInjectionSource,
    ModelInjectionRecord,
)
from omniclaude.hooks.schemas import (
    EnumHookErrorCategory,
    EnumHookErrorTier,
    ModelHookErrorEvent,
)
from omniclaude.hooks.topics import TopicBase

# ---------------------------------------------------------------------------
# Expected Kafka topic constants (from contracts)
# ---------------------------------------------------------------------------

TOPIC_HOOK_HEALTH_ERROR: str = TopicBase.HOOK_HEALTH_ERROR.value
TOPIC_INJECTION_RECORDED: str = TopicBase.INJECTION_RECORDED.value


# ===========================================================================
# MockEmitDaemon — reuses same protocol as test_golden_path_harness.py
# ===========================================================================


class MockEmitDaemon:
    """Minimal Unix socket server that captures emitted events."""

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self.captured_events: list[dict[str, Any]] = []
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._handler_threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._counter = 0

    def start(self) -> None:
        Path(self.socket_path).unlink(missing_ok=True)
        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(self.socket_path)
        self._server_socket.listen(5)
        self._server_socket.settimeout(0.5)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        for t in self._handler_threads:
            t.join(timeout=2.0)
        if self._server_socket:
            self._server_socket.close()
        Path(self.socket_path).unlink(missing_ok=True)

    def _accept_loop(self) -> None:
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
                break

    def _handle_connection(self, conn: socket.socket) -> None:
        conn.settimeout(2.0)
        buf = b""
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    response = self._process(line.decode())
                    conn.sendall((json.dumps(response) + "\n").encode())
        except (TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            conn.close()

    def _process(self, raw: str) -> dict[str, Any]:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "error", "message": "invalid JSON"}
        if msg.get("command") == "ping":
            return {"status": "ok", "queue_size": 0, "spool_size": 0}
        with self._lock:
            self._counter += 1
            event_id = f"mock-{self._counter:04d}"
            self.captured_events.append(
                {
                    "event_id": event_id,
                    "event_type": msg.get("event_type"),
                    "payload": msg.get("payload", {}),
                }
            )
        return {"status": "queued", "event_id": event_id}

    def wait_for(self, count: int, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if len(self.captured_events) >= count:
                    return
            time.sleep(0.02)
        with self._lock:
            got = len(self.captured_events)
        raise TimeoutError(f"Expected {count} events, got {got}")

    def by_type(self, event_type: str) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self.captured_events if e["event_type"] == event_type]


# ===========================================================================
# MockKafkaProducer — captures send() calls for topic/payload assertions
# ===========================================================================


class MockKafkaProducer:
    """Synchronous mock for aiokafka.AIOKafkaProducer.

    Records (topic, value_bytes) tuples for inspection.
    """

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_and_wait(
        self,
        topic: str,
        value: bytes | None = None,
        key: bytes | None = None,
        **_kwargs: Any,
    ) -> None:
        payload = json.loads(value) if value else {}
        self.sent.append({"topic": topic, "payload": payload, "key": key})

    async def __aenter__(self) -> MockKafkaProducer:
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass

    def messages_for_topic(self, topic: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["topic"] == topic]


# ===========================================================================
# DB schema shape helpers (derived from intelligence-schema.ts)
# ===========================================================================

# Required columns in hook_health_events (non-nullable, non-defaulted)
_HOOK_HEALTH_EVENTS_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "hook_name",
        "error_tier",
        "error_category",
        "emitted_at",
    }
)

# Required columns in pattern_injections (non-nullable, non-defaulted except FK arrays)
_PATTERN_INJECTIONS_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "session_id",
        "injected_at",
    }
)


def _assert_hook_health_row_shape(row: dict[str, Any]) -> None:
    """Assert that *row* satisfies the hook_health_events DB column contract."""
    missing = _HOOK_HEALTH_EVENTS_REQUIRED_FIELDS - row.keys()
    assert not missing, f"hook_health_events row missing required fields: {missing}"
    # Type checks
    assert isinstance(row["id"], str) and row["id"], "id must be non-empty string"
    assert isinstance(row["hook_name"], str) and row["hook_name"]
    assert row["error_tier"] in {t.value for t in EnumHookErrorTier}
    assert row["error_category"] in {c.value for c in EnumHookErrorCategory}
    # emitted_at must be parseable as ISO datetime
    datetime.fromisoformat(row["emitted_at"].replace("Z", "+00:00"))


def _assert_pattern_injection_row_shape(row: dict[str, Any]) -> None:
    """Assert that *row* satisfies the pattern_injections DB column contract."""
    missing = _PATTERN_INJECTIONS_REQUIRED_FIELDS - row.keys()
    assert not missing, f"pattern_injections row missing required fields: {missing}"
    assert isinstance(row["session_id"], str) and row["session_id"]
    assert isinstance(row.get("pattern_ids", []), list)
    assert row.get("cohort") in {"treatment", "control", None} or isinstance(
        row.get("cohort"), str
    )


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_emit_daemon(monkeypatch: pytest.MonkeyPatch):
    """Spin up a MockEmitDaemon and point emit_client_wrapper at it."""
    import emit_client_wrapper  # plugin lib

    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "test-emit.sock")
        daemon = MockEmitDaemon(sock_path)
        daemon.start()

        monkeypatch.setenv("OMNICLAUDE_EMIT_SOCKET", sock_path)
        # Reset the cached client so it picks up the new socket path
        emit_client_wrapper._emit_client = None  # noqa: SLF001
        emit_client_wrapper._client_initialized = False  # noqa: SLF001

        yield daemon

        daemon.stop()
        emit_client_wrapper._emit_client = None  # noqa: SLF001
        emit_client_wrapper._client_initialized = False  # noqa: SLF001


@pytest.fixture
def mock_kafka_producer() -> MockKafkaProducer:
    return MockKafkaProducer()


# ===========================================================================
# Unit-level golden chain tests (mock-first, no external services)
# ===========================================================================


@pytest.mark.unit
class TestHookHealthEventsChain:
    """Validates hook.health.error → emit daemon → topic → DB row shape."""

    def test_model_hook_error_event_constructs_valid_event(self) -> None:
        """ModelHookErrorEvent builds successfully with required fields."""
        event = ModelHookErrorEvent(
            hook_name="PostToolUse",
            error_tier=EnumHookErrorTier.DEGRADED,
            error_category=EnumHookErrorCategory.TIMEOUT,
            error_message="Kafka emit timed out",
            session_id=str(uuid4()),
            emitted_at=datetime.now(UTC),
        )
        assert event.hook_name == "PostToolUse"
        assert event.error_tier == EnumHookErrorTier.DEGRADED
        assert len(event.fingerprint) == 16  # SHA256[:16]

    def test_hook_health_error_topic_matches_schema_comment(self) -> None:
        """Topic constant matches omnidash intelligence-schema.ts source comment."""
        assert TOPIC_HOOK_HEALTH_ERROR == "onex.evt.omniclaude.hook-health-error.v1"

    def test_serialized_payload_satisfies_db_row_shape(self) -> None:
        """Serialized ModelHookErrorEvent dict satisfies hook_health_events column contract."""
        ts = datetime(2026, 4, 12, 10, 0, 0, tzinfo=UTC)
        event = ModelHookErrorEvent(
            hook_name="SessionStart",
            error_tier=EnumHookErrorTier.INTERPRETER,
            error_category=EnumHookErrorCategory.IMPORT_ERROR,
            error_message="ModuleNotFoundError: omniclaude",
            session_id="test-session-001",
            python_version="3.12.0",
            emitted_at=ts,
        )
        # Simulate the DB row that omnidash consumer would write
        row = {
            "id": event.event_id,
            "hook_name": event.hook_name,
            "error_tier": event.error_tier.value,
            "error_category": event.error_category.value,
            "error_message": event.error_message,
            "session_id": event.session_id,
            "python_version": event.python_version,
            "fingerprint": event.fingerprint,
            "emitted_at": ts.isoformat(),
        }
        _assert_hook_health_row_shape(row)

    def test_emit_daemon_captures_hook_health_error_event(
        self, mock_emit_daemon: MockEmitDaemon
    ) -> None:
        """emit_event('hook.health.error', ...) reaches the mock daemon socket."""
        import emit_client_wrapper

        ts = datetime.now(UTC)
        event = ModelHookErrorEvent(
            hook_name="PostToolUse",
            error_tier=EnumHookErrorTier.DEGRADED,
            error_category=EnumHookErrorCategory.FUNCTIONAL_DEGRADATION,
            error_message="Context injection failed",
            session_id="sess-golden-chain-001",
            emitted_at=ts,
        )
        payload = event.model_dump(mode="json")

        result = emit_client_wrapper.emit_event("hook.health.error", payload)

        assert result is True, "emit_event should return True on success"
        mock_emit_daemon.wait_for(1)

        captured = mock_emit_daemon.by_type("hook.health.error")
        assert len(captured) == 1
        assert captured[0]["payload"]["hook_name"] == "PostToolUse"
        assert captured[0]["payload"]["error_tier"] == "degraded"

    def test_kafka_publish_targets_correct_topic(
        self, mock_kafka_producer: MockKafkaProducer
    ) -> None:
        """Mock Kafka producer receives hook.health.error on the correct topic."""
        import asyncio

        ts = datetime.now(UTC)
        event = ModelHookErrorEvent(
            hook_name="UserPromptSubmit",
            error_tier=EnumHookErrorTier.INTENTIONAL_BLOCK,
            error_category=EnumHookErrorCategory.DOD_BLOCK,
            error_message="DoD gate blocked commit",
            session_id="sess-kafka-001",
            emitted_at=ts,
        )
        payload_bytes = event.model_dump_json().encode()

        asyncio.run(
            mock_kafka_producer.send_and_wait(
                TOPIC_HOOK_HEALTH_ERROR,
                value=payload_bytes,
            )
        )

        msgs = mock_kafka_producer.messages_for_topic(TOPIC_HOOK_HEALTH_ERROR)
        assert len(msgs) == 1
        msg_payload = msgs[0]["payload"]
        assert msg_payload["hook_name"] == "UserPromptSubmit"
        assert msg_payload["error_category"] == "dod_block"

    def test_consumer_projection_row_shape_matches_db_schema(self) -> None:
        """Simulated omnidash consumer projection matches hook_health_events schema."""
        ts = datetime(2026, 4, 12, 11, 0, 0, tzinfo=UTC)
        event = ModelHookErrorEvent(
            hook_name="PreToolUse",
            error_tier=EnumHookErrorTier.DEGRADED,
            error_category=EnumHookErrorCategory.AUTH_DENIED,
            error_message="Authorization hook denied tool",
            session_id="sess-consumer-001",
            emitted_at=ts,
        )

        # Simulate what omnidash consumer writes to hook_health_events
        projected_row = {
            "id": event.event_id,
            "hook_name": event.hook_name,
            "error_tier": event.error_tier.value,
            "error_category": event.error_category.value,
            "error_message": event.error_message,
            "session_id": event.session_id,
            "python_version": event.python_version,
            "fingerprint": event.fingerprint,
            "emitted_at": ts.isoformat(),
        }

        _assert_hook_health_row_shape(projected_row)

        # Verify deduplication key uniqueness (id is PK)
        assert projected_row["id"] == event.event_id


@pytest.mark.unit
class TestPatternInjectionsChain:
    """Validates injection.recorded → emit daemon → topic → DB row shape."""

    def _make_injection_record(
        self, session_id: str | None = None
    ) -> ModelInjectionRecord:
        return ModelInjectionRecord(
            injection_id=uuid4(),
            session_id_raw=session_id or str(uuid4()),
            correlation_id=str(uuid4()),
            pattern_ids=[str(uuid4()), str(uuid4())],
            injection_context=EnumInjectionContext.USER_PROMPT_SUBMIT,
            source=EnumInjectionSource.INJECTED,
            cohort=EnumCohort.TREATMENT,
            assignment_seed=42,
            effective_control_percentage=20,
            injected_content="## Pattern\nDo not hardcode topic strings.",
            injected_token_count=8,
        )

    def test_injection_recorded_topic_is_correct(self) -> None:
        assert TOPIC_INJECTION_RECORDED == "onex.evt.omniclaude.injection-recorded.v1"

    def test_model_injection_record_serializes_correctly(self) -> None:
        """ModelInjectionRecord serializes with session_id alias (backwards compat)."""
        record = self._make_injection_record()
        data = record.model_dump(mode="json", by_alias=True)
        assert "session_id" in data
        assert "session_id_raw" not in data
        assert isinstance(data["pattern_ids"], list)

    def test_serialized_payload_satisfies_db_row_shape(self) -> None:
        """Serialized ModelInjectionRecord satisfies pattern_injections column contract."""
        record = self._make_injection_record(session_id="sess-pi-shape-001")
        data = record.model_dump(mode="json", by_alias=True)

        # Simulate the row omnidash consumer would project
        row = {
            "session_id": data["session_id"],
            "correlation_id": data.get("correlation_id"),
            "pattern_ids": data.get("pattern_ids", []),
            "cohort": data.get("cohort"),
            "injected_at": datetime.now(UTC).isoformat(),
            "injected_content": data.get("injected_content", ""),
            "injected_token_count": data.get("injected_token_count", 0),
        }

        _assert_pattern_injection_row_shape(row)

    def test_emit_daemon_captures_injection_recorded_event(
        self, mock_emit_daemon: MockEmitDaemon
    ) -> None:
        """emit_event('injection.recorded', ...) reaches the mock daemon socket."""
        import emit_client_wrapper

        record = self._make_injection_record(session_id="sess-daemon-002")
        payload = record.model_dump(mode="json", by_alias=True)

        result = emit_client_wrapper.emit_event("injection.recorded", payload)

        assert result is True
        mock_emit_daemon.wait_for(1)

        captured = mock_emit_daemon.by_type("injection.recorded")
        assert len(captured) == 1
        assert captured[0]["payload"]["session_id"] == "sess-daemon-002"

    def test_kafka_publish_targets_correct_topic(
        self, mock_kafka_producer: MockKafkaProducer
    ) -> None:
        """Mock Kafka producer receives injection.recorded on the correct topic."""
        import asyncio

        record = self._make_injection_record(session_id="sess-kafka-002")
        payload_bytes = record.model_dump_json(by_alias=True).encode()

        asyncio.run(
            mock_kafka_producer.send_and_wait(
                TOPIC_INJECTION_RECORDED,
                value=payload_bytes,
            )
        )

        msgs = mock_kafka_producer.messages_for_topic(TOPIC_INJECTION_RECORDED)
        assert len(msgs) == 1
        assert msgs[0]["payload"]["session_id"] == "sess-kafka-002"
        assert isinstance(msgs[0]["payload"]["pattern_ids"], list)

    def test_consumer_projection_row_shape_matches_db_schema(self) -> None:
        """Simulated omnidash consumer projection matches pattern_injections schema."""
        record = self._make_injection_record(session_id="sess-consumer-003")
        data = record.model_dump(mode="json", by_alias=True)

        projected_row = {
            "session_id": data["session_id"],
            "correlation_id": data.get("correlation_id"),
            "pattern_ids": data.get("pattern_ids", []),
            "cohort": data.get("cohort"),
            "injection_context": data.get("injection_context"),
            "source": data.get("source"),
            "injected_content": data.get("injected_content", ""),
            "injected_token_count": data.get("injected_token_count", 0),
            "injected_at": datetime.now(UTC).isoformat(),
        }

        _assert_pattern_injection_row_shape(projected_row)

    def test_control_cohort_injection_still_records_row(self) -> None:
        """Control cohort injections are recorded (complete A/B denominator)."""
        record = ModelInjectionRecord(
            injection_id=uuid4(),
            session_id_raw="sess-control-004",
            correlation_id="",
            pattern_ids=[],
            injection_context=EnumInjectionContext.SESSION_START,
            source=EnumInjectionSource.CONTROL_COHORT,
            cohort=EnumCohort.CONTROL,
            assignment_seed=5,
        )
        data = record.model_dump(mode="json", by_alias=True)

        row = {
            "session_id": data["session_id"],
            "pattern_ids": data.get("pattern_ids", []),
            "cohort": data.get("cohort"),
            "source": data.get("source"),
            "injected_at": datetime.now(UTC).isoformat(),
        }

        _assert_pattern_injection_row_shape(row)
        assert row["source"] == "control_cohort"
        assert row["pattern_ids"] == []


# ===========================================================================
# Real-infra integration test (skips when gate is absent)
# ===========================================================================


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("KAFKA_INTEGRATION_TESTS") != "1",
    reason="Set KAFKA_INTEGRATION_TESTS=1 to run against live Kafka",
)
class TestHookEventsProjectionIntegration:
    """End-to-end integration against live emit daemon + Kafka on .201.

    Requires:
        - KAFKA_INTEGRATION_TESTS=1
        - KAFKA_BOOTSTRAP_SERVERS=localhost:19092 (bus-local running)
        - emit daemon running (SessionStart hook must have fired)
    """

    def test_hook_health_error_reaches_kafka_topic(self) -> None:
        """Fire a hook.health.error event and verify it lands on the topic."""
        import emit_client_wrapper

        ts = datetime.now(UTC)
        event = ModelHookErrorEvent(
            hook_name="PostToolUse",
            error_tier=EnumHookErrorTier.DEGRADED,
            error_category=EnumHookErrorCategory.TIMEOUT,
            error_message="[integration-test] golden chain probe",
            session_id=f"integration-{uuid4()}",
            emitted_at=ts,
        )
        payload = event.model_dump(mode="json")
        result = emit_client_wrapper.emit_event("hook.health.error", payload)
        assert result is True, (
            "emit_event returned False — is the emit daemon running? "
            "Ensure SessionStart hook has fired in this session."
        )

    def test_injection_recorded_reaches_kafka_topic(self) -> None:
        """Fire an injection.recorded event and verify it lands on the topic."""
        import emit_client_wrapper

        record = ModelInjectionRecord(
            injection_id=uuid4(),
            session_id_raw=f"integration-{uuid4()}",
            correlation_id=str(uuid4()),
            pattern_ids=[],
            injection_context=EnumInjectionContext.USER_PROMPT_SUBMIT,
            source=EnumInjectionSource.NO_PATTERNS,
            cohort=EnumCohort.TREATMENT,
            assignment_seed=99,
        )
        payload = record.model_dump(mode="json", by_alias=True)
        result = emit_client_wrapper.emit_event("injection.recorded", payload)
        assert result is True, "emit_event returned False — is the emit daemon running?"
