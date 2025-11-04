#!/usr/bin/env python3
"""
Unit Tests for Gate Aggregation and Quality Dashboard

Tests Week 2 Poly-J implementation:
- EnumGateCategory and ModelGateAggregation models
- GateResultAggregator analytics and quality scoring
- ModelPipelineQualityReport generation
- Recommendation and critical issue detection

Setup:
    Run with pytest from project root:

        cd /path/to/omniclaude
        pytest agents/tests/test_gate_aggregation.py -v

    Or use PYTHONPATH:

        PYTHONPATH=/path/to/omniclaude pytest agents/tests/test_gate_aggregation.py -v
"""


import pytest

from agents.lib.aggregators.gate_result_aggregator import GateResultAggregator
from agents.lib.models.model_gate_aggregation import (
    EnumGateCategory,
    ModelCategorySummary,
    ModelGateAggregation,
    ModelPipelineQualityReport,
)
from agents.lib.models.model_quality_gate import (  # noqa: E402
    EnumQualityGate,
    ModelQualityGateResult,
    QualityGateRegistry,
)


class TestGateCategoryEnum:
    """Test EnumGateCategory enum."""

    def test_all_categories_exist(self):
        """Test all 8 categories are defined."""
        categories = list(EnumGateCategory)
        assert len(categories) == 8

        expected = {
            "sequential_validation",
            "parallel_validation",
            "intelligence_validation",
            "coordination_validation",
            "quality_compliance",
            "performance_validation",
            "knowledge_validation",
            "framework_validation",
        }
        actual = {cat.value for cat in categories}
        assert actual == expected

    def test_category_display_names(self):
        """Test category display names."""
        assert EnumGateCategory.SEQUENTIAL.display_name == "Sequential Validation"
        assert EnumGateCategory.QUALITY.display_name == "Quality Compliance"
        assert EnumGateCategory.PERFORMANCE.display_name == "Performance Validation"

    def test_category_expected_gate_counts(self):
        """Test expected gate counts match spec."""
        assert EnumGateCategory.SEQUENTIAL.expected_gate_count == 4
        assert EnumGateCategory.PARALLEL.expected_gate_count == 3
        assert EnumGateCategory.INTELLIGENCE.expected_gate_count == 3
        assert EnumGateCategory.COORDINATION.expected_gate_count == 3
        assert EnumGateCategory.QUALITY.expected_gate_count == 4
        assert EnumGateCategory.PERFORMANCE.expected_gate_count == 2
        assert EnumGateCategory.KNOWLEDGE.expected_gate_count == 2
        assert EnumGateCategory.FRAMEWORK.expected_gate_count == 2


class TestCategorySummary:
    """Test ModelCategorySummary model."""

    def test_category_summary_creation(self):
        """Test creating category summary."""
        summary = ModelCategorySummary(
            category=EnumGateCategory.SEQUENTIAL,
            total_gates=4,
            passed_gates=3,
            failed_gates=1,
            skipped_gates=0,
            total_execution_time_ms=200,
            average_execution_time_ms=50.0,
            gates_meeting_performance=3,
        )

        assert summary.category == EnumGateCategory.SEQUENTIAL
        assert summary.total_gates == 4
        assert summary.passed_gates == 3
        assert summary.failed_gates == 1
        assert summary.pass_rate == 0.75
        assert summary.performance_compliance_rate == 0.75
        assert summary.has_failures is True

    def test_perfect_category_summary(self):
        """Test category summary with perfect score."""
        summary = ModelCategorySummary(
            category=EnumGateCategory.QUALITY,
            total_gates=4,
            passed_gates=4,
            failed_gates=0,
            skipped_gates=0,
            total_execution_time_ms=150,
            average_execution_time_ms=37.5,
            gates_meeting_performance=4,
        )

        assert summary.pass_rate == 1.0
        assert summary.performance_compliance_rate == 1.0
        assert summary.has_failures is False


class TestGateAggregation:
    """Test ModelGateAggregation model."""

    def test_quality_grade_calculation(self):
        """Test quality grade assignment."""
        # A+ grade
        agg = ModelGateAggregation(
            total_gates=10,
            passed_gates=10,
            failed_gates=0,
            skipped_gates=0,
            category_summary={},
            total_execution_time_ms=500,
            average_execution_time_ms=50.0,
            overall_quality_score=0.96,
            compliance_rate=1.0,
            performance_compliance_rate=1.0,
        )
        assert agg.quality_grade == "A+"

        # B grade
        agg.overall_quality_score = 0.82
        assert agg.quality_grade == "B"

        # F grade
        agg.overall_quality_score = 0.45
        assert agg.quality_grade == "F"

    def test_health_check(self):
        """Test is_healthy property."""
        agg = ModelGateAggregation(
            total_gates=5,
            passed_gates=5,
            failed_gates=0,
            skipped_gates=0,
            category_summary={},
            total_execution_time_ms=200,
            average_execution_time_ms=40.0,
            overall_quality_score=1.0,
            blocking_failures=[],
            compliance_rate=1.0,
            performance_compliance_rate=1.0,
        )
        assert agg.is_healthy is True
        assert agg.has_blocking_failures is False

        # Add blocking failure
        agg.blocking_failures = ["Type Safety failed"]
        assert agg.is_healthy is False
        assert agg.has_blocking_failures is True


