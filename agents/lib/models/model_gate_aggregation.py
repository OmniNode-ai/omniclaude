#!/usr/bin/env python3
"""
Quality Gate Aggregation Models - ONEX v2.0 Framework

Comprehensive aggregation and reporting for quality gate results.
Provides enhanced analytics, performance tracking, and actionable recommendations.

Models:
- EnumGateCategory: Quality gate categories from quality-gates-spec.yaml
- ModelCategorySummary: Per-category gate statistics
- ModelGateAggregation: Comprehensive gate result aggregation
- ModelPipelineQualityReport: Complete pipeline quality report with recommendations

ONEX v2.0 Compliance:
- Enum/Model naming conventions
- Pydantic v2 type safety
- Performance analytics with <200ms target per gate
- Comprehensive quality scoring
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EnumGateCategory(str, Enum):
    """
    Quality gate categories from quality-gates-spec.yaml.

    8 validation categories covering all aspects of pipeline quality:
    - Sequential: Input/process/output validation
    - Parallel: Distributed coordination validation
    - Intelligence: RAG intelligence application
    - Coordination: Multi-agent context inheritance
    - Quality: ONEX standards compliance
    - Performance: Threshold and resource validation
    - Knowledge: Learning pattern validation
    - Framework: Lifecycle integration validation
    """

    SEQUENTIAL = "sequential_validation"
    PARALLEL = "parallel_validation"
    INTELLIGENCE = "intelligence_validation"
    COORDINATION = "coordination_validation"
    QUALITY = "quality_compliance"
    PERFORMANCE = "performance_validation"
    KNOWLEDGE = "knowledge_validation"
    FRAMEWORK = "framework_validation"

    @property
    def display_name(self) -> str:
        """Get human-readable category name."""
        names = {
            self.SEQUENTIAL: "Sequential Validation",
            self.PARALLEL: "Parallel Validation",
            self.INTELLIGENCE: "Intelligence Validation",
            self.COORDINATION: "Coordination Validation",
            self.QUALITY: "Quality Compliance",
            self.PERFORMANCE: "Performance Validation",
            self.KNOWLEDGE: "Knowledge Validation",
            self.FRAMEWORK: "Framework Validation",
        }
        return names.get(self, "Unknown Category")

    @property
    def description(self) -> str:
        """Get category description."""
        descriptions = {
            self.SEQUENTIAL: "Input, process, output validation for sequential execution",
            self.PARALLEL: "Distributed validation for parallel agent coordination",
            self.INTELLIGENCE: "RAG intelligence gathering and application validation",
            self.COORDINATION: "Multi-agent coordination and context inheritance validation",
            self.QUALITY: "ONEX standards and architectural compliance validation",
            self.PERFORMANCE: "Performance threshold and optimization validation",
            self.KNOWLEDGE: "Knowledge capture and learning validation",
            self.FRAMEWORK: "Framework integration and lifecycle validation",
        }
        return descriptions.get(self, "Unknown category")

    @property
    def expected_gate_count(self) -> int:
        """Get expected number of gates in this category."""
        counts = {
            self.SEQUENTIAL: 4,
            self.PARALLEL: 3,
            self.INTELLIGENCE: 3,
            self.COORDINATION: 3,
            self.QUALITY: 4,
            self.PERFORMANCE: 2,
            self.KNOWLEDGE: 2,
            self.FRAMEWORK: 2,
        }
        return counts.get(self, 0)


class ModelCategorySummary(BaseModel):
    """Per-category quality gate statistics."""

    category: EnumGateCategory = Field(..., description="Gate category")
    total_gates: int = Field(..., ge=0, description="Total gates in category")
    passed_gates: int = Field(..., ge=0, description="Number of gates passed")
    failed_gates: int = Field(..., ge=0, description="Number of gates failed")
    skipped_gates: int = Field(..., ge=0, description="Number of gates skipped")
    total_execution_time_ms: int = Field(
        ..., ge=0, description="Total execution time for category"
    )
    average_execution_time_ms: float = Field(
        ..., ge=0.0, description="Average execution time per gate"
    )
    gates_meeting_performance: int = Field(
        ..., ge=0, description="Number of gates meeting performance targets"
    )

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate for this category."""
        if self.total_gates == 0:
            return 1.0
        return self.passed_gates / self.total_gates

    @property
    def performance_compliance_rate(self) -> float:
        """Calculate performance compliance rate."""
        if self.total_gates == 0:
            return 1.0
        return self.gates_meeting_performance / self.total_gates

    @property
    def has_failures(self) -> bool:
        """Check if category has any failures."""
        return self.failed_gates > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "category": self.category.value,
            "category_name": self.category.display_name,
            "total_gates": self.total_gates,
            "passed_gates": self.passed_gates,
            "failed_gates": self.failed_gates,
            "skipped_gates": self.skipped_gates,
            "pass_rate": self.pass_rate,
            "total_execution_time_ms": self.total_execution_time_ms,
            "average_execution_time_ms": self.average_execution_time_ms,
            "gates_meeting_performance": self.gates_meeting_performance,
            "performance_compliance_rate": self.performance_compliance_rate,
            "has_failures": self.has_failures,
        }


class ModelGateAggregation(BaseModel):
    """
    Comprehensive quality gate result aggregation.

    Aggregates all gate results with detailed analytics including:
    - Overall pass/fail statistics
    - Category-by-category breakdown
    - Performance analytics (slowest, fastest, average)
    - Quality scoring and compliance rates
    - Blocking failures and warnings
    - Execution timeline for performance analysis
    """

    # Overall statistics
    total_gates: int = Field(..., ge=0, description="Total number of gates executed")
    passed_gates: int = Field(..., ge=0, description="Number of gates passed")
    failed_gates: int = Field(..., ge=0, description="Number of gates failed")
    skipped_gates: int = Field(default=0, ge=0, description="Number of gates skipped")

    # Category breakdown
    category_summary: dict[EnumGateCategory, ModelCategorySummary] = Field(
        default_factory=dict, description="Per-category gate statistics"
    )

    # Performance analytics
    total_execution_time_ms: int = Field(
        ..., ge=0, description="Total execution time across all gates"
    )
    average_execution_time_ms: float = Field(
        ..., ge=0.0, description="Average execution time per gate"
    )
    slowest_gate: dict[str, Any] | None = Field(
        default=None, description="Details of slowest gate execution"
    )
    fastest_gate: dict[str, Any] | None = Field(
        default=None, description="Details of fastest gate execution"
    )

    # Quality metrics
    overall_quality_score: float = Field(
        ..., ge=0.0, le=1.0, description="Weighted quality score (0.0-1.0)"
    )
    blocking_failures: list[str] = Field(
        default_factory=list, description="List of blocking gate failures"
    )
    warnings: list[str] = Field(
        default_factory=list, description="List of warning messages"
    )

    # Timeline for performance analysis
    execution_timeline: list[dict[str, Any]] = Field(
        default_factory=list, description="Chronological execution timeline"
    )

    # Compliance rates
    compliance_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Overall gate pass rate"
    )
    performance_compliance_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Rate of gates meeting performance targets"
    )

    @property
    def has_blocking_failures(self) -> bool:
        """Check if there are any blocking failures."""
        return len(self.blocking_failures) > 0

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0

    @property
    def is_healthy(self) -> bool:
        """Check if pipeline quality is healthy (no blocking failures)."""
        return not self.has_blocking_failures

    @property
    def quality_grade(self) -> str:
        """Get quality grade based on overall score."""
        if self.overall_quality_score >= 0.95:
            return "A+"
        elif self.overall_quality_score >= 0.90:
            return "A"
        elif self.overall_quality_score >= 0.85:
            return "B+"
        elif self.overall_quality_score >= 0.80:
            return "B"
        elif self.overall_quality_score >= 0.70:
            return "C"
        elif self.overall_quality_score >= 0.60:
            return "D"
        else:
            return "F"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_gates": self.total_gates,
            "passed_gates": self.passed_gates,
            "failed_gates": self.failed_gates,
            "skipped_gates": self.skipped_gates,
            "category_summary": {
                cat.value: summary.to_dict()
                for cat, summary in self.category_summary.items()
            },
            "total_execution_time_ms": self.total_execution_time_ms,
            "average_execution_time_ms": self.average_execution_time_ms,
            "slowest_gate": self.slowest_gate,
            "fastest_gate": self.fastest_gate,
            "overall_quality_score": self.overall_quality_score,
            "quality_grade": self.quality_grade,
            "blocking_failures": self.blocking_failures,
            "warnings": self.warnings,
            "execution_timeline": self.execution_timeline,
            "compliance_rate": self.compliance_rate,
            "performance_compliance_rate": self.performance_compliance_rate,
            "has_blocking_failures": self.has_blocking_failures,
            "has_warnings": self.has_warnings,
            "is_healthy": self.is_healthy,
        }

    model_config = {
        "arbitrary_types_allowed": True,
    }


