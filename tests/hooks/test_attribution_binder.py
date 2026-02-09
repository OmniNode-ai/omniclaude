# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for attribution_binder module (M4).

Covers: bind composition, missing measurement, missing gate,
round-trip serialization, load/save, and bind_and_save convenience.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from omnibase_spi.contracts.measurement.contract_aggregated_run import (
    ContractAggregatedRun,
)
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
from omnibase_spi.contracts.validation.contract_attribution_record import (
    ContractAttributionRecord,
)

pytestmark = pytest.mark.unit

# -- Factories ---------------------------------------------------------------


def _make_attribution(
    *,
    record_id: str = "attr-1",
    pattern_id: str = "p1",
    proposed_by: str = "agent-test",
    proposed_at_iso: str = "2026-01-15T10:00:00Z",
    verdict_status: str = "PASS",
    promoted: bool = False,
) -> ContractAttributionRecord:
    return ContractAttributionRecord(
        record_id=record_id,
        pattern_id=pattern_id,
        proposed_by=proposed_by,
        proposed_at_iso=proposed_at_iso,
        verdict_status=verdict_status,
        promoted=promoted,
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


def _make_phase(
    phase: ContractEnumPipelinePhase,
    *,
    run_id: str = "run-1",
) -> ContractPhaseMetrics:
    return ContractPhaseMetrics(
        run_id=run_id,
        phase=phase,
        attempt=1,
        duration=ContractDurationMetrics(wall_clock_ms=100.0),
        cost=ContractCostMetrics(
            llm_input_tokens=1000,
            llm_output_tokens=500,
            llm_total_tokens=1500,
            estimated_cost_usd=0.50,
        ),
        outcome=ContractOutcomeMetrics(
            result_classification=ContractEnumResultClassification.SUCCESS,
        ),
        tests=ContractTestMetrics(total_tests=10),
    )


def _make_aggregated_run(
    run_id: str = "run-1",
    context: ContractMeasurementContext | None = None,
) -> ContractAggregatedRun:
    phases = [_make_phase(p, run_id=run_id) for p in ContractEnumPipelinePhase]
    return ContractAggregatedRun(
        run_id=run_id,
        context=context,
        overall_result="success",
        phase_metrics=phases,
        total_duration_ms=500.0,
        total_cost_usd=2.50,
        mandatory_phases_total=5,
        mandatory_phases_succeeded=5,
    )


def _make_gate(
    run_id: str = "run-1",
    gate_result: str = "pass",
) -> ContractPromotionGate:
    return ContractPromotionGate(
        run_id=run_id,
        gate_result=gate_result,
        dimensions=[
            ContractDimensionEvidence(
                dimension="duration",
                baseline_value=100.0,
                current_value=120.0,
                delta_pct=20.0,
                sufficient=True,
            ),
            ContractDimensionEvidence(
                dimension="tokens",
                baseline_value=1000.0,
                current_value=1200.0,
                delta_pct=20.0,
                sufficient=True,
            ),
            ContractDimensionEvidence(
                dimension="tests",
                baseline_value=10.0,
                current_value=12.0,
                delta_pct=20.0,
                sufficient=True,
            ),
        ],
        required_dimensions=["duration", "tokens", "tests"],
        sufficient_count=3,
        total_count=3,
    )


# =============================================================================
# Composition
# =============================================================================


class TestBindAttribution:
    def test_all_three_compose_correctly(self) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_attribution

        attr = _make_attribution()
        run = _make_aggregated_run()
        gate = _make_gate()

        measured = bind_attribution(attr, run, gate)

        assert measured.attribution_id == "attr-1"
        assert measured.proposed_by == "agent-test"
        assert measured.proposed_at_iso == "2026-01-15T10:00:00Z"
        assert measured.verdict == "PASS"
        assert measured.promoted is False
        assert measured.aggregated_run is not None
        assert measured.aggregated_run.run_id == "run-1"
        assert measured.promotion_gate is not None
        assert measured.promotion_gate.gate_result == "pass"

    def test_missing_measurement_is_valid(self) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_attribution

        attr = _make_attribution()
        measured = bind_attribution(attr, None, None)

        assert measured.attribution_id == "attr-1"
        assert measured.aggregated_run is None
        assert measured.promotion_gate is None

    def test_missing_gate_is_valid(self) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_attribution

        attr = _make_attribution()
        run = _make_aggregated_run()
        measured = bind_attribution(attr, run, None)

        assert measured.aggregated_run is not None
        assert measured.promotion_gate is None

    def test_context_from_run_when_not_explicit(self) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_attribution

        ctx = _make_context()
        attr = _make_attribution()
        run = _make_aggregated_run(context=ctx)
        measured = bind_attribution(attr, run)

        assert measured.context is not None
        assert measured.context.ticket_id == "OMN-TEST"

    def test_explicit_context_overrides_run(self) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_attribution

        run_ctx = _make_context(ticket_id="from-run")
        explicit_ctx = _make_context(ticket_id="explicit")
        attr = _make_attribution()
        run = _make_aggregated_run(context=run_ctx)
        measured = bind_attribution(attr, run, context=explicit_ctx)

        assert measured.context is not None
        assert measured.context.ticket_id == "explicit"

    def test_no_context_when_no_run(self) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_attribution

        attr = _make_attribution()
        measured = bind_attribution(attr)

        assert measured.context is None

    def test_verdict_maps_from_attribution(self) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_attribution

        for status in ("PASS", "FAIL", "QUARANTINE", ""):
            attr = _make_attribution(verdict_status=status)
            measured = bind_attribution(attr)
            assert measured.verdict == status

    def test_promoted_fields_map(self) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_attribution

        attr = _make_attribution(
            promoted=True,
        )
        # ContractAttributionRecord with promoted_at_iso and promoted_to
        attr2 = ContractAttributionRecord(
            record_id="attr-promo",
            pattern_id="p1",
            promoted=True,
            promoted_at_iso="2026-02-01T12:00:00Z",
            promoted_to="production",
        )
        measured = bind_attribution(attr2)
        assert measured.promoted is True
        assert measured.promoted_at_iso == "2026-02-01T12:00:00Z"
        assert measured.promoted_to == "production"

    def test_result_is_frozen(self) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_attribution

        attr = _make_attribution()
        measured = bind_attribution(attr)

        with pytest.raises(Exception):  # ValidationError for frozen model
            measured.verdict = "FAIL"  # type: ignore[misc]


# =============================================================================
# Round-trip Serialization
# =============================================================================


class TestRoundTrip:
    def test_json_round_trip_preserves_nested_contracts(self) -> None:
        from omnibase_spi.contracts.measurement.contract_measured_attribution import (
            ContractMeasuredAttribution,
        )

        from plugins.onex.hooks.lib.attribution_binder import bind_attribution

        ctx = _make_context()
        attr = _make_attribution()
        run = _make_aggregated_run(context=ctx)
        gate = _make_gate()

        measured = bind_attribution(attr, run, gate, context=ctx)
        json_str = measured.model_dump_json(indent=2)
        restored = ContractMeasuredAttribution.model_validate_json(json_str)

        assert restored.attribution_id == measured.attribution_id
        assert restored.aggregated_run is not None
        assert restored.aggregated_run.run_id == measured.aggregated_run.run_id
        assert restored.aggregated_run.overall_result == "success"
        assert restored.promotion_gate is not None
        assert restored.promotion_gate.gate_result == "pass"
        assert len(restored.promotion_gate.dimensions) == 3

    def test_json_round_trip_with_none_fields(self) -> None:
        from omnibase_spi.contracts.measurement.contract_measured_attribution import (
            ContractMeasuredAttribution,
        )

        from plugins.onex.hooks.lib.attribution_binder import bind_attribution

        attr = _make_attribution()
        measured = bind_attribution(attr)
        json_str = measured.model_dump_json(indent=2)
        restored = ContractMeasuredAttribution.model_validate_json(json_str)

        assert restored.aggregated_run is None
        assert restored.promotion_gate is None
        assert restored.context is None


# =============================================================================
# File Persistence
# =============================================================================


class TestSaveAndLoad:
    def test_save_creates_file(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.attribution_binder import (
            bind_attribution,
            save_measured_attribution,
        )

        attr = _make_attribution()
        run = _make_aggregated_run()
        measured = bind_attribution(attr, run)

        path = save_measured_attribution(
            measured, "p1", "run-1", attributions_root=tmp_path
        )
        assert path.exists()
        assert path.name == "run-1.measured.json"
        assert "p1" in str(path.parent)

    def test_save_content_is_valid_json(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.attribution_binder import (
            bind_attribution,
            save_measured_attribution,
        )

        attr = _make_attribution()
        measured = bind_attribution(attr)
        path = save_measured_attribution(
            measured, "p1", "run-x", attributions_root=tmp_path
        )

        data = json.loads(path.read_text())
        assert data["attribution_id"] == "attr-1"

    def test_load_attribution_record_round_trip(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.attribution_binder import (
            load_attribution_record,
        )

        attr = _make_attribution(record_id="rec-rt", pattern_id="p-rt")
        record_dir = tmp_path / "p-rt"
        record_dir.mkdir()
        (record_dir / "record.json").write_text(attr.model_dump_json(indent=2))

        loaded = load_attribution_record("p-rt", attributions_root=tmp_path)
        assert loaded is not None
        assert loaded.record_id == "rec-rt"
        assert loaded.pattern_id == "p-rt"

    def test_load_attribution_record_missing_returns_none(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.attribution_binder import (
            load_attribution_record,
        )

        result = load_attribution_record("nonexistent", attributions_root=tmp_path)
        assert result is None

    def test_load_aggregated_run_from_measured(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.attribution_binder import (
            bind_attribution,
            load_aggregated_run,
            save_measured_attribution,
        )

        attr = _make_attribution()
        run = _make_aggregated_run(run_id="run-load")
        measured = bind_attribution(attr, run)
        save_measured_attribution(
            measured, "p1", "run-load", attributions_root=tmp_path
        )

        loaded_run = load_aggregated_run("p1", "run-load", attributions_root=tmp_path)
        assert loaded_run is not None
        assert loaded_run.run_id == "run-load"

    def test_load_aggregated_run_missing_returns_none(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.attribution_binder import (
            load_aggregated_run,
        )

        result = load_aggregated_run("p1", "no-such-run", attributions_root=tmp_path)
        assert result is None


# =============================================================================
# bind_and_save convenience
# =============================================================================


class TestBindAndSave:
    def test_full_pipeline(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_and_save

        attr = _make_attribution(pattern_id="p-full")
        run = _make_aggregated_run(run_id="run-full")
        gate = _make_gate(run_id="run-full")

        measured, path = bind_and_save(attr, run, gate, attributions_root=tmp_path)

        assert path.exists()
        assert measured.attribution_id == "attr-1"
        assert measured.aggregated_run is not None
        assert measured.promotion_gate is not None

        # Verify file content
        data = json.loads(path.read_text())
        assert data["attribution_id"] == "attr-1"
        assert data["aggregated_run"]["run_id"] == "run-full"

    def test_run_id_derived_from_run(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_and_save

        attr = _make_attribution()
        run = _make_aggregated_run(run_id="derived-id")

        _, path = bind_and_save(attr, run, attributions_root=tmp_path)
        assert "derived-id" in path.name

    def test_run_id_unbound_when_no_run(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_and_save

        attr = _make_attribution()
        _, path = bind_and_save(attr, attributions_root=tmp_path)
        assert "unbound" in path.name

    def test_no_pattern_uses_fallback_dir(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.attribution_binder import bind_and_save

        attr = _make_attribution(pattern_id="")
        _, path = bind_and_save(attr, attributions_root=tmp_path)
        assert "_no_pattern" in str(path)
