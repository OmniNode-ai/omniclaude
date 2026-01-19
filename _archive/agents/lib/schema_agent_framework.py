#!/usr/bin/env python3
"""
Agent Framework Database Schema Models

Pydantic models for agent framework refinement and optimization tables:
- Mixin compatibility matrix
- Pattern feedback logging
- Generation performance metrics
- Template cache metadata
- Event processing metrics

ONEX Compliance: Type-safe data access with validation
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Enums
# =============================================================================


class NodeType(str, Enum):
    """ONEX node types"""

    EFFECT = "EFFECT"
    COMPUTE = "COMPUTE"
    REDUCER = "REDUCER"
    ORCHESTRATOR = "ORCHESTRATOR"


class FeedbackType(str, Enum):
    """Pattern feedback types"""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIAL = "partial"
    ADJUSTED = "adjusted"


class GenerationPhase(str, Enum):
    """Code generation phases"""

    PRD_ANALYSIS = "prd_analysis"
    TEMPLATE_LOAD = "template_load"
    CODE_GEN = "code_gen"
    VALIDATION = "validation"
    PERSISTENCE = "persistence"
    TOTAL = "total"


class TemplateType(str, Enum):
    """Template types for caching"""

    NODE = "node"
    CONTRACT = "contract"
    SUBCONTRACT = "subcontract"
    MIXIN = "mixin"
    TEST = "test"


# =============================================================================
# Mixin Compatibility Matrix
# =============================================================================


class MixinCompatibilityMatrix(BaseModel):
    """
    Tracks mixin combinations and compatibility for ML learning.

    ONEX Pattern: Reducer node (aggregation and learning)
    """

    id: UUID
    mixin_a: str = Field(..., max_length=100)
    mixin_b: str = Field(..., max_length=100)
    node_type: NodeType

    compatibility_score: Decimal | None = Field(None, ge=0.0, le=1.0, decimal_places=4)
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)

    last_tested_at: datetime | None = None
    conflict_reason: str | None = None
    resolution_pattern: str | None = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )

    @property
    def total_tests(self) -> int:
        """Total number of compatibility tests"""
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        """Success rate as percentage"""
        if self.total_tests == 0:
            return 0.0
        return (self.success_count / self.total_tests) * 100


class MixinCompatibilityCreate(BaseModel):
    """Schema for creating new mixin compatibility record"""

    mixin_a: str = Field(..., max_length=100)
    mixin_b: str = Field(..., max_length=100)
    node_type: NodeType
    success: bool
    conflict_reason: str | None = None
    resolution_pattern: str | None = None


# =============================================================================
# Pattern Feedback Log
# =============================================================================


class PatternFeedbackLog(BaseModel):
    """
    Stores pattern matching feedback for continuous learning.

    ONEX Pattern: Effect node (event persistence)
    """

    id: UUID
    session_id: UUID
    pattern_name: str = Field(..., max_length=100)

    detected_confidence: Decimal | None = Field(None, ge=0.0, le=1.0, decimal_places=4)
    actual_pattern: str = Field(..., max_length=100)
    feedback_type: FeedbackType

    user_provided: bool = False

    contract_json: dict[str, Any] | None = None
    capabilities_matched: list[str] = Field(default_factory=list)
    false_positives: list[str] = Field(default_factory=list)
    false_negatives: list[str] = Field(default_factory=list)

    learning_weight: Decimal = Field(
        default=Decimal("1.0"), ge=0.0, le=1.0, decimal_places=4
    )

    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )


class PatternFeedbackCreate(BaseModel):
    """Schema for creating pattern feedback record"""

    session_id: UUID
    pattern_name: str = Field(..., max_length=100)
    detected_confidence: Decimal | None = Field(None, ge=0.0, le=1.0)
    actual_pattern: str = Field(..., max_length=100)
    feedback_type: FeedbackType
    user_provided: bool = False
    contract_json: dict[str, Any] | None = None
    capabilities_matched: list[str] | None = None
    false_positives: list[str] | None = None
    false_negatives: list[str] | None = None


# =============================================================================
# Generation Performance Metrics
# =============================================================================


class GenerationPerformanceMetrics(BaseModel):
    """
    Tracks detailed performance metrics for code generation phases.

    ONEX Pattern: Effect node (metrics persistence)
    """

    id: UUID
    session_id: UUID
    node_type: str = Field(..., max_length=50)
    phase: GenerationPhase

    duration_ms: int = Field(..., ge=0)
    memory_usage_mb: int | None = Field(None, ge=0)
    cpu_percent: Decimal | None = Field(None, ge=0, decimal_places=2)

    cache_hit: bool = False
    parallel_execution: bool = False
    worker_count: int = Field(default=1, ge=1)

    metadata: dict[str, Any] | None = None

    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )


class GenerationPerformanceCreate(BaseModel):
    """Schema for creating performance metrics record"""

    session_id: UUID
    node_type: str = Field(..., max_length=50)
    phase: GenerationPhase
    duration_ms: int = Field(..., ge=0)
    memory_usage_mb: int | None = Field(None, ge=0)
    cpu_percent: float | None = Field(None, ge=0)
    cache_hit: bool = False
    parallel_execution: bool = False
    worker_count: int = Field(default=1, ge=1)
    metadata: dict[str, Any] | None = None


# =============================================================================
# Template Cache Metadata
# =============================================================================


class TemplateCacheMetadata(BaseModel):
    """
    Tracks template caching statistics for performance optimization.

    ONEX Pattern: Effect node (cache metrics)
    """

    id: UUID
    template_name: str = Field(..., max_length=200)
    template_type: TemplateType
    cache_key: str = Field(..., max_length=500)

    file_path: str
    file_hash: str = Field(..., max_length=64)
    size_bytes: int | None = Field(None, ge=0)

    load_time_ms: int | None = Field(None, ge=0)
    last_accessed_at: datetime | None = None
    access_count: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)
    cache_misses: int = Field(default=0, ge=0)

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @property
    def total_accesses(self) -> int:
        """Total cache accesses"""
        return self.cache_hits + self.cache_misses

    @property
    def hit_rate(self) -> float:
        """Cache hit rate as percentage"""
        if self.total_accesses == 0:
            return 0.0
        return (self.cache_hits / self.total_accesses) * 100


class TemplateCacheCreate(BaseModel):
    """Schema for creating template cache metadata"""

    template_name: str = Field(..., max_length=200)
    template_type: TemplateType
    cache_key: str = Field(..., max_length=500)
    file_path: str
    file_hash: str = Field(..., max_length=64)
    size_bytes: int | None = Field(None, ge=0)
    load_time_ms: int | None = Field(None, ge=0)


class TemplateCacheUpdate(BaseModel):
    """Schema for updating template cache metadata"""

    cache_hit: bool
    load_time_ms: int | None = None


# =============================================================================
# Event Processing Metrics
# =============================================================================


class EventProcessingMetrics(BaseModel):
    """
    Tracks event processing performance for optimization.

    ONEX Pattern: Effect node (event metrics)
    """

    id: UUID
    event_type: str = Field(..., max_length=100)
    event_source: str = Field(..., max_length=100)

    processing_duration_ms: int = Field(..., ge=0)
    queue_wait_time_ms: int | None = Field(None, ge=0)

    success: bool
    error_type: str | None = Field(None, max_length=100)
    error_message: str | None = None
    retry_count: int = Field(default=0, ge=0)

    batch_size: int = Field(default=1, ge=1)

    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EventProcessingCreate(BaseModel):
    """Schema for creating event processing metrics"""

    event_type: str = Field(..., max_length=100)
    event_source: str = Field(..., max_length=100)
    processing_duration_ms: int = Field(..., ge=0)
    queue_wait_time_ms: int | None = Field(None, ge=0)
    success: bool
    error_type: str | None = Field(None, max_length=100)
    error_message: str | None = None
    retry_count: int = Field(default=0, ge=0)
    batch_size: int = Field(default=1, ge=1)


# =============================================================================
# View Models (Read-Only Analytics)
# =============================================================================


class MixinCompatibilitySummary(BaseModel):
    """Aggregated mixin compatibility statistics by node type"""

    node_type: NodeType
    total_combinations: int
    avg_compatibility: Decimal | None
    total_successes: int
    total_failures: int
    success_rate: Decimal | None

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )


class PatternFeedbackAnalysis(BaseModel):
    """Analyzes pattern matching feedback for learning optimization"""

    pattern_name: str
    feedback_type: FeedbackType
    feedback_count: int
    avg_confidence: Decimal | None
    user_provided_count: int
    avg_learning_weight: Decimal | None

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )


class PerformanceMetricsSummary(BaseModel):
    """Aggregated performance metrics with percentiles by phase"""

    phase: GenerationPhase
    execution_count: int
    avg_duration_ms: Decimal | None
    p95_duration_ms: Decimal | None
    p99_duration_ms: Decimal | None
    cache_hits: int
    parallel_executions: int
    avg_workers: Decimal | None

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )


class TemplateCacheEfficiency(BaseModel):
    """Template cache hit rates and efficiency metrics by type"""

    template_type: TemplateType
    template_count: int
    avg_cache_hits: Decimal | None
    avg_cache_misses: Decimal | None
    hit_rate: Decimal | None
    avg_load_time_ms: Decimal | None
    total_size_mb: Decimal | None

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )


class EventProcessingHealth(BaseModel):
    """Event processing health metrics with success rates and performance"""

    event_type: str
    event_source: str
    total_events: int
    success_count: int
    failure_count: int
    success_rate: Decimal | None
    avg_duration_ms: Decimal | None
    avg_wait_ms: Decimal | None
    avg_retries: Decimal | None

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )
