#!/usr/bin/env python3
"""
Comprehensive tests for performance tracking system.

Tests:
- EnumPerformanceThreshold (all 33 thresholds)
- MetricsCollector (recording, aggregation, threshold checking)
- PipelineStage (performance tracking enhancements)

Coverage:
- All threshold properties and methods
- Metrics collection and aggregation
- Percentile calculations (p50, p95, p99)
- Threshold breach detection with severity levels
- Performance ratio calculations
"""


import pytest

from agents.lib.metrics.metrics_collector import (
    MetricsCollector,
)
from agents.lib.models.enum_performance_threshold import EnumPerformanceThreshold
from agents.lib.models.pipeline_models import PipelineStage, StageStatus


class TestEnumPerformanceThreshold:
    """Test EnumPerformanceThreshold with all 33 thresholds."""

    def test_all_thresholds_count(self):
        """Verify we have exactly 33 thresholds."""
        all_thresholds = EnumPerformanceThreshold.all_thresholds()
        assert len(all_thresholds) == 33, "Should have exactly 33 thresholds"

    def test_category_counts(self):
        """Verify threshold counts per category."""
        intelligence = EnumPerformanceThreshold.by_category("intelligence")
        parallel = EnumPerformanceThreshold.by_category("parallel_execution")
        coordination = EnumPerformanceThreshold.by_category("coordination")
        context = EnumPerformanceThreshold.by_category("context_management")
        template = EnumPerformanceThreshold.by_category("template_system")
        lifecycle = EnumPerformanceThreshold.by_category("lifecycle")
        dashboard = EnumPerformanceThreshold.by_category("dashboard")

        assert len(intelligence) == 6, "Intelligence should have 6 thresholds"
        assert len(parallel) == 5, "Parallel execution should have 5 thresholds"
        assert len(coordination) == 4, "Coordination should have 4 thresholds"
        assert len(context) == 6, "Context management should have 6 thresholds"
        assert len(template) == 4, "Template system should have 4 thresholds"
        assert len(lifecycle) == 4, "Lifecycle should have 4 thresholds"
        assert len(dashboard) == 4, "Dashboard should have 4 thresholds"

    def test_intelligence_thresholds(self):
        """Test intelligence category thresholds (INT-001 to INT-006)."""
        # INT-001: RAG Query Response Time
        threshold = EnumPerformanceThreshold.RAG_QUERY_RESPONSE_TIME
        assert threshold.category == "intelligence"
        assert threshold.threshold_ms == 1500
        assert threshold.tolerance_ms == 200
        assert threshold.alert_threshold_ms == 1200
        assert threshold.criticality == "high"
        assert threshold.measurement_type == "response_time"
        assert "RAG" in threshold.name

        # INT-002: Intelligence Gathering Overhead
        threshold = EnumPerformanceThreshold.INTELLIGENCE_GATHERING_OVERHEAD
        assert threshold.threshold_ms == 100
        assert threshold.criticality == "high"

        # INT-003: Pattern Recognition Performance
        threshold = EnumPerformanceThreshold.PATTERN_RECOGNITION_PERFORMANCE
        assert threshold.threshold_ms == 500
        assert threshold.criticality == "medium"

        # INT-004: Knowledge Capture Latency
        threshold = EnumPerformanceThreshold.KNOWLEDGE_CAPTURE_LATENCY
        assert threshold.threshold_ms == 300
        assert threshold.measurement_type == "storage_latency"

        # INT-005: Cross-Domain Synthesis
        threshold = EnumPerformanceThreshold.CROSS_DOMAIN_SYNTHESIS
        assert threshold.threshold_ms == 800
        assert threshold.tolerance_ms == 150

        # INT-006: Intelligence Application Time
        threshold = EnumPerformanceThreshold.INTELLIGENCE_APPLICATION_TIME
        assert threshold.threshold_ms == 200
        assert threshold.alert_threshold_ms == 150

    def test_parallel_execution_thresholds(self):
        """Test parallel execution category thresholds (PAR-001 to PAR-005)."""
        # PAR-001: Parallel Coordination Setup
        threshold = EnumPerformanceThreshold.PARALLEL_COORDINATION_SETUP
        assert threshold.category == "parallel_execution"
        assert threshold.threshold_ms == 500
        assert threshold.criticality == "high"

        # PAR-002: Context Distribution Time
        threshold = EnumPerformanceThreshold.CONTEXT_DISTRIBUTION_TIME
        assert threshold.threshold_ms == 200
        assert threshold.alert_threshold_ms == 150

        # PAR-003: Synchronization Point Latency
        threshold = EnumPerformanceThreshold.SYNCHRONIZATION_POINT_LATENCY
        assert threshold.threshold_ms == 1000
        assert threshold.criticality == "medium"

        # PAR-004: Result Aggregation Performance
        threshold = EnumPerformanceThreshold.RESULT_AGGREGATION_PERFORMANCE
        assert threshold.threshold_ms == 300
        assert threshold.tolerance_ms == 75

        # PAR-005: Parallel Efficiency Ratio (ratio-based)
        threshold = EnumPerformanceThreshold.PARALLEL_EFFICIENCY_RATIO
        assert threshold.threshold_ratio == 0.6
        assert threshold.tolerance_ratio == 0.1
        assert threshold.alert_threshold_ratio == 0.7
        assert threshold.threshold_ms == 0  # Not a time-based threshold

    def test_coordination_thresholds(self):
        """Test coordination category thresholds (COORD-001 to COORD-004)."""
        # COORD-001: Agent Delegation Handoff
        threshold = EnumPerformanceThreshold.AGENT_DELEGATION_HANDOFF
        assert threshold.category == "coordination"
        assert threshold.threshold_ms == 150
        assert threshold.criticality == "medium"

        # COORD-002: Context Inheritance Latency
        threshold = EnumPerformanceThreshold.CONTEXT_INHERITANCE_LATENCY
        assert threshold.threshold_ms == 50
        assert threshold.criticality == "high"

        # COORD-003: Multi-Agent Communication
        threshold = EnumPerformanceThreshold.MULTI_AGENT_COMMUNICATION
        assert threshold.threshold_ms == 100

        # COORD-004: Coordination Overhead
        threshold = EnumPerformanceThreshold.COORDINATION_OVERHEAD
        assert threshold.threshold_ms == 300
        assert threshold.criticality == "low"

    def test_context_management_thresholds(self):
        """Test context management category thresholds (CTX-001 to CTX-006)."""
        # CTX-001: Context Initialization Time
        threshold = EnumPerformanceThreshold.CONTEXT_INITIALIZATION_TIME
        assert threshold.category == "context_management"
        assert threshold.threshold_ms == 50
        assert threshold.criticality == "high"

        # CTX-002: Context Preservation Latency
        threshold = EnumPerformanceThreshold.CONTEXT_PRESERVATION_LATENCY
        assert threshold.threshold_ms == 25

        # CTX-003: Context Refresh Performance
        threshold = EnumPerformanceThreshold.CONTEXT_REFRESH_PERFORMANCE
        assert threshold.threshold_ms == 75

        # CTX-004: Context Memory Footprint (memory-based)
        threshold = EnumPerformanceThreshold.CONTEXT_MEMORY_FOOTPRINT
        assert threshold.threshold_mb == 10
        assert threshold.tolerance_mb == 2
        assert threshold.alert_threshold_mb == 8
        assert threshold.threshold_ms == 0  # Not a time-based threshold
        assert threshold.measurement_type == "memory_usage"

        # CTX-005: Context Lifecycle Management
        threshold = EnumPerformanceThreshold.CONTEXT_LIFECYCLE_MANAGEMENT
        assert threshold.threshold_ms == 200

        # CTX-006: Context Cleanup Performance
        threshold = EnumPerformanceThreshold.CONTEXT_CLEANUP_PERFORMANCE
        assert threshold.threshold_ms == 100
        assert threshold.criticality == "low"

    def test_template_system_thresholds(self):
        """Test template system category thresholds (TPL-001 to TPL-004)."""
        # TPL-001: Template Instantiation Time
        threshold = EnumPerformanceThreshold.TEMPLATE_INSTANTIATION_TIME
        assert threshold.category == "template_system"
        assert threshold.threshold_ms == 100

        # TPL-002: Template Parameter Resolution
        threshold = EnumPerformanceThreshold.TEMPLATE_PARAMETER_RESOLUTION
        assert threshold.threshold_ms == 50

        # TPL-003: Configuration Overlay Performance
        threshold = EnumPerformanceThreshold.CONFIGURATION_OVERLAY_PERFORMANCE
        assert threshold.threshold_ms == 30

        # TPL-004: Template Cache Hit Ratio (ratio-based)
        threshold = EnumPerformanceThreshold.TEMPLATE_CACHE_HIT_RATIO
        assert threshold.threshold_ratio == 0.85
        assert threshold.tolerance_ratio == 0.05
        assert threshold.alert_threshold_ratio == 0.9

    def test_lifecycle_thresholds(self):
        """Test lifecycle category thresholds (LCL-001 to LCL-004)."""
        # LCL-001: Agent Initialization Performance
        threshold = EnumPerformanceThreshold.AGENT_INITIALIZATION_PERFORMANCE
        assert threshold.category == "lifecycle"
        assert threshold.threshold_ms == 300
        assert threshold.criticality == "medium"

        # LCL-002: Framework Integration Time
        threshold = EnumPerformanceThreshold.FRAMEWORK_INTEGRATION_TIME
        assert threshold.threshold_ms == 100

        # LCL-003: Quality Gate Execution
        threshold = EnumPerformanceThreshold.QUALITY_GATE_EXECUTION
        assert threshold.threshold_ms == 200
        assert threshold.criticality == "high"

        # LCL-004: Agent Cleanup Performance
        threshold = EnumPerformanceThreshold.AGENT_CLEANUP_PERFORMANCE
        assert threshold.threshold_ms == 150
        assert threshold.criticality == "low"

    def test_dashboard_thresholds(self):
        """Test dashboard category thresholds (DASH-001 to DASH-004)."""
        # DASH-001: Performance Data Collection
        threshold = EnumPerformanceThreshold.PERFORMANCE_DATA_COLLECTION
        assert threshold.category == "dashboard"
        assert threshold.threshold_ms == 50
        assert threshold.criticality == "low"

        # DASH-002: Dashboard Update Latency
        threshold = EnumPerformanceThreshold.DASHBOARD_UPDATE_LATENCY
        assert threshold.threshold_ms == 100

        # DASH-003: Trend Analysis Performance
        threshold = EnumPerformanceThreshold.TREND_ANALYSIS_PERFORMANCE
        assert threshold.threshold_ms == 500

        # DASH-004: Optimization Recommendation Time
        threshold = EnumPerformanceThreshold.OPTIMIZATION_RECOMMENDATION_TIME
        assert threshold.threshold_ms == 300

    def test_criticality_filtering(self):
        """Test filtering thresholds by criticality."""
        high_critical = EnumPerformanceThreshold.by_criticality("high")
        medium_critical = EnumPerformanceThreshold.by_criticality("medium")
        low_critical = EnumPerformanceThreshold.by_criticality("low")

        assert len(high_critical) > 0, "Should have high criticality thresholds"
        assert len(medium_critical) > 0, "Should have medium criticality thresholds"
        assert len(low_critical) > 0, "Should have low criticality thresholds"

        # Verify all are accounted for
        total = len(high_critical) + len(medium_critical) + len(low_critical)
        assert total == 33, "All 33 thresholds should be categorized by criticality"


