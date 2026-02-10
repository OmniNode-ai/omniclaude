# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for metrics_aggregator module (M3).

Covers: aggregate_run, flake detection, baseline storage,
evidence assessment, and zero-baseline guard.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from omnibase_spi.contracts.measurement.contract_measurement_context import (
    ContractMeasurementContext,
    derive_baseline_key,
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
    cost_usd: float | None = 0.50,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    total_tests: int = 10,
    failed_tests: list[str] | None = None,
    error_codes: list[str] | None = None,
    skip_reason_code: str = "",
    error_messages: list[str] | None = None,
) -> ContractPhaseMetrics:
    """Build a ContractPhaseMetrics for testing."""
    return ContractPhaseMetrics(
        run_id=run_id,
        phase=phase,
        attempt=attempt,
        duration=ContractDurationMetrics(wall_clock_ms=wall_clock_ms),
        cost=ContractCostMetrics(
            llm_input_tokens=input_tokens,
            llm_output_tokens=output_tokens,
            llm_total_tokens=input_tokens + output_tokens,
            estimated_cost_usd=cost_usd,
        ),
        outcome=ContractOutcomeMetrics(
            result_classification=rc,
            failed_tests=failed_tests or [],
            error_codes=error_codes or [],
            skip_reason_code=skip_reason_code,
            error_messages=error_messages or [],
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


def _all_phases_success(run_id: str = "run-1") -> list[ContractPhaseMetrics]:
    """One successful metric per canonical phase."""
    return [_make_phase(phase, run_id=run_id) for phase in ContractEnumPipelinePhase]


# =============================================================================
# aggregate_run
# =============================================================================


class TestAggregateRun:
    def test_all_mandatory_success(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        result = aggregate_run(_all_phases_success())
        assert result.overall_result == "success"
        assert result.mandatory_phases_total == 5
        assert result.mandatory_phases_succeeded == 5

    def test_missing_mandatory_phase_gives_partial(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        metrics = [
            _make_phase(phase)
            for phase in ContractEnumPipelinePhase
            if phase != ContractEnumPipelinePhase.VERIFY
        ]
        result = aggregate_run(metrics)
        assert result.overall_result == "partial"
        assert result.mandatory_phases_succeeded == 4

    def test_skipped_mandatory_phase_gives_partial(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        metrics = _all_phases_success()
        # Replace VERIFY with a skipped phase
        metrics = [m for m in metrics if m.phase != ContractEnumPipelinePhase.VERIFY]
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.VERIFY,
                ContractEnumResultClassification.SKIPPED,
                skip_reason_code="not_applicable",
            )
        )
        result = aggregate_run(metrics)
        assert result.overall_result == "partial"

    def test_failed_mandatory_phase_gives_failure(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        metrics = _all_phases_success()
        metrics = [m for m in metrics if m.phase != ContractEnumPipelinePhase.IMPLEMENT]
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.IMPLEMENT,
                ContractEnumResultClassification.FAILURE,
            )
        )
        result = aggregate_run(metrics)
        assert result.overall_result == "failure"

    def test_error_mandatory_phase_gives_failure(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        metrics = _all_phases_success()
        metrics = [m for m in metrics if m.phase != ContractEnumPipelinePhase.REVIEW]
        metrics.append(
            _make_phase(
                ContractEnumPipelinePhase.REVIEW,
                ContractEnumResultClassification.ERROR,
            )
        )
        result = aggregate_run(metrics)
        assert result.overall_result == "failure"

    def test_failure_takes_precedence_over_partial(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        # One phase missing (partial) + one failed (failure) → failure wins
        metrics = [
            _make_phase(ContractEnumPipelinePhase.PLAN),
            _make_phase(
                ContractEnumPipelinePhase.IMPLEMENT,
                ContractEnumResultClassification.FAILURE,
            ),
            _make_phase(ContractEnumPipelinePhase.REVIEW),
            # VERIFY missing → partial
            # RELEASE missing → partial
        ]
        result = aggregate_run(metrics)
        assert result.overall_result == "failure"

    def test_computes_total_duration(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        metrics = _all_phases_success()
        result = aggregate_run(metrics)
        assert result.total_duration_ms == pytest.approx(500.0)  # 5 x 100ms

    def test_computes_total_cost(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        metrics = _all_phases_success()
        result = aggregate_run(metrics)
        assert result.total_cost_usd == pytest.approx(2.50)  # 5 x $0.50

    def test_custom_mandatory_phases(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        metrics = [
            _make_phase(ContractEnumPipelinePhase.PLAN),
            _make_phase(ContractEnumPipelinePhase.IMPLEMENT),
        ]
        result = aggregate_run(
            metrics,
            mandatory_phases={
                ContractEnumPipelinePhase.PLAN,
                ContractEnumPipelinePhase.IMPLEMENT,
            },
        )
        assert result.overall_result == "success"
        assert result.mandatory_phases_total == 2
        assert result.mandatory_phases_succeeded == 2

    def test_empty_metrics_gives_partial(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        result = aggregate_run([], run_id="empty-run")
        assert result.overall_result == "partial"
        assert result.mandatory_phases_succeeded == 0
        assert result.total_duration_ms is None
        assert result.total_cost_usd is None

    def test_run_id_derived_from_first_metric(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        metrics = _all_phases_success(run_id="derived-id")
        result = aggregate_run(metrics)
        assert result.run_id == "derived-id"

    def test_highest_attempt_wins(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        metrics = [
            _make_phase(
                ContractEnumPipelinePhase.PLAN,
                ContractEnumResultClassification.FAILURE,
                attempt=1,
            ),
            _make_phase(
                ContractEnumPipelinePhase.PLAN,
                ContractEnumResultClassification.SUCCESS,
                attempt=2,
            ),
        ]
        result = aggregate_run(
            metrics,
            mandatory_phases={ContractEnumPipelinePhase.PLAN},
            run_id="retry-run",
        )
        assert result.overall_result == "success"


# =============================================================================
# Flake Detection
# =============================================================================


class TestFlakeDetection:
    def test_same_signatures_not_flaky(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import detect_flakes

        metrics = [
            _make_phase(ContractEnumPipelinePhase.VERIFY, attempt=1),
            _make_phase(ContractEnumPipelinePhase.VERIFY, attempt=2),
        ]
        flakes = detect_flakes(metrics)
        assert flakes[ContractEnumPipelinePhase.VERIFY] is False

    def test_different_signatures_flaky(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import detect_flakes

        metrics = [
            _make_phase(
                ContractEnumPipelinePhase.VERIFY,
                ContractEnumResultClassification.SUCCESS,
                attempt=1,
            ),
            _make_phase(
                ContractEnumPipelinePhase.VERIFY,
                ContractEnumResultClassification.FAILURE,
                attempt=2,
                failed_tests=["test_foo"],
            ),
        ]
        flakes = detect_flakes(metrics)
        assert flakes[ContractEnumPipelinePhase.VERIFY] is True

    def test_error_messages_excluded_from_signature(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            compute_outcome_signature,
        )

        m1 = _make_phase(
            ContractEnumPipelinePhase.VERIFY,
            error_messages=["original error"],
        )
        m2 = _make_phase(
            ContractEnumPipelinePhase.VERIFY,
            error_messages=["redacted error"],
        )
        assert compute_outcome_signature(m1) == compute_outcome_signature(m2)

    def test_signature_is_16_hex_chars(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            compute_outcome_signature,
        )

        sig = compute_outcome_signature(_make_phase(ContractEnumPipelinePhase.PLAN))
        assert len(sig) == 16
        assert all(c in "0123456789abcdef" for c in sig)


# =============================================================================
# Baseline Storage
# =============================================================================


class TestBaselineStorage:
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            aggregate_run,
            load_baseline,
            save_baseline,
        )

        ctx = _make_context()
        run = aggregate_run(_all_phases_success(), context=ctx)

        path = save_baseline(run, ctx, baselines_root=tmp_path)
        assert path is not None
        assert path.exists()

        loaded = load_baseline(ctx, baselines_root=tmp_path)
        assert loaded is not None
        assert loaded.run_id == run.run_id
        assert loaded.overall_result == run.overall_result
        assert loaded.total_duration_ms == run.total_duration_ms

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import load_baseline

        ctx = _make_context(ticket_id="nonexistent")
        result = load_baseline(ctx, baselines_root=tmp_path)
        assert result is None

    def test_missing_pattern_id_uses_no_pattern_dir(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            aggregate_run,
            save_baseline,
        )

        ctx = _make_context(pattern_id="")
        run = aggregate_run(_all_phases_success(), context=ctx, run_id="no-pat")

        path = save_baseline(run, ctx, baselines_root=tmp_path)
        assert path is not None
        assert "_no_pattern" in str(path)

    def test_baseline_key_deterministic(self) -> None:
        ctx = _make_context()
        key1 = derive_baseline_key(ctx)
        key2 = derive_baseline_key(ctx)
        assert key1 == key2


# =============================================================================
# Evidence Assessment
# =============================================================================


class TestEvidenceAssessment:
    def _make_runs(
        self,
        *,
        baseline_duration: float = 100.0,
        baseline_tokens: int = 1000,
        baseline_tests: int = 10,
        candidate_duration: float = 120.0,
        candidate_tokens: int = 1200,
        candidate_tests: int = 12,
    ) -> tuple[ContractAggregatedRun, ContractAggregatedRun]:
        from plugins.onex.hooks.lib.metrics_aggregator import aggregate_run

        ctx = _make_context()

        baseline_metrics = [
            _make_phase(
                phase,
                wall_clock_ms=baseline_duration / 5,
                input_tokens=baseline_tokens // 5,
                output_tokens=0,
                total_tests=baseline_tests // 5,
            )
            for phase in ContractEnumPipelinePhase
        ]
        candidate_metrics = [
            _make_phase(
                phase,
                wall_clock_ms=candidate_duration / 5,
                input_tokens=candidate_tokens // 5,
                output_tokens=0,
                total_tests=candidate_tests // 5,
            )
            for phase in ContractEnumPipelinePhase
        ]

        baseline = aggregate_run(baseline_metrics, context=ctx, run_id="b")
        candidate = aggregate_run(candidate_metrics, context=ctx, run_id="c")
        return baseline, candidate

    def test_all_dimensions_sufficient_passes(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import assess_evidence

        baseline, candidate = self._make_runs()
        ctx = _make_context()
        gate = assess_evidence(candidate, baseline, ctx)

        assert gate.gate_result == "pass"
        assert gate.sufficient_count == 3
        assert gate.total_count == 3

    def test_duration_insufficient_fails(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import assess_evidence

        baseline, candidate = self._make_runs(
            baseline_duration=0.0, candidate_duration=100.0
        )
        ctx = _make_context()
        gate = assess_evidence(candidate, baseline, ctx)

        assert gate.gate_result == "fail"
        duration_dim = next(d for d in gate.dimensions if d.dimension == "duration")
        assert duration_dim.sufficient is False

    def test_tokens_insufficient_fails(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import assess_evidence

        baseline, candidate = self._make_runs(baseline_tokens=0, candidate_tokens=1000)
        ctx = _make_context()
        gate = assess_evidence(candidate, baseline, ctx)

        assert gate.gate_result == "fail"
        tokens_dim = next(d for d in gate.dimensions if d.dimension == "tokens")
        assert tokens_dim.sufficient is False

    def test_tests_insufficient_fails(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import assess_evidence

        baseline, candidate = self._make_runs(baseline_tests=0, candidate_tests=10)
        ctx = _make_context()
        gate = assess_evidence(candidate, baseline, ctx)

        assert gate.gate_result == "fail"
        tests_dim = next(d for d in gate.dimensions if d.dimension == "tests")
        assert tests_dim.sufficient is False

    def test_missing_pattern_id_insufficient_evidence(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            aggregate_run,
            assess_evidence,
        )

        candidate = aggregate_run(_all_phases_success(), run_id="c")
        ctx = _make_context(pattern_id="")
        gate = assess_evidence(candidate, None, ctx)

        assert gate.gate_result == "insufficient_evidence"
        assert gate.total_count == 0

    def test_no_context_insufficient_evidence(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            aggregate_run,
            assess_evidence,
        )

        candidate = aggregate_run(_all_phases_success(), run_id="c")
        gate = assess_evidence(candidate, None, None)

        assert gate.gate_result == "insufficient_evidence"

    def test_no_baseline_insufficient_evidence(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            aggregate_run,
            assess_evidence,
        )

        candidate = aggregate_run(_all_phases_success(), run_id="c")
        ctx = _make_context()
        gate = assess_evidence(candidate, None, ctx)

        assert gate.gate_result == "insufficient_evidence"
        assert gate.baseline_key != ""


# =============================================================================
# Zero-Baseline Guard
# =============================================================================


class TestZeroBaselineGuard:
    def test_zero_baseline_delta_pct_none(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            _make_dimension_evidence,
        )

        ev = _make_dimension_evidence("duration", 0.0, 100.0)
        assert ev.delta_pct is None

    def test_zero_baseline_insufficient(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            _make_dimension_evidence,
        )

        ev = _make_dimension_evidence("duration", 0.0, 100.0)
        assert ev.sufficient is False

    def test_nonzero_baseline_has_delta_pct(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            _make_dimension_evidence,
        )

        ev = _make_dimension_evidence("duration", 100.0, 120.0)
        assert ev.delta_pct is not None
        assert ev.delta_pct == pytest.approx(20.0)
        assert ev.sufficient is True

    def test_zero_current_insufficient(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            _make_dimension_evidence,
        )

        ev = _make_dimension_evidence("tokens", 100.0, 0.0)
        assert ev.sufficient is False
        assert ev.delta_pct == pytest.approx(-100.0)

    def test_no_zero_division_error(self) -> None:
        from plugins.onex.hooks.lib.metrics_aggregator import (
            _make_dimension_evidence,
        )

        # Should never raise ZeroDivisionError
        ev = _make_dimension_evidence("tests", 0.0, 0.0)
        assert ev.delta_pct is None
        assert ev.sufficient is False


# =============================================================================
# Gate Storage (OMN-2092)
# =============================================================================


class TestGateStorage:
    """Tests for gate storage functions (save_gate, load_gate, load_latest_gate_result)."""

    def test_save_and_load_gate_round_trip(self, tmp_path: Path) -> None:
        """Save gate, load gate, verify fields match."""
        from omnibase_spi.contracts.measurement.contract_promotion_gate import (
            ContractPromotionGate,
        )

        from plugins.onex.hooks.lib.metrics_aggregator import load_gate, save_gate

        ctx = _make_context(ticket_id="OMN-2092", pattern_id="pat-rt")
        gate = ContractPromotionGate(
            run_id="test-run-rt",
            gate_result="pass",
            baseline_key="test-key",
            required_dimensions=["duration", "tokens", "tests"],
            sufficient_count=3,
            total_count=3,
        )

        path = save_gate(gate, ctx, baselines_root=tmp_path)
        assert path is not None
        assert path.exists()

        loaded = load_gate(ctx, baselines_root=tmp_path)
        assert loaded is not None
        assert loaded.run_id == gate.run_id
        assert loaded.gate_result == gate.gate_result
        assert loaded.baseline_key == gate.baseline_key
        assert loaded.sufficient_count == gate.sufficient_count
        assert loaded.total_count == gate.total_count

    def test_load_gate_nonexistent_returns_none(self, tmp_path: Path) -> None:
        """No gate file → None."""
        from plugins.onex.hooks.lib.metrics_aggregator import load_gate

        ctx = _make_context(ticket_id="OMN-NONE", pattern_id="pat-none")
        result = load_gate(ctx, baselines_root=tmp_path)
        assert result is None

    def test_load_latest_gate_result_per_pattern(self, tmp_path: Path) -> None:
        """Save gates for different pattern_ids, load by specific pattern_id."""
        from omnibase_spi.contracts.measurement.contract_promotion_gate import (
            ContractPromotionGate,
        )

        from plugins.onex.hooks.lib.metrics_aggregator import (
            load_latest_gate_result,
            save_gate,
        )

        # Create gates in different patterns (same ticket)
        ctx_a = _make_context(ticket_id="OMN-2092", pattern_id="pat-a")
        ctx_b = _make_context(ticket_id="OMN-2092", pattern_id="pat-b")

        gate_a = ContractPromotionGate(
            run_id="run-a",
            gate_result="pass",
            baseline_key="key-a",
            required_dimensions=["duration"],
            sufficient_count=1,
            total_count=1,
        )
        gate_b = ContractPromotionGate(
            run_id="run-b",
            gate_result="fail",
            baseline_key="key-b",
            required_dimensions=["tokens"],
            sufficient_count=0,
            total_count=1,
        )

        save_gate(gate_a, ctx_a, baselines_root=tmp_path)
        path_b = save_gate(gate_b, ctx_b, baselines_root=tmp_path)

        # Load by specific pattern_id — should return that pattern's gate
        assert load_latest_gate_result("pat-a", baselines_root=tmp_path) == "pass"
        assert load_latest_gate_result("pat-b", baselines_root=tmp_path) == "fail"
        assert path_b is not None and path_b.exists()

    def test_load_latest_gate_result_scans_subdirs(self, tmp_path: Path) -> None:
        """Multiple baseline_keys under one pattern_id; most recent wins."""
        import json
        import os

        from plugins.onex.hooks.lib.metrics_aggregator import load_latest_gate_result

        pattern_dir = tmp_path / "pat-multi"

        # Create two baseline_key subdirs with gate files
        old_dir = pattern_dir / "baseline-old"
        old_dir.mkdir(parents=True)
        old_file = old_dir / "latest.gate.json"
        old_file.write_text(json.dumps({"gate_result": "fail", "run_id": "old"}))

        # Set explicit mtime in the past for deterministic ordering
        os.utime(old_file, (1000000.0, 1000000.0))

        new_dir = pattern_dir / "baseline-new"
        new_dir.mkdir(parents=True)
        new_file = new_dir / "latest.gate.json"
        new_file.write_text(json.dumps({"gate_result": "pass", "run_id": "new"}))

        # Should return the most recently modified gate
        result = load_latest_gate_result("pat-multi", baselines_root=tmp_path)
        assert result == "pass"

    def test_load_latest_gate_result_nonexistent_returns_none(
        self, tmp_path: Path
    ) -> None:
        """No pattern dir → None."""
        from plugins.onex.hooks.lib.metrics_aggregator import load_latest_gate_result

        result = load_latest_gate_result("pat-nonexistent", baselines_root=tmp_path)
        assert result is None
