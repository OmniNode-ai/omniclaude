#!/usr/bin/env python3
"""Compliance result subscriber — transform violations to PatternAdvisory (OMN-2340).

Subscribes to `onex.evt.omniintelligence.compliance-evaluated.v1`, deserializes
`ModelComplianceResult` payloads, filters to violated entries, transforms them
into `PatternAdvisory` format, and persists via `save_advisories()` so that
`UserPromptSubmit` context injection picks them up on the next turn.

This is the final leg of the OMN-2256 compliance pipeline:
  1. PostToolUse emits `compliance.evaluate` (PR #161 — shipped)
  2. omniintelligence processes and emits `compliance-evaluated.v1`
  3. THIS module subscribes, transforms violations → PatternAdvisory, persists

Design principles (consistent with the rest of omniclaude hooks lib):
- **All failures are silent**: the subscriber never raises, never blocks UX.
- **stdlib-only**: no external imports required; Kafka is imported lazily with
  graceful fallback when `kafka-python` is not installed.
- **Fail-open**: if Kafka is unavailable or the payload is malformed, the
  subscriber logs and returns — pattern injection continues without advisories.
- **Do NOT update cooldown**: cooldown was already set by PostToolUse when the
  `compliance.evaluate` event was emitted. Writing the advisory IS the signal.
- **Merge, not overwrite**: multiple compliance events per session (different
  files) accumulate — `save_advisories()` handles deduplication by pattern_id.

Ticket: OMN-2340
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Topic constant (mirrors TopicBase.COMPLIANCE_EVALUATED)
# ---------------------------------------------------------------------------

COMPLIANCE_EVALUATED_TOPIC = "onex.evt.omniintelligence.compliance-evaluated.v1"

# ---------------------------------------------------------------------------
# Lazy import helpers for kafka-python
# ---------------------------------------------------------------------------


def _get_kafka_consumer_class() -> type | None:
    """Import KafkaConsumer lazily; return None if kafka-python not installed."""
    try:
        from kafka import KafkaConsumer  # noqa: PLC0415

        result: type = KafkaConsumer
        return result
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Payload deserialization
# ---------------------------------------------------------------------------


def _parse_compliance_result(raw: bytes) -> dict[str, Any] | None:
    """Deserialize a raw Kafka message value into a compliance result dict.

    Expects JSON with the shape of `ModelComplianceResult`:
        {
            "correlation_id": str,
            "session_id": str,
            "source_path": str,
            "content_sha256": str,
            "language": str,
            "violations": [
                {
                    "pattern_id": str,
                    "pattern_signature": str,
                    "domain_id": str,
                    "confidence": float,
                    "violated": bool,
                    "severity": str,
                    "message": str,
                },
                ...
            ]
        }

    Returns None on any parse failure.
    """
    try:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, UnicodeDecodeError, Exception):
        return None


# ---------------------------------------------------------------------------
# Violation → PatternAdvisory transformation
# ---------------------------------------------------------------------------


def violations_to_advisories(
    violations: list[Any],
) -> list[dict[str, Any]]:
    """Filter violated entries and transform to PatternAdvisory format.

    Only entries where `violated == True` are included. The `status` field is
    set to `"validated"` to match the existing advisory consumer expectations in
    `pattern_advisory_formatter.py`.

    Args:
        violations: List of ViolationDetail dicts from ModelComplianceResult.

    Returns:
        List of PatternAdvisory-compatible dicts (may be empty).
    """
    advisories: list[dict[str, Any]] = []

    for v in violations:
        # Guard: skip non-dict entries before entering the try block
        if not isinstance(v, dict):
            continue
        try:
            # Filter: only transform entries where violated is True
            violated = v.get("violated", False)
            if not violated:
                continue

            pattern_id = str(v.get("pattern_id", "")).strip()
            pattern_signature = str(v.get("pattern_signature", "")).strip()
            domain_id = str(v.get("domain_id", "")).strip()
            message = str(v.get("message", "")).strip()

            # Validate confidence is a finite number in [0, 1]
            try:
                import math  # noqa: PLC0415

                confidence = float(v.get("confidence", 0.0))
                if not math.isfinite(confidence):
                    confidence = 0.0
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                confidence = 0.0

            # Skip entries without a usable identifier
            if not pattern_id and not pattern_signature:
                continue

            advisory: dict[str, Any] = {
                "pattern_id": pattern_id,
                "pattern_signature": pattern_signature,
                "domain_id": domain_id,
                "confidence": confidence,
                "status": "validated",
                "message": message,
            }
            advisories.append(advisory)

        except Exception:
            # Per design: individual entry failures are silent
            continue

    return advisories


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _resolve_hooks_lib_dir() -> Path:
    """Return the absolute path to this script's directory (hooks lib)."""
    return Path(__file__).resolve().parent


