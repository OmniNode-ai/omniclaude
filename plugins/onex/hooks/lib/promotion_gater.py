"""Promotion gater -- M5.

Evaluates whether a pattern should be promoted based on measurement evidence.
Composes M3 evidence assessment (detect_flakes, dimension evidence) with
promotion-specific policy: failure blocks, flake blocks, insufficient evidence
warns, regression above threshold warns, all clear allows.

Tier mapping to ContractPromotionGate.gate_result:
    block → "fail"
    warn  → "insufficient_evidence"
    allow → "pass"

Extensions carry the promotion-specific tier and human-readable reasons
for downstream consumers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from omnibase_spi.contracts.measurement.contract_measurement_context import (
    derive_baseline_key,
)
from omnibase_spi.contracts.measurement.contract_promotion_gate import (
    ContractDimensionEvidence,
    ContractPromotionGate,
)
from pydantic import BaseModel, ConfigDict

from plugins.onex.hooks.lib.metrics_aggregator import (
    _get_total_tokens,
    _make_dimension_evidence,
    detect_flakes,
)

if TYPE_CHECKING:
    from omnibase_spi.contracts.measurement.contract_aggregated_run import (
        ContractAggregatedRun,
    )
    from omnibase_spi.contracts.measurement.contract_measurement_context import (
        ContractMeasurementContext,
    )


class PromotionThresholds(BaseModel):
    """Contract-driven regression thresholds for promotion gating.

    Each field specifies the maximum acceptable percentage increase
    for the corresponding dimension.  Values above the threshold
    trigger a "warn" gate result.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    duration_regression_pct: float = 20.0
    token_regression_pct: float = 30.0


def evaluate_promotion_gate(
    candidate: ContractAggregatedRun,
    baseline: ContractAggregatedRun | None,
    context: ContractMeasurementContext | None = None,
    *,
    thresholds: PromotionThresholds | None = None,
) -> ContractPromotionGate:
    """Evaluate whether a pattern should be promoted.

    Checks are applied in strict priority order (first match wins):

    1. Candidate failed → block (gate_result="fail")
    2. Flake detected   → block (gate_result="fail")
    3. No context / no pattern_id / no baseline → warn (gate_result="insufficient_evidence")
    4. Zero-baseline on any dimension → warn (gate_result="insufficient_evidence")
    5. Duration regression > threshold → warn (gate_result="insufficient_evidence")
    6. Token regression > threshold   → warn (gate_result="insufficient_evidence")
    7. All clear → allow (gate_result="pass")

    The ``extensions`` dict on the returned gate carries:
        promotion_tier: "block" | "warn" | "allow"
        promotion_reasons: list[str]
    """
    if thresholds is None:
        thresholds = PromotionThresholds()

    run_id = candidate.run_id
    required = ["duration", "tokens", "tests"]

    # -- Check 1: candidate overall failure --------------------------------
    if candidate.overall_result == "failure":
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="fail",
            tier="block",
            reasons=["Candidate run failed (overall_result=failure)"],
            dimensions=[],
            required=required,
        )

    # -- Check 2: flake detection ------------------------------------------
    flakes = detect_flakes(candidate.phase_metrics)
    flaky_phases = [phase.value for phase, is_flaky in flakes.items() if is_flaky]
    if flaky_phases:
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="fail",
            tier="block",
            reasons=[f"Flake detected in phases: {', '.join(flaky_phases)}"],
            dimensions=[],
            required=required,
        )

    # -- Check 3: insufficient context / baseline --------------------------
    if context is None or not context.pattern_id:
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="insufficient_evidence",
            tier="warn",
            reasons=["No measurement context or pattern_id available"],
            dimensions=[],
            required=required,
        )

    if baseline is None:
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="insufficient_evidence",
            tier="warn",
            reasons=["No baseline available for comparison"],
            dimensions=[],
            required=required,
        )

    # -- Build dimension evidence ------------------------------------------
    dimensions = _build_dimensions(candidate, baseline)

    # -- Check 4: zero-baseline on any dimension ---------------------------
    zero_dims = [d.dimension for d in dimensions if d.delta_pct is None]
    if zero_dims:
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="insufficient_evidence",
            tier="warn",
            reasons=[
                f"Zero baseline for dimensions: {', '.join(zero_dims)} "
                "(cannot compute meaningful delta)"
            ],
            dimensions=dimensions,
            required=required,
        )

    # -- Check 5 & 6: regression thresholds --------------------------------
    regression_reasons = _check_regressions(dimensions, thresholds)
    if regression_reasons:
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="insufficient_evidence",
            tier="warn",
            reasons=regression_reasons,
            dimensions=dimensions,
            required=required,
        )

    # -- Check 7: all clear ------------------------------------------------
    return _gate(
        run_id=run_id,
        context=context,
        gate_result="pass",
        tier="allow",
        reasons=["Evidence supports promotion"],
        dimensions=dimensions,
        required=required,
    )


# -- Internal helpers --------------------------------------------------------


def _gate(
    *,
    run_id: str,
    context: ContractMeasurementContext | None,
    gate_result: Literal["pass", "fail", "insufficient_evidence"],
    tier: Literal["block", "warn", "allow"],
    reasons: list[str],
    dimensions: list[ContractDimensionEvidence],
    required: list[str],
) -> ContractPromotionGate:
    baseline_key = ""
    if context is not None and context.pattern_id:
        baseline_key = derive_baseline_key(context)

    sufficient_count = sum(1 for d in dimensions if d.sufficient)

    return ContractPromotionGate(
        run_id=run_id,
        context=context,
        baseline_key=baseline_key,
        gate_result=gate_result,
        dimensions=dimensions,
        required_dimensions=required,
        sufficient_count=sufficient_count,
        total_count=len(dimensions),
        extensions={
            "promotion_tier": tier,
            "promotion_reasons": reasons,
        },
    )


def _build_dimensions(
    candidate: ContractAggregatedRun,
    baseline: ContractAggregatedRun,
) -> list[ContractDimensionEvidence]:
    return [
        _make_dimension_evidence(
            "duration",
            baseline.total_duration_ms or 0.0,
            candidate.total_duration_ms or 0.0,
        ),
        _make_dimension_evidence(
            "tokens",
            float(_get_total_tokens(baseline)),
            float(_get_total_tokens(candidate)),
        ),
        _make_dimension_evidence(
            "tests",
            float(_get_total_tests(baseline)),
            float(_get_total_tests(candidate)),
        ),
    ]


def _get_total_tests(run: ContractAggregatedRun) -> int:
    total = 0
    for m in run.phase_metrics:
        if m.tests is not None:
            total += m.tests.total_tests
    return total


def _check_regressions(
    dimensions: list[ContractDimensionEvidence],
    thresholds: PromotionThresholds,
) -> list[str]:
    """Check each dimension against its regression threshold.

    Returns a list of human-readable reason strings for any threshold
    violations.  Empty list means all dimensions are within limits.
    """
    reasons: list[str] = []

    threshold_map: dict[str, float] = {
        "duration": thresholds.duration_regression_pct,
        "tokens": thresholds.token_regression_pct,
    }

    for dim in dimensions:
        limit = threshold_map.get(dim.dimension)
        if limit is None:
            continue
        if dim.delta_pct is not None and dim.delta_pct > limit:
            reasons.append(
                f"{dim.dimension} regression {dim.delta_pct:.1f}% "
                f"exceeds threshold {limit:.1f}%"
            )

    return reasons
