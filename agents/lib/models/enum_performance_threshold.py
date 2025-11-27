#!/usr/bin/env python3
"""
Performance Threshold Enumeration - ONEX Agent Framework.

Defines 33 performance thresholds across 7 categories for agent execution monitoring.
Each threshold includes target values, tolerances, and alert thresholds.

ONEX Compliance:
- Enum-based naming: EnumPerformanceThreshold
- Clear threshold definitions with metadata
- Integration with metrics collection framework

Total Thresholds: 33
Categories: 7 (intelligence, parallel_execution, coordination, context_management,
             template_system, lifecycle, dashboard)
"""

from enum import Enum
from typing import TypedDict

from typing_extensions import NotRequired


class ThresholdMetadata(TypedDict):
    """TypedDict for threshold metadata with type-safe field definitions.

    Required fields (always present):
        name: Human-readable threshold name
        description: Detailed threshold description
        category: Threshold category (e.g., 'intelligence', 'parallel_execution')
        criticality: Criticality level ('high', 'medium', 'low')
        measurement_type: Type of measurement (e.g., 'response_time', 'overhead')

    Optional fields (one set per measurement unit):
        threshold_ms/mb/ratio: Target threshold value
        tolerance_ms/mb/ratio: Acceptable tolerance range
        alert_threshold_ms/mb/ratio: Early warning threshold
    """

    # Required fields (always present in all threshold metadata)
    name: str
    description: str
    category: str
    criticality: str
    measurement_type: str
    # Time-based thresholds (optional - only for time-based measurements)
    threshold_ms: NotRequired[int]
    tolerance_ms: NotRequired[int]
    alert_threshold_ms: NotRequired[int]
    # Memory-based thresholds (optional - only for memory-based measurements)
    threshold_mb: NotRequired[int]
    tolerance_mb: NotRequired[int]
    alert_threshold_mb: NotRequired[int]
    # Ratio-based thresholds (optional - only for ratio-based measurements)
    threshold_ratio: NotRequired[float]
    tolerance_ratio: NotRequired[float]
    alert_threshold_ratio: NotRequired[float]


