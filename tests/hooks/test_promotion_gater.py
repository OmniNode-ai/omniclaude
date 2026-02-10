# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for promotion_gater module (M5).

Covers: block on failure, block on flake, warn on insufficient evidence,
warn on regression, allow when clear, custom thresholds, zero-baseline guard,
and extensions metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from omnibase_spi.contracts.measurement.contract_measurement_context import (
    ContractMeasurementContext,
)
from omnibase_spi.contracts.measurement.contract_phase_metrics import (
    ContractCostMetrics,
    ContractDurationMetrics,
    ContractOutcomeMetrics,
    ContractPhaseMetrics,
    ContractTestMetrics,
)
from omnibase_spi.contracts.measurement.enum_pipeline_phase import (
    ContractEnumPipelinePhase,
)
from omnibase_spi.contracts.measurement.enum_result_classification import (
    ContractEnumResultClassification,
)

if TYPE_CHECKING:
    from omnibase_spi.contracts.measurement.contract_aggregated_run import (
        ContractAggregatedRun,
    )

pytestmark = pytest.mark.unit

# -- Factories ---------------------------------------------------------------


def _make_phase(
    phase: ContractEnumPipelinePhase,
    rc: ContractEnumResultClassification = ContractEnumResultClassification.SUCCESS,
    *,
    run_id: str = "run-1",
    attempt: int = 1,
    wall_clock_ms: float = 100.0,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    total_tests: int = 10,
    failed_tests: list[str] | None = None,
    error_codes: list[str] | None = None,
) -> ContractPhaseMetrics:
    return ContractPhaseMetrics(
        run_id=run_id,
        phase=phase,
        attempt=attempt,
        duration=ContractDurationMetrics(wall_clock_ms=wall_clock_ms),
        cost=ContractCostMetrics(
            llm_input_tokens=input_tokens,
            llm_output_tokens=output_tokens,
            llm_total_tokens=input_tokens + output_tokens,
            estimated_cost_usd=0.50,
        ),
        outcome=ContractOutcomeMetrics(
            result_classification=rc,
            failed_tests=failed_tests or [],
            error_codes=error_codes or [],
        ),
        tests=ContractTestMetrics(total_tests=total_tests),
    )


def _make_context(
    *,
    ticket_id: str = "OMN-TEST",
    pattern_id: str = "p1",
    repo_id: str = "repo",
) -> ContractMeasurementContext:
    return ContractMeasurementContext(
        ticket_id=ticket_id,
        pattern_id=pattern_id,
        repo_id=repo_id,
    )


def _all_phases_success(
    run_id: str = "run-1",
    wall_clock_ms: float = 100.0,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    total_tests: int = 10,
) -> list[ContractPhaseMetrics]:
    return [
        _make_phase(
            phase,
            run_id=run_id,
            wall_clock_ms=wall_clock_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tests=total_tests,
        )
        for phase in ContractEnumPipelinePhase
    ]


def _aggregate(
    metrics: list[ContractPhaseMetrics],
    context: ContractMeasurementContext | None = None,
    run_id: str = "",
) -> ContractAggregatedRun:
    from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

    return aggregate_run(metrics, context=context, run_id=run_id)


# =============================================================================
# Block on failure
# =============================================================================


