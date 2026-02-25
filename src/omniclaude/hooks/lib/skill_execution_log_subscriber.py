# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Skill execution log subscriber — Kafka-to-table projection consumer (OMN-2778).

Subscribes to ``onex.evt.omniclaude.skill-completed.v1``, deserializes
``ModelSkillCompletedEvent`` payloads, and upserts rows into the
``skill_execution_logs`` PostgreSQL table.

This is the follow-on consumer from OMN-2773 (skill lifecycle event emission).
Once this consumer is active, ``pipeline-metrics`` reads ``skill_execution_logs``
instead of using ``agent_execution_logs`` as a proxy.

Design principles (consistent with omniclaude hooks lib):
- **All failures are silent**: the subscriber never raises, never blocks UX.
- **stdlib-only Kafka import**: kafka-python imported lazily with graceful
  fallback when not installed.
- **Fail-open DB**: if the DB is unavailable, rows are dropped (logged at DEBUG).
  Data loss is acceptable; UI freeze is not.
- **Idempotent upsert**: ON CONFLICT (run_id) DO UPDATE ensures replayed
  consumer offsets do not produce duplicates.
- **No earliest offset without version bump**: auto_offset_reset="latest" per
  consumer group guard F5 rules (OMN-2593).

Migration note:
    The ``skill_execution_logs`` DDL lives in ``docs/db/003_create_skill_execution_logs.sql``
    rather than ``sql/migrations/`` because the omniclaude migration freeze (OMN-2073/OMN-2055)
    is active. Apply the DDL manually once the freeze lifts.

Ticket: OMN-2778
Depends-on: OMN-2773 (TopicBase.SKILL_COMPLETED, ModelSkillCompletedEvent)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Topic constant (mirrors TopicBase.SKILL_COMPLETED)
# ---------------------------------------------------------------------------

SKILL_COMPLETED_TOPIC = "onex.evt.omniclaude.skill-completed.v1"

# Consumer group ID — version suffix required by F5 rules (OMN-2593)
DEFAULT_GROUP_ID = "omniclaude-skill-execution-log-subscriber.v1"

# ---------------------------------------------------------------------------
# Lazy import helpers
# ---------------------------------------------------------------------------


def _get_kafka_consumer_class() -> type | None:
    """Import KafkaConsumer lazily; return None if kafka-python not installed."""
    try:
        from kafka import KafkaConsumer  # noqa: PLC0415

        result: type = KafkaConsumer
        return result
    except ImportError:
        return None


