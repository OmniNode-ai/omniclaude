#!/usr/bin/env python3
"""Decision record subscriber — audit-log consumer for Decision Provenance (OMN-2720).

Subscribes to ``onex.cmd.omniintelligence.decision-recorded.v1``, deserializes
full ``DecisionRecord`` payloads (including ``agent_rationale`` and
``reproducibility_snapshot``), and writes them to a local append-only JSONL
audit log at ``~/.claude/decision_audit.jsonl``.

This is the consumer side of the Decision Provenance restricted data path
(OMN-2465). ``omniclaude`` registers ``DECISION_RECORDED_CMD`` in its
``TopicBase`` enum because it owns the audit-log consumer for the full
payload; the summary EVT topic is consumed elsewhere for dashboards.

Design principles (consistent with the rest of omniclaude hooks lib):
- **All failures are silent**: the subscriber never raises, never blocks UX.
- **stdlib-only**: no external imports required; Kafka is imported lazily with
  graceful fallback when ``kafka-python`` is not installed.
- **Fail-open**: if Kafka is unavailable or the payload is malformed, the
  subscriber logs and returns — decision records may be lost, but the UI
  is never blocked.
- **Append-only**: records are written as newline-delimited JSON (JSONL) to
  ``~/.claude/decision_audit.jsonl`` using O_APPEND semantics. This is safe
  for concurrent writers within a single process; do not use from multiple
  processes without an external lock.
- **No secrets in logs**: ``agent_rationale`` is retained (this is the audit
  purpose), but prompt content is NOT stored here — only the decision
  provenance fields that omniintelligence populates.

Ticket: OMN-2720
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Topic constant (mirrors TopicBase.DECISION_RECORDED_CMD)
# ---------------------------------------------------------------------------

DECISION_RECORDED_CMD_TOPIC = "onex.cmd.omniintelligence.decision-recorded.v1"

# ---------------------------------------------------------------------------
# Default audit log path
# ---------------------------------------------------------------------------

_DEFAULT_AUDIT_LOG_PATH = Path.home() / ".claude" / "decision_audit.jsonl"

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


def _parse_decision_record(raw: bytes) -> dict[str, Any] | None:
    """Deserialize a raw Kafka message value into a decision record dict.

    Expects JSON with the shape of the ``cmd`` payload from
    ``DecisionEmitter._do_emit()``:
        {
            "decision_id": str,
            "decision_type": str,
            "timestamp": str (ISO-8601),
            "candidates_considered": list[str],
            "constraints_applied": dict[str, str],
            "scoring_breakdown": list[dict],
            "tie_breaker": str | null,
            "selected_candidate": str,
            "agent_rationale": str | null,
            "reproducibility_snapshot": dict[str, str],
            "emitted_at": str (ISO-8601),
            # optional fields
            "session_id": str | null,
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
# Audit log persistence
# ---------------------------------------------------------------------------


def _resolve_audit_log_path() -> Path:
    """Return the audit log path, honouring ``OMNICLAUDE_DECISION_AUDIT_LOG`` override.

    Returns:
        Absolute path to the decision audit JSONL file.
    """
    override = os.environ.get("OMNICLAUDE_DECISION_AUDIT_LOG", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _DEFAULT_AUDIT_LOG_PATH


def _append_audit_record(record: dict[str, Any]) -> bool:
    """Append one decision record to the JSONL audit log.

    Uses O_APPEND semantics (``mode="a"``) to ensure writes from multiple
    threads within the same process are atomic at the line level on POSIX
    systems when the line fits in one write call.

    Args:
        record: Parsed decision record dict from the Kafka payload.

    Returns:
        True if the record was written, False on any I/O failure.
    """
    try:
        audit_path = _resolve_audit_log_path()
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        return True
    except Exception as exc:
        logger.debug("Failed to append decision audit record: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Process a single decision-recorded event
# ---------------------------------------------------------------------------


def process_decision_record_event(raw_value: bytes) -> bool:
    """Process one raw Kafka message from the decision-recorded (cmd) topic.

    Full pipeline:
      1. Parse JSON payload
      2. Validate required fields (decision_id, decision_type, selected_candidate)
      3. Append to JSONL audit log

    Args:
        raw_value: Raw bytes from Kafka message value (JSON-encoded payload).

    Returns:
        True if the record was persisted to the audit log, False otherwise.
    """
    try:
        payload = _parse_decision_record(raw_value)
        if payload is None:
            logger.debug("Skipping unparseable decision-recorded message")
            return False

        decision_id = str(payload.get("decision_id", "")).strip()
        if not decision_id:
            logger.debug("Skipping decision-recorded message: missing decision_id")
            return False

        # Validate minimum required fields before persisting
        decision_type = str(payload.get("decision_type", "")).strip()
        selected_candidate = str(payload.get("selected_candidate", "")).strip()
        if not decision_type or not selected_candidate:
            logger.debug(
                "Skipping decision-recorded message: missing decision_type or "
                "selected_candidate. decision_id=%s",
                decision_id,
            )
            return False

        return _append_audit_record(payload)

    except Exception as exc:
        # Absolute fail-open: never propagate
        logger.debug("process_decision_record_event error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Subscriber loop (used by the emit daemon extension or standalone runner)
# ---------------------------------------------------------------------------


def run_subscriber(
    *,
    kafka_bootstrap_servers: str,
    group_id: str = "omniclaude-decision-record-subscriber.v1",
    poll_timeout_ms: int = 1000,
    max_poll_records: int = 50,
    stop_event: Any = None,
) -> None:
    """Run a blocking Kafka consumer loop for decision-recorded (cmd) events.

    Designed to run in a background thread (or daemon process) launched by
    SessionStart. Exits when ``stop_event`` is set or on unrecoverable error.

    All KafkaConsumer parameters are chosen for audit delivery:
    - ``auto_offset_reset="latest"``: only process new decisions (not historical)
    - ``enable_auto_commit=True``: fire-and-forget; audit record loss is
      acceptable over blocking the UX

    Args:
        kafka_bootstrap_servers: Kafka bootstrap servers string.
        group_id: Consumer group ID (schema version encoded; default:
            ``omniclaude-decision-record-subscriber.v1``).
        poll_timeout_ms: Kafka poll timeout in milliseconds.
        max_poll_records: Maximum records per poll.
        stop_event: Optional threading.Event; loop exits when set.
    """
    KafkaConsumer = _get_kafka_consumer_class()  # noqa: N806
    if KafkaConsumer is None:
        logger.warning(
            "kafka-python not installed; decision-record subscriber disabled"
        )
        return

    if not kafka_bootstrap_servers:
        logger.warning(
            "KAFKA_BOOTSTRAP_SERVERS not set; decision-record subscriber disabled"
        )
        return

    logger.info(
        "Starting decision-record subscriber (topic=%s, servers=%s)",
        DECISION_RECORDED_CMD_TOPIC,
        kafka_bootstrap_servers,
    )

    try:
        consumer = KafkaConsumer(
            DECISION_RECORDED_CMD_TOPIC,
            bootstrap_servers=kafka_bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=None,  # We handle raw bytes in process_decision_record_event
            max_poll_records=max_poll_records,
        )
    except Exception as exc:
        logger.warning("Failed to create Kafka consumer for decision-record: %s", exc)
        return

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                logger.info("Decision-record subscriber stop_event set; exiting")
                break

            try:
                records = consumer.poll(timeout_ms=poll_timeout_ms)
                for _tp, messages in records.items():
                    for msg in messages:
                        try:
                            process_decision_record_event(msg.value)
                        except Exception as exc:
                            # Per design: individual message failures are silent
                            logger.debug(
                                "Error processing decision-record message: %s", exc
                            )
            except Exception as exc:
                logger.warning(
                    "Kafka poll error in decision-record subscriber: %s", exc
                )
                # Brief backoff before retrying
                time.sleep(1.0)

    finally:
        try:
            consumer.close()
        except Exception:
            pass
        logger.info("Decision-record subscriber stopped")


# ---------------------------------------------------------------------------
# Background thread launcher (used by plugin.py:start_consumers)
# ---------------------------------------------------------------------------


def run_subscriber_background(
    *,
    kafka_bootstrap_servers: str,
    group_id: str = "omniclaude-decision-record-subscriber.v1",
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
    thread = threading.Thread(
        target=run_subscriber,
        kwargs={
            "kafka_bootstrap_servers": kafka_bootstrap_servers,
            "group_id": group_id,
            "stop_event": stop_event,
        },
        name="decision-record-subscriber",
        daemon=True,
    )
    thread.start()
    logger.debug(
        "Decision-record subscriber daemon thread started (group_id=%s)",
        group_id,
    )
    return thread


# ---------------------------------------------------------------------------
# CLI entry point (called from session-start.sh to launch background subscriber)
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the decision record subscriber.

    Modes:
        run: Start subscriber loop (blocks until SIGTERM/SIGINT).
            env: KAFKA_BOOTSTRAP_SERVERS must be set.
        process: Process a single raw payload from stdin (for testing/scripting).
            stdin: Raw JSON bytes of a decision-recorded event payload.

    Always exits 0 (fail-open).

    Usage:
        python decision_record_subscriber.py run
        echo '<payload_json>' | python decision_record_subscriber.py process
    """
    import threading

    try:
        if len(sys.argv) < 2:
            print(
                "Usage: decision_record_subscriber.py <run|process>",
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
                result = process_decision_record_event(raw)
                print(json.dumps({"processed": result}))
            else:
                print(json.dumps({"processed": False}))

        else:
            print(f"Unknown mode: {mode}", file=sys.stderr)

    except Exception as exc:
        # Silent failure — never crash
        print(f"decision_record_subscriber error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