class EnumPerformanceThreshold(str, Enum):
    """
    33 Performance thresholds across 7 categories.

    Each threshold includes:
    - Target value (ms, MB, or ratio)
    - Tolerance range
    - Alert threshold for early warning
    - Criticality level (high/medium/low)
    - Measurement type

    Categories:
    - Intelligence (INT-001 to INT-006): RAG and intelligence gathering
    - Parallel Execution (PAR-001 to PAR-005): Parallel coordination
    - Coordination (COORD-001 to COORD-004): Multi-agent coordination
    - Context Management (CTX-001 to CTX-006): Context lifecycle
    - Template System (TPL-001 to TPL-004): Template instantiation
    - Lifecycle (LCL-001 to LCL-004): Agent lifecycle
    - Dashboard (DASH-001 to DASH-004): Performance monitoring
    """

    # Intelligence Thresholds (INT-001 to INT-006)
    RAG_QUERY_RESPONSE_TIME = "int_001_rag_query_response"
    INTELLIGENCE_GATHERING_OVERHEAD = "int_002_intelligence_overhead"
    PATTERN_RECOGNITION_PERFORMANCE = "int_003_pattern_recognition"
    KNOWLEDGE_CAPTURE_LATENCY = "int_004_knowledge_capture"
    CROSS_DOMAIN_SYNTHESIS = "int_005_cross_domain_synthesis"
    INTELLIGENCE_APPLICATION_TIME = "int_006_intelligence_application"

    # Parallel Execution Thresholds (PAR-001 to PAR-005)
    PARALLEL_COORDINATION_SETUP = "par_001_coordination_setup"
    CONTEXT_DISTRIBUTION_TIME = "par_002_context_distribution"
    SYNCHRONIZATION_POINT_LATENCY = "par_003_sync_latency"
    RESULT_AGGREGATION_PERFORMANCE = "par_004_result_aggregation"
    PARALLEL_EFFICIENCY_RATIO = "par_005_efficiency_ratio"

    # Coordination Thresholds (COORD-001 to COORD-004)
    AGENT_DELEGATION_HANDOFF = "coord_001_delegation_handoff"
    CONTEXT_INHERITANCE_LATENCY = "coord_002_context_inheritance"
    MULTI_AGENT_COMMUNICATION = "coord_003_multi_agent_comm"
    COORDINATION_OVERHEAD = "coord_004_coordination_overhead"

    # Context Management Thresholds (CTX-001 to CTX-006)
    CONTEXT_INITIALIZATION_TIME = "ctx_001_initialization"
    CONTEXT_PRESERVATION_LATENCY = "ctx_002_preservation"
    CONTEXT_REFRESH_PERFORMANCE = "ctx_003_refresh"
    CONTEXT_MEMORY_FOOTPRINT = "ctx_004_memory_footprint"
    CONTEXT_LIFECYCLE_MANAGEMENT = "ctx_005_lifecycle"
    CONTEXT_CLEANUP_PERFORMANCE = "ctx_006_cleanup"

    # Template System Thresholds (TPL-001 to TPL-004)
    TEMPLATE_INSTANTIATION_TIME = "tpl_001_instantiation"
    TEMPLATE_PARAMETER_RESOLUTION = "tpl_002_parameter_resolution"
    CONFIGURATION_OVERLAY_PERFORMANCE = "tpl_003_overlay_performance"
    TEMPLATE_CACHE_HIT_RATIO = "tpl_004_cache_hit_ratio"

    # Lifecycle Thresholds (LCL-001 to LCL-004)
    AGENT_INITIALIZATION_PERFORMANCE = "lcl_001_initialization"
    FRAMEWORK_INTEGRATION_TIME = "lcl_002_framework_integration"
    QUALITY_GATE_EXECUTION = "lcl_003_quality_gate_execution"
    AGENT_CLEANUP_PERFORMANCE = "lcl_004_cleanup"

    # Dashboard Thresholds (DASH-001 to DASH-004)
    PERFORMANCE_DATA_COLLECTION = "dash_001_data_collection"
    DASHBOARD_UPDATE_LATENCY = "dash_002_update_latency"
    TREND_ANALYSIS_PERFORMANCE = "dash_003_trend_analysis"
    OPTIMIZATION_RECOMMENDATION_TIME = "dash_004_optimization_rec"

    @property
    def category(self) -> str:
        """Get threshold category."""
        result: str = self._get_metadata()["category"]
        return result

    @property
    def threshold_ms(self) -> int:
        """Get threshold value in milliseconds (0 for ratio-based thresholds)."""
        metadata = self._get_metadata()
        result: int = metadata.get("threshold_ms", 0)
        return result

    @property
    def threshold_mb(self) -> int:
        """Get threshold value in megabytes (0 for non-memory thresholds)."""
        metadata = self._get_metadata()
        result: int = metadata.get("threshold_mb", 0)
        return result

    @property
    def threshold_ratio(self) -> float:
        """Get threshold ratio (0.0 for non-ratio thresholds)."""
        metadata = self._get_metadata()
        result: float = metadata.get("threshold_ratio", 0.0)
        return result

    @property
    def tolerance_ms(self) -> int:
        """Get tolerance in milliseconds (0 for ratio-based thresholds)."""
        metadata = self._get_metadata()
        result: int = metadata.get("tolerance_ms", 0)
        return result

    @property
    def tolerance_mb(self) -> int:
        """Get tolerance in megabytes (0 for non-memory thresholds)."""
        metadata = self._get_metadata()
        result: int = metadata.get("tolerance_mb", 0)
        return result

    @property
    def tolerance_ratio(self) -> float:
        """Get tolerance ratio (0.0 for non-ratio thresholds)."""
        metadata = self._get_metadata()
        result: float = metadata.get("tolerance_ratio", 0.0)
        return result

    @property
    def alert_threshold_ms(self) -> int:
        """Get alert threshold in milliseconds (0 for ratio-based thresholds)."""
        metadata = self._get_metadata()
        result: int = metadata.get("alert_threshold_ms", 0)
        return result

    @property
    def alert_threshold_mb(self) -> int:
        """Get alert threshold in megabytes (0 for non-memory thresholds)."""
        metadata = self._get_metadata()
        result: int = metadata.get("alert_threshold_mb", 0)
        return result

    @property
    def alert_threshold_ratio(self) -> float:
        """Get alert threshold ratio (0.0 for non-ratio thresholds)."""
        metadata = self._get_metadata()
        result: float = metadata.get("alert_threshold_ratio", 0.0)
        return result

    @property
    def criticality(self) -> str:
        """Get criticality level (high/medium/low)."""
        result: str = self._get_metadata()["criticality"]
        return result

    @property
    def measurement_type(self) -> str:
        """Get measurement type (response_time, overhead, etc.)."""
        result: str = self._get_metadata()["measurement_type"]
        return result

    @property
    def name(self) -> str:
        """Get human-readable threshold name."""
        result: str = self._get_metadata()["name"]
        return result

    @property
    def description(self) -> str:
        """Get threshold description."""
        result: str = self._get_metadata()["description"]
        return result

    def _get_metadata(self) -> ThresholdMetadata:
        """Get metadata for this threshold from specification.

        Returns:
            ThresholdMetadata: The metadata for this threshold.

        Raises:
            KeyError: If threshold metadata is not defined (programming error).
        """
        # Use direct access - missing metadata is a programming error
        # that should fail fast rather than return invalid data
        return _THRESHOLD_METADATA[self]

    @staticmethod
    def all_thresholds() -> list["EnumPerformanceThreshold"]:
        """Get all performance thresholds."""
        return list(EnumPerformanceThreshold)

    @staticmethod
    def by_category(category: str) -> list["EnumPerformanceThreshold"]:
        """Get thresholds by category."""
        return [
            threshold
            for threshold in EnumPerformanceThreshold
            if threshold.category == category
        ]

    @staticmethod
    def by_criticality(criticality: str) -> list["EnumPerformanceThreshold"]:
        """Get thresholds by criticality level."""
        return [
            threshold
            for threshold in EnumPerformanceThreshold
            if threshold.criticality == criticality
        ]