def _get_db_connection() -> Any | None:
    """Open a psycopg2 connection using omniclaude settings.

    Returns None on any failure (fail-open).
    """
    try:
        import psycopg2  # noqa: PLC0415

        from omniclaude.config import settings  # noqa: PLC0415

        dsn = settings.omniclaude_db_url.get_secret_value().strip()
        if dsn:
            return psycopg2.connect(dsn, connect_timeout=5)
        return psycopg2.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            database=settings.postgres_database,
            user=settings.postgres_user,
            password=settings.get_effective_postgres_password(),
            connect_timeout=5,
        )
    except Exception as exc:
        logger.debug("skill-execution-log-subscriber: DB connect failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Payload deserialization
# ---------------------------------------------------------------------------


def _parse_skill_completed_event(raw: bytes) -> dict[str, Any] | None:
    """Deserialize a raw Kafka message value into a skill-completed event dict.

    Args:
        raw: Raw bytes from Kafka message value (JSON-encoded payload).

    Returns:
        Parsed dict, or None if deserialization fails.
    """
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))  # type: ignore[no-any-return]
    except Exception as exc:
        logger.debug("skill-execution-log-subscriber: failed to parse payload: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Database upsert
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT INTO skill_execution_logs (
    run_id,
    skill_name,
    skill_id,
    repo_id,
    correlation_id,
    session_id,
    status,
    duration_ms,
    error_type,
    started_emit_failed,
    emitted_at
) VALUES (
    %(run_id)s,
    %(skill_name)s,
    %(skill_id)s,
    %(repo_id)s,
    %(correlation_id)s,
    %(session_id)s,
    %(status)s,
    %(duration_ms)s,
    %(error_type)s,
    %(started_emit_failed)s,
    %(emitted_at)s
)
ON CONFLICT (run_id) DO UPDATE SET
    status             = EXCLUDED.status,
    duration_ms        = EXCLUDED.duration_ms,
    error_type         = EXCLUDED.error_type,
    started_emit_failed = EXCLUDED.started_emit_failed,
    emitted_at         = EXCLUDED.emitted_at
"""


def _upsert_skill_execution_log(payload: dict[str, Any]) -> bool:
    """Upsert one skill-completed payload into skill_execution_logs.

    Idempotent: ON CONFLICT (run_id) DO UPDATE ensures replayed offsets
    do not create duplicates.

    Args:
        payload: Parsed dict from the skill-completed Kafka event.

    Returns:
        True if the row was written, False on any failure.
    """
    run_id_raw = payload.get("run_id")
    if not run_id_raw:
        logger.debug(
            "skill-execution-log-subscriber: skipping event with missing run_id"
        )
        return False

    skill_name = str(payload.get("skill_name", "")).strip()
    repo_id = str(payload.get("repo_id", "")).strip()
    status = str(payload.get("status", "")).strip()

    if not skill_name or not repo_id or status not in ("success", "failed", "partial"):
        logger.debug(
            "skill-execution-log-subscriber: skipping malformed event "
            "(skill_name=%r, repo_id=%r, status=%r)",
            skill_name,
            repo_id,
            status,
        )
        return False

    # Coerce UUID fields — accept both str and pre-parsed UUID
    def _to_uuid_str(v: Any) -> str | None:
        if v is None:
            return None
        try:
            return str(UUID(str(v)))
        except Exception:
            return None

    params: dict[str, Any] = {
        "run_id": _to_uuid_str(run_id_raw),
        "skill_name": skill_name,
        "skill_id": payload.get("skill_id") or None,
        "repo_id": repo_id,
        "correlation_id": _to_uuid_str(payload.get("correlation_id")),
        "session_id": payload.get("session_id") or None,
        "status": status,
        "duration_ms": int(payload.get("duration_ms", 0)),
        "error_type": payload.get("error_type") or None,
        "started_emit_failed": bool(payload.get("started_emit_failed", False)),
        "emitted_at": payload.get("emitted_at"),
    }

    if params["run_id"] is None:
        logger.debug(
            "skill-execution-log-subscriber: invalid run_id %r; skipping",
            run_id_raw,
        )
        return False

    conn = _get_db_connection()
    if conn is None:
        return False

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(_UPSERT_SQL, params)
        return True
    except Exception as exc:
        logger.debug(
            "skill-execution-log-subscriber: upsert failed (run_id=%s): %s",
            params["run_id"],
            exc,
        )
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Process a single skill-completed event
# ---------------------------------------------------------------------------


def process_skill_completed_event(raw_value: bytes) -> bool:
    """Process one raw Kafka message from the skill-completed topic.

    Full pipeline:
      1. Parse JSON payload
      2. Validate required fields (run_id, skill_name, repo_id, status)
      3. Upsert into skill_execution_logs

    Args:
        raw_value: Raw bytes from Kafka message value (JSON-encoded payload).

    Returns:
        True if the row was persisted, False otherwise.
    """
    try:
        payload = _parse_skill_completed_event(raw_value)
        if payload is None:
            logger.debug("skill-execution-log-subscriber: skipping unparseable message")
            return False
        return _upsert_skill_execution_log(payload)
    except Exception as exc:
        # Absolute fail-open: never propagate
        logger.debug("process_skill_completed_event error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Subscriber loop
# ---------------------------------------------------------------------------


def run_subscriber(
    *,
    kafka_bootstrap_servers: str,
    group_id: str = DEFAULT_GROUP_ID,
    poll_timeout_ms: int = 1000,
    max_poll_records: int = 50,
    stop_event: Any = None,
) -> None:
    """Run a blocking Kafka consumer loop for skill-completed events.

    Designed to run in a background thread (or daemon process). Exits when
    ``stop_event`` is set or on unrecoverable error.

    Consumer parameters:
    - ``auto_offset_reset="latest"``: only process new skill invocations.
      Per F5 rules (OMN-2593), changing to "earliest" requires a version bump
      in the consumer group ID.
    - ``enable_auto_commit=True``: fire-and-forget; row loss is acceptable
      over blocking UX.

    Args:
        kafka_bootstrap_servers: Kafka bootstrap servers string.
        group_id: Consumer group ID (default includes schema version suffix).
        poll_timeout_ms: Kafka poll timeout in milliseconds.
        max_poll_records: Maximum records per poll batch.
        stop_event: Optional threading.Event; loop exits when set.
    """
    KafkaConsumer = _get_kafka_consumer_class()  # noqa: N806
    if KafkaConsumer is None:
        logger.warning(
            "kafka-python not installed; skill-execution-log subscriber disabled"
        )
        return

    if not kafka_bootstrap_servers:
        logger.warning(
            "KAFKA_BOOTSTRAP_SERVERS not set; skill-execution-log subscriber disabled"
        )
        return

    logger.info(
        "Starting skill-execution-log subscriber (topic=%s, group=%s, servers=%s)",
        SKILL_COMPLETED_TOPIC,
        group_id,
        kafka_bootstrap_servers,
    )

    try:
        consumer = KafkaConsumer(
            SKILL_COMPLETED_TOPIC,
            bootstrap_servers=kafka_bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=None,  # Raw bytes; deserialized in process_skill_completed_event
            max_poll_records=max_poll_records,
        )
    except Exception as exc:
        logger.warning(
            "skill-execution-log-subscriber: failed to create Kafka consumer: %s",
            exc,
        )
        return

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                logger.info("skill-execution-log subscriber stop_event set; exiting")
                break

            try:
                records = consumer.poll(timeout_ms=poll_timeout_ms)
                for _tp, messages in records.items():
                    for msg in messages:
                        try:
                            process_skill_completed_event(msg.value)
                        except Exception as exc:
                            # Per design: individual message failures are silent
                            logger.debug(
                                "Error processing skill-completed message: %s", exc
                            )
            except Exception as exc:
                logger.warning(
                    "Kafka poll error in skill-execution-log subscriber: %s", exc
                )
                time.sleep(1.0)

    finally:
        try:
            consumer.close()
        except Exception:
            pass
        logger.info("skill-execution-log subscriber stopped")


# ---------------------------------------------------------------------------
# Background thread launcher
# ---------------------------------------------------------------------------


def run_subscriber_background(
    *,
    kafka_bootstrap_servers: str,
    group_id: str = DEFAULT_GROUP_ID,
    stop_event: Any = None,
) -> threading.Thread:
    """Launch ``run_subscriber`` in a daemon background thread.

    The thread is marked daemon=True so it does not block interpreter exit.
    The caller owns the ``stop_event`` and must set it to request graceful
    shutdown.

    Args:
        kafka_bootstrap_servers: Kafka bootstrap servers string.
        group_id: Consumer group ID.
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
        name="skill-execution-log-subscriber",
        daemon=True,
    )
    thread.start()
    logger.debug(
        "skill-execution-log subscriber daemon thread started (group_id=%s)",
        group_id,
    )
    return thread


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the skill execution log subscriber.

    Modes:
        run: Start subscriber loop (blocks until SIGTERM/SIGINT).
            env: KAFKA_BOOTSTRAP_SERVERS must be set.
        process: Process a single raw payload from stdin (for testing/scripting).
            stdin: Raw JSON bytes of a skill-completed event payload.

    Always exits 0 (fail-open).

    Usage:
        python skill_execution_log_subscriber.py run
        echo '<payload_json>' | python skill_execution_log_subscriber.py process
    """
    try:
        if len(sys.argv) < 2:
            print(
                "Usage: skill_execution_log_subscriber.py <run|process>",
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
                result = process_skill_completed_event(raw)
                print(json.dumps({"processed": result}))
            else:
                print(json.dumps({"processed": False}))

        else:
            print(f"Unknown mode: {mode}", file=sys.stderr)

    except Exception as exc:
        # Silent failure — never crash
        print(f"skill_execution_log_subscriber error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()


__all__ = [
    "SKILL_COMPLETED_TOPIC",
    "DEFAULT_GROUP_ID",
    "process_skill_completed_event",
    "run_subscriber",
    "run_subscriber_background",
]
