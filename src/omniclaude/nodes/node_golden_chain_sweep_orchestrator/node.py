# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Golden chain sweep orchestrator — coordinates the full validation sweep.

ORCHESTRATOR node that:
1. Invokes payload_compute to build all payloads
2. Runs publish_effect in parallel for all chains (asyncio.gather)
3. Invokes status_reducer to aggregate results
4. Persists sweep results to golden_chain_sweep_results table
5. Writes evidence artifact to $ONEX_STATE_DIR/golden-chain-sweep/
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from omniclaude.nodes.node_golden_chain_payload_compute.node import build_payloads
from omniclaude.nodes.node_golden_chain_publish_effect.models.model_chain_result import (
    ModelChainResult,
)
from omniclaude.nodes.node_golden_chain_publish_effect.node import run_chain
from omniclaude.nodes.node_golden_chain_publish_effect.persist import (
    persist_sweep_results,
)
from omniclaude.nodes.node_golden_chain_status_reducer.models.model_sweep_summary import (
    ModelSweepSummary,
)
from omniclaude.nodes.node_golden_chain_status_reducer.node import reduce_results
from omniclaude.nodes.node_golden_chain_sweep_orchestrator.models.model_sweep_request import (
    ModelSweepRequest,
)

logger = logging.getLogger(__name__)


async def run_sweep(
    request: ModelSweepRequest,
    *,
    bootstrap_servers: str,
    db_dsn: str,
) -> ModelSweepSummary:
    """Execute the full golden chain validation sweep.

    Args:
        request: Sweep configuration with optional chain filter.
        bootstrap_servers: Kafka bootstrap servers string.
        db_dsn: PostgreSQL DSN for omnidash_analytics.

    Returns:
        ModelSweepSummary with per-chain results and overall status.
    """
    sweep_id = str(uuid4())
    sweep_started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    # Step 1: Build payloads
    payloads = build_payloads(
        chain_filter=request.chain_filter,
        timeout_ms=request.timeout_ms,
    )
    logger.info("Golden chain sweep %s: built %d payloads", sweep_id, len(payloads))

    # Step 2: Run all chains in parallel
    chain_results: list[ModelChainResult] = list(
        await asyncio.gather(
            *(
                run_chain(
                    payload,
                    bootstrap_servers=bootstrap_servers,
                    db_dsn=db_dsn,
                )
                for payload in payloads
            )
        )
    )

    # Step 3: Reduce results
    summary = reduce_results(
        chain_results,
        sweep_started_at=sweep_started_at,
        sweep_id=sweep_id,
    )

    # Step 4: Persist to golden_chain_sweep_results (runs in effect node — DB access is
    # correctly scoped outside this orchestrator per arch-no-db-in-orchestrator)
    await persist_sweep_results(summary, chain_results, db_dsn=db_dsn)

    # Step 5: Write evidence artifact
    _write_evidence(summary, chain_results)

    logger.info(
        "Golden chain sweep %s completed: %s (%d pass, %d fail, %d timeout, %d error)",
        sweep_id,
        summary.overall_status,
        summary.pass_count,
        summary.fail_count,
        summary.timeout_count,
        summary.error_count,
    )

    return summary


def _write_evidence(
    summary: ModelSweepSummary,
    chain_results: list[ModelChainResult],
    *,
    _state_dir: Path | None = None,
) -> None:
    """Write evidence artifact to $ONEX_STATE_DIR/golden-chain-sweep/."""
    try:
        if _state_dir is not None:
            base_dir = _state_dir
        else:
            from plugins.onex.hooks.lib.onex_state import (
                ensure_state_dir,  # noqa: PLC0415
            )

            base_dir = ensure_state_dir("golden-chain-sweep")

        date_str = summary.sweep_started_at[:10]
        artifact_dir = base_dir / date_str / summary.sweep_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        artifact: dict[str, Any] = {  # ONEX_EXCLUDE: dict_str_any
            "sweep_id": summary.sweep_id,
            "sweep_started_at": summary.sweep_started_at,
            "sweep_completed_at": summary.sweep_completed_at,
            "overall_status": summary.overall_status,
            "pass_count": summary.pass_count,
            "fail_count": summary.fail_count,
            "timeout_count": summary.timeout_count,
            "error_count": summary.error_count,
            "chains": [
                {
                    "name": r.chain_name,
                    "correlation_id": r.correlation_id,
                    "publish_status": r.publish_status,
                    "publish_latency_ms": r.publish_latency_ms,
                    "projection_status": r.projection_status,
                    "projection_latency_ms": r.projection_latency_ms,
                    "assertion_results": r.assertion_results,
                    "raw_row_preview": r.raw_row_preview,
                    "error_reason": r.error_reason,
                }
                for r in chain_results
            ],
        }

        artifact_path = artifact_dir / "sweep_results.json"
        artifact_path.write_text(
            json.dumps(artifact, indent=2, default=str), encoding="utf-8"
        )
        logger.info("Evidence artifact written: %s", artifact_path)
    except Exception:  # noqa: BLE001 — evidence writing is best-effort; never crash the sweep
        logger.warning("Failed to write evidence artifact; skipping")


__all__ = ["run_sweep"]