class TestGateResultAggregator:
    """Test GateResultAggregator functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = QualityGateRegistry()
        self.aggregator = GateResultAggregator(self.registry)

    def test_empty_aggregation(self):
        """Test aggregation with no gate results."""
        agg = self.aggregator.aggregate()

        assert agg.total_gates == 0
        assert agg.passed_gates == 0
        assert agg.failed_gates == 0
        assert agg.overall_quality_score == 1.0
        assert agg.compliance_rate == 1.0
        assert agg.is_healthy is True

    def test_all_gates_passed(self):
        """Test aggregation when all gates pass."""
        # Add passing gate results
        gates = [
            EnumQualityGate.INPUT_VALIDATION,
            EnumQualityGate.PROCESS_VALIDATION,
            EnumQualityGate.OUTPUT_VALIDATION,
        ]

        for gate in gates:
            result = ModelQualityGateResult(
                gate=gate,
                status="passed",
                execution_time_ms=gate.performance_target_ms - 10,
                message="Validation passed",
            )
            self.registry.results.append(result)

        agg = self.aggregator.aggregate()

        assert agg.total_gates == 3
        assert agg.passed_gates == 3
        assert agg.failed_gates == 0
        assert agg.overall_quality_score == 1.0
        assert agg.compliance_rate == 1.0
        assert agg.performance_compliance_rate == 1.0
        assert agg.is_healthy is True

    def test_blocking_failure_detection(self):
        """Test detection of blocking failures."""
        # Add blocking gate failure
        result = ModelQualityGateResult(
            gate=EnumQualityGate.TYPE_SAFETY,  # Blocking gate
            status="failed",
            execution_time_ms=100,
            message="Type safety violation detected",
        )
        self.registry.results.append(result)

        agg = self.aggregator.aggregate()

        assert agg.total_gates == 1
        assert agg.passed_gates == 0
        assert agg.failed_gates == 1
        assert len(agg.blocking_failures) == 1
        assert "Type Safety" in agg.blocking_failures[0]
        assert agg.is_healthy is False

    def test_quality_score_weighting(self):
        """Test quality score calculation with weighted gates."""
        # Add one blocking pass and one monitoring fail
        blocking_pass = ModelQualityGateResult(
            gate=EnumQualityGate.INPUT_VALIDATION,  # Blocking, weight 1.0
            status="passed",
            execution_time_ms=40,
            message="Input validation passed",
        )
        monitoring_fail = ModelQualityGateResult(
            gate=EnumQualityGate.PROCESS_VALIDATION,  # Monitoring, weight 0.6
            status="failed",
            execution_time_ms=50,
            message="Process validation failed",
        )

        self.registry.results.extend([blocking_pass, monitoring_fail])

        agg = self.aggregator.aggregate()

        # Quality score should be higher because blocking gate passed
        # (1.0 * 1.0 + 0.6 * 0.0) / (1.0 + 0.6) = 1.0 / 1.6 = 0.625
        assert agg.overall_quality_score == pytest.approx(0.625, rel=0.01)

    def test_performance_compliance_calculation(self):
        """Test performance compliance rate calculation."""
        # Add gates with different performance characteristics
        fast_gate = ModelQualityGateResult(
            gate=EnumQualityGate.INPUT_VALIDATION,
            status="passed",
            execution_time_ms=30,  # Target is 50ms
            message="Fast execution",
        )
        slow_gate = ModelQualityGateResult(
            gate=EnumQualityGate.OUTPUT_VALIDATION,
            status="passed",
            execution_time_ms=100,  # Target is 40ms - exceeds target
            message="Slow execution",
        )

        self.registry.results.extend([fast_gate, slow_gate])

        agg = self.aggregator.aggregate()

        # Only 1 of 2 gates meets performance target
        assert agg.performance_compliance_rate == 0.5

    def test_category_breakdown(self):
        """Test category-based result aggregation."""
        # Add gates from different categories
        sequential_gate = ModelQualityGateResult(
            gate=EnumQualityGate.INPUT_VALIDATION,
            status="passed",
            execution_time_ms=40,
            message="Sequential gate passed",
        )
        quality_gate = ModelQualityGateResult(
            gate=EnumQualityGate.TYPE_SAFETY,
            status="passed",
            execution_time_ms=50,
            message="Quality gate passed",
        )

        self.registry.results.extend([sequential_gate, quality_gate])

        agg = self.aggregator.aggregate()

        # Should have 2 categories
        assert len(agg.category_summary) == 2
        assert EnumGateCategory.SEQUENTIAL in agg.category_summary
        assert EnumGateCategory.QUALITY in agg.category_summary

        # Check sequential category
        seq_summary = agg.category_summary[EnumGateCategory.SEQUENTIAL]
        assert seq_summary.total_gates == 1
        assert seq_summary.passed_gates == 1

    def test_slowest_fastest_detection(self):
        """Test detection of slowest and fastest gates."""
        # Add gates with different execution times
        fast = ModelQualityGateResult(
            gate=EnumQualityGate.ANTI_YOLO_COMPLIANCE,
            status="passed",
            execution_time_ms=20,
            message="Fast",
        )
        medium = ModelQualityGateResult(
            gate=EnumQualityGate.INPUT_VALIDATION,
            status="passed",
            execution_time_ms=50,
            message="Medium",
        )
        slow = ModelQualityGateResult(
            gate=EnumQualityGate.RAG_QUERY_VALIDATION,
            status="passed",
            execution_time_ms=150,
            message="Slow",
        )

        self.registry.results.extend([fast, medium, slow])

        agg = self.aggregator.aggregate()

        assert agg.slowest_gate is not None
        assert agg.slowest_gate["execution_time_ms"] == 150
        assert agg.slowest_gate["gate_name"] == "RAG Query Validation"

        assert agg.fastest_gate is not None
        assert agg.fastest_gate["execution_time_ms"] == 20
        assert agg.fastest_gate["gate_name"] == "Anti-YOLO Compliance"

    def test_warning_extraction(self):
        """Test extraction of warnings from results."""
        # Add gate that passed but exceeded performance target
        slow_pass = ModelQualityGateResult(
            gate=EnumQualityGate.INPUT_VALIDATION,
            status="passed",
            execution_time_ms=100,  # Target is 50ms
            message="Passed but slow",
        )

        self.registry.results.append(slow_pass)

        agg = self.aggregator.aggregate()

        # Should have warning about performance
        assert len(agg.warnings) > 0
        assert "exceeded performance target" in agg.warnings[0].lower()

    def test_recommendation_generation(self):
        """Test actionable recommendation generation."""
        # Add slow gate
        slow_gate = ModelQualityGateResult(
            gate=EnumQualityGate.RAG_QUERY_VALIDATION,
            status="passed",
            execution_time_ms=200,  # Target is 100ms
            message="Slow query",
        )

        self.registry.results.append(slow_gate)

        quality_report = self.aggregator.generate_report(
            correlation_id="test-123",
            performance_metrics={},
            stage_results=[],
        )

        # Should have recommendations about slow gate
        assert len(quality_report.recommendations) > 0

    def test_critical_issue_identification(self):
        """Test critical issue identification."""
        # Add blocking failure
        blocking_fail = ModelQualityGateResult(
            gate=EnumQualityGate.TYPE_SAFETY,
            status="failed",
            execution_time_ms=60,
            message="Type safety violation",
        )

        self.registry.results.append(blocking_fail)

        quality_report = self.aggregator.generate_report(
            correlation_id="test-456",
            performance_metrics={},
            stage_results=[],
        )

        # Should have critical issues
        assert len(quality_report.critical_issues) > 0
        assert "BLOCKING FAILURE" in quality_report.critical_issues[0]


class TestPipelineQualityReport:
    """Test ModelPipelineQualityReport model."""

    def test_report_creation(self):
        """Test creating quality report."""
        agg = ModelGateAggregation(
            total_gates=5,
            passed_gates=5,
            failed_gates=0,
            skipped_gates=0,
            category_summary={},
            total_execution_time_ms=250,
            average_execution_time_ms=50.0,
            overall_quality_score=0.95,
            compliance_rate=1.0,
            performance_compliance_rate=1.0,
        )

        report = ModelPipelineQualityReport(
            correlation_id="test-789",
            gate_aggregation=agg,
            performance_summary={"total_duration_ms": 5000},
            stage_quality=[],
            recommendations=["Excellent quality!"],
            critical_issues=[],
        )

        assert report.correlation_id == "test-789"
        assert report.overall_status == "SUCCESS"
        assert report.requires_action is False

    def test_report_status_mapping(self):
        """Test report status based on gate results."""
        # Test FAILED status
        failed_agg = ModelGateAggregation(
            total_gates=2,
            passed_gates=1,
            failed_gates=1,
            skipped_gates=0,
            category_summary={},
            total_execution_time_ms=100,
            average_execution_time_ms=50.0,
            overall_quality_score=0.5,
            blocking_failures=["Type Safety failed"],
            compliance_rate=0.5,
            performance_compliance_rate=1.0,
        )

        report = ModelPipelineQualityReport(
            correlation_id="test-fail",
            gate_aggregation=failed_agg,
            performance_summary={},
            stage_quality=[],
        )

        assert report.overall_status == "FAILED"
        assert report.gate_aggregation.has_blocking_failures is True

    def test_report_summary_text(self):
        """Test human-readable summary generation."""
        agg = ModelGateAggregation(
            total_gates=3,
            passed_gates=3,
            failed_gates=0,
            skipped_gates=0,
            category_summary={},
            total_execution_time_ms=150,
            average_execution_time_ms=50.0,
            overall_quality_score=1.0,
            compliance_rate=1.0,
            performance_compliance_rate=1.0,
        )

        report = ModelPipelineQualityReport(
            correlation_id="test-summary",
            gate_aggregation=agg,
            performance_summary={},
            stage_quality=[],
        )

        summary = report.to_summary()

        assert "SUCCESS" in summary
        assert "100.0%" in summary or "100%" in summary
        assert "3/3" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