# Threshold metadata from performance-thresholds.yaml specification
_THRESHOLD_METADATA: dict[EnumPerformanceThreshold, ThresholdMetadata] = {
    # Intelligence Thresholds (INT-001 to INT-006)
    EnumPerformanceThreshold.RAG_QUERY_RESPONSE_TIME: {
        "name": "RAG Query Response Time",
        "description": "Maximum time for RAG intelligence queries",
        "category": "intelligence",
        "threshold_ms": 1500,
        "tolerance_ms": 200,
        "alert_threshold_ms": 1200,
        "criticality": "high",
        "measurement_type": "response_time",
    },
    EnumPerformanceThreshold.INTELLIGENCE_GATHERING_OVERHEAD: {
        "name": "Intelligence Gathering Overhead",
        "description": "Pre-execution intelligence gathering time",
        "category": "intelligence",
        "threshold_ms": 100,
        "tolerance_ms": 25,
        "alert_threshold_ms": 80,
        "criticality": "high",
        "measurement_type": "overhead",
    },
    EnumPerformanceThreshold.PATTERN_RECOGNITION_PERFORMANCE: {
        "name": "Pattern Recognition Performance",
        "description": "Pattern extraction and synthesis time",
        "category": "intelligence",
        "threshold_ms": 500,
        "tolerance_ms": 100,
        "alert_threshold_ms": 400,
        "criticality": "medium",
        "measurement_type": "processing_time",
    },
    EnumPerformanceThreshold.KNOWLEDGE_CAPTURE_LATENCY: {
        "name": "Knowledge Capture Latency",
        "description": "UAKS knowledge capture and storage time",
        "category": "intelligence",
        "threshold_ms": 300,
        "tolerance_ms": 50,
        "alert_threshold_ms": 250,
        "criticality": "medium",
        "measurement_type": "storage_latency",
    },
    EnumPerformanceThreshold.CROSS_DOMAIN_SYNTHESIS: {
        "name": "Cross-Domain Synthesis",
        "description": "Multi-source intelligence synthesis time",
        "category": "intelligence",
        "threshold_ms": 800,
        "tolerance_ms": 150,
        "alert_threshold_ms": 650,
        "criticality": "medium",
        "measurement_type": "processing_time",
    },
    EnumPerformanceThreshold.INTELLIGENCE_APPLICATION_TIME: {
        "name": "Intelligence Application Time",
        "description": "Time to apply gathered intelligence to execution",
        "category": "intelligence",
        "threshold_ms": 200,
        "tolerance_ms": 50,
        "alert_threshold_ms": 150,
        "criticality": "high",
        "measurement_type": "application_time",
    },
    # Parallel Execution Thresholds (PAR-001 to PAR-005)
    EnumPerformanceThreshold.PARALLEL_COORDINATION_SETUP: {
        "name": "Parallel Coordination Setup",
        "description": "Time to establish parallel coordination state",
        "category": "parallel_execution",
        "threshold_ms": 500,
        "tolerance_ms": 100,
        "alert_threshold_ms": 400,
        "criticality": "high",
        "measurement_type": "setup_time",
    },
    EnumPerformanceThreshold.CONTEXT_DISTRIBUTION_TIME: {
        "name": "Context Distribution Time",
        "description": "Time to distribute context to parallel agents",
        "category": "parallel_execution",
        "threshold_ms": 200,
        "tolerance_ms": 50,
        "alert_threshold_ms": 150,
        "criticality": "high",
        "measurement_type": "distribution_time",
    },
    EnumPerformanceThreshold.SYNCHRONIZATION_POINT_LATENCY: {
        "name": "Synchronization Point Latency",
        "description": "Time for parallel agents to reach sync points",
        "category": "parallel_execution",
        "threshold_ms": 1000,
        "tolerance_ms": 200,
        "alert_threshold_ms": 800,
        "criticality": "medium",
        "measurement_type": "sync_latency",
    },
    EnumPerformanceThreshold.RESULT_AGGREGATION_PERFORMANCE: {
        "name": "Result Aggregation Performance",
        "description": "Time to collect and merge parallel results",
        "category": "parallel_execution",
        "threshold_ms": 300,
        "tolerance_ms": 75,
        "alert_threshold_ms": 225,
        "criticality": "high",
        "measurement_type": "aggregation_time",
    },
    EnumPerformanceThreshold.PARALLEL_EFFICIENCY_RATIO: {
        "name": "Parallel Efficiency Ratio",
        "description": "Parallel execution speedup vs sequential baseline",
        "category": "parallel_execution",
        "threshold_ratio": 0.6,
        "tolerance_ratio": 0.1,
        "alert_threshold_ratio": 0.7,
        "criticality": "medium",
        "measurement_type": "efficiency_ratio",
    },
    # Coordination Thresholds (COORD-001 to COORD-004)
    EnumPerformanceThreshold.AGENT_DELEGATION_HANDOFF: {
        "name": "Agent Delegation Handoff",
        "description": "Time to delegate task to specialized agent",
        "category": "coordination",
        "threshold_ms": 150,
        "tolerance_ms": 30,
        "alert_threshold_ms": 120,
        "criticality": "medium",
        "measurement_type": "handoff_time",
    },
    EnumPerformanceThreshold.CONTEXT_INHERITANCE_LATENCY: {
        "name": "Context Inheritance Latency",
        "description": "Time to preserve and transfer context",
        "category": "coordination",
        "threshold_ms": 50,
        "tolerance_ms": 15,
        "alert_threshold_ms": 35,
        "criticality": "high",
        "measurement_type": "inheritance_time",
    },
    EnumPerformanceThreshold.MULTI_AGENT_COMMUNICATION: {
        "name": "Multi-Agent Communication",
        "description": "Inter-agent communication response time",
        "category": "coordination",
        "threshold_ms": 100,
        "tolerance_ms": 25,
        "alert_threshold_ms": 75,
        "criticality": "medium",
        "measurement_type": "communication_time",
    },
    EnumPerformanceThreshold.COORDINATION_OVERHEAD: {
        "name": "Coordination Overhead",
        "description": "Total coordination overhead per multi-agent task",
        "category": "coordination",
        "threshold_ms": 300,
        "tolerance_ms": 75,
        "alert_threshold_ms": 225,
        "criticality": "low",
        "measurement_type": "total_overhead",
    },
    # Context Management Thresholds (CTX-001 to CTX-006)
    EnumPerformanceThreshold.CONTEXT_INITIALIZATION_TIME: {
        "name": "Context Initialization Time",
        "description": "Time to establish agent execution context",
        "category": "context_management",
        "threshold_ms": 50,
        "tolerance_ms": 15,
        "alert_threshold_ms": 35,
        "criticality": "high",
        "measurement_type": "initialization_time",
    },
    EnumPerformanceThreshold.CONTEXT_PRESERVATION_LATENCY: {
        "name": "Context Preservation Latency",
        "description": "Time to preserve context during operations",
        "category": "context_management",
        "threshold_ms": 25,
        "tolerance_ms": 10,
        "alert_threshold_ms": 15,
        "criticality": "high",
        "measurement_type": "preservation_time",
    },
    EnumPerformanceThreshold.CONTEXT_REFRESH_PERFORMANCE: {
        "name": "Context Refresh Performance",
        "description": "Selective context refresh operation time",
        "category": "context_management",
        "threshold_ms": 75,
        "tolerance_ms": 20,
        "alert_threshold_ms": 55,
        "criticality": "medium",
        "measurement_type": "refresh_time",
    },
    EnumPerformanceThreshold.CONTEXT_MEMORY_FOOTPRINT: {
        "name": "Context Memory Footprint",
        "description": "Memory usage for context storage per agent",
        "category": "context_management",
        "threshold_mb": 10,
        "tolerance_mb": 2,
        "alert_threshold_mb": 8,
        "criticality": "medium",
        "measurement_type": "memory_usage",
    },
    EnumPerformanceThreshold.CONTEXT_LIFECYCLE_MANAGEMENT: {
        "name": "Context Lifecycle Management",
        "description": "Complete context lifecycle operation time",
        "category": "context_management",
        "threshold_ms": 200,
        "tolerance_ms": 50,
        "alert_threshold_ms": 150,
        "criticality": "medium",
        "measurement_type": "lifecycle_time",
    },
    EnumPerformanceThreshold.CONTEXT_CLEANUP_PERFORMANCE: {
        "name": "Context Cleanup Performance",
        "description": "Time to properly cleanup context resources",
        "category": "context_management",
        "threshold_ms": 100,
        "tolerance_ms": 25,
        "alert_threshold_ms": 75,
        "criticality": "low",
        "measurement_type": "cleanup_time",
    },
    # Template System Thresholds (TPL-001 to TPL-004)
    EnumPerformanceThreshold.TEMPLATE_INSTANTIATION_TIME: {
        "name": "Template Instantiation Time",
        "description": "Time to instantiate agent templates",
        "category": "template_system",
        "threshold_ms": 100,
        "tolerance_ms": 25,
        "alert_threshold_ms": 75,
        "criticality": "low",
        "measurement_type": "instantiation_time",
    },
    EnumPerformanceThreshold.TEMPLATE_PARAMETER_RESOLUTION: {
        "name": "Template Parameter Resolution",
        "description": "Time to resolve template parameters and caching",
        "category": "template_system",
        "threshold_ms": 50,
        "tolerance_ms": 15,
        "alert_threshold_ms": 35,
        "criticality": "low",
        "measurement_type": "resolution_time",
    },
    EnumPerformanceThreshold.CONFIGURATION_OVERLAY_PERFORMANCE: {
        "name": "Configuration Overlay Performance",
        "description": "Time to apply configuration overlays",
        "category": "template_system",
        "threshold_ms": 30,
        "tolerance_ms": 10,
        "alert_threshold_ms": 20,
        "criticality": "low",
        "measurement_type": "overlay_time",
    },
    EnumPerformanceThreshold.TEMPLATE_CACHE_HIT_RATIO: {
        "name": "Template Cache Hit Ratio",
        "description": "Template caching effectiveness ratio",
        "category": "template_system",
        "threshold_ratio": 0.85,
        "tolerance_ratio": 0.05,
        "alert_threshold_ratio": 0.9,
        "criticality": "low",
        "measurement_type": "cache_hit_ratio",
    },
    # Lifecycle Thresholds (LCL-001 to LCL-004)
    EnumPerformanceThreshold.AGENT_INITIALIZATION_PERFORMANCE: {
        "name": "Agent Initialization Performance",
        "description": "Complete agent initialization time",
        "category": "lifecycle",
        "threshold_ms": 300,
        "tolerance_ms": 75,
        "alert_threshold_ms": 225,
        "criticality": "medium",
        "measurement_type": "initialization_time",
    },
    EnumPerformanceThreshold.FRAMEWORK_INTEGRATION_TIME: {
        "name": "Framework Integration Time",
        "description": "Time to integrate with framework components",
        "category": "lifecycle",
        "threshold_ms": 100,
        "tolerance_ms": 25,
        "alert_threshold_ms": 75,
        "criticality": "medium",
        "measurement_type": "integration_time",
    },
    EnumPerformanceThreshold.QUALITY_GATE_EXECUTION: {
        "name": "Quality Gate Execution",
        "description": "Total time for quality gate validation",
        "category": "lifecycle",
        "threshold_ms": 200,
        "tolerance_ms": 50,
        "alert_threshold_ms": 150,
        "criticality": "high",
        "measurement_type": "validation_time",
    },
    EnumPerformanceThreshold.AGENT_CLEANUP_PERFORMANCE: {
        "name": "Agent Cleanup Performance",
        "description": "Time for proper agent resource cleanup",
        "category": "lifecycle",
        "threshold_ms": 150,
        "tolerance_ms": 40,
        "alert_threshold_ms": 110,
        "criticality": "low",
        "measurement_type": "cleanup_time",
    },
    # Dashboard Thresholds (DASH-001 to DASH-004)
    EnumPerformanceThreshold.PERFORMANCE_DATA_COLLECTION: {
        "name": "Performance Data Collection",
        "description": "Time to collect performance metrics",
        "category": "dashboard",
        "threshold_ms": 50,
        "tolerance_ms": 15,
        "alert_threshold_ms": 35,
        "criticality": "low",
        "measurement_type": "collection_time",
    },
    EnumPerformanceThreshold.DASHBOARD_UPDATE_LATENCY: {
        "name": "Dashboard Update Latency",
        "description": "Time to update performance dashboard",
        "category": "dashboard",
        "threshold_ms": 100,
        "tolerance_ms": 25,
        "alert_threshold_ms": 75,
        "criticality": "low",
        "measurement_type": "update_time",
    },
    EnumPerformanceThreshold.TREND_ANALYSIS_PERFORMANCE: {
        "name": "Trend Analysis Performance",
        "description": "Time to analyze performance trends",
        "category": "dashboard",
        "threshold_ms": 500,
        "tolerance_ms": 100,
        "alert_threshold_ms": 400,
        "criticality": "low",
        "measurement_type": "analysis_time",
    },
    EnumPerformanceThreshold.OPTIMIZATION_RECOMMENDATION_TIME: {
        "name": "Optimization Recommendation Time",
        "description": "Time to generate optimization recommendations",
        "category": "dashboard",
        "threshold_ms": 300,
        "tolerance_ms": 75,
        "alert_threshold_ms": 225,
        "criticality": "low",
        "measurement_type": "recommendation_time",
    },
}
