"""Metrics aggregation reducer -- M3.

Rolls up per-phase ContractPhaseMetrics into ContractAggregatedRun,
detects flakes via outcome signatures, manages baseline storage,
and assesses per-dimension evidence sufficiency.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from omnibase_spi.contracts.measurement.contract_aggregated_run import (
    ContractAggregatedRun,
)
from omnibase_spi.contracts.measurement.contract_measurement_context import (
    ContractMeasurementContext,
    derive_baseline_key,
)
from omnibase_spi.contracts.measurement.contract_promotion_gate import (
    ContractDimensionEvidence,
    ContractPromotionGate,
)
from omnibase_spi.contracts.measurement.enum_pipeline_phase import (
    ContractEnumPipelinePhase,
)
from omnibase_spi.contracts.measurement.enum_result_classification import (
    ContractEnumResultClassification,
)

if TYPE_CHECKING:
    from omnibase_spi.contracts.measurement.contract_phase_metrics import (
        ContractPhaseMetrics,
    )

ALL_PHASES: frozenset[ContractEnumPipelinePhase] = frozenset(ContractEnumPipelinePhase)

BASELINES_ROOT = Path.home() / ".claude" / "baselines"


# -- Outcome signatures (flake detection) ------------------------------------


def compute_outcome_signature(metrics: ContractPhaseMetrics) -> str:
    """Compute a machine-stable outcome signature for flake detection.

    Hashes result_classification + sorted(failed_tests) + sorted(error_codes)
    + skip_reason_code.  error_messages are excluded (unstable after redaction).

    Returns:
        16-character hex digest.
    """
    outcome = metrics.outcome
    if outcome is None:
        return hashlib.sha256(b"no-outcome").hexdigest()[:16]

    parts: list[str] = [
        outcome.result_classification.value,
        f"ft:{len(outcome.failed_tests)}",
        *sorted(outcome.failed_tests),
        f"ec:{len(outcome.error_codes)}",
        *sorted(outcome.error_codes),
        outcome.skip_reason_code,
    ]
    raw = "\0".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def detect_flakes(
    phase_metrics: list[ContractPhaseMetrics],
) -> dict[ContractEnumPipelinePhase, bool]:
    """Detect flaky phases by comparing outcome signatures across attempts.

    A phase is flaky when it has multiple distinct outcome signatures
    (i.e. non-deterministic outcomes across attempts).
    """
    by_phase: dict[ContractEnumPipelinePhase, set[str]] = defaultdict(set)
    for m in phase_metrics:
        sig = compute_outcome_signature(m)
        by_phase[m.phase].add(sig)
    return {phase: len(sigs) > 1 for phase, sigs in by_phase.items()}


# -- Run aggregation ---------------------------------------------------------


def aggregate_run(
    phase_metrics: list[ContractPhaseMetrics],
    context: ContractMeasurementContext | None = None,
    *,
    mandatory_phases: set[ContractEnumPipelinePhase] | None = None,
    run_id: str = "",
) -> ContractAggregatedRun:
    """Aggregate per-phase metrics into a run-level summary.

    overall_result semantics:
    - success: all mandatory phases have result_classification=SUCCESS
    - partial: at least one mandatory phase is missing or SKIPPED
    - failure: any mandatory phase has FAILURE or ERROR classification
    """
    if mandatory_phases is None:
        mandatory_phases = set(ALL_PHASES)

    if not run_id and phase_metrics:
        run_id = phase_metrics[0].run_id

    # Index by phase -- keep highest attempt per phase
    by_phase: dict[ContractEnumPipelinePhase, ContractPhaseMetrics] = {}
    for m in phase_metrics:
        existing = by_phase.get(m.phase)
        if existing is None or m.attempt > existing.attempt:
            by_phase[m.phase] = m

    overall_result = _compute_overall_result(by_phase, mandatory_phases)
    total_duration_ms = _sum_durations(phase_metrics)
    total_cost_usd = _sum_costs(phase_metrics)

    mandatory_succeeded = 0
    for phase in mandatory_phases:
        pm = by_phase.get(phase)
        if pm is not None and pm.outcome is not None:
            if (
                pm.outcome.result_classification
                == ContractEnumResultClassification.SUCCESS
            ):
                mandatory_succeeded += 1

    return ContractAggregatedRun(
        run_id=run_id,
        context=context,
        overall_result=overall_result,
        phase_metrics=phase_metrics,
        total_duration_ms=total_duration_ms,
        total_cost_usd=total_cost_usd,
        mandatory_phases_total=len(mandatory_phases),
        mandatory_phases_succeeded=mandatory_succeeded,
    )


def _compute_overall_result(
    by_phase: dict[ContractEnumPipelinePhase, ContractPhaseMetrics],
    mandatory_phases: set[ContractEnumPipelinePhase],
) -> Literal["success", "partial", "failure"]:
    has_failure = False
    has_partial = False

    for phase in mandatory_phases:
        metrics = by_phase.get(phase)
        if metrics is None:
            has_partial = True
            continue
        outcome = metrics.outcome
        if outcome is None:
            has_partial = True
            continue
        rc = outcome.result_classification
        if rc in (
            ContractEnumResultClassification.FAILURE,
            ContractEnumResultClassification.ERROR,
        ):
            has_failure = True
        elif rc in (
            ContractEnumResultClassification.SKIPPED,
            ContractEnumResultClassification.PARTIAL,
        ):
            has_partial = True

    if has_failure:
        return "failure"
    if has_partial:
        return "partial"
    return "success"


def _sum_durations(metrics: list[ContractPhaseMetrics]) -> float | None:
    total = 0.0
    found = False
    for m in metrics:
        if m.duration is not None:
            total += m.duration.wall_clock_ms
            found = True
    return total if found else None


def _sum_costs(metrics: list[ContractPhaseMetrics]) -> float | None:
    total = 0.0
    found = False
    for m in metrics:
        if m.cost is not None and m.cost.estimated_cost_usd is not None:
            total += m.cost.estimated_cost_usd
            found = True
    return total if found else None


# -- Baseline storage --------------------------------------------------------


def save_baseline(
    run: ContractAggregatedRun,
    context: ContractMeasurementContext,
    *,
    baselines_root: Path | None = None,
) -> Path:
    """Persist a run as the baseline for the given context.

    Storage: {baselines_root}/{pattern_id}/{baseline_key}/latest.metrics.json
    Uses atomic write (tmp + rename).
    """
    root = baselines_root or BASELINES_ROOT
    baseline_key = derive_baseline_key(context)
    pattern_id = context.pattern_id or "_no_pattern"

    target_dir = root / pattern_id / baseline_key
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / "latest.metrics.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(run.model_dump_json(indent=2))
    tmp.rename(target)
    return target


def load_baseline(
    context: ContractMeasurementContext,
    *,
    baselines_root: Path | None = None,
) -> ContractAggregatedRun | None:
    """Load the baseline for the given context, or None if not found."""
    root = baselines_root or BASELINES_ROOT
    baseline_key = derive_baseline_key(context)
    pattern_id = context.pattern_id or "_no_pattern"

    target = root / pattern_id / baseline_key / "latest.metrics.json"
    if not target.exists():
        return None

    data = json.loads(target.read_text())
    return ContractAggregatedRun.model_validate(data)


# -- Evidence assessment -----------------------------------------------------


def _get_total_tokens(run: ContractAggregatedRun) -> int:
    total = 0
    for m in run.phase_metrics:
        if m.cost is not None:
            total += m.cost.llm_input_tokens + m.cost.llm_output_tokens
    return total


def _get_total_tests(run: ContractAggregatedRun) -> int:
    total = 0
    for m in run.phase_metrics:
        if m.tests is not None:
            total += m.tests.total_tests
    return total


def _make_dimension_evidence(
    dimension: str,
    baseline_value: float,
    current_value: float,
) -> ContractDimensionEvidence:
    """Create a dimension evidence record with zero-baseline guard.

    When baseline_value == 0:  delta_pct is None, sufficient is False.
    When current_value == 0:   sufficient is False.
    """
    if baseline_value == 0.0:
        return ContractDimensionEvidence(
            dimension=dimension,
            baseline_value=baseline_value,
            current_value=current_value,
            delta_pct=None,
            sufficient=False,
        )

    delta_pct = ((current_value - baseline_value) / baseline_value) * 100.0
    sufficient = current_value > 0.0

    return ContractDimensionEvidence(
        dimension=dimension,
        baseline_value=baseline_value,
        current_value=current_value,
        delta_pct=delta_pct,
        sufficient=sufficient,
    )


def assess_evidence(
    candidate: ContractAggregatedRun,
    baseline: ContractAggregatedRun | None,
    context: ContractMeasurementContext | None = None,
) -> ContractPromotionGate:
    """Assess per-dimension evidence sufficiency for a candidate run.

    Returns ContractPromotionGate with:
    - gate_result='insufficient_evidence' when pattern_id missing or no baseline
    - gate_result='pass' when all required dimensions are sufficient
    - gate_result='fail' when any required dimension is insufficient
    """
    run_id = candidate.run_id
    required = ["duration", "tokens", "tests"]

    if context is None or not context.pattern_id:
        return ContractPromotionGate(
            run_id=run_id,
            context=context,
            baseline_key="",
            gate_result="insufficient_evidence",
            dimensions=[],
            required_dimensions=required,
            sufficient_count=0,
            total_count=0,
        )

    baseline_key = derive_baseline_key(context)

    if baseline is None:
        return ContractPromotionGate(
            run_id=run_id,
            context=context,
            baseline_key=baseline_key,
            gate_result="insufficient_evidence",
            dimensions=[],
            required_dimensions=required,
            sufficient_count=0,
            total_count=0,
        )

    dimensions = [
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

    sufficient_count = sum(1 for d in dimensions if d.sufficient)
    gate_result: Literal["pass", "fail"] = (
        "pass" if sufficient_count == len(required) else "fail"
    )

    return ContractPromotionGate(
        run_id=run_id,
        context=context,
        baseline_key=baseline_key,
        gate_result=gate_result,
        dimensions=dimensions,
        required_dimensions=required,
        sufficient_count=sufficient_count,
        total_count=len(dimensions),
    )
