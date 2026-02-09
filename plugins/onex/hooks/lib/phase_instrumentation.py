"""Phase Instrumentation Protocol -- mandatory metrics for every pipeline phase.

Every pipeline phase MUST emit metrics via this instrumentation layer.
A phase that exits without emitting metrics is a protocol violation.
The orchestrator detects silent omissions and emits a `skipped` record
with ``skip_reason_code="metrics_missing_protocol_violation"``.

Architecture:
    - ``instrumented_phase()`` wraps any phase callable, captures timing,
      outcome, and test metrics, then emits + persists results.
    - ``detect_silent_omission()`` checks after each phase whether the
      metrics artifact exists, and emits a violation record if missing.
    - ``run_measurement_checks()`` produces ContractCheckResult instances
      for the measurement domain (CHECK-MEAS-001 through 006).

Phase -> SPI Enum Mapping:
    Pipeline Phase          | SPI ContractEnumPipelinePhase
    ----------------------- | -----------------------------
    implement (ticket_work) | IMPLEMENT
    local_review            | VERIFY
    create_pr               | RELEASE
    pr_release_ready        | REVIEW
    ready_for_merge         | RELEASE (terminal)

Related Tickets:
    - OMN-2024: M1 Measurement Contracts (SPI)
    - OMN-2025: M2 Metrics Emission via Emit Daemon
    - OMN-2027: M6 Phase Instrumentation Protocol

.. versionadded:: 0.2.1
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

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

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Producer identity for phase instrumentation
PRODUCER_NAME = "ticket-pipeline"
PRODUCER_VERSION = "0.2.1"

# Pipeline phase -> SPI phase mapping
PHASE_TO_SPI: dict[str, ContractEnumPipelinePhase] = {
    "implement": ContractEnumPipelinePhase.IMPLEMENT,
    "local_review": ContractEnumPipelinePhase.VERIFY,
    "create_pr": ContractEnumPipelinePhase.RELEASE,
    "pr_release_ready": ContractEnumPipelinePhase.REVIEW,
    "ready_for_merge": ContractEnumPipelinePhase.RELEASE,
}

# Phases that are expected to run tests
TEST_BEARING_PHASES = frozenset({"local_review"})

# Duration budgets per phase (milliseconds)
DURATION_BUDGETS_MS: dict[str, float] = {
    "implement": 1_800_000,  # 30 minutes
    "local_review": 600_000,  # 10 minutes
    "create_pr": 120_000,  # 2 minutes
    "pr_release_ready": 600_000,  # 10 minutes
    "ready_for_merge": 60_000,  # 1 minute
}

# Token budgets per phase
TOKEN_BUDGETS: dict[str, int] = {
    "implement": 500_000,
    "local_review": 200_000,
    "create_pr": 50_000,
    "pr_release_ready": 200_000,
    "ready_for_merge": 10_000,
}


# ---------------------------------------------------------------------------
# Phase Result Type
# ---------------------------------------------------------------------------


class PhaseResult:
    """Structured result from an instrumented phase execution.

    Attributes:
        status: One of "completed", "blocked", "failed".
        blocking_issues: Count of remaining blocking issues.
        nit_count: Count of deferred nit issues.
        artifacts: Dict of produced artifact keys and values.
        reason: Human-readable reason if blocked/failed.
        block_kind: Machine-stable block classification.
        tokens_used: Total tokens consumed (if tracked).
        api_calls: Number of API calls made (if tracked).
        tests_total: Total test count (if applicable).
        tests_passed: Passed test count (if applicable).
        tests_failed: Failed test count (if applicable).
        review_iteration: Review iteration number (if applicable).
    """

    __slots__ = (
        "api_calls",
        "artifacts",
        "block_kind",
        "blocking_issues",
        "nit_count",
        "reason",
        "review_iteration",
        "status",
        "tests_failed",
        "tests_passed",
        "tests_total",
        "tokens_used",
    )

    def __init__(
        self,
        *,
        status: str = "completed",
        blocking_issues: int = 0,
        nit_count: int = 0,
        artifacts: dict[str, Any] | None = None,
        reason: str | None = None,
        block_kind: str | None = None,
        tokens_used: int = 0,
        api_calls: int = 0,
        tests_total: int = 0,
        tests_passed: int = 0,
        tests_failed: int = 0,
        review_iteration: int = 0,
    ) -> None:
        self.status = status
        self.blocking_issues = blocking_issues
        self.nit_count = nit_count
        self.artifacts = artifacts or {}
        self.reason = reason
        self.block_kind = block_kind
        self.tokens_used = tokens_used
        self.api_calls = api_calls
        self.tests_total = tests_total
        self.tests_passed = tests_passed
        self.tests_failed = tests_failed
        self.review_iteration = review_iteration


# ---------------------------------------------------------------------------
# Metrics Building
# ---------------------------------------------------------------------------


def _classify_result(phase_result: PhaseResult) -> ContractEnumResultClassification:
    """Map a PhaseResult status to a ContractEnumResultClassification.

    Args:
        phase_result: The phase result to classify.

    Returns:
        The SPI result classification enum value.
    """
    mapping = {
        "completed": ContractEnumResultClassification.SUCCESS,
        "blocked": ContractEnumResultClassification.PARTIAL,
        "failed": ContractEnumResultClassification.FAILURE,
    }
    return mapping.get(phase_result.status, ContractEnumResultClassification.ERROR)


def build_metrics_from_result(
    *,
    run_id: str,
    phase: str,
    attempt: int,
    ticket_id: str,
    repo_id: str,
    started_at: datetime,
    completed_at: datetime,
    phase_result: PhaseResult,
    instance_id: str = "",
) -> ContractPhaseMetrics:
    """Build a ContractPhaseMetrics from a PhaseResult.

    Populates all sub-contracts (duration, cost, outcome, tests) based
    on the phase result and timing information.

    Args:
        run_id: Pipeline run identifier.
        phase: Pipeline phase name.
        attempt: Attempt number (1-based).
        ticket_id: Ticket identifier (e.g. OMN-2027).
        repo_id: Repository identifier.
        started_at: Phase start timestamp.
        completed_at: Phase completion timestamp.
        phase_result: The structured phase result.
        instance_id: Optional instance identifier.

    Returns:
        A fully populated ContractPhaseMetrics.
    """
    wall_clock_ms = (completed_at - started_at).total_seconds() * 1000.0

    spi_phase = PHASE_TO_SPI.get(phase, ContractEnumPipelinePhase.IMPLEMENT)
    classification = _classify_result(phase_result)

    context = ContractMeasurementContext(
        ticket_id=ticket_id,
        repo_id=repo_id,
        toolchain="claude-code",
        strictness="default",
    )

    producer = ContractProducer(
        name=PRODUCER_NAME,
        version=PRODUCER_VERSION,
        instance_id=instance_id or str(uuid.uuid4())[:8],
    )

    duration = ContractDurationMetrics(wall_clock_ms=wall_clock_ms)

    cost = ContractCostMetrics(
        llm_total_tokens=phase_result.tokens_used,
    )

    outcome = ContractOutcomeMetrics(
        result_classification=classification,
        error_messages=(
            [phase_result.reason]
            if phase_result.reason
            and classification != ContractEnumResultClassification.SUCCESS
            else []
        ),
        error_codes=([phase_result.block_kind] if phase_result.block_kind else []),
    )

    tests = ContractTestMetrics(
        total_tests=phase_result.tests_total,
        passed_tests=phase_result.tests_passed,
        failed_tests=phase_result.tests_failed,
        pass_rate=(
            phase_result.tests_passed / phase_result.tests_total
            if phase_result.tests_total > 0
            else None
        ),
    )

    return ContractPhaseMetrics(
        run_id=run_id,
        phase=spi_phase,
        phase_id=f"{run_id}-{phase}-{attempt}",
        attempt=attempt,
        context=context,
        producer=producer,
        duration=duration,
        cost=cost,
        outcome=outcome,
        tests=tests,
    )


def build_error_metrics(
    *,
    run_id: str,
    phase: str,
    attempt: int,
    ticket_id: str,
    repo_id: str,
    started_at: datetime,
    error: Exception,
    instance_id: str = "",
) -> ContractPhaseMetrics:
    """Build a ContractPhaseMetrics for an error case.

    Called when a phase raises an unexpected exception.

    Args:
        run_id: Pipeline run identifier.
        phase: Pipeline phase name.
        attempt: Attempt number.
        ticket_id: Ticket identifier.
        repo_id: Repository identifier.
        started_at: Phase start timestamp.
        error: The exception that was raised.
        instance_id: Optional instance identifier.

    Returns:
        A ContractPhaseMetrics with ERROR classification.
    """
    completed_at = datetime.now(UTC)
    wall_clock_ms = (completed_at - started_at).total_seconds() * 1000.0

    spi_phase = PHASE_TO_SPI.get(phase, ContractEnumPipelinePhase.IMPLEMENT)

    context = ContractMeasurementContext(
        ticket_id=ticket_id,
        repo_id=repo_id,
        toolchain="claude-code",
        strictness="default",
    )

    producer = ContractProducer(
        name=PRODUCER_NAME,
        version=PRODUCER_VERSION,
        instance_id=instance_id or str(uuid.uuid4())[:8],
    )

    duration = ContractDurationMetrics(wall_clock_ms=wall_clock_ms)

    # Sanitize error message
    error_msg = str(error)[:200]

    outcome = ContractOutcomeMetrics(
        result_classification=ContractEnumResultClassification.ERROR,
        error_messages=[error_msg],
        error_codes=[type(error).__name__],
    )

    return ContractPhaseMetrics(
        run_id=run_id,
        phase=spi_phase,
        phase_id=f"{run_id}-{phase}-{attempt}",
        attempt=attempt,
        context=context,
        producer=producer,
        duration=duration,
        outcome=outcome,
    )


def build_skipped_metrics(
    *,
    run_id: str,
    phase: str,
    attempt: int,
    ticket_id: str,
    repo_id: str,
    skip_reason: str,
    skip_reason_code: str,
    instance_id: str = "",
) -> ContractPhaseMetrics:
    """Build a ContractPhaseMetrics for a skipped phase.

    Used both for explicitly skipped phases and for silent omission
    violations detected by the orchestrator.

    Args:
        run_id: Pipeline run identifier.
        phase: Pipeline phase name.
        attempt: Attempt number.
        ticket_id: Ticket identifier.
        repo_id: Repository identifier.
        skip_reason: Human-readable skip reason.
        skip_reason_code: Machine-stable skip reason code.
        instance_id: Optional instance identifier.

    Returns:
        A ContractPhaseMetrics with SKIPPED classification.
    """
    spi_phase = PHASE_TO_SPI.get(phase, ContractEnumPipelinePhase.IMPLEMENT)

    context = ContractMeasurementContext(
        ticket_id=ticket_id,
        repo_id=repo_id,
        toolchain="claude-code",
        strictness="default",
    )

    producer = ContractProducer(
        name=PRODUCER_NAME,
        version=PRODUCER_VERSION,
        instance_id=instance_id or str(uuid.uuid4())[:8],
    )

    duration = ContractDurationMetrics(wall_clock_ms=0.0)

    outcome = ContractOutcomeMetrics(
        result_classification=ContractEnumResultClassification.SKIPPED,
        skip_reason=skip_reason,
        skip_reason_code=skip_reason_code,
    )

    return ContractPhaseMetrics(
        run_id=run_id,
        phase=spi_phase,
        phase_id=f"{run_id}-{phase}-{attempt}",
        attempt=attempt,
        context=context,
        producer=producer,
        duration=duration,
        outcome=outcome,
    )


# ---------------------------------------------------------------------------
# Instrumentation Wrapper
# ---------------------------------------------------------------------------


def instrumented_phase(
    *,
    run_id: str,
    phase: str,
    attempt: int,
    ticket_id: str,
    repo_id: str,
    phase_fn: Callable[[], PhaseResult],
    instance_id: str = "",
) -> PhaseResult:
    """Execute a pipeline phase with full instrumentation.

    Wraps the phase callable with timing, metrics building, emission,
    and artifact persistence. Captures both success and error paths.

    This is the primary entry point for instrumented phase execution.
    Every pipeline phase MUST be called through this wrapper.

    Args:
        run_id: Pipeline run identifier.
        phase: Pipeline phase name.
        attempt: Attempt number (1-based).
        ticket_id: Ticket identifier.
        repo_id: Repository identifier.
        phase_fn: Zero-argument callable that executes the phase.
        instance_id: Optional instance identifier.

    Returns:
        The PhaseResult from phase_fn.

    Raises:
        Exception: Re-raises any exception from phase_fn after recording
            error metrics.
    """
    from plugins.onex.hooks.lib.metrics_emitter import (
        emit_phase_metrics,
        write_metrics_artifact,
    )

    started_at = datetime.now(UTC)

    try:
        result = phase_fn()

        completed_at = datetime.now(UTC)
        metrics = build_metrics_from_result(
            run_id=run_id,
            phase=phase,
            attempt=attempt,
            ticket_id=ticket_id,
            repo_id=repo_id,
            started_at=started_at,
            completed_at=completed_at,
            phase_result=result,
            instance_id=instance_id,
        )

    except Exception as e:
        metrics = build_error_metrics(
            run_id=run_id,
            phase=phase,
            attempt=attempt,
            ticket_id=ticket_id,
            repo_id=repo_id,
            started_at=started_at,
            error=e,
            instance_id=instance_id,
        )
        # Emit and persist even on error
        emit_phase_metrics(metrics)
        write_metrics_artifact(ticket_id, run_id, phase, attempt, metrics)
        raise

    # Emit and persist on success
    emit_phase_metrics(metrics)
    write_metrics_artifact(ticket_id, run_id, phase, attempt, metrics)

    return result


# ---------------------------------------------------------------------------
# Silent Omission Detection
# ---------------------------------------------------------------------------


def detect_silent_omission(
    *,
    ticket_id: str,
    run_id: str,
    phase: str,
    attempt: int,
    repo_id: str,
    instance_id: str = "",
) -> ContractPhaseMetrics | None:
    """Detect and record a silent omission violation.

    Called by the pipeline orchestrator after each phase. If no metrics
    artifact exists for the given phase/attempt, this function builds
    and emits a skipped record with the protocol violation code.

    Args:
        ticket_id: Ticket identifier.
        run_id: Pipeline run identifier.
        phase: Pipeline phase name.
        attempt: Attempt number.
        repo_id: Repository identifier.
        instance_id: Optional instance identifier.

    Returns:
        A ContractPhaseMetrics with SKIPPED classification if omission
        detected, or None if metrics artifact exists.
    """
    from plugins.onex.hooks.lib.metrics_emitter import (
        emit_phase_metrics,
        metrics_artifact_exists,
        write_metrics_artifact,
    )

    if metrics_artifact_exists(ticket_id, run_id, phase, attempt):
        return None

    logger.warning(
        f"Silent omission detected: {phase} attempt {attempt} "
        f"for {ticket_id} run {run_id} did not emit metrics. "
        f"Recording protocol violation."
    )

    violation = build_skipped_metrics(
        run_id=run_id,
        phase=phase,
        attempt=attempt,
        ticket_id=ticket_id,
        repo_id=repo_id,
        skip_reason=(
            f"Phase {phase} exited without emitting metrics. "
            f"This is a protocol violation."
        ),
        skip_reason_code="metrics_missing_protocol_violation",
        instance_id=instance_id,
    )

    # Emit and persist the violation record
    emit_phase_metrics(violation)
    write_metrics_artifact(ticket_id, run_id, phase, attempt, violation)

    return violation


# ---------------------------------------------------------------------------
# MeasurementCheck Integration
# ---------------------------------------------------------------------------


class MeasurementCheckResult:
    """Result of a single measurement check.

    Compatible with ContractCheckResult(domain="measurement").

    Attributes:
        check_id: The MeasurementCheck enum value.
        passed: Whether the check passed.
        message: Human-readable result message.
        domain: Always "measurement".
    """

    __slots__ = ("check_id", "domain", "message", "passed")

    def __init__(
        self,
        *,
        check_id: str,
        passed: bool,
        message: str,
    ) -> None:
        self.check_id = check_id
        self.passed = passed
        self.message = message
        self.domain = "measurement"

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"MeasurementCheckResult({self.check_id}: {status} - {self.message})"


def run_measurement_checks(
    metrics: ContractPhaseMetrics,
    phase: str,
) -> list[MeasurementCheckResult]:
    """Run all measurement checks against a ContractPhaseMetrics.

    Produces CHECK-MEAS-001 through CHECK-MEAS-006 results.

    Args:
        metrics: The phase metrics to validate.
        phase: The pipeline phase name (for budget lookups).

    Returns:
        List of MeasurementCheckResult instances.
    """
    results: list[MeasurementCheckResult] = []

    # CHECK-MEAS-001: Phase metrics were emitted (artifact exists)
    # If we have a metrics object at all, this check passes.
    has_metrics = metrics is not None
    results.append(
        MeasurementCheckResult(
            check_id=MeasurementCheck.CHECK_MEAS_001,
            passed=has_metrics,
            message="Phase metrics emitted" if has_metrics else "Phase metrics missing",
        )
    )

    if not has_metrics:
        # Remaining checks cannot run without metrics
        for check in [
            MeasurementCheck.CHECK_MEAS_002,
            MeasurementCheck.CHECK_MEAS_003,
            MeasurementCheck.CHECK_MEAS_004,
            MeasurementCheck.CHECK_MEAS_005,
            MeasurementCheck.CHECK_MEAS_006,
        ]:
            results.append(
                MeasurementCheckResult(
                    check_id=check,
                    passed=False,
                    message="Cannot evaluate: no metrics available",
                )
            )
        return results

    # CHECK-MEAS-002: Duration within budget
    budget_ms = DURATION_BUDGETS_MS.get(phase, float("inf"))
    actual_ms = metrics.duration.wall_clock_ms if metrics.duration else 0.0
    within_budget = actual_ms <= budget_ms
    results.append(
        MeasurementCheckResult(
            check_id=MeasurementCheck.CHECK_MEAS_002,
            passed=within_budget,
            message=(
                f"Duration {actual_ms:.0f}ms within budget {budget_ms:.0f}ms"
                if within_budget
                else f"Duration {actual_ms:.0f}ms exceeds budget {budget_ms:.0f}ms"
            ),
        )
    )

    # CHECK-MEAS-003: Tokens within budget
    token_budget = TOKEN_BUDGETS.get(phase, float("inf"))
    actual_tokens = metrics.cost.llm_total_tokens if metrics.cost else 0
    tokens_ok = actual_tokens <= token_budget
    results.append(
        MeasurementCheckResult(
            check_id=MeasurementCheck.CHECK_MEAS_003,
            passed=tokens_ok,
            message=(
                f"Tokens {actual_tokens} within budget {token_budget}"
                if tokens_ok
                else f"Tokens {actual_tokens} exceeds budget {token_budget}"
            ),
        )
    )

    # CHECK-MEAS-004: Tests ran (tests_total > 0 for test-bearing phases)
    if phase in TEST_BEARING_PHASES:
        tests_ran = metrics.tests is not None and metrics.tests.total_tests > 0
        results.append(
            MeasurementCheckResult(
                check_id=MeasurementCheck.CHECK_MEAS_004,
                passed=tests_ran,
                message=(
                    f"Tests ran: {metrics.tests.total_tests} total"
                    if tests_ran and metrics.tests
                    else "No tests ran for test-bearing phase"
                ),
            )
        )
    else:
        results.append(
            MeasurementCheckResult(
                check_id=MeasurementCheck.CHECK_MEAS_004,
                passed=True,
                message=f"Phase {phase} is not test-bearing, check N/A",
            )
        )

    # CHECK-MEAS-005: No flake (stable outcome signature)
    # A phase is considered flaky if outcome is ERROR with no error_codes
    outcome = metrics.outcome
    if outcome:
        has_stable_outcome = (
            outcome.result_classification != ContractEnumResultClassification.ERROR
            or len(outcome.error_codes) > 0
        )
    else:
        has_stable_outcome = False
    results.append(
        MeasurementCheckResult(
            check_id=MeasurementCheck.CHECK_MEAS_005,
            passed=has_stable_outcome,
            message=(
                "Outcome has stable classification"
                if has_stable_outcome
                else "Outcome is ERROR with no error codes (possible flake)"
            ),
        )
    )

    # CHECK-MEAS-006: Metrics complete (all mandatory fields non-default)
    mandatory_present = all(
        [
            metrics.run_id,
            metrics.phase,
            metrics.duration is not None,
            metrics.outcome is not None,
            metrics.context is not None,
            metrics.producer is not None,
        ]
    )
    results.append(
        MeasurementCheckResult(
            check_id=MeasurementCheck.CHECK_MEAS_006,
            passed=mandatory_present,
            message=(
                "All mandatory measurement fields present"
                if mandatory_present
                else "Some mandatory measurement fields are missing or default"
            ),
        )
    )

    return results


__all__ = [
    # Core types
    "PhaseResult",
    "MeasurementCheckResult",
    # Constants
    "PHASE_TO_SPI",
    "TEST_BEARING_PHASES",
    "DURATION_BUDGETS_MS",
    "TOKEN_BUDGETS",
    "PRODUCER_NAME",
    "PRODUCER_VERSION",
    # Metrics building
    "build_metrics_from_result",
    "build_error_metrics",
    "build_skipped_metrics",
    # Instrumentation
    "instrumented_phase",
    # Omission detection
    "detect_silent_omission",
    # Checks
    "run_measurement_checks",
]