class TestMetricsCollector:
    """Test MetricsCollector functionality."""

    def test_initialization(self):
        """Test collector initialization."""
        collector = MetricsCollector()
        assert len(collector.stage_timings) == 0
        assert len(collector.threshold_breaches) == 0

    def test_record_stage_timing_within_threshold(self):
        """Test recording timing that meets threshold."""
        collector = MetricsCollector()

        # Record timing well within threshold (below 80% warning level)
        # INTELLIGENCE_GATHERING_OVERHEAD threshold is 100ms
        # 70ms is 70% of threshold - no breach
        result = collector.record_stage_timing(
            stage_name="test_stage",
            duration_ms=70,
            target_ms=100,
            threshold=EnumPerformanceThreshold.INTELLIGENCE_GATHERING_OVERHEAD,
        )

        assert result is True, "Should pass threshold"
        assert len(collector.stage_timings) == 1
        assert len(collector.threshold_breaches) == 0

    def test_record_stage_timing_breach(self):
        """Test recording timing that breaches threshold."""
        collector = MetricsCollector()

        # Record timing that breaches threshold (critical level)
        result = collector.record_stage_timing(
            stage_name="slow_stage",
            duration_ms=110,
            target_ms=100,
            threshold=EnumPerformanceThreshold.INTELLIGENCE_GATHERING_OVERHEAD,
        )

        assert result is False, "Should fail threshold"
        assert len(collector.stage_timings) == 1
        assert len(collector.threshold_breaches) == 1

        breach = collector.threshold_breaches[0]
        assert breach.breach_type == "emergency"  # 110% is >105%
        assert breach.actual_value == 110

    def test_threshold_breach_severity_levels(self):
        """Test threshold breach severity classification."""
        collector = MetricsCollector()
        threshold = EnumPerformanceThreshold.INTELLIGENCE_GATHERING_OVERHEAD
        # threshold_ms = 100

        # Warning level (80-95%): 85ms
        collector.check_threshold(threshold, 85)
        assert len(collector.threshold_breaches) == 1
        assert collector.threshold_breaches[0].breach_type == "warning"

        # Critical level (95-105%): 98ms
        collector.check_threshold(threshold, 98)
        assert len(collector.threshold_breaches) == 2
        assert collector.threshold_breaches[1].breach_type == "critical"

        # Emergency level (>105%): 110ms
        collector.check_threshold(threshold, 110)
        assert len(collector.threshold_breaches) == 3
        assert collector.threshold_breaches[2].breach_type == "emergency"

        # Within threshold (<80%): 70ms
        collector.check_threshold(threshold, 70)
        assert len(collector.threshold_breaches) == 3  # No new breach

    def test_get_summary_empty(self):
        """Test summary with no data."""
        collector = MetricsCollector()
        summary = collector.get_summary()

        assert summary.total_timings == 0
        assert summary.total_breaches == 0
        assert summary.avg_duration_ms == 0.0
        assert summary.p50_duration_ms == 0.0

    def test_get_summary_with_data(self):
        """Test summary with recorded data."""
        collector = MetricsCollector()

        # Record multiple timings
        timings = [50, 75, 100, 125, 150, 200, 250]
        for duration in timings:
            collector.record_stage_timing(
                stage_name="test_stage",
                duration_ms=duration,
                target_ms=100,
            )

        summary = collector.get_summary()

        assert summary.total_timings == 7
        assert summary.avg_duration_ms == pytest.approx(
            135.71, rel=0.01
        )  # Mean of timings
        assert summary.p50_duration_ms == 125  # Median
        assert summary.min_duration_ms == 50
        assert summary.max_duration_ms == 250

        # Check performance ratios
        assert summary.avg_performance_ratio > 1.0  # Many are over target
        assert summary.p50_performance_ratio == 1.25  # Median is 125/100

    def test_percentile_calculations(self):
        """Test percentile calculation accuracy."""
        collector = MetricsCollector()

        # Create dataset with known percentiles
        # 100 values: 0-99
        for i in range(100):
            collector.record_stage_timing(
                stage_name="perf_test",
                duration_ms=i,
                target_ms=100,
            )

        summary = collector.get_summary()

        # p50 should be around 50
        assert 48 <= summary.p50_duration_ms <= 52

        # p95 should be around 95
        assert 93 <= summary.p95_duration_ms <= 97

        # p99 should be around 99
        assert 97 <= summary.p99_duration_ms <= 99

    def test_stage_metrics_aggregation(self):
        """Test per-stage metrics computation."""
        collector = MetricsCollector()

        # Record timings for multiple stages
        collector.record_stage_timing("stage_a", 50, 100)
        collector.record_stage_timing("stage_a", 75, 100)
        collector.record_stage_timing("stage_b", 150, 200)
        collector.record_stage_timing("stage_b", 175, 200)

        summary = collector.get_summary()

        assert "stage_a" in summary.stage_metrics
        assert "stage_b" in summary.stage_metrics

        stage_a = summary.stage_metrics["stage_a"]
        assert stage_a["total_executions"] == 2
        assert stage_a["avg_duration_ms"] == 62.5  # (50 + 75) / 2

        stage_b = summary.stage_metrics["stage_b"]
        assert stage_b["total_executions"] == 2
        assert stage_b["avg_duration_ms"] == 162.5  # (150 + 175) / 2

    def test_threshold_metrics_aggregation(self):
        """Test per-threshold metrics computation."""
        collector = MetricsCollector()
        threshold = EnumPerformanceThreshold.INTELLIGENCE_GATHERING_OVERHEAD

        # Record multiple breaches
        # INTELLIGENCE_GATHERING_OVERHEAD threshold is 100ms
        collector.check_threshold(threshold, 85)  # 85% - warning
        collector.check_threshold(threshold, 98)  # 98% - critical
        collector.check_threshold(threshold, 110)  # 110% - emergency

        # Verify breaches were recorded
        assert len(collector.threshold_breaches) == 3, "Should have 3 breaches"

        summary = collector.get_summary()

        # The key is the enum value
        threshold_key = threshold.value
        assert threshold_key in summary.threshold_metrics, (
            f"Threshold '{threshold_key}' not found in metrics. "
            f"Available keys: {list(summary.threshold_metrics.keys())}"
        )

        metrics = summary.threshold_metrics[threshold_key]
        assert (
            metrics["total_breaches"] == 3
        ), f"Expected 3 total breaches, got {metrics['total_breaches']}"
        assert (
            metrics["warning_count"] == 1
        ), f"Expected 1 warning, got {metrics['warning_count']}"
        assert (
            metrics["critical_count"] == 1
        ), f"Expected 1 critical, got {metrics['critical_count']}"
        assert (
            metrics["emergency_count"] == 1
        ), f"Expected 1 emergency, got {metrics['emergency_count']}"

    def test_reset(self):
        """Test collector reset functionality."""
        collector = MetricsCollector()

        # Add some data
        collector.record_stage_timing("test", 100, 50)
        collector.check_threshold(
            EnumPerformanceThreshold.INTELLIGENCE_GATHERING_OVERHEAD, 150
        )

        assert len(collector.stage_timings) > 0
        assert len(collector.threshold_breaches) > 0

        # Reset
        collector.reset()

        assert len(collector.stage_timings) == 0
        assert len(collector.threshold_breaches) == 0


