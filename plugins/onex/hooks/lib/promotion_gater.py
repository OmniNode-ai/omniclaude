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

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

from omnibase_spi.contracts.measurement.contract_measurement_context import (
    derive_baseline_key,
)
from omnibase_spi.contracts.measurement.contract_promotion_gate import (
    ContractDimensionEvidence,
    ContractPromotionGate,
)
from pydantic import BaseModel, ConfigDict, Field

from plugins.onex.hooks.lib.metrics_aggregator import (
    REQUIRED_DIMENSIONS,
    build_dimension_evidence_list,
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

    ``duration_regression_pct`` / ``token_regression_pct``: maximum
    acceptable percentage *increase* (positive delta).

    ``test_decrease_pct``: maximum acceptable percentage *decrease*
    in test count (negative delta).  A candidate that drops more than
    this percentage of tests relative to baseline triggers a warn.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    duration_regression_pct: float = Field(default=20.0, ge=0.0)
    token_regression_pct: float = Field(default=30.0, ge=0.0)
    test_decrease_pct: float = Field(default=20.0, ge=0.0)


def evaluate_promotion_gate(
    candidate: ContractAggregatedRun,
    baseline: ContractAggregatedRun | None,
    context: ContractMeasurementContext | None = None,
    *,
    thresholds: PromotionThresholds | None = None,
) -> ContractPromotionGate:
    """Evaluate whether a pattern should be promoted.

    Checks are applied in strict priority order (first match wins):

    1a. Candidate failed  → block (gate_result="fail")
    1b. Candidate partial → warn  (gate_result="insufficient_evidence")
    1c. Unexpected result → warn  (gate_result="insufficient_evidence")
    2.  Flake detected    → block (gate_result="fail")
    3.  No context / no pattern_id / no baseline → warn (gate_result="insufficient_evidence")
    4.  Insufficient evidence on any dimension → warn (early exit, skips regression checks)
    5.  Duration regression > threshold → warn (gate_result="insufficient_evidence")
    6a. Token regression > threshold    → warn (gate_result="insufficient_evidence")
    6b. Test count decrease > threshold → warn (gate_result="insufficient_evidence")
    7.  All clear → allow (gate_result="pass")

    The ``extensions`` dict on the returned gate carries:
        promotion_tier: "block" | "warn" | "allow"
        promotion_reasons: list[str]
    """
    if thresholds is None:
        thresholds = PromotionThresholds()

    run_id = candidate.run_id

    # -- Check 1a: candidate overall failure --------------------------------
    if candidate.overall_result == "failure":
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="fail",
            tier="block",
            reasons=["Candidate run failed (overall_result=failure)"],
            dimensions=[],
            required=REQUIRED_DIMENSIONS,
        )

    # -- Check 1b: candidate partial run ------------------------------------
    if candidate.overall_result == "partial":
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="insufficient_evidence",
            tier="warn",
            reasons=["Candidate run is partial (not all phases completed)"],
            dimensions=[],
            required=REQUIRED_DIMENSIONS,
        )

    # -- Check 1c: unexpected overall_result --------------------------------
    # Upstream _compute_overall_result returns Literal["success", "partial",
    # "failure"] so this guard should be unreachable today.  We warn rather
    # than block because an unknown result doesn't necessarily indicate
    # failure -- it may be a new benign classification.
    if candidate.overall_result != "success":
        return _gate(  # type: ignore[unreachable]
            run_id=run_id,
            context=context,
            gate_result="insufficient_evidence",
            tier="warn",
            reasons=[f"Unexpected overall_result={candidate.overall_result!r}"],
            dimensions=[],
            required=REQUIRED_DIMENSIONS,
        )

    # -- Check 2: flake detection ------------------------------------------
    flakes = detect_flakes(candidate.phase_metrics)
    flaky_phases = sorted(phase.value for phase, is_flaky in flakes.items() if is_flaky)
    if flaky_phases:
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="fail",
            tier="block",
            reasons=[f"Flake detected in phases: {', '.join(flaky_phases)}"],
            dimensions=[],
            required=REQUIRED_DIMENSIONS,
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
            required=REQUIRED_DIMENSIONS,
        )

    if baseline is None:
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="insufficient_evidence",
            tier="warn",
            reasons=["No baseline available for comparison"],
            dimensions=[],
            required=REQUIRED_DIMENSIONS,
        )

    # -- Build dimension evidence ------------------------------------------
    dimensions = build_dimension_evidence_list(candidate, baseline)

    # -- Check 4: insufficient evidence on any dimension --------------------
    #    Covers both zero-baseline (delta_pct=None) and zero-current
    #    (current_value=0, sufficient=False) cases.
    insuf_dims = [d.dimension for d in dimensions if not d.sufficient]
    if insuf_dims:
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="insufficient_evidence",
            tier="warn",
            reasons=[
                f"Insufficient evidence for dimensions: {', '.join(insuf_dims)} "
                "(zero baseline or zero current value)"
            ],
            dimensions=dimensions,
            required=REQUIRED_DIMENSIONS,
        )

    # -- Check 5, 6a, 6b: regression thresholds -----------------------------
    regression_reasons = _check_regressions(dimensions, thresholds)
    if regression_reasons:
        return _gate(
            run_id=run_id,
            context=context,
            gate_result="insufficient_evidence",
            tier="warn",
            reasons=regression_reasons,
            dimensions=dimensions,
            required=REQUIRED_DIMENSIONS,
        )

    # -- Check 7: all clear ------------------------------------------------
    return _gate(
        run_id=run_id,
        context=context,
        gate_result="pass",
        tier="allow",
        reasons=["Evidence supports promotion"],
        dimensions=dimensions,
        required=REQUIRED_DIMENSIONS,
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
    required: Sequence[str],
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
        required_dimensions=list(required),
        sufficient_count=sufficient_count,
        total_count=len(dimensions),
        extensions={
            "promotion_tier": tier,
            "promotion_reasons": reasons,
        },
    )


