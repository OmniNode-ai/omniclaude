"""Tests for phase instrumentation protocol (OMN-2027).

Covers:
    - Success path: instrumented_phase wraps and emits correctly
    - Failure path: instrumented_phase captures errors and emits
    - Skip path: build_skipped_metrics produces correct records
    - Silent omission detection: detect_silent_omission fires correctly
    - MeasurementCheck validation: all 6 checks produce correct results
    - Metrics building: all sub-contracts populated correctly
    - Phase -> SPI mapping: all 5 phases map correctly

.. versionadded:: 0.2.1
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure src is importable
_src_path = str(Path(__file__).parent.parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

# Ensure plugins is importable
_plugins_path = str(
    Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if _plugins_path not in sys.path:
    sys.path.insert(0, _plugins_path)

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

    def test_pr_release_ready_maps_to_review(self):
        assert PHASE_TO_SPI["pr_release_ready"] == ContractEnumPipelinePhase.REVIEW

    def test_ready_for_merge_maps_to_release(self):
        assert PHASE_TO_SPI["ready_for_merge"] == ContractEnumPipelinePhase.RELEASE

    def test_all_pipeline_phases_have_mapping(self):
        """All 5 pipeline phases must have an SPI mapping."""
        expected_phases = {
            "implement",
            "local_review",
            "create_pr",
            "pr_release_ready",
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
        error = RuntimeError("Connection timeout")

        metrics = build_error_metrics(
            run_id="run-err",
            phase="implement",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            started_at=started,
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
        long_msg = "x" * 500
        error = ValueError(long_msg)

        metrics = build_error_metrics(
            run_id="run-err2",
            phase="local_review",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            started_at=started,
            error=error,
        )

        assert metrics.outcome is not None
        assert len(metrics.outcome.error_messages[0]) <= 200


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
        expected_result = PhaseResult(status="completed", tokens_used=1000)

        result = instrumented_phase(
            run_id="run-inst-1",
            phase="implement",
            attempt=1,
            ticket_id="OMN-2027",
            repo_id="omniclaude2",
            phase_fn=lambda: expected_result,
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

    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.emit_phase_metrics", return_value=True
    )
    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.write_metrics_artifact",
        return_value=Path("/tmp/test.json"),
    )
    def test_error_path(self, mock_write, mock_emit):
        """Phase that raises emits error metrics and re-raises."""

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

    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.emit_phase_metrics", return_value=True
    )
    @patch(
        "plugins.onex.hooks.lib.metrics_emitter.write_metrics_artifact",
        return_value=Path("/tmp/test.json"),
    )
    def test_blocked_result(self, mock_write, mock_emit):
        """Blocked phase result maps to PARTIAL classification."""
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
        )

        assert result.status == "blocked"
        emitted_metrics = mock_emit.call_args[0][0]
        assert (
            emitted_metrics.outcome.result_classification
            == ContractEnumResultClassification.PARTIAL
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

    @patch("plugins.onex.hooks.lib.emit_client_wrapper.emit_event", return_value=True)
    def test_emit_phase_metrics_calls_daemon(
        self, mock_emit, sample_metrics: ContractPhaseMetrics
    ):
        """emit_phase_metrics wraps in event and calls daemon."""
        success = emit_phase_metrics(sample_metrics)

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
        success = emit_phase_metrics(sample_metrics)
        assert success is False


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
# Tests: Frozen contract compliance
# ---------------------------------------------------------------------------


class TestFrozenCompliance:
    """Verify metrics contracts are immutable (frozen=True)."""

    def test_phase_metrics_is_frozen(self, sample_metrics: ContractPhaseMetrics):
        with pytest.raises(Exception):
            sample_metrics.run_id = "mutated"  # type: ignore[misc]

    def test_round_trip_json(self, sample_metrics: ContractPhaseMetrics):
        """Metrics survive JSON round-trip."""
        data = sample_metrics.model_dump(mode="json")
        restored = ContractPhaseMetrics.model_validate(data)
        assert restored.run_id == sample_metrics.run_id
        assert restored.phase == sample_metrics.phase