class TestBlockOnFailure:
    def test_failure_overall_result_blocks(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        # Candidate with a failed phase
        metrics = list(_all_phases_success(run_id="c"))
        metrics = [m for m in metrics if m.phase != ContractEnumPipelinePhase.VERIFY]
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.VERIFY,
                ContractEnumResultClassification.FAILURE,
                run_id="c",
            )
        )
        candidate = _aggregate(metrics, context=ctx, run_id="c")
        baseline = _aggregate(_all_phases_success(run_id="b"), context=ctx, run_id="b")

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "fail"
        assert gate.extensions["promotion_tier"] == "block"
        assert "failed" in gate.extensions["promotion_reasons"][0].lower()

    def test_error_overall_result_blocks(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        metrics = list(_all_phases_success(run_id="c"))
        metrics = [m for m in metrics if m.phase != ContractEnumPipelinePhase.IMPLEMENT]
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.IMPLEMENT,
                ContractEnumResultClassification.ERROR,
                run_id="c",
            )
        )
        candidate = _aggregate(metrics, context=ctx, run_id="c")
        baseline = _aggregate(_all_phases_success(run_id="b"), context=ctx, run_id="b")

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "fail"
        assert gate.extensions["promotion_tier"] == "block"

    def test_partial_overall_result_warns(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        # Candidate missing VERIFY phase entirely → overall_result="partial"
        metrics = [
            _make_phase(phase, run_id="c")
            for phase in ContractEnumPipelinePhase
            if phase != ContractEnumPipelinePhase.VERIFY
        ]
        candidate = _aggregate(metrics, context=ctx, run_id="c")
        baseline = _aggregate(_all_phases_success(run_id="b"), context=ctx, run_id="b")

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "insufficient_evidence"
        assert gate.extensions["promotion_tier"] == "warn"
        assert "partial" in gate.extensions["promotion_reasons"][0].lower()


# =============================================================================
# Block on flake
# =============================================================================


class TestBlockOnFlake:
    def test_flaky_phase_blocks(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        # Two attempts of VERIFY with different outcomes → flaky
        # Attempt 1 fails, attempt 2 succeeds → overall_result="success"
        # but different signatures → flake detected
        metrics = [
            _make_phase(phase, run_id="c")
            for phase in ContractEnumPipelinePhase
            if phase != ContractEnumPipelinePhase.VERIFY
        ]
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.VERIFY,
                ContractEnumResultClassification.FAILURE,
                run_id="c",
                attempt=1,
                failed_tests=["test_flaky"],
            )
        )
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.VERIFY,
                ContractEnumResultClassification.SUCCESS,
                run_id="c",
                attempt=2,
            )
        )
        candidate = _aggregate(metrics, context=ctx, run_id="c")
        baseline = _aggregate(_all_phases_success(run_id="b"), context=ctx, run_id="b")

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "fail"
        assert gate.extensions["promotion_tier"] == "block"
        assert "flake" in gate.extensions["promotion_reasons"][0].lower()


# =============================================================================
# Warn on insufficient evidence
# =============================================================================


