#!/usr/bin/env python3
"""
Code Pattern Models - ONEX v2.0 Framework Implementation

Models for extracting, storing, and reusing code generation patterns.
Part of KV-002 (Pattern Recognition) quality gate integration.

Architecture:
- ModelCodePattern: Core pattern storage model
- ModelPatternExtractionResult: Pattern extraction metadata
- ModelPatternMatch: Pattern similarity match result

ONEX v2.0 Compliance:
- Model/Enum naming conventions
- Pydantic v2 for type safety
- Comprehensive metadata tracking
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EnumPatternType(str, Enum):
    """
    Pattern types for code generation.

    Categories:
    - Workflow: Stage sequences, orchestration flows
    - Code: Common implementations, reusable functions
    - Naming: ONEX conventions, naming rules
    - Architecture: Design patterns (Factory, Strategy, etc.)
    - Error Handling: Try-catch structures, error propagation
    - Testing: Test structure, mocking, fixtures
    """

    WORKFLOW = "workflow"
    CODE = "code"
    NAMING = "naming"
    ARCHITECTURE = "architecture"
    ERROR_HANDLING = "error_handling"
    TESTING = "testing"


class ModelCodePattern(BaseModel):
    """
    Code pattern extracted from successful generation.

    Stores reusable patterns with context for intelligent reuse.
    Integrates with Qdrant for vector similarity search.

    Example:
        pattern = ModelCodePattern(
            pattern_type="workflow",
            pattern_name="6-stage ONEX generation",
            pattern_description="Complete ONEX node generation workflow",
            pattern_template="{% for stage in stages %}...",
            confidence_score=0.95,
            source_context={"node_type": "effect", "framework": "onex"},
            reuse_conditions=["node_type matches", "framework is onex"]
        )
    """

    pattern_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique pattern identifier",
    )
    pattern_type: EnumPatternType = Field(..., description="Type of pattern")
    pattern_name: str = Field(..., min_length=1, description="Human-readable name")
    pattern_description: str = Field(
        ..., min_length=1, description="Detailed description"
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Pattern quality score (0.0-1.0)"
    )

    # Pattern content
    pattern_template: str = Field(
        ..., min_length=1, description="Jinja2 template or code snippet"
    )
    example_usage: list[str] = Field(
        default_factory=list, description="Example code using this pattern"
    )

    # Context and conditions
    source_context: dict[str, Any] = Field(
        default_factory=dict, description="Context where pattern was extracted"
    )
    reuse_conditions: list[str] = Field(
        default_factory=list, description="Conditions for pattern reuse"
    )

    # Metadata
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Pattern creation timestamp (UTC)",
    )
    last_used: datetime | None = Field(
        None, description="Last time pattern was applied (UTC)"
    )
    usage_count: int = Field(
        0, ge=0, description="Number of times pattern has been reused"
    )

    # Quality metrics
    success_rate: float = Field(
        1.0, ge=0.0, le=1.0, description="Success rate when pattern is applied"
    )
    average_quality_score: float = Field(
        0.0, ge=0.0, le=1.0, description="Average quality score of generated code"
    )

    # Vector embedding (not stored in model, managed by Qdrant)
    embedding_model: str | None = Field(
        None, description="Model used for vector embedding"
    )

    def update_usage(self, success: bool = True, quality_score: float = 0.0) -> None:
        """
        Update pattern usage statistics.

        Args:
            success: Whether pattern application succeeded
            quality_score: Quality score of generated code (0.0-1.0)
        """
        self.usage_count += 1
        self.last_used = datetime.now(timezone.utc)

        # Update success rate (exponential moving average)
        if self.usage_count == 1:
            self.success_rate = 1.0 if success else 0.0
        else:
            alpha = 0.3  # Weight for new observation
            self.success_rate = (
                alpha * (1.0 if success else 0.0) + (1 - alpha) * self.success_rate
            )

        # Update average quality score
        if quality_score > 0:
            if self.average_quality_score == 0:
                self.average_quality_score = quality_score
            else:
                self.average_quality_score = (
                    alpha * quality_score + (1 - alpha) * self.average_quality_score
                )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type.value,
            "pattern_name": self.pattern_name,
            "pattern_description": self.pattern_description,
            "confidence_score": self.confidence_score,
            "pattern_template": self.pattern_template,
            "example_usage": self.example_usage,
            "source_context": self.source_context,
            "reuse_conditions": self.reuse_conditions,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
            "average_quality_score": self.average_quality_score,
            "embedding_model": self.embedding_model,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelCodePattern":
        """Create pattern from dictionary."""
        # Handle datetime fields
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if data.get("last_used") and isinstance(data["last_used"], str):
            data["last_used"] = datetime.fromisoformat(data["last_used"])

        # Handle enum
        if isinstance(data.get("pattern_type"), str):
            data["pattern_type"] = EnumPatternType(data["pattern_type"])

        return cls(**data)

    model_config = {
        "arbitrary_types_allowed": True,
    }


class ModelPatternExtractionResult(BaseModel):
    """
    Result of pattern extraction from generated code.

    Tracks extraction process and quality metrics.
    """

    patterns: list[ModelCodePattern] = Field(
        default_factory=list, description="Extracted patterns"
    )
    extraction_time_ms: int = Field(..., ge=0, description="Time taken to extract")
    source_file: str | None = Field(None, description="Source file analyzed")
    source_context: dict[str, Any] = Field(
        default_factory=dict, description="Context during extraction"
    )
    extraction_method: str = Field(
        ..., description="Method used for extraction (AST, regex, etc.)"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @property
    def pattern_count(self) -> int:
        """Get count of extracted patterns."""
        return len(self.patterns)

    @property
    def high_confidence_patterns(self) -> list[ModelCodePattern]:
        """Get patterns with confidence >= 0.7."""
        return [p for p in self.patterns if p.confidence_score >= 0.7]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "patterns": [p.to_dict() for p in self.patterns],
            "pattern_count": self.pattern_count,
            "high_confidence_patterns_count": len(self.high_confidence_patterns),
            "extraction_time_ms": self.extraction_time_ms,
            "source_file": self.source_file,
            "source_context": self.source_context,
            "extraction_method": self.extraction_method,
            "metadata": self.metadata,
        }


class ModelPatternMatch(BaseModel):
    """
    Pattern similarity match result from vector search.

    Returned by pattern storage when querying for similar patterns.
    """

    pattern: ModelCodePattern = Field(..., description="Matched pattern")
    similarity_score: float = Field(
        ..., ge=0.0, le=1.0, description="Similarity score (0.0-1.0)"
    )
    match_reason: str = Field(..., min_length=1, description="Why this pattern matched")
    applicable: bool = Field(
        True, description="Whether pattern is applicable in current context"
    )

    @property
    def is_high_confidence(self) -> bool:
        """Check if match has high confidence (>= 0.7)."""
        return self.similarity_score >= 0.7

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "pattern": self.pattern.to_dict(),
            "similarity_score": self.similarity_score,
            "match_reason": self.match_reason,
            "applicable": self.applicable,
            "is_high_confidence": self.is_high_confidence,
        }

    model_config = {
        "arbitrary_types_allowed": True,
    }
