# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Golden chain publish effect node — publish to Kafka, poll DB, assert, cleanup.

EFFECT node that:
1. Publishes a synthetic event to Kafka
2. Polls omnidash_analytics for the projected row (by correlation_id)
3. Runs assertions against the projected row
4. Cleans up the synthetic row
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from omniclaude.lib.kafka_publisher_base import (
    create_event_envelope,
    publish_to_kafka,
)
from omniclaude.nodes.node_golden_chain_payload_compute.models.model_enriched_payload import (
    ModelEnrichedPayload,
)
from omniclaude.nodes.node_golden_chain_publish_effect.models.model_chain_result import (
    ModelChainResult,
)
from plugins.onex.skills._golden_path_validate.golden_path_runner import (
    AssertionEngine,
    _get_nested,
)

logger = logging.getLogger(__name__)


async def run_chain(
    payload: ModelEnrichedPayload,
    *,
    bootstrap_servers: str,
    db_dsn: str,
) -> ModelChainResult:
    """Execute a single chain: publish -> poll -> assert -> cleanup.

    Args:
        payload: Enriched payload from the compute node.
        bootstrap_servers: Kafka bootstrap servers string (passed for compat; resolved
            from KAFKA_BOOTSTRAP_SERVERS env var by the shared publisher).
        db_dsn: PostgreSQL DSN for omnidash_analytics.

    Returns:
        ModelChainResult with publish/projection status and assertion results.
    """
    import psycopg2  # noqa: PLC0415

    assertion_engine = AssertionEngine()

    # Step 1: Publish to Kafka via shared publisher abstraction
    try:
        envelope = create_event_envelope(
            event_type_value=payload.head_topic,
            payload=payload.fixture,
            correlation_id=payload.correlation_id,
            schema_ref=f"golden-chain/{payload.chain_name}",
        )
        publish_start = time.monotonic()
        published = await publish_to_kafka(
            topic=payload.head_topic,
            envelope=envelope,
            partition_key=payload.correlation_id,
        )
        publish_latency_ms = (time.monotonic() - publish_start) * 1000.0
        if not published:
            raise RuntimeError("Shared publisher returned False (producer unavailable)")
        publish_status = "ok"
    except Exception as exc:  # noqa: BLE001 — boundary: publish errors must degrade gracefully
        logger.error("Kafka publish failed for chain %s: %s", payload.chain_name, exc)
        return ModelChainResult(
            chain_name=payload.chain_name,
            correlation_id=payload.correlation_id,
            publish_status="error",
            publish_latency_ms=-1,
            projection_status="error",
            projection_latency_ms=-1,
            error_reason=f"Kafka publish failed: {exc}",
        )

    # Step 2: Poll omnidash_analytics for projected row
    timeout_s = payload.timeout_ms / 1000.0
    poll_interval_s = 0.5
    poll_start = time.monotonic()
    projected_row: dict[str, Any] | None = None  # ONEX_EXCLUDE: dict_str_any

    # Validate tail_table against allowed identifier pattern
    import re  # noqa: PLC0415

    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", payload.tail_table):
        return ModelChainResult(
            chain_name=payload.chain_name,
            correlation_id=payload.correlation_id,
            publish_status=publish_status,
            publish_latency_ms=publish_latency_ms,
            projection_status="error",
            projection_latency_ms=-1,
            error_reason=f"Invalid tail_table identifier: {payload.tail_table}",
        )

    # Determine lookup column and value (supports tables without correlation_id)
    lookup_column = payload.lookup_column or "correlation_id"
    lookup_value = payload.lookup_value or payload.correlation_id

    # Validate lookup_column against allowed identifier pattern
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", lookup_column):
        return ModelChainResult(
            chain_name=payload.chain_name,
            correlation_id=payload.correlation_id,
            publish_status=publish_status,
            publish_latency_ms=publish_latency_ms,
            projection_status="error",
            projection_latency_ms=-1,
            error_reason=f"Invalid lookup_column identifier: {lookup_column}",
        )

    conn = None
    try:
        conn = psycopg2.connect(db_dsn)
        conn.autocommit = True
        cur = conn.cursor()

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            cur.execute(
                f"SELECT * FROM {payload.tail_table} "  # noqa: S608  # nosec B608 — table and column names validated above
                f"WHERE {lookup_column} = %s LIMIT 1",  # noqa: S608  # nosec B608
                (lookup_value,),
            )
            row = cur.fetchone()
            if row is not None:
                description = cur.description or []
                col_names = [desc[0] for desc in description]
                projected_row = dict(zip(col_names, row))
                break
            await asyncio.sleep(poll_interval_s)

        projection_latency_ms = (time.monotonic() - poll_start) * 1000.0

        if projected_row is None:
            return ModelChainResult(
                chain_name=payload.chain_name,
                correlation_id=payload.correlation_id,
                publish_status=publish_status,
                publish_latency_ms=publish_latency_ms,
                projection_status="timeout",
                projection_latency_ms=projection_latency_ms,
            )

        # Step 3: Run assertions
        enriched_assertions = [
            {
                "field": a.field,
                "op": a.op,
                "expected": a.expected,
                "actual": _get_nested(projected_row, a.field),
            }
            for a in payload.assertions
        ]
        assertion_results = assertion_engine.evaluate_all(enriched_assertions)
        all_pass = all(r["passed"] for r in assertion_results)

        raw_preview = json.dumps(projected_row, default=str)[:500]

        projection_status = "pass" if all_pass else "fail"

        # Step 4: Cleanup synthetic row
        try:
            cur.execute(
                f"DELETE FROM {payload.tail_table} "  # noqa: S608  # nosec B608 — table and column names validated above
                f"WHERE {lookup_column} = %s",  # noqa: S608  # nosec B608
                (lookup_value,),
            )
            logger.info(
                "Cleaned up synthetic row from %s (%s=%s)",
                payload.tail_table,
                lookup_column,
                lookup_value,
            )
        except Exception as cleanup_exc:  # noqa: BLE001 — cleanup failure is non-fatal
            logger.warning("Cleanup failed for %s: %s", payload.tail_table, cleanup_exc)

        cur.close()

        return ModelChainResult(
            chain_name=payload.chain_name,
            correlation_id=payload.correlation_id,
            publish_status=publish_status,
            publish_latency_ms=publish_latency_ms,
            projection_status=projection_status,
            projection_latency_ms=projection_latency_ms,
            assertion_results=assertion_results,
            raw_row_preview=raw_preview,
        )

    except Exception as exc:  # noqa: BLE001 — boundary: DB poll errors must degrade gracefully
        logger.error("DB poll failed for chain %s: %s", payload.chain_name, exc)
        return ModelChainResult(
            chain_name=payload.chain_name,
            correlation_id=payload.correlation_id,
            publish_status=publish_status,
            publish_latency_ms=publish_latency_ms,
            projection_status="error",
            projection_latency_ms=(time.monotonic() - poll_start) * 1000.0,
            error_reason=f"DB poll failed: {exc}",
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001, S110  # nosec B110 — cleanup close is best-effort
                pass


__all__ = ["run_chain"]
