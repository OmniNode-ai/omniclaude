# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Golden chain status reducer — aggregates chain results into sweep summary."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from omniclaude.nodes.node_golden_chain_publish_effect.models.model_chain_result import (
    ModelChainResult,
)
from omniclaude.nodes.node_golden_chain_status_reducer.models.model_sweep_summary import (
    ModelChainSummary,
    ModelSweepSummary,
)


def reduce_results(
    chain_results: list[ModelChainResult],
    *,
    sweep_started_at: str,
    sweep_id: str | None = None,
) -> ModelSweepSummary:
    """Aggregate per-chain results into a sweep summary.

    Args:
        chain_results: List of chain results from publish_effect.
        sweep_started_at: ISO-8601 timestamp when the sweep started.
        sweep_id: Optional sweep ID. Generated if not provided.

    Returns:
        ModelSweepSummary with overall status and counts.
    """
    if sweep_id is None:
        sweep_id = str(uuid4())

    sweep_completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    chain_summaries: list[ModelChainSummary] = []
    pass_count = 0
    fail_count = 0
    timeout_count = 0
    error_count = 0

    for result in chain_results:
        status = result.projection_status
        if result.publish_status == "error":
            status = "error"

        if status == "pass":
            pass_count += 1
        elif status == "timeout":
            timeout_count += 1
        elif status == "error":
            error_count += 1
        else:
            fail_count += 1

        chain_summaries.append(
            ModelChainSummary(
                name=result.chain_name,
                status=status,
                publish_latency_ms=result.publish_latency_ms,
                projection_latency_ms=result.projection_latency_ms,
            )
        )

    total = len(chain_results)
    if pass_count == total:
        overall_status = "pass"
    elif pass_count == 0:
        overall_status = "fail"
    else:
        overall_status = "partial"

    return ModelSweepSummary(
        sweep_id=sweep_id,
        sweep_started_at=sweep_started_at,
        sweep_completed_at=sweep_completed_at,
        overall_status=overall_status,
        chains=tuple(chain_summaries),
        pass_count=pass_count,
        fail_count=fail_count,
        timeout_count=timeout_count,
        error_count=error_count,
    )


__all__ = ["reduce_results"]