def _check_regressions(
    dimensions: list[ContractDimensionEvidence],
    thresholds: PromotionThresholds,
) -> list[str]:
    """Check each dimension against its regression threshold.

    Duration/tokens: flag when delta_pct > positive threshold (increase = bad).
    Tests: flag when delta_pct < -(threshold) (decrease = bad).

    Every dimension must appear in exactly one of ``increase_map`` or
    ``decrease_map``; unmapped dimensions trigger a warning reason so
    that adding a new required dimension without a threshold is caught.

    Returns a list of human-readable reason strings for any threshold
    violations.  Empty list means all dimensions are within limits.
    """
    reasons: list[str] = []

    # Increase = bad (duration, tokens)
    increase_map: dict[str, float] = {
        "duration": thresholds.duration_regression_pct,
        "tokens": thresholds.token_regression_pct,
    }

    # Decrease = bad (tests)
    decrease_map: dict[str, float] = {
        "tests": thresholds.test_decrease_pct,
    }

    all_mapped = set(increase_map) | set(decrease_map)

    for dim in dimensions:
        if dim.dimension not in all_mapped:
            reasons.append(f"{dim.dimension} has no regression threshold configured")
            continue

        # Precondition: check 4 (insufficient evidence) catches all
        # dimensions with delta_pct=None before _check_regressions runs.
        # This guard is defence-in-depth for safety if ordering changes.
        if dim.delta_pct is None:
            continue

        inc_limit = increase_map.get(dim.dimension)
        if inc_limit is not None and dim.delta_pct > inc_limit:
            reasons.append(
                f"{dim.dimension} regression {dim.delta_pct:.1f}% "
                f"exceeds threshold {inc_limit:.1f}%"
            )

        dec_limit = decrease_map.get(dim.dimension)
        if dec_limit is not None and dim.delta_pct < -dec_limit:
            reasons.append(
                f"{dim.dimension} decreased {abs(dim.delta_pct):.1f}% "
                f"exceeds threshold {dec_limit:.1f}%"
            )

    return reasons