class TestWarnInsufficientEvidence:
    def test_no_context_warns(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        candidate = _aggregate(_all_phases_success(run_id="c"), run_id="c")
        baseline = _aggregate(_all_phases_success(run_id="b"), run_id="b")

        gate = evaluate_promotion_gate(candidate, baseline, None)

        assert gate.gate_result == "insufficient_evidence"
        assert gate.extensions["promotion_tier"] == "warn"

    def test_no_pattern_id_warns(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context(pattern_id="")
        candidate = _aggregate(_all_phases_success(run_id="c"), context=ctx, run_id="c")
        baseline = _aggregate(_all_phases_success(run_id="b"), context=ctx, run_id="b")

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "insufficient_evidence"
        assert gate.extensions["promotion_tier"] == "warn"

    def test_no_baseline_warns(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        candidate = _aggregate(_all_phases_success(run_id="c"), context=ctx, run_id="c")

        gate = evaluate_promotion_gate(candidate, None, ctx)

        assert gate.gate_result == "insufficient_evidence"
        assert gate.extensions["promotion_tier"] == "warn"
        assert "no baseline" in gate.extensions["promotion_reasons"][0].lower()


# =============================================================================
# Warn on zero baseline
# =============================================================================


class TestWarnZeroBaseline:
    def test_zero_baseline_duration_warns(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        candidate = _aggregate(
            _all_phases_success(run_id="c", wall_clock_ms=100.0),
            context=ctx,
            run_id="c",
        )
        baseline = _aggregate(
            _all_phases_success(run_id="b", wall_clock_ms=0.0),
            context=ctx,
            run_id="b",
        )

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "insufficient_evidence"
        assert gate.extensions["promotion_tier"] == "warn"
        assert "zero baseline" in gate.extensions["promotion_reasons"][0].lower()

    def test_zero_baseline_tokens_warns(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        candidate = _aggregate(
            _all_phases_success(run_id="c"),
            context=ctx,
            run_id="c",
        )
        baseline = _aggregate(
            _all_phases_success(run_id="b", input_tokens=0, output_tokens=0),
            context=ctx,
            run_id="b",
        )

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "insufficient_evidence"
        assert gate.extensions["promotion_tier"] == "warn"


# =============================================================================
# Warn on regression
# =============================================================================


class TestWarnRegression:
    def test_duration_regression_above_threshold_warns(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        # Baseline: 100ms per phase, Candidate: 130ms per phase → 30% regression
        baseline = _aggregate(
            _all_phases_success(run_id="b", wall_clock_ms=100.0),
            context=ctx,
            run_id="b",
        )
        candidate = _aggregate(
            _all_phases_success(run_id="c", wall_clock_ms=130.0),
            context=ctx,
            run_id="c",
        )

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "insufficient_evidence"
        assert gate.extensions["promotion_tier"] == "warn"
        reasons = gate.extensions["promotion_reasons"]
        assert any("duration" in r.lower() for r in reasons)

    def test_token_regression_above_threshold_warns(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        # Baseline: 1000 input + 500 output = 1500/phase
        # Candidate: 1500 input + 500 output = 2000/phase → 33% regression
        baseline = _aggregate(
            _all_phases_success(run_id="b", input_tokens=1000, output_tokens=500),
            context=ctx,
            run_id="b",
        )
        candidate = _aggregate(
            _all_phases_success(run_id="c", input_tokens=1500, output_tokens=500),
            context=ctx,
            run_id="c",
        )

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "insufficient_evidence"
        assert gate.extensions["promotion_tier"] == "warn"
        reasons = gate.extensions["promotion_reasons"]
        assert any("tokens" in r.lower() for r in reasons)

    def test_duration_at_threshold_allows(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        # Exactly 20% increase → at threshold, not above
        baseline = _aggregate(
            _all_phases_success(run_id="b", wall_clock_ms=100.0),
            context=ctx,
            run_id="b",
        )
        candidate = _aggregate(
            _all_phases_success(run_id="c", wall_clock_ms=120.0),
            context=ctx,
            run_id="c",
        )

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "pass"
        assert gate.extensions["promotion_tier"] == "allow"


# =============================================================================
# Allow when clear
# =============================================================================


class TestAllowWhenClear:
    def test_all_within_thresholds_allows(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        baseline = _aggregate(
            _all_phases_success(run_id="b"),
            context=ctx,
            run_id="b",
        )
        candidate = _aggregate(
            _all_phases_success(run_id="c"),
            context=ctx,
            run_id="c",
        )

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "pass"
        assert gate.extensions["promotion_tier"] == "allow"
        assert gate.sufficient_count == 3
        assert gate.total_count == 3

    def test_improvement_allows(self) -> None:
        """Candidate is faster and cheaper than baseline → allow."""
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        baseline = _aggregate(
            _all_phases_success(run_id="b", wall_clock_ms=200.0, input_tokens=2000),
            context=ctx,
            run_id="b",
        )
        candidate = _aggregate(
            _all_phases_success(run_id="c", wall_clock_ms=100.0, input_tokens=1000),
            context=ctx,
            run_id="c",
        )

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.gate_result == "pass"
        assert gate.extensions["promotion_tier"] == "allow"


# =============================================================================
# Custom thresholds
# =============================================================================


class TestCustomThresholds:
    def test_stricter_duration_threshold_warns(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import (
            PromotionThresholds,
            evaluate_promotion_gate,
        )

        ctx = _make_context()
        # 10% increase, default threshold=20% would allow, but custom=5% should warn
        baseline = _aggregate(
            _all_phases_success(run_id="b", wall_clock_ms=100.0),
            context=ctx,
            run_id="b",
        )
        candidate = _aggregate(
            _all_phases_success(run_id="c", wall_clock_ms=110.0),
            context=ctx,
            run_id="c",
        )

        strict = PromotionThresholds(duration_regression_pct=5.0)
        gate = evaluate_promotion_gate(candidate, baseline, ctx, thresholds=strict)

        assert gate.gate_result == "insufficient_evidence"
        assert gate.extensions["promotion_tier"] == "warn"

    def test_relaxed_token_threshold_allows(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import (
            PromotionThresholds,
            evaluate_promotion_gate,
        )

        ctx = _make_context()
        # 33% token increase, default=30% would warn, but custom=50% should allow
        baseline = _aggregate(
            _all_phases_success(run_id="b", input_tokens=1000, output_tokens=500),
            context=ctx,
            run_id="b",
        )
        candidate = _aggregate(
            _all_phases_success(run_id="c", input_tokens=1500, output_tokens=500),
            context=ctx,
            run_id="c",
        )

        relaxed = PromotionThresholds(token_regression_pct=50.0)
        gate = evaluate_promotion_gate(candidate, baseline, ctx, thresholds=relaxed)

        assert gate.gate_result == "pass"
        assert gate.extensions["promotion_tier"] == "allow"

    def test_thresholds_model_is_frozen(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import PromotionThresholds

        t = PromotionThresholds()
        with pytest.raises(Exception):
            t.duration_regression_pct = 50.0  # type: ignore[misc]


# =============================================================================
# Extensions metadata
# =============================================================================


class TestExtensionsMetadata:
    def test_extensions_contain_tier_and_reasons(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        candidate = _aggregate(_all_phases_success(run_id="c"), context=ctx, run_id="c")
        baseline = _aggregate(_all_phases_success(run_id="b"), context=ctx, run_id="b")

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert "promotion_tier" in gate.extensions
        assert "promotion_reasons" in gate.extensions
        assert isinstance(gate.extensions["promotion_reasons"], list)
        assert len(gate.extensions["promotion_reasons"]) >= 1

    def test_block_extensions_carry_failure_reason(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        metrics = list(_all_phases_success(run_id="c"))
        metrics = [m for m in metrics if m.phase != ContractEnumPipelinePhase.VERIFY]
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.VERIFY,
                ContractEnumResultClassification.FAILURE,
                run_id="c",
            )
        )
        candidate = _aggregate(metrics, context=ctx, run_id="c")

        gate = evaluate_promotion_gate(candidate, None, ctx)

        assert gate.extensions["promotion_tier"] == "block"
        assert "failure" in gate.extensions["promotion_reasons"][0].lower()

    def test_baseline_key_derived_from_context(self) -> None:
        from omnibase_spi.contracts.measurement.contract_measurement_context import (
            derive_baseline_key,
        )

        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        candidate = _aggregate(_all_phases_success(run_id="c"), context=ctx, run_id="c")
        baseline = _aggregate(_all_phases_success(run_id="b"), context=ctx, run_id="b")

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        assert gate.baseline_key == derive_baseline_key(ctx)

    def test_no_context_has_empty_baseline_key(self) -> None:
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        candidate = _aggregate(_all_phases_success(run_id="c"), run_id="c")

        gate = evaluate_promotion_gate(candidate, None, None)

        assert gate.baseline_key == ""


# =============================================================================
# Priority order
# =============================================================================


class TestPriorityOrder:
    def test_failure_takes_precedence_over_flake(self) -> None:
        """If candidate both failed AND is flaky, failure wins (block)."""
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        # Failed + flaky: two VERIFY attempts, one success one failure
        metrics = [
            _make_phase(phase, run_id="c")
            for phase in ContractEnumPipelinePhase
            if phase != ContractEnumPipelinePhase.VERIFY
        ]
        # Replace IMPLEMENT with failure to make overall_result="failure"
        metrics = [m for m in metrics if m.phase != ContractEnumPipelinePhase.IMPLEMENT]
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.IMPLEMENT,
                ContractEnumResultClassification.FAILURE,
                run_id="c",
            )
        )
        # Flaky VERIFY
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.VERIFY,
                ContractEnumResultClassification.SUCCESS,
                run_id="c",
                attempt=1,
            )
        )
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.VERIFY,
                ContractEnumResultClassification.FAILURE,
                run_id="c",
                attempt=2,
                failed_tests=["test_a"],
            )
        )
        candidate = _aggregate(metrics, context=ctx, run_id="c")
        baseline = _aggregate(_all_phases_success(run_id="b"), context=ctx, run_id="b")

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        # Failure check comes before flake check
        assert gate.gate_result == "fail"
        assert "failed" in gate.extensions["promotion_reasons"][0].lower()

    def test_flake_takes_precedence_over_regression(self) -> None:
        """If candidate is flaky AND has regression, flake wins (block > warn)."""
        from plugins.onex.hooks.lib.promotion_gater import evaluate_promotion_gate

        ctx = _make_context()
        # Flaky VERIFY (attempt 1 fails, attempt 2 succeeds → overall success)
        # + high duration (200ms vs 100ms baseline → regression)
        metrics = [
            _make_phase(phase, run_id="c", wall_clock_ms=200.0)
            for phase in ContractEnumPipelinePhase
            if phase != ContractEnumPipelinePhase.VERIFY
        ]
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.VERIFY,
                ContractEnumResultClassification.FAILURE,
                run_id="c",
                attempt=1,
                wall_clock_ms=200.0,
                failed_tests=["test_b"],
            )
        )
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.VERIFY,
                ContractEnumResultClassification.SUCCESS,
                run_id="c",
                attempt=2,
                wall_clock_ms=200.0,
            )
        )
        candidate = _aggregate(metrics, context=ctx, run_id="c")
        baseline = _aggregate(
            _all_phases_success(run_id="b", wall_clock_ms=100.0),
            context=ctx,
            run_id="b",
        )

        gate = evaluate_promotion_gate(candidate, baseline, ctx)

        # Flake check comes before regression check
        assert gate.gate_result == "fail"
        assert gate.extensions["promotion_tier"] == "block"
        assert "flake" in gate.extensions["promotion_reasons"][0].lower()
