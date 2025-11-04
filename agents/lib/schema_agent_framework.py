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
from typing import Any, Dict, List, Optional
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

    compatibility_score: Optional[Decimal] = Field(
        None, ge=0.0, le=1.0, decimal_places=4
    )
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)

    last_tested_at: Optional[datetime] = None
    conflict_reason: Optional[str] = None
    resolution_pattern: Optional[str] = None

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
    conflict_reason: Optional[str] = None
    resolution_pattern: Optional[str] = None


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

    detected_confidence: Optional[Decimal] = Field(
        None, ge=0.0, le=1.0, decimal_places=4
    )
    actual_pattern: str = Field(..., max_length=100)
    feedback_type: FeedbackType

    user_provided: bool = False

    contract_json: Optional[Dict[str, Any]] = None
    capabilities_matched: List[str] = Field(default_factory=list)
    false_positives: List[str] = Field(default_factory=list)
    false_negatives: List[str] = Field(default_factory=list)

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
    detected_confidence: Optional[Decimal] = Field(None, ge=0.0, le=1.0)
    actual_pattern: str = Field(..., max_length=100)
    feedback_type: FeedbackType
    user_provided: bool = False
    contract_json: Optional[Dict[str, Any]] = None
    capabilities_matched: Optional[List[str]] = None
    false_positives: Optional[List[str]] = None
    false_negatives: Optional[List[str]] = None


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
    memory_usage_mb: Optional[int] = Field(None, ge=0)
    cpu_percent: Optional[Decimal] = Field(None, ge=0, decimal_places=2)

    cache_hit: bool = False
    parallel_execution: bool = False
    worker_count: int = Field(default=1, ge=1)

    metadata: Optional[Dict[str, Any]] = None

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
    memory_usage_mb: Optional[int] = Field(None, ge=0)
    cpu_percent: Optional[float] = Field(None, ge=0)
    cache_hit: bool = False
    parallel_execution: bool = False
    worker_count: int = Field(default=1, ge=1)
    metadata: Optional[Dict[str, Any]] = None


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
    size_bytes: Optional[int] = Field(None, ge=0)

    load_time_ms: Optional[int] = Field(None, ge=0)
    last_accessed_at: Optional[datetime] = None
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
    size_bytes: Optional[int] = Field(None, ge=0)
    load_time_ms: Optional[int] = Field(None, ge=0)


class TemplateCacheUpdate(BaseModel):
    """Schema for updating template cache metadata"""

    cache_hit: bool
    load_time_ms: Optional[int] = None


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
    queue_wait_time_ms: Optional[int] = Field(None, ge=0)

    success: bool
    error_type: Optional[str] = Field(None, max_length=100)
    error_message: Optional[str] = None
    retry_count: int = Field(default=0, ge=0)

    batch_size: int = Field(default=1, ge=1)

    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EventProcessingCreate(BaseModel):
    """Schema for creating event processing metrics"""

    event_type: str = Field(..., max_length=100)
    event_source: str = Field(..., max_length=100)
    processing_duration_ms: int = Field(..., ge=0)
    queue_wait_time_ms: Optional[int] = Field(None, ge=0)
    success: bool
    error_type: Optional[str] = Field(None, max_length=100)
    error_message: Optional[str] = None
    retry_count: int = Field(default=0, ge=0)
    batch_size: int = Field(default=1, ge=1)


# =============================================================================
# View Models (Read-Only Analytics)
# =============================================================================


class MixinCompatibilitySummary(BaseModel):
    """Aggregated mixin compatibility statistics by node type"""

    node_type: NodeType
    total_combinations: int
    avg_compatibility: Optional[Decimal]
    total_successes: int
    total_failures: int
    success_rate: Optional[Decimal]

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )


class PatternFeedbackAnalysis(BaseModel):
    """Analyzes pattern matching feedback for learning optimization"""

    pattern_name: str
    feedback_type: FeedbackType
    feedback_count: int
    avg_confidence: Optional[Decimal]
    user_provided_count: int
    avg_learning_weight: Optional[Decimal]

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )


class PerformanceMetricsSummary(BaseModel):
    """Aggregated performance metrics with percentiles by phase"""

    phase: GenerationPhase
    execution_count: int
    avg_duration_ms: Optional[Decimal]
    p95_duration_ms: Optional[Decimal]
    p99_duration_ms: Optional[Decimal]
    cache_hits: int
    parallel_executions: int
    avg_workers: Optional[Decimal]

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )


class TemplateCacheEfficiency(BaseModel):
    """Template cache hit rates and efficiency metrics by type"""

    template_type: TemplateType
    template_count: int
    avg_cache_hits: Optional[Decimal]
    avg_cache_misses: Optional[Decimal]
    hit_rate: Optional[Decimal]
    avg_load_time_ms: Optional[Decimal]
    total_size_mb: Optional[Decimal]

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
    success_rate: Optional[Decimal]
    avg_duration_ms: Optional[Decimal]
    avg_wait_ms: Optional[Decimal]
    avg_retries: Optional[Decimal]

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: float(v) if v is not None else None},
    )
