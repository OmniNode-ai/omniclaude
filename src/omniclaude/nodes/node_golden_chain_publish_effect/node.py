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

from aiokafka import AIOKafkaProducer

from plugins.onex.skills._golden_path_validate.golden_path_runner import (
    AssertionEngine,
    _get_nested,
)

from omniclaude.nodes.node_golden_chain_payload_compute.models.model_enriched_payload import (
    ModelEnrichedPayload,
)
from omniclaude.nodes.node_golden_chain_publish_effect.models.model_chain_result import (
    ModelChainResult,
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
        bootstrap_servers: Kafka bootstrap servers string.
        db_dsn: PostgreSQL DSN for omnidash_analytics.

    Returns:
        ModelChainResult with publish/projection status and assertion results.
    """
    import psycopg2  # noqa: PLC0415

    assertion_engine = AssertionEngine()

    # Step 1: Publish to Kafka
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)
    try:
        await producer.start()
        fixture_bytes = json.dumps(payload.fixture).encode()
        publish_start = time.monotonic()
        await producer.send_and_wait(payload.head_topic, value=fixture_bytes)
        publish_latency_ms = (time.monotonic() - publish_start) * 1000.0
        publish_status = "ok"
    except Exception as exc:
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
    finally:
        try:
            await producer.stop()
        except Exception:
            pass

    # Step 2: Poll omnidash_analytics for projected row
    timeout_s = payload.timeout_ms / 1000.0
    poll_interval_s = 0.5
    poll_start = time.monotonic()
    projected_row: dict[str, Any] | None = None

    try:
        conn = psycopg2.connect(db_dsn)
        conn.autocommit = True
        cur = conn.cursor()

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            cur.execute(
                f"SELECT * FROM {payload.tail_table} "  # noqa: S608
                "WHERE correlation_id = %s LIMIT 1",
                (payload.correlation_id,),
            )
            row = cur.fetchone()
            if row is not None:
                col_names = [desc[0] for desc in cur.description]
                projected_row = dict(zip(col_names, row))
                break
            await asyncio.sleep(poll_interval_s)

        projection_latency_ms = (time.monotonic() - poll_start) * 1000.0

        if projected_row is None:
            cur.close()
            conn.close()
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
                f"DELETE FROM {payload.tail_table} "  # noqa: S608
                "WHERE correlation_id = %s",
                (payload.correlation_id,),
            )
            logger.info(
                "Cleaned up synthetic row from %s (correlation_id=%s)",
                payload.tail_table,
                payload.correlation_id,
            )
        except Exception as cleanup_exc:
            logger.warning(
                "Cleanup failed for %s: %s", payload.tail_table, cleanup_exc
            )

        cur.close()
        conn.close()

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

    except Exception as exc:
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


__all__ = ["run_chain"]
