"""Metrics Emitter -- adapter layer for phase metrics emission.

Wraps ContractPhaseMetrics in ContractMeasurementEvent and emits via
the emit daemon. Also writes local file artifacts for crash recovery.

Architecture (three-layer separation):
    - SPI contracts (omnibase_spi): Produce ContractPhaseMetrics -- pure data, no I/O
    - Adapter layer (this module): Owns daemon integration -- wraps in
      ContractMeasurementEvent, calls emit_event(), writes file artifact
    - Emit daemon (omnibase_infra): Routes flat JSON to Kafka topic

Related Tickets:
    - OMN-2025: Metrics emission via emit daemon
    - OMN-2027: Phase instrumentation protocol

.. versionadded:: 0.2.1
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnibase_spi.contracts.measurement import (
        ContractMeasurementEvent,
        ContractPhaseMetrics,
    )

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum error message length after redaction (per M2 spec)
MAX_ERROR_MESSAGE_LENGTH = 100
MAX_ERROR_MESSAGES = 5

# Maximum failed test name length and count (per M2 spec)
MAX_FAILED_TEST_LENGTH = 100
MAX_FAILED_TESTS = 20

# Artifact base directory
ARTIFACT_BASE_DIR = Path.home() / ".claude" / "pipelines"

# Characters that must not appear in path components to prevent traversal
_INVALID_PATH_CHARS = ("..", "/", "\\", "\x00")


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------


def _get_redact_secrets() -> callable:  # type: ignore[valid-type]
    """Return the ``redact_secrets`` callable, with a safe fallback.

    If ``secret_redactor`` is unavailable, the fallback replaces all input
    with a placeholder to prevent leaking unredacted secrets to evt topics.
    """
    try:
        from plugins.onex.hooks.lib.secret_redactor import redact_secrets

        return redact_secrets
    except ImportError:
        logger.warning(
            "secret_redactor not available; stripping text to prevent "
            "unredacted secrets on evt topics"
        )

        def _fallback(text: str) -> str:
            return "[redacted - secret_redactor unavailable]"

        return _fallback


def _sanitize_error_messages(messages: list[str]) -> list[str]:
    """Sanitize error messages for evt topic emission.

    Applies secret redaction and length truncation per M2 spec:
    - redact_secrets() from secret_redactor.py
    - Truncate each message to 100 chars
    - Max 5 messages

    Args:
        messages: Raw error messages.

    Returns:
        Sanitized list of error messages.
    """
    redact = _get_redact_secrets()
    sanitized = []
    for msg in messages[:MAX_ERROR_MESSAGES]:
        clean = redact(msg)
        if len(clean) > MAX_ERROR_MESSAGE_LENGTH:
            clean = clean[: MAX_ERROR_MESSAGE_LENGTH - 3] + "..."
        sanitized.append(clean)
    return sanitized


def _sanitize_skip_reason(reason: str) -> str:
    """Sanitize a skip_reason string for evt topic emission.

    Applies secret redaction and length truncation, mirroring the
    treatment applied to error_messages.

    Args:
        reason: Raw skip reason string.

    Returns:
        Sanitized skip reason string.
    """
    redact = _get_redact_secrets()
    clean = redact(reason)
    if len(clean) > MAX_ERROR_MESSAGE_LENGTH:
        clean = clean[: MAX_ERROR_MESSAGE_LENGTH - 3] + "..."
    return clean


def _sanitize_failed_tests(tests: list[str]) -> list[str]:
    """Truncate failed test names per M2 spec.

    Args:
        tests: Failed test name list.

    Returns:
        Truncated list of test names.
    """
    sanitized = []
    for test in tests[:MAX_FAILED_TESTS]:
        if len(test) > MAX_FAILED_TEST_LENGTH:
            test = test[: MAX_FAILED_TEST_LENGTH - 3] + "..."
        sanitized.append(test)
    return sanitized


# Absolute path prefixes that leak machine identity and must be rejected.
_ABSOLUTE_PATH_PREFIXES = (
    "/Users/",
    "/home/",
    "/root/",
    "/var/",
    "/tmp/",  # noqa: S108
    "/opt/",
    "/etc/",
    "/srv/",
    "/Volumes/",
)

# Matches UNC paths like \\server\share anywhere in the string.
_UNC_PATH_RE = re.compile(r"\\\\[^\\]+")

# Matches Windows drive-letter paths like C:\, D:\, c:\, etc. anywhere in the string.
_WINDOWS_DRIVE_RE = re.compile(r"[A-Za-z]:\\")


def _validate_artifact_uri(uri: str) -> bool:
    """Validate artifact pointer URI does not contain absolute or local paths.

    Rejects file:// URIs, tilde paths, well-known absolute path prefixes, and
    Windows drive paths to prevent PII leakage on the broad-access evt topic.

    Args:
        uri: The artifact URI to validate.

    Returns:
        True if URI is safe for emission.
    """
    uri_lower = uri.lower()
    if uri_lower.startswith("file://") or uri.startswith("~"):
        logger.warning(
            f"Artifact URI contains local path scheme, rejecting: {uri[:50]}..."
        )
        return False
    if any(prefix.lower() in uri_lower for prefix in _ABSOLUTE_PATH_PREFIXES):
        logger.warning(f"Artifact URI contains absolute path, rejecting: {uri[:50]}...")
        return False
    if len(uri) > 0 and uri[0] == "/" and not uri.startswith("//"):
        logger.warning(f"Artifact URI contains absolute path, rejecting: {uri[:50]}...")
        return False
    if _WINDOWS_DRIVE_RE.search(uri):
        logger.warning(
            f"Artifact URI contains Windows drive path, rejecting: {uri[:50]}..."
        )
        return False
    if _UNC_PATH_RE.search(uri):
        logger.warning(f"Artifact URI contains UNC path, rejecting: {uri[:50]}...")
        return False
    return True


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------


def _build_measurement_event(
    metrics: ContractPhaseMetrics,
    *,
    timestamp_iso: str,
    event_id: str | None = None,
) -> ContractMeasurementEvent:
    """Wrap ContractPhaseMetrics in a ContractMeasurementEvent.

    ``timestamp_iso`` is required (no ``datetime.now()`` default) per the
    repository invariant that emitted_at timestamps must be explicitly
    injected for deterministic testing.

    Args:
        metrics: The phase metrics to wrap.
        timestamp_iso: ISO-8601 timestamp for the event envelope.
            Must be explicitly provided by the caller.
        event_id: Explicit short event identifier for deterministic testing.
            Defaults to ``str(uuid.uuid4())[:8]`` when *None*.

    Returns:
        A ContractMeasurementEvent domain envelope.
    """
    from omnibase_spi.contracts.measurement import ContractMeasurementEvent

    if event_id is None:
        event_id = str(uuid.uuid4())[:8]

    return ContractMeasurementEvent(
        event_id=event_id,
        event_type="phase_completed",
        timestamp_iso=timestamp_iso,
        payload=metrics,
    )


def emit_phase_metrics(
    metrics: ContractPhaseMetrics,
    *,
    timestamp_iso: str,
    event_id: str | None = None,
) -> bool:
    """Emit phase metrics to Kafka via the emit daemon.

    Wraps metrics in ContractMeasurementEvent, serializes via model_dump,
    and sends through the daemon. The daemon transports the dict unchanged.

    ``timestamp_iso`` is required (no ``datetime.now()`` default) per the
    repository invariant that emitted_at timestamps must be explicitly
    injected for deterministic testing.

    Args:
        metrics: The ContractPhaseMetrics to emit.
        timestamp_iso: ISO-8601 timestamp for the event envelope.
            Must be explicitly provided by the caller.
        event_id: Explicit short event identifier for deterministic testing.
            Forwarded to ``_build_measurement_event``.

    Returns:
        True if emission succeeded, False otherwise.
    """
    try:
        event = _build_measurement_event(
            metrics, timestamp_iso=timestamp_iso, event_id=event_id
        )
        payload = event.model_dump(mode="json")

        # Sanitize before emission
        if "payload" in payload and "outcome" in (payload["payload"] or {}):
            outcome = payload["payload"]["outcome"]
            if outcome and "error_messages" in outcome:
                outcome["error_messages"] = _sanitize_error_messages(
                    outcome.get("error_messages", [])
                )
            if outcome and "failed_tests" in outcome:
                outcome["failed_tests"] = _sanitize_failed_tests(
                    outcome.get("failed_tests", [])
                )
            if outcome and outcome.get("skip_reason"):
                outcome["skip_reason"] = _sanitize_skip_reason(outcome["skip_reason"])

        # Validate artifact URIs
        if "payload" in payload and "artifact_pointers" in (payload["payload"] or {}):
            pointers = payload["payload"].get("artifact_pointers", [])
            payload["payload"]["artifact_pointers"] = [
                p for p in pointers if _validate_artifact_uri(p.get("uri", ""))
            ]

        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

        return emit_event("phase.metrics", payload)

    except Exception as e:
        logger.warning(f"Failed to emit phase metrics: {e}")
        return False


# ---------------------------------------------------------------------------
# File Artifacts
# ---------------------------------------------------------------------------


def write_metrics_artifact(
    ticket_id: str,
    run_id: str,
    phase: str,
    attempt: int,
    metrics: ContractPhaseMetrics,
) -> Path | None:
    """Write metrics as a local file artifact for crash recovery.

    File path: ~/.claude/pipelines/{ticket_id}/metrics/{run_id}/{phase}_{attempt}.metrics.json

    Persisted via model_dump(mode="json"). Survives daemon outage.

    Args:
        ticket_id: The ticket identifier (e.g. OMN-2027).
        run_id: The pipeline run identifier.
        phase: The phase name.
        attempt: The attempt number.
        metrics: The ContractPhaseMetrics to persist.

    Returns:
        Path to the written artifact, or None on failure.
    """
    try:
        # Reject path traversal in user-influenced components
        for component in (ticket_id, run_id, phase):
            if any(c in str(component) for c in _INVALID_PATH_CHARS):
                logger.warning(
                    f"Rejected path component with traversal chars: {component!r}"
                )
                return None

        metrics_dir = ARTIFACT_BASE_DIR / ticket_id / "metrics" / run_id
        metrics_dir.mkdir(parents=True, exist_ok=True)

        artifact_path = metrics_dir / f"{phase}_{attempt}.metrics.json"
        data = metrics.model_dump(mode="json")

        # Sanitize file artifact (same redaction as Kafka path)
        if data.get("outcome"):
            outcome = data["outcome"]
            if "error_messages" in outcome:
                outcome["error_messages"] = _sanitize_error_messages(
                    outcome.get("error_messages", [])
                )
            if "failed_tests" in outcome:
                outcome["failed_tests"] = _sanitize_failed_tests(
                    outcome.get("failed_tests", [])
                )
            if outcome.get("skip_reason"):
                outcome["skip_reason"] = _sanitize_skip_reason(outcome["skip_reason"])

        # Atomic write via temp file
        tmp_path = artifact_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2))
        tmp_path.rename(artifact_path)

        logger.debug(f"Metrics artifact written: {artifact_path}")
        return artifact_path

    except Exception as e:
        logger.warning(f"Failed to write metrics artifact: {e}")
        return None


def read_metrics_artifact(
    ticket_id: str,
    run_id: str,
    phase: str,
    attempt: int,
) -> dict | None:
    """Read a metrics artifact file.

    Args:
        ticket_id: The ticket identifier.
        run_id: The pipeline run identifier.
        phase: The phase name.
        attempt: The attempt number.

    Returns:
        Parsed JSON dict, or None if file does not exist or is corrupt.
    """
    for component in (ticket_id, run_id, phase):
        if any(c in str(component) for c in _INVALID_PATH_CHARS):
            logger.warning(
                f"Rejected path component with traversal chars: {component!r}"
            )
            return None

    artifact_path = (
        ARTIFACT_BASE_DIR
        / ticket_id
        / "metrics"
        / run_id
        / f"{phase}_{attempt}.metrics.json"
    )
    if not artifact_path.exists():
        return None
    try:
        return json.loads(artifact_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read metrics artifact {artifact_path}: {e}")
        return None


def metrics_artifact_exists(
    ticket_id: str,
    run_id: str,
    phase: str,
    attempt: int,
) -> bool:
    """Check if a metrics artifact file exists for a given phase/attempt.

    Used by the silent omission detector in the orchestrator.

    Args:
        ticket_id: The ticket identifier.
        run_id: The pipeline run identifier.
        phase: The phase name.
        attempt: The attempt number.

    Returns:
        True if the artifact file exists.
    """
    for component in (ticket_id, run_id, phase):
        if any(c in str(component) for c in _INVALID_PATH_CHARS):
            logger.warning(
                f"Rejected path component with traversal chars: {component!r}"
            )
            return False

    artifact_path = (
        ARTIFACT_BASE_DIR
        / ticket_id
        / "metrics"
        / run_id
        / f"{phase}_{attempt}.metrics.json"
    )
    return artifact_path.exists()


__all__ = [
    "emit_phase_metrics",
    "write_metrics_artifact",
    "read_metrics_artifact",
    "metrics_artifact_exists",
    "ARTIFACT_BASE_DIR",
]
