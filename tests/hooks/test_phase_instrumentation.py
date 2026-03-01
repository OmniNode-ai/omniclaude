# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for phase instrumentation protocol (OMN-2027).

Covers:
    - Success path: instrumented_phase wraps and emits correctly
    - Failure path: instrumented_phase captures errors and emits
    - Skip path: build_skipped_metrics produces correct records
    - Silent omission detection: detect_silent_omission fires correctly
    - MeasurementCheck validation: all 6 checks produce correct results
    - Metrics building: all sub-contracts populated correctly
    - Phase -> SPI mapping: all 4 phases map correctly

.. versionadded:: 0.2.1
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

from omnibase_spi.contracts.measurement import (
    ContractCostMetrics,
    ContractDurationMetrics,
    ContractEnumPipelinePhase,
    ContractEnumResultClassification,
    ContractMeasurementContext,
    ContractOutcomeMetrics,
    ContractPhaseMetrics,
    ContractProducer,
    ContractTestMetrics,
    MeasurementCheck,
)

from plugins.onex.hooks.lib.metrics_emitter import (
    MAX_ERROR_MESSAGE_LENGTH,
    _build_measurement_event,
    _sanitize_error_messages,
    _sanitize_failed_tests,
    _sanitize_skip_reason,
    _validate_artifact_uri,
    emit_phase_metrics,
    metrics_artifact_exists,
    read_metrics_artifact,
    write_metrics_artifact,
)
from plugins.onex.hooks.lib.phase_instrumentation import (
    DURATION_BUDGETS_MS,
    PHASE_TO_SPI,
    PRODUCER_NAME,
    PRODUCER_VERSION,
    TEST_BEARING_PHASES,
    TOKEN_BUDGETS,
    MeasurementCheckResult,
    PhaseResult,
    build_error_metrics,
    build_metrics_from_result,
    build_skipped_metrics,
    detect_silent_omission,
    instrumented_phase,
    run_measurement_checks,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _tmp_artifact_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect artifact writes to a temp directory."""
    import plugins.onex.hooks.lib.metrics_emitter as emitter_mod

    monkeypatch.setattr(emitter_mod, "ARTIFACT_BASE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def sample_phase_result() -> PhaseResult:
    """A successful phase result with typical values."""
    return PhaseResult(
        status="completed",
        blocking_issues=0,
        nit_count=2,
        artifacts={"commits": "3 commits"},
        tokens_used=15000,
        api_calls=5,
        tests_total=42,
        tests_passed=40,
        tests_failed=2,
    )


@pytest.fixture
def sample_failed_result() -> PhaseResult:
    """A failed phase result."""
    return PhaseResult(
        status="failed",
        blocking_issues=3,
        reason="Tests failed: 3 blocking issues remain",
        block_kind="blocked_review_limit",
        tokens_used=8000,
        tests_total=42,
        tests_passed=39,
        tests_failed=3,
    )


@pytest.fixture
def sample_metrics() -> ContractPhaseMetrics:
    """A fully populated ContractPhaseMetrics."""
    return ContractPhaseMetrics(
        run_id="test-run-1",
        phase=ContractEnumPipelinePhase.IMPLEMENT,
        phase_id="test-run-1-implement-1",
        attempt=1,
        context=ContractMeasurementContext(
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            toolchain="claude-code",
        ),
        producer=ContractProducer(
            name=PRODUCER_NAME,
            version=PRODUCER_VERSION,
            instance_id="test-inst",
        ),
        duration=ContractDurationMetrics(wall_clock_ms=5000.0),
        cost=ContractCostMetrics(llm_total_tokens=15000),
        outcome=ContractOutcomeMetrics(
            result_classification=ContractEnumResultClassification.SUCCESS,
        ),
        tests=ContractTestMetrics(
            total_tests=42,
            passed_tests=42,
            pass_rate=1.0,
        ),
    )


# ---------------------------------------------------------------------------
# Tests: Phase -> SPI Mapping
# ---------------------------------------------------------------------------


class TestPhaseSpiMapping:
    """Verify all pipeline phases map to correct SPI enum values."""

    def test_implement_maps_to_implement(self):
        assert PHASE_TO_SPI["implement"] == ContractEnumPipelinePhase.IMPLEMENT

    def test_local_review_maps_to_verify(self):
        assert PHASE_TO_SPI["local_review"] == ContractEnumPipelinePhase.VERIFY

    def test_create_pr_maps_to_release(self):
        assert PHASE_TO_SPI["create_pr"] == ContractEnumPipelinePhase.RELEASE

    def test_ready_for_merge_maps_to_release(self):
        assert PHASE_TO_SPI["ready_for_merge"] == ContractEnumPipelinePhase.RELEASE

    def test_all_pipeline_phases_have_mapping(self):
        """All 4 pipeline phases must have an SPI mapping."""
        expected_phases = {
            "implement",
            "local_review",
            "create_pr",
            "ready_for_merge",
        }
        assert expected_phases == set(PHASE_TO_SPI.keys())


# ---------------------------------------------------------------------------
# Tests: build_metrics_from_result
# ---------------------------------------------------------------------------


class TestBuildMetricsFromResult:
    """Test metrics building from PhaseResult."""

    def test_success_path(self, sample_phase_result: PhaseResult):
        started = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 2, 9, 10, 5, 0, tzinfo=UTC)

        metrics = build_metrics_from_result(
            run_id="run-123",
            phase="implement",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            started_at=started,
            completed_at=completed,
            phase_result=sample_phase_result,
        )

        assert metrics.run_id == "run-123"
        assert metrics.phase == ContractEnumPipelinePhase.IMPLEMENT
        assert metrics.attempt == 1
        assert metrics.duration is not None
        assert metrics.duration.wall_clock_ms == 300_000.0  # 5 minutes
        assert metrics.cost is not None
        assert metrics.cost.llm_total_tokens == 15000
        assert metrics.outcome is not None
        assert (
            metrics.outcome.result_classification
            == ContractEnumResultClassification.SUCCESS
        )
        assert metrics.tests is not None
        assert metrics.tests.total_tests == 42
        assert metrics.tests.passed_tests == 40
        assert metrics.tests.failed_tests == 2
        assert metrics.context is not None
        assert metrics.context.ticket_id == "OMN-2027"
        assert metrics.producer is not None
        assert metrics.producer.name == PRODUCER_NAME

    def test_failure_path(self, sample_failed_result: PhaseResult):
        started = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 2, 9, 10, 2, 0, tzinfo=UTC)

        metrics = build_metrics_from_result(
            run_id="run-456",
            phase="local_review",
            attempt=2,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            started_at=started,
            completed_at=completed,
            phase_result=sample_failed_result,
        )

        assert metrics.phase == ContractEnumPipelinePhase.VERIFY
        assert metrics.attempt == 2
        assert metrics.outcome is not None
        assert (
            metrics.outcome.result_classification
            == ContractEnumResultClassification.FAILURE
        )
        assert "Tests failed" in metrics.outcome.error_messages[0]
        assert metrics.outcome.error_codes == ["blocked_review_limit"]

    def test_context_populated(self, sample_phase_result: PhaseResult):
        started = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 2, 9, 10, 1, 0, tzinfo=UTC)

        metrics = build_metrics_from_result(
            run_id="run-789",
            phase="implement",
            attempt=1,
            ticket_id="OMN-9999",
            repo_id="test-repo",
            started_at=started,
            completed_at=completed,
            phase_result=sample_phase_result,
        )

        assert metrics.context is not None
        assert metrics.context.ticket_id == "OMN-9999"
        assert metrics.context.repo_id == "test-repo"
        assert metrics.context.toolchain == "claude-code"

    def test_failure_reason_truncated_to_max(self):
        """Long reason strings are truncated to MAX_ERROR_MESSAGE_LENGTH in error_messages."""
        started = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 2, 9, 10, 2, 0, tzinfo=UTC)
        long_reason = "R" * 300  # well over MAX_ERROR_MESSAGE_LENGTH

        failed_result = PhaseResult(
            status="failed",
            blocking_issues=1,
            reason=long_reason,
            block_kind="test_failure",
        )

        metrics = build_metrics_from_result(
            run_id="run-trunc",
            phase="local_review",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            started_at=started,
            completed_at=completed,
            phase_result=failed_result,
        )

        assert metrics.outcome is not None
        assert len(metrics.outcome.error_messages) == 1
        assert len(metrics.outcome.error_messages[0]) == MAX_ERROR_MESSAGE_LENGTH
        assert metrics.outcome.error_messages[0].endswith("...")

    def test_short_reason_not_truncated(self):
        """Reason strings under MAX_ERROR_MESSAGE_LENGTH are kept verbatim."""
        started = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 2, 9, 10, 2, 0, tzinfo=UTC)
        short_reason = "3 blocking issues remain"

        failed_result = PhaseResult(
            status="failed",
            blocking_issues=3,
            reason=short_reason,
            block_kind="blocked_review_limit",
        )

        metrics = build_metrics_from_result(
            run_id="run-short",
            phase="local_review",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            started_at=started,
            completed_at=completed,
            phase_result=failed_result,
        )

        assert metrics.outcome is not None
        assert metrics.outcome.error_messages == [short_reason]

    def test_phase_id_format(self, sample_phase_result: PhaseResult):
        started = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 2, 9, 10, 1, 0, tzinfo=UTC)

        metrics = build_metrics_from_result(
            run_id="abc123",
            phase="create_pr",
            attempt=3,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            started_at=started,
            completed_at=completed,
            phase_result=sample_phase_result,
        )

        assert metrics.phase_id == "abc123-create_pr-3"


# ---------------------------------------------------------------------------
# Tests: build_error_metrics
# ---------------------------------------------------------------------------


class TestBuildErrorMetrics:
    """Test error metrics building."""

    def test_error_classification(self):
        started = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 2, 9, 10, 0, 5, tzinfo=UTC)
        error = RuntimeError("Connection timeout")

        metrics = build_error_metrics(
            run_id="run-err",
            phase="implement",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            started_at=started,
            completed_at=completed,
            error=error,
        )

        assert metrics.outcome is not None
        assert (
            metrics.outcome.result_classification
            == ContractEnumResultClassification.ERROR
        )
        assert "Connection timeout" in metrics.outcome.error_messages[0]
        assert "RuntimeError" in metrics.outcome.error_codes

    def test_error_message_truncation(self):
        started = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 2, 9, 10, 0, 5, tzinfo=UTC)
        long_msg = "x" * 500
        error = ValueError(long_msg)

        metrics = build_error_metrics(
            run_id="run-err2",
            phase="local_review",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            started_at=started,
            completed_at=completed,
            error=error,
        )

        assert metrics.outcome is not None
        assert len(metrics.outcome.error_messages[0]) == MAX_ERROR_MESSAGE_LENGTH
        assert metrics.outcome.error_messages[0].endswith("...")

    def test_short_error_message_not_truncated(self):
        """Error messages under MAX_ERROR_MESSAGE_LENGTH are kept verbatim."""
        started = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 2, 9, 10, 0, 5, tzinfo=UTC)
        short_msg = "Connection refused"
        error = RuntimeError(short_msg)

        metrics = build_error_metrics(
            run_id="run-err3",
            phase="implement",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            started_at=started,
            completed_at=completed,
            error=error,
        )

        assert metrics.outcome is not None
        assert metrics.outcome.error_messages[0] == short_msg
        assert not metrics.outcome.error_messages[0].endswith("...")


# ---------------------------------------------------------------------------
# Tests: build_skipped_metrics
# ---------------------------------------------------------------------------


class TestBuildSkippedMetrics:
    """Test skipped metrics building."""

    def test_skipped_classification(self):
        metrics = build_skipped_metrics(
            run_id="run-skip",
            phase="create_pr",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            skip_reason="Phase skipped by --skip-to",
            skip_reason_code="user_requested_skip",
        )

        assert metrics.outcome is not None
        assert (
            metrics.outcome.result_classification
            == ContractEnumResultClassification.SKIPPED
        )
        assert metrics.outcome.skip_reason_code == "user_requested_skip"
        assert "skipped by --skip-to" in metrics.outcome.skip_reason

    def test_silent_omission_code(self):
        metrics = build_skipped_metrics(
            run_id="run-omit",
            phase="implement",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            skip_reason="Phase exited without emitting metrics",
            skip_reason_code="metrics_missing_protocol_violation",
        )

        assert metrics.outcome is not None
        assert metrics.outcome.skip_reason_code == "metrics_missing_protocol_violation"

    def test_zero_duration(self):
        metrics = build_skipped_metrics(
            run_id="run-skip2",
            phase="local_review",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            skip_reason="test",
            skip_reason_code="test_skip",
        )

        assert metrics.duration is not None
        assert metrics.duration.wall_clock_ms == 0.0


# ---------------------------------------------------------------------------
# Tests: instrumented_phase
# ---------------------------------------------------------------------------


class TestInstrumentedPhase:
    """Test the instrumentation wrapper."""

    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.emit_phase_metrics", return_value=True
    )
    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.write_metrics_artifact",
        return_value=Path("/tmp/test.json"),
    )
    def test_success_path(self, mock_write, mock_emit):
        """Successful phase emits metrics and writes artifact."""
        fixed_start = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        fixed_end = datetime(2026, 2, 9, 10, 1, 0, tzinfo=UTC)
        expected_result = PhaseResult(status="completed", tokens_used=1000)

        result = instrumented_phase(
            run_id="run-inst-1",
            phase="implement",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            phase_fn=lambda: expected_result,
            started_at=fixed_start,
            completed_at=fixed_end,
        )

        assert result.status == "completed"
        mock_emit.assert_called_once()
        mock_write.assert_called_once()

        # Verify the metrics passed to emit
        emitted_metrics = mock_emit.call_args[0][0]
        assert emitted_metrics.run_id == "run-inst-1"
        assert (
            emitted_metrics.outcome.result_classification
            == ContractEnumResultClassification.SUCCESS
        )
        assert emitted_metrics.duration.wall_clock_ms == 60_000.0

    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.emit_phase_metrics", return_value=True
    )
    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.write_metrics_artifact",
        return_value=Path("/tmp/test.json"),
    )
    def test_error_path(self, mock_write, mock_emit):
        """Phase that raises emits error metrics and re-raises."""
        fixed_start = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        fixed_end = datetime(2026, 2, 9, 10, 0, 30, tzinfo=UTC)

        def failing_phase():
            raise RuntimeError("Phase crashed")

        with pytest.raises(RuntimeError, match="Phase crashed"):
            instrumented_phase(
                run_id="run-inst-2",
                phase="local_review",
                attempt=1,
                ticket_id="OMN-2027",
                repo_id="omniclaude2",
                phase_fn=failing_phase,
                started_at=fixed_start,
                completed_at=fixed_end,
            )

        # Metrics should still be emitted and written on error
        mock_emit.assert_called_once()
        mock_write.assert_called_once()

        emitted_metrics = mock_emit.call_args[0][0]
        assert (
            emitted_metrics.outcome.result_classification
            == ContractEnumResultClassification.ERROR
        )
        assert "Phase crashed" in emitted_metrics.outcome.error_messages[0]
        assert emitted_metrics.duration.wall_clock_ms == 30_000.0

    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.emit_phase_metrics", return_value=True
    )
    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.write_metrics_artifact",
        return_value=Path("/tmp/test.json"),
    )
    def test_blocked_result(self, mock_write, mock_emit):
        """Blocked phase result maps to PARTIAL classification."""
        fixed_start = datetime(2026, 2, 9, 10, 0, 0, tzinfo=UTC)
        fixed_end = datetime(2026, 2, 9, 10, 10, 0, tzinfo=UTC)
        blocked_result = PhaseResult(
            status="blocked",
            blocking_issues=2,
            reason="Review limit reached",
            block_kind="blocked_review_limit",
        )

        result = instrumented_phase(
            run_id="run-inst-3",
            phase="local_review",
            attempt=3,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            phase_fn=lambda: blocked_result,
            started_at=fixed_start,
            completed_at=fixed_end,
        )

        assert result.status == "blocked"
        emitted_metrics = mock_emit.call_args[0][0]
        assert (
            emitted_metrics.outcome.result_classification
            == ContractEnumResultClassification.PARTIAL
        )

    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.emit_phase_metrics", return_value=True
    )
    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.write_metrics_artifact",
        return_value=Path("/tmp/test.json"),
    )
    def test_injectable_started_at(self, mock_write, mock_emit):
        """instrumented_phase uses injected started_at for deterministic timing."""
        fixed_start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        fixed_end = datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC)
        result = instrumented_phase(
            run_id="run-timing",
            phase="implement",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            phase_fn=lambda: PhaseResult(status="completed"),
            started_at=fixed_start,
            completed_at=fixed_end,
        )
        assert result.status == "completed"
        emitted_metrics = mock_emit.call_args[0][0]
        # Duration should be exactly 5 minutes = 300000ms
        assert emitted_metrics.duration.wall_clock_ms == 300_000.0

    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.emit_phase_metrics", return_value=True
    )
    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.write_metrics_artifact",
        return_value=Path("/tmp/test.json"),
    )
    def test_injectable_completed_at_success(self, mock_write, mock_emit):
        """instrumented_phase uses injected completed_at on success path."""
        fixed_start = datetime(2026, 3, 1, 8, 0, 0, tzinfo=UTC)
        fixed_end = datetime(2026, 3, 1, 8, 2, 30, tzinfo=UTC)

        result = instrumented_phase(
            run_id="run-completed-at",
            phase="create_pr",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            phase_fn=lambda: PhaseResult(status="completed", tokens_used=500),
            started_at=fixed_start,
            completed_at=fixed_end,
        )

        assert result.status == "completed"
        emitted_metrics = mock_emit.call_args[0][0]
        # Duration should be exactly 2m30s = 150000ms
        assert emitted_metrics.duration.wall_clock_ms == 150_000.0

    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.emit_phase_metrics", return_value=True
    )
    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.write_metrics_artifact",
        return_value=Path("/tmp/test.json"),
    )
    def test_injectable_completed_at_error(self, mock_write, mock_emit):
        """instrumented_phase uses injected completed_at on error path."""
        fixed_start = datetime(2026, 3, 1, 8, 0, 0, tzinfo=UTC)
        fixed_end = datetime(2026, 3, 1, 8, 0, 10, tzinfo=UTC)

        def failing_phase():
            raise ValueError("Something broke")

        with pytest.raises(ValueError, match="Something broke"):
            instrumented_phase(
                run_id="run-completed-at-err",
                phase="implement",
                attempt=1,
                ticket_id="OMN-2027",
                repo_id="omniclaude2",
                phase_fn=failing_phase,
                started_at=fixed_start,
                completed_at=fixed_end,
            )

        emitted_metrics = mock_emit.call_args[0][0]
        # Duration should be exactly 10s = 10000ms
        assert emitted_metrics.duration.wall_clock_ms == 10_000.0
        assert (
            emitted_metrics.outcome.result_classification
            == ContractEnumResultClassification.ERROR
        )


# ---------------------------------------------------------------------------
# Tests: detect_silent_omission
# ---------------------------------------------------------------------------


class TestDetectSilentOmission:
    """Test silent omission detection."""

    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.metrics_artifact_exists",
        return_value=True,
    )
    def test_no_omission_when_artifact_exists(self, mock_exists):
        """No violation when artifact exists."""
        result = detect_silent_omission(
            ticket_id="OMN-2027",
            run_id="run-ok",
            phase="implement",
            attempt=1,
            repo_id="omniclaude2",
        )
        assert result is None

    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.write_metrics_artifact",
        return_value=Path("/tmp/test.json"),
    )
    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.emit_phase_metrics", return_value=True
    )
    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.metrics_artifact_exists",
        return_value=False,
    )
    def test_omission_detected_when_artifact_missing(
        self, mock_exists, mock_emit, mock_write
    ):
        """Violation record emitted when artifact missing."""
        result = detect_silent_omission(
            ticket_id="OMN-2027",
            run_id="run-bad",
            phase="implement",
            attempt=1,
            repo_id="omniclaude2",
        )

        assert result is not None
        assert result.outcome is not None
        assert (
            result.outcome.result_classification
            == ContractEnumResultClassification.SKIPPED
        )
        assert result.outcome.skip_reason_code == "metrics_missing_protocol_violation"

        # Should emit and write the violation
        mock_emit.assert_called_once()
        mock_write.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: MeasurementCheck results
# ---------------------------------------------------------------------------


class TestMeasurementChecks:
    """Test measurement check validation."""

    def test_all_checks_pass_for_valid_metrics(
        self, sample_metrics: ContractPhaseMetrics
    ):
        results = run_measurement_checks(sample_metrics, "implement")

        assert len(results) == 6
        for r in results:
            assert r.domain == "measurement"

        # All should pass for a well-formed metrics object
        check_ids = {r.check_id: r for r in results}
        assert check_ids[MeasurementCheck.CHECK_MEAS_001].passed  # metrics emitted
        assert check_ids[MeasurementCheck.CHECK_MEAS_002].passed  # duration in budget
        assert check_ids[MeasurementCheck.CHECK_MEAS_003].passed  # tokens in budget
        assert check_ids[MeasurementCheck.CHECK_MEAS_004].passed  # not test-bearing
        assert check_ids[MeasurementCheck.CHECK_MEAS_005].passed  # stable outcome
        assert check_ids[MeasurementCheck.CHECK_MEAS_006].passed  # complete metrics

    def test_duration_over_budget_fails(self):
        """CHECK-MEAS-002 fails when duration exceeds budget."""
        metrics = ContractPhaseMetrics(
            run_id="test",
            phase=ContractEnumPipelinePhase.IMPLEMENT,
            duration=ContractDurationMetrics(wall_clock_ms=99_999_999.0),
            outcome=ContractOutcomeMetrics(
                result_classification=ContractEnumResultClassification.SUCCESS,
            ),
            context=ContractMeasurementContext(ticket_id="TEST"),
            producer=ContractProducer(name="test"),
        )

        results = run_measurement_checks(metrics, "implement")
        check_map = {r.check_id: r for r in results}
        assert not check_map[MeasurementCheck.CHECK_MEAS_002].passed
        assert "exceeds budget" in check_map[MeasurementCheck.CHECK_MEAS_002].message

    def test_tokens_over_budget_fails(self):
        """CHECK-MEAS-003 fails when tokens exceed budget."""
        metrics = ContractPhaseMetrics(
            run_id="test",
            phase=ContractEnumPipelinePhase.IMPLEMENT,
            duration=ContractDurationMetrics(wall_clock_ms=1000.0),
            cost=ContractCostMetrics(llm_total_tokens=999_999),
            outcome=ContractOutcomeMetrics(
                result_classification=ContractEnumResultClassification.SUCCESS,
            ),
            context=ContractMeasurementContext(ticket_id="TEST"),
            producer=ContractProducer(name="test"),
        )

        results = run_measurement_checks(metrics, "implement")
        check_map = {r.check_id: r for r in results}
        assert not check_map[MeasurementCheck.CHECK_MEAS_003].passed

    def test_test_bearing_phase_requires_tests(self):
        """CHECK-MEAS-004 fails for test-bearing phase with no tests."""
        metrics = ContractPhaseMetrics(
            run_id="test",
            phase=ContractEnumPipelinePhase.VERIFY,
            duration=ContractDurationMetrics(wall_clock_ms=1000.0),
            outcome=ContractOutcomeMetrics(
                result_classification=ContractEnumResultClassification.SUCCESS,
            ),
            tests=ContractTestMetrics(total_tests=0),
            context=ContractMeasurementContext(ticket_id="TEST"),
            producer=ContractProducer(name="test"),
        )

        results = run_measurement_checks(metrics, "local_review")
        check_map = {r.check_id: r for r in results}
        assert not check_map[MeasurementCheck.CHECK_MEAS_004].passed
        assert "No tests ran" in check_map[MeasurementCheck.CHECK_MEAS_004].message

    def test_non_test_bearing_phase_passes_check_004(self):
        """CHECK-MEAS-004 passes for non-test-bearing phase."""
        metrics = ContractPhaseMetrics(
            run_id="test",
            phase=ContractEnumPipelinePhase.RELEASE,
            duration=ContractDurationMetrics(wall_clock_ms=1000.0),
            outcome=ContractOutcomeMetrics(
                result_classification=ContractEnumResultClassification.SUCCESS,
            ),
            context=ContractMeasurementContext(ticket_id="TEST"),
            producer=ContractProducer(name="test"),
        )

        results = run_measurement_checks(metrics, "create_pr")
        check_map = {r.check_id: r for r in results}
        assert check_map[MeasurementCheck.CHECK_MEAS_004].passed

    def test_error_without_codes_fails_flake_check(self):
        """CHECK-MEAS-005 fails when ERROR has no error_codes."""
        metrics = ContractPhaseMetrics(
            run_id="test",
            phase=ContractEnumPipelinePhase.IMPLEMENT,
            duration=ContractDurationMetrics(wall_clock_ms=1000.0),
            outcome=ContractOutcomeMetrics(
                result_classification=ContractEnumResultClassification.ERROR,
                error_codes=[],  # No codes = possible flake
            ),
            context=ContractMeasurementContext(ticket_id="TEST"),
            producer=ContractProducer(name="test"),
        )

        results = run_measurement_checks(metrics, "implement")
        check_map = {r.check_id: r for r in results}
        assert not check_map[MeasurementCheck.CHECK_MEAS_005].passed

    def test_missing_mandatory_fields_fails_completeness(self):
        """CHECK-MEAS-006 fails when mandatory fields missing."""
        metrics = ContractPhaseMetrics(
            run_id="test",
            phase=ContractEnumPipelinePhase.IMPLEMENT,
            # No duration, no outcome, no context, no producer
        )

        results = run_measurement_checks(metrics, "implement")
        check_map = {r.check_id: r for r in results}
        assert not check_map[MeasurementCheck.CHECK_MEAS_006].passed

    def test_none_metrics_fails_all_checks(self):
        """All checks fail when metrics are None (no metrics emitted)."""
        results = run_measurement_checks(None, "implement")

        assert len(results) == 6
        # CHECK-MEAS-001 should fail (no metrics emitted)
        assert not results[0].passed
        assert results[0].check_id == MeasurementCheck.CHECK_MEAS_001
        assert "missing" in results[0].message.lower()

        # All remaining checks should fail with "no metrics available"
        for r in results[1:]:
            assert not r.passed
            assert "no metrics available" in r.message.lower()


# ---------------------------------------------------------------------------
# Tests: Metrics Emitter
# ---------------------------------------------------------------------------


class TestMetricsEmitter:
    """Test the metrics emission adapter layer."""

    def test_write_and_read_artifact(
        self, _tmp_artifact_dir: Path, sample_metrics: ContractPhaseMetrics
    ):
        """Write then read a metrics artifact."""
        path = write_metrics_artifact(
            ticket_id="OMN-2027",
            run_id="test-run",
            phase="implement",
            attempt=1,
            metrics=sample_metrics,
        )

        assert path is not None
        assert path.exists()

        # Read it back
        data = read_metrics_artifact(
            ticket_id="OMN-2027",
            run_id="test-run",
            phase="implement",
            attempt=1,
        )

        assert data is not None
        assert data["run_id"] == "test-run-1"
        assert data["phase"] == "implement"

    def test_artifact_exists_check(
        self, _tmp_artifact_dir: Path, sample_metrics: ContractPhaseMetrics
    ):
        """metrics_artifact_exists returns correct values."""
        assert not metrics_artifact_exists("OMN-2027", "test-run", "implement", 1)

        write_metrics_artifact(
            ticket_id="OMN-2027",
            run_id="test-run",
            phase="implement",
            attempt=1,
            metrics=sample_metrics,
        )

        assert metrics_artifact_exists("OMN-2027", "test-run", "implement", 1)

    def test_read_nonexistent_artifact(self, _tmp_artifact_dir: Path):
        """Reading nonexistent artifact returns None."""
        result = read_metrics_artifact("OMN-XXXX", "no-run", "fake", 1)
        assert result is None

    @pytest.mark.parametrize(
        "bad_component",
        ["../escape", "a/b", "a\\b", "a\x00b"],
        ids=["dotdot", "slash", "backslash", "null"],
    )
    def test_write_rejects_path_traversal(
        self,
        _tmp_artifact_dir: Path,
        sample_metrics: ContractPhaseMetrics,
        bad_component: str,
    ):
        """write_metrics_artifact rejects path traversal in components."""
        assert (
            write_metrics_artifact(bad_component, "run", "phase", 1, sample_metrics)
            is None
        )
        assert (
            write_metrics_artifact("OMN-1", bad_component, "phase", 1, sample_metrics)
            is None
        )
        assert (
            write_metrics_artifact("OMN-1", "run", bad_component, 1, sample_metrics)
            is None
        )

    @pytest.mark.parametrize(
        "bad_component",
        ["../escape", "a/b", "a\\b", "a\x00b"],
        ids=["dotdot", "slash", "backslash", "null"],
    )
    def test_read_rejects_path_traversal(
        self, _tmp_artifact_dir: Path, bad_component: str
    ):
        """read_metrics_artifact rejects path traversal in components."""
        assert read_metrics_artifact(bad_component, "run", "phase", 1) is None
        assert read_metrics_artifact("OMN-1", bad_component, "phase", 1) is None
        assert read_metrics_artifact("OMN-1", "run", bad_component, 1) is None

    @pytest.mark.parametrize(
        "bad_component",
        ["../escape", "a/b", "a\\b", "a\x00b"],
        ids=["dotdot", "slash", "backslash", "null"],
    )
    def test_exists_rejects_path_traversal(
        self, _tmp_artifact_dir: Path, bad_component: str
    ):
        """metrics_artifact_exists rejects path traversal in components."""
        assert not metrics_artifact_exists(bad_component, "run", "phase", 1)
        assert not metrics_artifact_exists("OMN-1", bad_component, "phase", 1)
        assert not metrics_artifact_exists("OMN-1", "run", bad_component, 1)

    @patch("plugins.onex.hooks.lib.emit_client_wrapper.emit_event", return_value=True)
    def test_emit_phase_metrics_calls_daemon(
        self, mock_emit, sample_metrics: ContractPhaseMetrics
    ):
        """emit_phase_metrics wraps in event and calls daemon."""
        success = emit_phase_metrics(
            sample_metrics, timestamp_iso="2026-02-09T12:00:00+00:00"
        )

        assert success is True
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        assert call_args[0][0] == "phase.metrics"
        payload = call_args[0][1]
        assert "event_id" in payload
        assert "payload" in payload

    @patch("plugins.onex.hooks.lib.emit_client_wrapper.emit_event", return_value=False)
    def test_emit_returns_false_on_daemon_failure(
        self, mock_emit, sample_metrics: ContractPhaseMetrics
    ):
        """emit_phase_metrics returns False when daemon fails."""
        success = emit_phase_metrics(
            sample_metrics, timestamp_iso="2026-02-09T12:00:00+00:00"
        )
        assert success is False

    @patch("plugins.onex.hooks.lib.emit_client_wrapper.emit_event", return_value=True)
    def test_emit_forwards_injectable_params(
        self, mock_emit, sample_metrics: ContractPhaseMetrics
    ):
        """emit_phase_metrics forwards timestamp_iso and event_id to event."""
        success = emit_phase_metrics(
            sample_metrics,
            timestamp_iso="2026-02-09T12:00:00+00:00",
            event_id="fixed123",
        )
        assert success is True
        payload = mock_emit.call_args[0][1]
        assert payload["event_id"] == "fixed123"
        assert payload["timestamp_iso"] == "2026-02-09T12:00:00+00:00"

    @patch("plugins.onex.hooks.lib.emit_client_wrapper.emit_event", return_value=True)
    def test_emit_sanitizes_failed_tests_in_payload(self, mock_emit):
        """emit_phase_metrics truncates and caps failed_tests before emission."""
        long_test_name = "test_" + "x" * 200  # Over MAX_FAILED_TEST_LENGTH
        many_tests = [f"test_case_{i}" for i in range(30)]  # Over MAX_FAILED_TESTS

        metrics = ContractPhaseMetrics(
            run_id="test-sanitize",
            phase=ContractEnumPipelinePhase.VERIFY,
            phase_id="test-sanitize-local_review-1",
            attempt=1,
            context=ContractMeasurementContext(
                ticket_id="OMN-TEST",
                repo_id="test-repo",
                toolchain="claude-code",
            ),
            producer=ContractProducer(
                name=PRODUCER_NAME,
                version=PRODUCER_VERSION,
                instance_id="test-inst",
            ),
            duration=ContractDurationMetrics(wall_clock_ms=1000.0),
            outcome=ContractOutcomeMetrics(
                result_classification=ContractEnumResultClassification.FAILURE,
                failed_tests=[long_test_name] + many_tests,
            ),
        )

        success = emit_phase_metrics(metrics, timestamp_iso="2026-02-09T12:00:00+00:00")
        assert success is True

        # Verify the payload sent to emit_event has sanitized failed_tests
        call_args = mock_emit.call_args
        payload = call_args[0][1]
        emitted_tests = payload["payload"]["outcome"]["failed_tests"]

        # Capped at MAX_FAILED_TESTS (20)
        assert len(emitted_tests) <= 20

        # First entry (long name) should be truncated to MAX_FAILED_TEST_LENGTH (100)
        assert len(emitted_tests[0]) <= 100
        assert emitted_tests[0].endswith("...")

    @patch("plugins.onex.hooks.lib.emit_client_wrapper.emit_event", return_value=True)
    def test_emit_sanitizes_skip_reason_in_payload(self, mock_emit):
        """emit_phase_metrics redacts and truncates skip_reason before emission."""
        secret_key = "sk-abc123456789abcdefghij"
        long_reason = f"Skipped due to key {secret_key} " + "x" * 200

        metrics = ContractPhaseMetrics(
            run_id="test-skip-sanitize",
            phase=ContractEnumPipelinePhase.IMPLEMENT,
            phase_id="test-skip-sanitize-implement-1",
            attempt=1,
            context=ContractMeasurementContext(
                ticket_id="OMN-TEST",
                repo_id="test-repo",
                toolchain="claude-code",
            ),
            producer=ContractProducer(
                name=PRODUCER_NAME,
                version=PRODUCER_VERSION,
                instance_id="test-inst",
            ),
            duration=ContractDurationMetrics(wall_clock_ms=0.0),
            outcome=ContractOutcomeMetrics(
                result_classification=ContractEnumResultClassification.SKIPPED,
                skip_reason=long_reason,
                skip_reason_code="test_skip",
            ),
        )

        success = emit_phase_metrics(metrics, timestamp_iso="2026-02-09T12:00:00+00:00")
        assert success is True

        call_args = mock_emit.call_args
        payload = call_args[0][1]
        emitted_reason = payload["payload"]["outcome"]["skip_reason"]

        # Must be truncated to MAX_ERROR_MESSAGE_LENGTH
        assert len(emitted_reason) <= MAX_ERROR_MESSAGE_LENGTH
        # Must not contain the raw secret
        assert secret_key not in emitted_reason
        assert "REDACTED" in emitted_reason

    def test_write_artifact_sanitizes_skip_reason(
        self,
        _tmp_artifact_dir: Path,
    ):
        """write_metrics_artifact redacts and truncates skip_reason in file."""
        secret_key = "sk-abc123456789abcdefghij"
        long_reason = f"Skipped with key {secret_key} " + "y" * 200

        metrics = ContractPhaseMetrics(
            run_id="test-skip-artifact",
            phase=ContractEnumPipelinePhase.IMPLEMENT,
            phase_id="test-skip-artifact-implement-1",
            attempt=1,
            context=ContractMeasurementContext(
                ticket_id="OMN-TEST",
                repo_id="test-repo",
                toolchain="claude-code",
            ),
            producer=ContractProducer(
                name=PRODUCER_NAME,
                version=PRODUCER_VERSION,
                instance_id="test-inst",
            ),
            duration=ContractDurationMetrics(wall_clock_ms=0.0),
            outcome=ContractOutcomeMetrics(
                result_classification=ContractEnumResultClassification.SKIPPED,
                skip_reason=long_reason,
                skip_reason_code="test_skip",
            ),
        )

        path = write_metrics_artifact(
            ticket_id="OMN-TEST",
            run_id="test-skip-artifact",
            phase="implement",
            attempt=1,
            metrics=metrics,
        )

        assert path is not None
        assert path.exists()

        data = read_metrics_artifact(
            ticket_id="OMN-TEST",
            run_id="test-skip-artifact",
            phase="implement",
            attempt=1,
        )

        assert data is not None
        written_reason = data["outcome"]["skip_reason"]
        # Must be truncated
        assert len(written_reason) <= MAX_ERROR_MESSAGE_LENGTH
        # Must not contain the raw secret
        assert secret_key not in written_reason
        assert "REDACTED" in written_reason


# ---------------------------------------------------------------------------
# Tests: PhaseResult
# ---------------------------------------------------------------------------


class TestPhaseResult:
    """Test the PhaseResult data class."""

    def test_default_values(self):
        result = PhaseResult()
        assert result.status == "completed"
        assert result.blocking_issues == 0
        assert result.nit_count == 0
        assert result.artifacts == {}
        assert result.reason is None
        assert result.block_kind is None
        assert result.tokens_used == 0
        assert result.api_calls == 0
        assert result.tests_total == 0
        assert result.tests_passed == 0
        assert result.tests_failed == 0
        assert result.review_iteration == 0

    def test_custom_values(self):
        result = PhaseResult(
            status="blocked",
            blocking_issues=5,
            reason="max iterations",
            block_kind="blocked_review_limit",
            tokens_used=50000,
        )
        assert result.status == "blocked"
        assert result.blocking_issues == 5
        assert result.tokens_used == 50000

    def test_invalid_status_coerced_to_failed(self):
        """Invalid status values are silently coerced to 'failed' for safety."""
        result = PhaseResult(status="success")  # type: ignore[arg-type]
        assert result.status == "failed"

    def test_all_valid_statuses_accepted(self):
        """All valid statuses are accepted without coercion."""
        for status in ("completed", "blocked", "failed"):
            result = PhaseResult(status=status)  # type: ignore[arg-type]
            assert result.status == status


# ---------------------------------------------------------------------------
# Tests: MeasurementCheckResult
# ---------------------------------------------------------------------------


class TestMeasurementCheckResult:
    """Test the MeasurementCheckResult type."""

    def test_repr_pass(self):
        r = MeasurementCheckResult(
            check_id="CHECK-MEAS-001",
            passed=True,
            message="Phase metrics emitted",
        )
        assert "PASS" in repr(r)
        assert r.domain == "measurement"

    def test_repr_fail(self):
        r = MeasurementCheckResult(
            check_id="CHECK-MEAS-002",
            passed=False,
            message="Duration exceeds budget",
        )
        assert "FAIL" in repr(r)


# ---------------------------------------------------------------------------
# Tests: Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Test that constants are configured correctly."""

    def test_all_phases_have_duration_budget(self):
        for phase in PHASE_TO_SPI:
            assert phase in DURATION_BUDGETS_MS, f"Missing duration budget for {phase}"

    def test_all_phases_have_token_budget(self):
        for phase in PHASE_TO_SPI:
            assert phase in TOKEN_BUDGETS, f"Missing token budget for {phase}"

    def test_local_review_is_test_bearing(self):
        assert "local_review" in TEST_BEARING_PHASES

    def test_implement_is_not_test_bearing(self):
        assert "implement" not in TEST_BEARING_PHASES

    def test_producer_identity(self):
        assert PRODUCER_NAME == "ticket-pipeline"
        assert PRODUCER_VERSION == "0.2.1"


# ---------------------------------------------------------------------------
# Tests: Sanitization functions (security-critical for evt topic)
# ---------------------------------------------------------------------------


class TestSanitization:
    """Direct tests for sanitization functions in metrics_emitter.py.

    These functions guard the broad-access evt topic against secret leakage
    and oversized payloads. Each is security-critical.
    """

    # -- _sanitize_error_messages --

    def test_error_message_truncation(self):
        """Messages over MAX_ERROR_MESSAGE_LENGTH are truncated with trailing '...'."""
        long_msg = "A" * 300
        result = _sanitize_error_messages([long_msg])
        assert len(result) == 1
        assert len(result[0]) == MAX_ERROR_MESSAGE_LENGTH
        assert result[0].endswith("...")

    def test_error_messages_capped_at_five(self):
        """More than 5 messages are trimmed to exactly 5."""
        messages = [f"error-{i}" for i in range(10)]
        result = _sanitize_error_messages(messages)
        assert len(result) == 5

    def test_error_messages_secret_redaction(self):
        """Messages containing secrets (e.g. OpenAI key) get redacted."""
        # Pattern requires sk- followed by 20+ alphanumeric chars
        secret_key = "sk-abc123456789abcdefghij"
        secret_msg = f"Failed with key {secret_key} in request"
        result = _sanitize_error_messages([secret_msg])
        assert len(result) == 1
        # The original secret should not appear verbatim in the output
        assert secret_key not in result[0]
        assert "REDACTED" in result[0]

    def test_error_messages_empty_list(self):
        """Empty input returns empty output."""
        assert _sanitize_error_messages([]) == []

    # -- _sanitize_failed_tests --

    def test_failed_test_truncation(self):
        """Test names over 100 chars are truncated with trailing '...'."""
        long_name = "test_" + "x" * 200
        result = _sanitize_failed_tests([long_name])
        assert len(result) == 1
        assert len(result[0]) == 100
        assert result[0].endswith("...")

    def test_failed_tests_capped_at_twenty(self):
        """More than 20 tests are trimmed to exactly 20."""
        tests = [f"test_case_{i}" for i in range(30)]
        result = _sanitize_failed_tests(tests)
        assert len(result) == 20

    def test_failed_tests_empty_list(self):
        """Empty input returns empty output."""
        assert _sanitize_failed_tests([]) == []

    # -- _validate_artifact_uri --

    def test_rejects_users_path(self):
        """/Users/ in URI is rejected."""
        assert (
            _validate_artifact_uri("/Users/jonah/artifacts/report.html")
            is False  # local-path-ok
        )

    def test_rejects_home_path(self):
        """/home/ in URI is rejected."""
        assert (
            _validate_artifact_uri("/home/deploy/artifacts/report.html")
            is False  # local-path-ok
        )

    def test_rejects_root_path(self):
        """/root/ in URI is rejected."""
        assert _validate_artifact_uri("/root/.cache/artifact.json") is False

    def test_rejects_windows_path(self):
        """C:\\ in URI is rejected."""
        assert _validate_artifact_uri("C:\\Users\\admin\\report.html") is False

    def test_rejects_file_uri(self):
        """file:// URIs are rejected."""
        assert _validate_artifact_uri("file:///tmp/secret.json") is False

    def test_rejects_file_uri_case_insensitive(self):
        """file:// scheme check is case-insensitive per RFC 3986."""
        assert _validate_artifact_uri("File:///custom/data.json") is False
        assert _validate_artifact_uri("FILE:///opt/report.html") is False
        assert _validate_artifact_uri("fIlE:///secret") is False

    def test_rejects_tilde_path(self):
        """~ paths are rejected."""
        assert _validate_artifact_uri("~/.ssh/id_rsa") is False

    def test_rejects_absolute_path(self):
        """Arbitrary absolute paths are rejected."""
        assert _validate_artifact_uri("/etc/passwd") is False
        assert _validate_artifact_uri("/var/log/syslog") is False

    def test_rejects_var_path(self):
        """/var/ in URI is rejected."""
        assert _validate_artifact_uri("/var/log/pipeline/report.html") is False

    def test_rejects_tmp_path(self):
        """/tmp/ in URI is rejected."""
        assert _validate_artifact_uri("/tmp/metrics-output.json") is False

    def test_rejects_opt_path(self):
        """/opt/ in URI is rejected."""
        assert _validate_artifact_uri("/opt/app/artifacts/report.html") is False

    def test_rejects_srv_path(self):
        """/srv/ in URI is rejected."""
        assert _validate_artifact_uri("/srv/data/artifact.json") is False

    def test_rejects_d_drive(self):
        """D:\\ in URI is rejected."""
        assert _validate_artifact_uri("D:\\Projects\\report.html") is False

    def test_rejects_e_drive(self):
        """E:\\ in URI is rejected."""
        assert _validate_artifact_uri("E:\\Builds\\artifact.json") is False

    def test_rejects_lowercase_windows_drive(self):
        """Lowercase drive letters like c:\\ are also rejected."""
        assert _validate_artifact_uri("c:\\Users\\admin\\report.html") is False
        assert _validate_artifact_uri("d:\\Projects\\build.json") is False

    def test_rejects_volumes_path(self):
        """/Volumes/ in URI is rejected (macOS external drives)."""
        assert (
            _validate_artifact_uri("/Volumes/PRO-G40/Code/report.html")
            is False  # local-path-ok
        )

    def test_rejects_unc_path(self):
        """UNC paths like \\\\server\\share are rejected."""
        assert _validate_artifact_uri("\\\\fileserver\\builds\\report.html") is False
        unc_ip_path = "\\\\192.168.1.1\\share\\artifact.json"  # onex-allow-internal-ip
        assert not _validate_artifact_uri(unc_ip_path)

    def test_rejects_case_insensitive_prefix_at_start(self):
        """Absolute path prefixes are matched case-insensitively at URI start."""
        # Uppercase variants that would bypass a case-sensitive check
        assert _validate_artifact_uri("/USERS/admin/file.txt") is False
        assert _validate_artifact_uri("/HOME/deploy/file.txt") is False
        assert _validate_artifact_uri("/VOLUMES/drive/file.txt") is False

    def test_accepts_path_prefix_as_substring_in_url(self):
        """Path prefixes appearing as substrings in URLs should NOT be rejected.

        Only URIs that *start with* absolute path prefixes are rejected.
        S3/GCS/HTTPS URIs containing words like 'users' in their path
        segments are legitimate artifact pointers.
        """
        assert _validate_artifact_uri("s3://bucket/users/admin/file.txt") is True
        assert _validate_artifact_uri("s3://bucket/USERS/admin/file.txt") is True
        assert _validate_artifact_uri("s3://bucket/volumes/drive/file.txt") is True
        assert _validate_artifact_uri("s3://bucket/HOME/deploy/file.txt") is True
        assert (
            _validate_artifact_uri(
                "https://cdn.example.com/home/assets/img.png"  # local-path-ok
            )
            is True
        )

    def test_accepts_relative_path(self):
        """Relative paths like artifacts/report.html are accepted."""
        assert _validate_artifact_uri("artifacts/report.html") is True

    def test_accepts_https_url(self):
        """HTTPS URLs are accepted."""
        assert _validate_artifact_uri("https://ci.example.com/report") is True

    # -- _sanitize_skip_reason --

    def test_skip_reason_truncation(self):
        """Long skip_reason is truncated to MAX_ERROR_MESSAGE_LENGTH."""
        long_reason = "S" * 300
        result = _sanitize_skip_reason(long_reason)
        assert len(result) == MAX_ERROR_MESSAGE_LENGTH
        assert result.endswith("...")

    def test_skip_reason_short_passthrough(self):
        """Short skip_reason passes through unchanged."""
        short_reason = "Phase skipped by user"
        result = _sanitize_skip_reason(short_reason)
        assert result == short_reason

    def test_skip_reason_secret_redaction(self):
        """skip_reason containing secrets gets redacted."""
        secret_key = "sk-abc123456789abcdefghij"
        reason = f"Skipped due to auth failure with key {secret_key}"
        result = _sanitize_skip_reason(reason)
        assert secret_key not in result
        assert "REDACTED" in result

    # -- _build_measurement_event --

    def test_injectable_timestamp_and_event_id(
        self, sample_metrics: ContractPhaseMetrics
    ):
        """Explicit timestamp_iso and event_id are used when provided."""
        event = _build_measurement_event(
            sample_metrics,
            timestamp_iso="2026-02-09T12:00:00+00:00",
            event_id="test1234",
        )
        assert event.event_id == "test1234"
        assert event.timestamp_iso == "2026-02-09T12:00:00+00:00"

    def test_event_envelope_structure(self, sample_metrics: ContractPhaseMetrics):
        """Event envelope has required keys."""
        event = _build_measurement_event(
            sample_metrics,
            timestamp_iso="2026-02-09T00:00:00+00:00",
            event_id="abcd1234",
        )
        assert event.event_type == "phase_completed"
        assert event.payload is sample_metrics


# ---------------------------------------------------------------------------
# Tests: Frozen contract compliance
# ---------------------------------------------------------------------------


class TestFrozenCompliance:
    """Verify metrics contracts are immutable (frozen=True)."""

    def test_phase_metrics_is_frozen(self, sample_metrics: ContractPhaseMetrics):
        with pytest.raises(ValidationError):
            sample_metrics.run_id = "mutated"  # type: ignore[misc]

    def test_round_trip_json(self, sample_metrics: ContractPhaseMetrics):
        """Metrics survive JSON round-trip."""
        data = sample_metrics.model_dump(mode="json")
        restored = ContractPhaseMetrics.model_validate(data)
        assert restored.run_id == sample_metrics.run_id
        assert restored.phase == sample_metrics.phase