class TestPipelineStagePerformance:
    """Test PipelineStage performance tracking enhancements."""

    def test_pipeline_stage_defaults(self):
        """Test default values for performance fields."""
        stage = PipelineStage(stage_name="test_stage")

        assert stage.performance_target_ms == 0
        assert stage.actual_duration_ms == 0
        assert stage.performance_ratio == 0.0

    def test_calculate_performance_ratio(self):
        """Test performance ratio calculation."""
        stage = PipelineStage(stage_name="test_stage")

        # Set performance data
        stage.performance_target_ms = 100
        stage.actual_duration_ms = 80

        ratio = stage.calculate_performance_ratio()
        assert ratio == 0.8  # 80/100 - better than target

        # Update and test again
        stage.actual_duration_ms = 120
        ratio = stage.calculate_performance_ratio()
        assert ratio == 1.2  # 120/100 - slower than target

    def test_calculate_performance_ratio_edge_cases(self):
        """Test performance ratio with edge cases."""
        stage = PipelineStage(stage_name="test_stage")

        # No target set
        stage.performance_target_ms = 0
        stage.actual_duration_ms = 100
        assert stage.calculate_performance_ratio() == 0.0

        # No actual duration
        stage.performance_target_ms = 100
        stage.actual_duration_ms = 0
        assert stage.calculate_performance_ratio() == 0.0

    def test_update_performance_metrics(self):
        """Test update_performance_metrics method."""
        stage = PipelineStage(
            stage_name="test_stage",
            status=StageStatus.COMPLETED,
            duration_ms=85,
        )

        # Update performance metrics with target
        stage.update_performance_metrics(target_ms=100)

        assert stage.performance_target_ms == 100
        assert stage.actual_duration_ms == 85
        assert stage.performance_ratio == 0.85

    def test_update_performance_metrics_no_duration(self):
        """Test update when duration is not set."""
        stage = PipelineStage(stage_name="test_stage")

        # Update without duration set
        stage.update_performance_metrics(target_ms=100)

        assert stage.performance_target_ms == 100
        # Since duration_ms is None, actual_duration_ms and ratio should remain 0
        assert stage.actual_duration_ms == 0
        assert stage.performance_ratio == 0.0


