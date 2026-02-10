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
from collections.abc import Callable
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


_redact_secrets_fn: Callable[[str], str] | None = None

# Lightweight fallback patterns for common secret formats.
# Used only when the full secret_redactor module is unavailable.
# Known coverage gaps vs full secret_redactor: Azure keys, GCP service
# account JSON, generic high-entropy tokens, JWT tokens, Datadog/Stripe
# keys. If the full module is never deployed, these gaps are accepted —
# see OMN-2027 for follow-up tracking.
_FALLBACK_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI API keys
    re.compile(r"AKIA[A-Z0-9]{16}"),  # AWS access keys
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),  # GitHub PATs
    re.compile(r"gho_[A-Za-z0-9]{36,}"),  # GitHub OAuth tokens
    re.compile(r"xox[bpsar]-[A-Za-z0-9\-]+"),  # Slack tokens
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),  # Bearer tokens
    re.compile(r"-----BEGIN\s+\w+\s+PRIVATE\s+KEY-----"),  # PEM keys
    re.compile(r"://[^@\s]+:[^@\s]+@"),  # Passwords in URLs
]


def _lightweight_redact(text: str) -> str:
    """Fallback redactor that masks common secret patterns.

    Preserves non-secret text for readability while catching the most
    common secret formats. Less comprehensive than the full
    ``secret_redactor`` module but avoids blanket replacement.
    """
    result = text
    for pattern in _FALLBACK_SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def get_redact_secrets() -> Callable[[str], str]:
    """Return the ``redact_secrets`` callable, with a safe fallback.

    If ``secret_redactor`` is unavailable, the fallback uses
    ``_lightweight_redact`` which applies regex-based redaction for
    common secret formats (API keys, tokens, PEM keys, passwords in
    URLs) while preserving non-secret text.

    Both the real redactor and the fallback are cached after first resolution.
    If the module is later deployed, call ``reset_redactor()`` or restart the
    process to pick it up — the global is cleared on module reload.

    Note:
        The import path ``plugins.onex.hooks.lib.secret_redactor`` requires
        the repository root on ``sys.path``. In deployed environments (plugin
        cache under ``~/.claude/``), this path will not resolve and the
        lightweight fallback is used instead. This is by design — the fallback
        is the expected redactor in deployed mode.
    """
    global _redact_secrets_fn
    if _redact_secrets_fn is not None:
        return _redact_secrets_fn

    try:
        from plugins.onex.hooks.lib.secret_redactor import redact_secrets

        _redact_secrets_fn = redact_secrets
        return redact_secrets
    except ImportError:
        logger.warning(
            "secret_redactor not available; using lightweight fallback "
            "redactor for common secret patterns"
        )

        _redact_secrets_fn = _lightweight_redact
        return _lightweight_redact


def reset_redactor() -> None:
    """Clear the cached redactor, forcing re-import on next call.

    Use after deploying ``secret_redactor`` at runtime so the fallback
    placeholder is replaced with the real implementation.
    """
    global _redact_secrets_fn
    _redact_secrets_fn = None


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
    redact = get_redact_secrets()
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
    redact = get_redact_secrets()
    clean = redact(reason)
    if len(clean) > MAX_ERROR_MESSAGE_LENGTH:
        clean = clean[: MAX_ERROR_MESSAGE_LENGTH - 3] + "..."
    return clean


def _sanitize_failed_tests(tests: list[str]) -> list[str]:
    """Redact and truncate failed test names per M2 spec.

    Args:
        tests: Failed test name list.

    Returns:
        Sanitized list of test names.
    """
    redact = get_redact_secrets()
    sanitized = []
    for test in tests[:MAX_FAILED_TESTS]:
        clean = redact(test)
        if len(clean) > MAX_FAILED_TEST_LENGTH:
            clean = clean[: MAX_FAILED_TEST_LENGTH - 3] + "..."
        sanitized.append(clean)
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

# Matches UNC paths like \\server\share at the start of the string only.
_UNC_PATH_RE = re.compile(r"^\\\\[^\\]+")

# Matches Windows drive-letter paths like C:\, D:\, c:\ at the start of the string only.
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:\\")


def _validate_artifact_uri(uri: str) -> bool:
    """Validate artifact pointer URI does not contain absolute or local paths.

    Rejects file:// URIs, tilde paths, well-known absolute path prefixes, and
    Windows drive paths to prevent PII leakage on the broad-access evt topic.

    Args:
        uri: The artifact URI to validate.

    Returns:
        True if URI is safe for emission.
    """
    if not uri:
        logger.warning("Artifact URI is empty, rejecting")
        return False
    uri_lower = uri.lower()
    if uri_lower.startswith("file://") or uri.startswith("~"):
        logger.warning(
            f"Artifact URI contains local path scheme, rejecting: {uri[:50]}..."
        )
        return False
    if any(uri_lower.startswith(prefix.lower()) for prefix in _ABSOLUTE_PATH_PREFIXES):
        logger.warning(f"Artifact URI contains absolute path, rejecting: {uri[:50]}...")
        return False
    # Reject absolute Unix paths, but allow protocol-relative URIs (//)
    # that point to remote hosts. Reject //localhost and //127.0.0.1 to
    # prevent local resource references leaking onto the evt topic.
    if uri.startswith("//"):
        host = uri[2:].split("/", 1)[0].split(":")[0].lower()
        if not host or host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):  # noqa: S104
            logger.warning(
                f"Artifact URI references local host or has empty host, rejecting: {uri[:50]}..."
            )
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

        # Sanitize before emission — defense-in-depth layer.
        # Builders (build_metrics_from_result, build_error_metrics) now also
        # redact and truncate, but this layer ensures safety even for metrics
        # constructed outside the standard builder path.
        inner = payload.get("payload")
        if isinstance(inner, dict) and "outcome" in inner:
            outcome = inner["outcome"]
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
            if outcome and "error_codes" in outcome:
                outcome["error_codes"] = _sanitize_error_messages(
                    outcome.get("error_codes", [])
                )

        # Validate artifact URIs
        if isinstance(inner, dict) and "artifact_pointers" in inner:
            pointers = inner.get("artifact_pointers", [])
            inner["artifact_pointers"] = [
                p
                for p in pointers
                if isinstance(p, dict) and _validate_artifact_uri(p.get("uri", ""))
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
    Uses atomic write (temp file + rename) which is safe on local POSIX
    filesystems. Not guaranteed atomic on network-mounted filesystems.

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
        for component in (ticket_id, run_id, phase, str(attempt)):
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
            if "error_codes" in outcome:
                outcome["error_codes"] = _sanitize_error_messages(
                    outcome.get("error_codes", [])
                )

        # Atomic write via temp file (same-filesystem rename is atomic on POSIX)
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
    for component in (ticket_id, run_id, phase, str(attempt)):
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
    for component in (ticket_id, run_id, phase, str(attempt)):
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
    "get_redact_secrets",
    "reset_redactor",
    "MAX_ERROR_MESSAGE_LENGTH",
    "ARTIFACT_BASE_DIR",
]