def _save_advisory(session_id: str, advisories: list[dict[str, Any]]) -> bool:
    """Persist advisories via pattern_advisory_formatter.save_advisories().

    Imports `save_advisories` from the adjacent module. Adjusts sys.path
    if needed (hooks lib modules run as standalone scripts outside the
    normal package tree).

    Args:
        session_id: Session to store advisories for.
        advisories: Transformed PatternAdvisory dicts.

    Returns:
        True if saved successfully, False on any failure.
    """
    if not session_id or not advisories:
        return False

    lib_dir = str(_resolve_hooks_lib_dir())
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)

    try:
        from pattern_advisory_formatter import save_advisories  # noqa: PLC0415

        result: bool = save_advisories(session_id, advisories)
        return result
    except Exception as exc:
        logger.debug("Failed to save advisories: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Process a single compliance-evaluated event
# ---------------------------------------------------------------------------


def process_compliance_event(raw_value: bytes) -> bool:
    """Process one raw Kafka message from the compliance-evaluated topic.

    Full pipeline:
      1. Parse JSON payload
      2. Extract session_id and violations list
      3. Filter violations to `violated == True`
      4. Transform to PatternAdvisory format
      5. Persist via save_advisories() keyed on session_id

    Args:
        raw_value: Raw bytes from Kafka message value (JSON-encoded payload).

    Returns:
        True if at least one advisory was persisted, False otherwise.
    """
    try:
        payload = _parse_compliance_result(raw_value)
        if payload is None:
            logger.debug("Skipping unparseable compliance-evaluated message")
            return False

        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            logger.debug("Skipping compliance-evaluated message: missing session_id")
            return False

        violations = payload.get("violations", [])
        if not isinstance(violations, list):
            logger.debug(
                "Skipping compliance-evaluated message: violations is not a list"
            )
            return False

        advisories = violations_to_advisories(violations)
        if not advisories:
            # All violations were `violated=False` or list was empty — normal case
            return False

        return _save_advisory(session_id, advisories)

    except Exception as exc:
        # Absolute fail-open: never propagate
        logger.debug("process_compliance_event error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Subscriber loop (used by the emit daemon extension or standalone runner)
# ---------------------------------------------------------------------------


def run_subscriber(
    *,
    kafka_bootstrap_servers: str,
    group_id: str = "omniclaude-compliance-subscriber",
    poll_timeout_ms: int = 1000,
    max_poll_records: int = 50,
    stop_event: Any = None,
) -> None:
    """Run a blocking Kafka consumer loop for compliance-evaluated events.

    Designed to run in a background thread (or daemon process) launched by
    SessionStart. Exits when `stop_event` is set or on unrecoverable error.

    All KafkaConsumer parameters are chosen for low-latency advisory delivery:
    - `auto_offset_reset="latest"`: only process new events (not historical ones)
    - `enable_auto_commit=True`: fire-and-forget; advisory loss is acceptable
    - No manual commit needed — we tolerate re-delivery on crash restart

    Args:
        kafka_bootstrap_servers: Kafka bootstrap servers string.
        group_id: Consumer group ID (one per omniclaude instance is fine).
        poll_timeout_ms: Kafka poll timeout in milliseconds.
        max_poll_records: Maximum records per poll.
        stop_event: Optional threading.Event; loop exits when set.
    """
    KafkaConsumer = _get_kafka_consumer_class()  # noqa: N806
    if KafkaConsumer is None:
        logger.warning(
            "kafka-python not installed; compliance-evaluated subscriber disabled"
        )
        return

    if not kafka_bootstrap_servers:
        logger.warning(
            "KAFKA_BOOTSTRAP_SERVERS not set; compliance-evaluated subscriber disabled"
        )
        return

    logger.info(
        "Starting compliance-evaluated subscriber (topic=%s, servers=%s)",
        COMPLIANCE_EVALUATED_TOPIC,
        kafka_bootstrap_servers,
    )

    try:
        consumer = KafkaConsumer(
            COMPLIANCE_EVALUATED_TOPIC,
            bootstrap_servers=kafka_bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=None,  # We handle raw bytes in process_compliance_event
            max_poll_records=max_poll_records,
        )
    except Exception as exc:
        logger.warning("Failed to create Kafka consumer: %s", exc)
        return

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                logger.info("Compliance subscriber stop_event set; exiting")
                break

            try:
                records = consumer.poll(timeout_ms=poll_timeout_ms)
                for _tp, messages in records.items():
                    for msg in messages:
                        try:
                            process_compliance_event(msg.value)
                        except Exception as exc:
                            # Per design: individual message failures are silent
                            logger.debug("Error processing message: %s", exc)
            except Exception as exc:
                logger.warning("Kafka poll error: %s", exc)
                # Brief backoff before retrying
                import time  # noqa: PLC0415

                time.sleep(1.0)

    finally:
        try:
            consumer.close()
        except Exception:
            pass
        logger.info("Compliance-evaluated subscriber stopped")


# ---------------------------------------------------------------------------
# Background thread launcher (used by plugin.py:start_consumers)
# ---------------------------------------------------------------------------


def run_subscriber_background(
    *,
    kafka_bootstrap_servers: str,
    group_id: str = "omniclaude-compliance-subscriber.v1",
    stop_event: Any = None,
) -> threading.Thread:
    """Launch ``run_subscriber`` in a daemon background thread.

    The thread is marked daemon=True so it does not block interpreter exit.
    The caller owns the ``stop_event`` and must set it to request a graceful
    shutdown before the thread naturally exits.

    Args:
        kafka_bootstrap_servers: Kafka bootstrap servers string.
        group_id: Consumer group ID (schema version encoded).
        stop_event: ``threading.Event`` instance; loop exits when set.

    Returns:
        The started ``threading.Thread`` instance.
    """
    import threading  # noqa: PLC0415

    thread = threading.Thread(
        target=run_subscriber,
        kwargs={
            "kafka_bootstrap_servers": kafka_bootstrap_servers,
            "group_id": group_id,
            "stop_event": stop_event,
        },
        name="compliance-subscriber",
        daemon=True,
    )
    thread.start()
    logger.info(
        "Compliance subscriber daemon thread started (group_id=%s)",
        group_id,
    )
    return thread


# ---------------------------------------------------------------------------
# CLI entry point (called from session-start.sh to launch background subscriber)
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the compliance result subscriber.

    Modes:
        run: Start subscriber loop (blocks until SIGTERM/SIGINT).
            env: KAFKA_BOOTSTRAP_SERVERS must be set.
        process: Process a single raw payload from stdin (for testing/scripting).
            stdin: Raw JSON bytes of a compliance-evaluated event payload.

    Always exits 0 (fail-open).

    Usage:
        python compliance_result_subscriber.py run
        echo '<payload_json>' | python compliance_result_subscriber.py process
    """
    import threading

    try:
        if len(sys.argv) < 2:
            print(
                "Usage: compliance_result_subscriber.py <run|process>",
                file=sys.stderr,
            )
            sys.exit(0)

        mode = sys.argv[1]

        if mode == "run":
            servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
            if not servers:
                print(
                    "KAFKA_BOOTSTRAP_SERVERS not set; subscriber exiting",
                    file=sys.stderr,
                )
                sys.exit(0)

            stop_event = threading.Event()

            import signal  # noqa: PLC0415

            def _handle_signal(sig: int, frame: Any) -> None:
                stop_event.set()

            signal.signal(signal.SIGTERM, _handle_signal)
            signal.signal(signal.SIGINT, _handle_signal)

            run_subscriber(
                kafka_bootstrap_servers=servers,
                stop_event=stop_event,
            )

        elif mode == "process":
            raw = sys.stdin.buffer.read()
            if raw.strip():
                result = process_compliance_event(raw)
                print(json.dumps({"processed": result}))
            else:
                print(json.dumps({"processed": False}))

        else:
            print(f"Unknown mode: {mode}", file=sys.stderr)

    except Exception as exc:
        # Silent failure — never crash
        print(f"compliance_result_subscriber error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
