#!/usr/bin/env python3
"""
Gate Result Aggregator - ONEX v2.0 Framework

Comprehensive aggregation and analysis of quality gate results.
Provides detailed analytics, quality scoring, and actionable recommendations.

Features:
- Category-based result aggregation
- Performance analytics (slowest, fastest, average)
- Quality score calculation with weighted importance
- Compliance rate computation
- Blocking failure detection
- Timeline construction for performance analysis
- Actionable recommendation generation
"""

from datetime import UTC, datetime
from typing import Any

from ..models.model_gate_aggregation import (
    EnumGateCategory,
    ModelCategorySummary,
    ModelGateAggregation,
    ModelPipelineQualityReport,
)
from ..models.model_quality_gate import (
    ModelQualityGateResult,
    QualityGateRegistry,
)


class GateResultAggregator:
    """
    Aggregate and analyze quality gate results.

    Transforms raw gate results into comprehensive analytics including:
    - Overall and per-category statistics
    - Performance analytics
    - Quality scoring
    - Compliance rates
    - Actionable recommendations
    """

    # Quality score weights by validation type
    VALIDATION_TYPE_WEIGHTS = {
        "blocking": 1.0,  # Critical - must pass
        "checkpoint": 0.8,  # Important - should pass
        "monitoring": 0.6,  # Medium - track performance
        "quality_check": 0.7,  # Important - quality gates
    }

    def __init__(self, quality_gate_registry: QualityGateRegistry):
        """
        Initialize aggregator.

        Args:
            quality_gate_registry: Registry containing gate execution results
        """
        self.registry = quality_gate_registry

    def aggregate(self) -> ModelGateAggregation:
        """
        Create comprehensive aggregation of all gate results.

        Returns:
            ModelGateAggregation: Comprehensive aggregated results
        """
        results = self.registry.get_results()

        if not results:
            # Return empty aggregation if no results
            return self._create_empty_aggregation()

        # Calculate overall metrics
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed and r.status == "failed")
        skipped = sum(1 for r in results if r.status == "skipped")

        # Category breakdown
        category_summary = self._categorize_results(results)

        # Performance analytics
        exec_times = [r.execution_time_ms for r in results]
        total_time = sum(exec_times)
        avg_time = total_time / len(exec_times) if exec_times else 0.0

        # Find slowest and fastest gates
        slowest = self._find_slowest(results)
        fastest = self._find_fastest(results)

        # Quality score (weighted by gate importance)
        quality_score = self._calculate_quality_score(results)

        # Compliance rates
        compliance_rate = passed / total if total > 0 else 1.0
        perf_compliance = self._calculate_performance_compliance(results)

        # Blocking failures and warnings
        blocking_failures = self._find_blocking_failures(results)
        warnings = self._extract_warnings(results)

        # Execution timeline
        timeline = self._build_timeline(results)

        return ModelGateAggregation(
            total_gates=total,
            passed_gates=passed,
            failed_gates=failed,
            skipped_gates=skipped,
            category_summary=category_summary,
            total_execution_time_ms=total_time,
            average_execution_time_ms=avg_time,
            slowest_gate=slowest,
            fastest_gate=fastest,
            overall_quality_score=quality_score,
            blocking_failures=blocking_failures,
            warnings=warnings,
            execution_timeline=timeline,
            compliance_rate=compliance_rate,
            performance_compliance_rate=perf_compliance,
        )

    def generate_report(
        self,
        correlation_id: str,
        performance_metrics: dict[str, Any],
        stage_results: list[dict[str, Any]],
    ) -> ModelPipelineQualityReport:
        """
        Generate complete pipeline quality report.

        Args:
            correlation_id: Pipeline execution correlation ID
            performance_metrics: Performance metrics from pipeline
            stage_results: Stage-by-stage results

        Returns:
            ModelPipelineQualityReport: Complete quality report with recommendations
        """
        aggregation = self.aggregate()

        recommendations = self._generate_recommendations(aggregation)
        critical_issues = self._identify_critical_issues(aggregation)

        return ModelPipelineQualityReport(
            correlation_id=correlation_id,
            timestamp=datetime.now(UTC),
            gate_aggregation=aggregation,
            performance_summary=performance_metrics,
            stage_quality=stage_results,
            recommendations=recommendations,
            critical_issues=critical_issues,
        )

    def _categorize_results(
        self, results: list[ModelQualityGateResult]
    ) -> dict[EnumGateCategory, ModelCategorySummary]:
        """
        Categorize results by gate category.

        Args:
            results: List of gate results

        Returns:
            Dictionary mapping categories to their summaries
        """
        category_data: dict[EnumGateCategory, list[ModelQualityGateResult]] = {}

        # Group results by category
        for result in results:
            category = EnumGateCategory(result.gate.category)
            if category not in category_data:
                category_data[category] = []
            category_data[category].append(result)

        # Create summaries for each category
        summaries: dict[EnumGateCategory, ModelCategorySummary] = {}
        for category, cat_results in category_data.items():
            total = len(cat_results)
            passed = sum(1 for r in cat_results if r.passed)
            failed = sum(
                1 for r in cat_results if not r.passed and r.status == "failed"
            )
            skipped = sum(1 for r in cat_results if r.status == "skipped")
            exec_times = [r.execution_time_ms for r in cat_results]
            total_time = sum(exec_times)
            avg_time = total_time / len(exec_times) if exec_times else 0.0
            perf_meeting = sum(1 for r in cat_results if r.meets_performance_target)

            summaries[category] = ModelCategorySummary(
                category=category,
                total_gates=total,
                passed_gates=passed,
                failed_gates=failed,
                skipped_gates=skipped,
                total_execution_time_ms=total_time,
                average_execution_time_ms=avg_time,
                gates_meeting_performance=perf_meeting,
            )

        return summaries

    def _find_slowest(
        self, results: list[ModelQualityGateResult]
    ) -> dict[str, Any] | None:
        """Find slowest gate execution."""
        if not results:
            return None

        slowest = max(results, key=lambda r: r.execution_time_ms)
        return {
            "gate_id": slowest.gate.value,
            "gate_name": slowest.gate.gate_name,
            "execution_time_ms": slowest.execution_time_ms,
            "performance_target_ms": slowest.gate.performance_target_ms,
            "exceeded_target_by_ms": max(
                0, slowest.execution_time_ms - slowest.gate.performance_target_ms
            ),
        }

    def _find_fastest(
        self, results: list[ModelQualityGateResult]
    ) -> dict[str, Any] | None:
        """Find fastest gate execution."""
        if not results:
            return None

        fastest = min(results, key=lambda r: r.execution_time_ms)
        return {
            "gate_id": fastest.gate.value,
            "gate_name": fastest.gate.gate_name,
            "execution_time_ms": fastest.execution_time_ms,
            "performance_target_ms": fastest.gate.performance_target_ms,
        }

    def _calculate_quality_score(self, results: list[ModelQualityGateResult]) -> float:
        """
        Calculate weighted quality score.

        Quality score is weighted by gate validation type:
        - Blocking gates: 1.0 weight (critical)
        - Checkpoint gates: 0.8 weight (important)
        - Quality check gates: 0.7 weight (important)
        - Monitoring gates: 0.6 weight (medium)

        Args:
            results: List of gate results

        Returns:
            Quality score from 0.0 to 1.0
        """
        if not results:
            return 1.0

        total_weight = 0.0
        weighted_passed = 0.0

        for result in results:
            weight = self.VALIDATION_TYPE_WEIGHTS.get(result.gate.validation_type, 0.5)
            total_weight += weight

            if result.passed:
                weighted_passed += weight

        return weighted_passed / total_weight if total_weight > 0 else 0.0

    def _calculate_performance_compliance(
        self, results: list[ModelQualityGateResult]
    ) -> float:
        """Calculate percentage of gates meeting performance targets."""
        if not results:
            return 1.0

        meeting_target = sum(1 for r in results if r.meets_performance_target)
        return meeting_target / len(results)

    def _find_blocking_failures(
        self, results: list[ModelQualityGateResult]
    ) -> list[str]:
        """Find all blocking gate failures."""
        failures = []
        for result in results:
            if not result.passed and result.is_blocking:
                failures.append(
                    f"{result.gate.gate_name}: {result.message} "
                    f"(took {result.execution_time_ms}ms)"
                )
        return failures

    def _extract_warnings(self, results: list[ModelQualityGateResult]) -> list[str]:
        """Extract warning messages from results."""
        warnings = []
        for result in results:
            # Add warnings for gates that passed but exceeded performance targets
            if result.passed and not result.meets_performance_target:
                exceeded_by = (
                    result.execution_time_ms - result.gate.performance_target_ms
                )
                warnings.append(
                    f"{result.gate.gate_name} exceeded performance target by {exceeded_by}ms "
                    f"({result.execution_time_ms}ms vs {result.gate.performance_target_ms}ms target)"
                )

            # Add warnings for failed non-blocking gates
            if not result.passed and not result.is_blocking:
                warnings.append(
                    f"{result.gate.gate_name} failed (non-blocking): {result.message}"
                )

        return warnings

    def _build_timeline(
        self, results: list[ModelQualityGateResult]
    ) -> list[dict[str, Any]]:
        """
        Build chronological execution timeline.

        Args:
            results: List of gate results

        Returns:
            List of timeline entries sorted by timestamp
        """
        # Sort by timestamp
        sorted_results = sorted(results, key=lambda r: r.timestamp)

        timeline = []
        for result in sorted_results:
            timeline.append(
                {
                    "timestamp": result.timestamp.isoformat(),
                    "gate_id": result.gate.value,
                    "gate_name": result.gate.gate_name,
                    "category": result.gate.category,
                    "status": result.status,
                    "passed": result.passed,
                    "execution_time_ms": result.execution_time_ms,
                    "performance_target_ms": result.gate.performance_target_ms,
                    "meets_performance_target": result.meets_performance_target,
                    "validation_type": result.gate.validation_type,
                    "message": result.message,
                }
            )

        return timeline

    def _generate_recommendations(self, aggregation: ModelGateAggregation) -> list[str]:
        """
        Generate actionable recommendations based on aggregation.

        Args:
            aggregation: Aggregated results

        Returns:
            List of actionable recommendations
        """
        recommendations = []

        # Performance recommendations
        if aggregation.performance_compliance_rate < 0.8:
            recommendations.append(
                f"Performance compliance is low ({aggregation.performance_compliance_rate:.1%}). "
                "Consider optimizing slow gates or adjusting performance targets."
            )

        if aggregation.slowest_gate:
            slowest = aggregation.slowest_gate
            if slowest["exceeded_target_by_ms"] > 50:
                recommendations.append(
                    f"Gate '{slowest['gate_name']}' is significantly slow "
                    f"({slowest['execution_time_ms']}ms vs {slowest['performance_target_ms']}ms target). "
                    "Investigate and optimize this validation."
                )

        # Quality recommendations
        if aggregation.overall_quality_score < 0.8:
            recommendations.append(
                f"Overall quality score is low ({aggregation.overall_quality_score:.1%}). "
                "Review failed gates and improve validation logic."
            )

        # Category-specific recommendations
        for category, summary in aggregation.category_summary.items():
            if summary.has_failures:
                recommendations.append(
                    f"{category.display_name} has {summary.failed_gates} failed gate(s). "
                    "Review and address validation issues in this category."
                )

        # If everything is good
        if not recommendations and aggregation.overall_quality_score >= 0.95:
            recommendations.append(
                "Excellent quality! All gates passed with good performance."
            )

        return recommendations

    def _identify_critical_issues(self, aggregation: ModelGateAggregation) -> list[str]:
        """
        Identify critical issues requiring immediate attention.

        Args:
            aggregation: Aggregated results

        Returns:
            List of critical issues
        """
        issues = []

        # Blocking failures are always critical
        if aggregation.blocking_failures:
            issues.extend(
                [
                    f"BLOCKING FAILURE: {failure}"
                    for failure in aggregation.blocking_failures
                ]
            )

        # Very low quality score is critical
        if aggregation.overall_quality_score < 0.5:
            issues.append(
                f"CRITICAL: Overall quality score is extremely low "
                f"({aggregation.overall_quality_score:.1%}). "
                "Pipeline quality is unacceptable."
            )

        # Multiple category failures are critical
        failing_categories = [
            cat
            for cat, summary in aggregation.category_summary.items()
            if summary.has_failures
        ]
        if len(failing_categories) >= 3:
            cat_names = ", ".join(cat.display_name for cat in failing_categories)
            issues.append(
                f"CRITICAL: Multiple categories have failures ({cat_names}). "
                "Systemic quality issues detected."
            )

        return issues

    def _create_empty_aggregation(self) -> ModelGateAggregation:
        """Create empty aggregation when no results exist."""
        return ModelGateAggregation(
            total_gates=0,
            passed_gates=0,
            failed_gates=0,
            skipped_gates=0,
            category_summary={},
            total_execution_time_ms=0,
            average_execution_time_ms=0.0,
            slowest_gate=None,
            fastest_gate=None,
            overall_quality_score=1.0,  # No gates = perfect score
            blocking_failures=[],
            warnings=[],
            execution_timeline=[],
            compliance_rate=1.0,
            performance_compliance_rate=1.0,
        )