class TestIntegration:
    """Integration tests combining components."""

    def test_full_workflow(self):
        """Test complete performance tracking workflow."""
        collector = MetricsCollector()

        # Simulate pipeline execution with multiple stages
        # Using values that won't trigger warning breaches (<80% of threshold)
        stages_config = [
            # Stage 1: 45/50 = 90% (warning level) - will trigger warning
            (
                "stage_1",
                35,
                50,
                EnumPerformanceThreshold.CONTEXT_INITIALIZATION_TIME,
            ),  # 70% - OK
            # Stage 2: 70/100 = 70% - OK
            (
                "stage_2",
                70,
                100,
                EnumPerformanceThreshold.INTELLIGENCE_GATHERING_OVERHEAD,
            ),
            # Stage 3: 1200/1500 = 80% - will trigger warning (at boundary)
            (
                "stage_3",
                1100,
                1500,
                EnumPerformanceThreshold.RAG_QUERY_RESPONSE_TIME,
            ),  # 73% - OK
            # Stage 4: 240/300 = 80% - will trigger warning
            (
                "stage_4",
                225,
                300,
                EnumPerformanceThreshold.KNOWLEDGE_CAPTURE_LATENCY,
            ),  # 75% - OK
        ]

        for stage_name, duration, target, threshold in stages_config:
            collector.record_stage_timing(stage_name, duration, target, threshold)

        # Get summary
        summary = collector.get_summary()

        # Verify summary
        assert summary.total_timings == 4
        # All values are <80% so no breaches expected
        assert summary.total_breaches == 0, (
            f"Expected 0 breaches but got {summary.total_breaches}. "
            f"Breach details: {[(b.threshold.value, b.breach_percentage, b.breach_type) for b in collector.threshold_breaches]}"
        )
        assert len(summary.stage_metrics) == 4
        assert summary.avg_performance_ratio < 1.0  # All better than target

    def test_pipeline_stage_with_collector(self):
        """Test PipelineStage integration with MetricsCollector."""
        # Create pipeline stage
        stage = PipelineStage(
            stage_name="intelligence_gathering",
            status=StageStatus.COMPLETED,
            duration_ms=85,
        )

        # Update performance metrics
        threshold = EnumPerformanceThreshold.INTELLIGENCE_GATHERING_OVERHEAD
        stage.update_performance_metrics(target_ms=threshold.threshold_ms)

        # Record in collector
        collector = MetricsCollector()
        collector.record_stage_timing(
            stage_name=stage.stage_name,
            duration_ms=stage.actual_duration_ms,
            target_ms=stage.performance_target_ms,
            threshold=threshold,
        )

        # Verify
        summary = collector.get_summary()
        assert summary.total_timings == 1
        assert summary.total_breaches == 1  # 85/100 = 85% (warning level)
        assert summary.warning_breaches == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