class ModelPipelineQualityReport(BaseModel):
    """
    Complete pipeline quality report with recommendations.

    Comprehensive report combining:
    - Quality gate aggregation and analytics
    - Performance metrics summary
    - Stage-by-stage quality results
    - Actionable recommendations
    - Critical issues requiring attention
    """

    correlation_id: str = Field(..., description="Pipeline execution correlation ID")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Report generation timestamp (UTC)",
    )

    # Gate aggregation
    gate_aggregation: ModelGateAggregation = Field(
        ..., description="Aggregated quality gate results"
    )

    # Performance metrics
    performance_summary: dict[str, Any] = Field(
        default_factory=dict, description="Performance metrics summary"
    )

    # Stage-by-stage results
    stage_quality: list[dict[str, Any]] = Field(
        default_factory=list, description="Quality results for each pipeline stage"
    )

    # Actionable insights
    recommendations: list[str] = Field(
        default_factory=list, description="Actionable recommendations for improvement"
    )
    critical_issues: list[str] = Field(
        default_factory=list,
        description="Critical issues requiring immediate attention",
    )

    @property
    def overall_status(self) -> str:
        """Get overall pipeline status."""
        if self.gate_aggregation.has_blocking_failures:
            return "FAILED"
        elif self.gate_aggregation.failed_gates > 0:
            return "PARTIAL"
        elif self.gate_aggregation.has_warnings:
            return "WARNING"
        else:
            return "SUCCESS"

    @property
    def requires_action(self) -> bool:
        """Check if report requires immediate action."""
        return len(self.critical_issues) > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "overall_status": self.overall_status,
            "gate_aggregation": self.gate_aggregation.to_dict(),
            "performance_summary": self.performance_summary,
            "stage_quality": self.stage_quality,
            "recommendations": self.recommendations,
            "critical_issues": self.critical_issues,
            "requires_action": self.requires_action,
        }

    def to_summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Pipeline Quality Report: {self.overall_status}",
            f"Correlation ID: {self.correlation_id}",
            f"Quality Score: {self.gate_aggregation.overall_quality_score:.1%} (Grade: {self.gate_aggregation.quality_grade})",
            f"Gates: {self.gate_aggregation.passed_gates}/{self.gate_aggregation.total_gates} passed",
            f"Compliance: {self.gate_aggregation.compliance_rate:.1%}",
            f"Performance Compliance: {self.gate_aggregation.performance_compliance_rate:.1%}",
        ]

        if self.critical_issues:
            lines.append(f"\nCritical Issues ({len(self.critical_issues)}):")
            for issue in self.critical_issues:
                lines.append(f"  - {issue}")

        if self.recommendations:
            lines.append(f"\nRecommendations ({len(self.recommendations)}):")
            for rec in self.recommendations[:3]:  # Show top 3
                lines.append(f"  - {rec}")
            if len(self.recommendations) > 3:
                lines.append(f"  ... and {len(self.recommendations) - 3} more")

        return "\n".join(lines)

    model_config = {
        "arbitrary_types_allowed": True,
    }
