#!/usr/bin/env python3
"""
Event Models for Event-Sourcing Memory Store - Phase 1.2

Defines event types and data structures for tracking complete workflows
from intent detection through validation, correction, and final outcome.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(Enum):
    """
    Workflow event types in chronological order.

    Tracks the full lifecycle:
    1. INTENT_DETECTED - Intent classification completed
    2. VALIDATION_FAILED - Quality violations detected
    3. CORRECTION_GENERATED - RAG/Quorum produced suggestions
    4. CORRECTION_ATTEMPTED - Attempting to apply correction
    5. CORRECTION_APPLIED - Correction successfully applied
    6. VALIDATION_PASSED - No violations after correction
    7. WRITE_SUCCESS - File write completed successfully
    8. WRITE_FAILED - Write operation failed
    """

    INTENT_DETECTED = "intent_detected"
    VALIDATION_FAILED = "validation_failed"
    CORRECTION_GENERATED = "correction_generated"
    CORRECTION_ATTEMPTED = "correction_attempted"
    CORRECTION_APPLIED = "correction_applied"
    VALIDATION_PASSED = "validation_passed"
    WRITE_SUCCESS = "write_success"
    WRITE_FAILED = "write_failed"


@dataclass
class Violation:
    """
    Quality violation detected during validation.

    Attributes:
        rule: Validation rule that was violated
        severity: error, warning, info
        message: Human-readable violation description
        line_number: Line where violation occurred
        suggested_fix: Optional suggested correction
    """

    rule: str
    severity: str
    message: str
    line_number: Optional[int] = None
    suggested_fix: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "line_number": self.line_number,
            "suggested_fix": self.suggested_fix,
        }


@dataclass
class Correction:
    """
    Correction suggestion from RAG or AI Quorum.

    Attributes:
        source: Origin of correction (rag, quorum, validator)
        confidence: Confidence score 0.0-1.0
        original_content: Content before correction
        corrected_content: Content after correction
        reasoning: Why this correction was suggested
        applied: Whether correction was actually applied
    """

    source: str
    confidence: float
    original_content: str
    corrected_content: str
    reasoning: str
    applied: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "source": self.source,
            "confidence": self.confidence,
            "original_content": self.original_content,
            "corrected_content": self.corrected_content,
            "reasoning": self.reasoning,
            "applied": self.applied,
        }


@dataclass
class AIQuorumScore:
    """
    AI Quorum consensus scoring results.

    Attributes:
        consensus_score: Overall consensus 0.0-1.0
        model_votes: Individual model scores
        decision: auto_apply, suggest, or reject
        reasoning: Consensus reasoning
    """

    consensus_score: float
    model_votes: Dict[str, float]
    decision: str  # auto_apply, suggest, reject
    reasoning: str

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "consensus_score": self.consensus_score,
            "model_votes": self.model_votes,
            "decision": self.decision,
            "reasoning": self.reasoning,
        }


@dataclass
class IntentContextData:
    """
    Intent classification context (from Phase 1.1).

    Simplified version for event storage.
    """

    primary_intent: str
    confidence: float
    suggested_agents: List[str]
    validators: List[str]
    onex_rules: List[str]
    secondary_intents: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "primary_intent": self.primary_intent,
            "confidence": self.confidence,
            "suggested_agents": self.suggested_agents,
            "validators": self.validators,
            "onex_rules": self.onex_rules,
            "secondary_intents": self.secondary_intents,
        }

    @classmethod
    def from_intent_context(cls, intent_context) -> "IntentContextData":
        """Create from IntentContext object."""
        return cls(
            primary_intent=intent_context.primary_intent,
            confidence=intent_context.confidence,
            suggested_agents=intent_context.suggested_agents,
            validators=intent_context.validators,
            onex_rules=intent_context.onex_rules,
            secondary_intents=intent_context.secondary_intents,
        )


@dataclass
class WorkflowEvent:
    """
    Single event in a workflow execution.

    Represents one step in the full workflow from intent → validation → correction → outcome.
    All events with the same correlation_id are part of the same workflow execution.

    Attributes:
        event_id: Unique identifier for this specific event
        correlation_id: Links all events in the same workflow
        timestamp: When the event occurred
        event_type: Type of event (see EventType enum)
        tool_name: Claude Code tool that triggered workflow (Write, Edit, etc)
        file_path: File being operated on
        content_hash: SHA-256 hash of content (tracks changes)

        # Event-specific optional data
        intent: Intent classification results (INTENT_DETECTED events)
        violations: Quality violations (VALIDATION_FAILED events)
        corrections: Correction suggestions (CORRECTION_GENERATED events)
        scores: AI Quorum scoring (CORRECTION_GENERATED events)

        # Outcome tracking
        success: Whether the event/workflow succeeded
        iteration_number: Track multiple correction attempts (1, 2, 3...)
        parent_event_id: Link to previous event in workflow
        metadata: Flexible additional context
    """

    event_id: str
    correlation_id: str
    timestamp: datetime
    event_type: EventType
    tool_name: str
    file_path: str
    content_hash: str

    # Optional event-specific data
    intent: Optional[IntentContextData] = None
    violations: Optional[List[Violation]] = None
    corrections: Optional[List[Correction]] = None
    scores: Optional[AIQuorumScore] = None

    # Outcome tracking
    success: Optional[bool] = None
    iteration_number: int = 1
    parent_event_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        correlation_id: str,
        event_type: EventType,
        tool_name: str,
        file_path: str,
        content: str,
        **kwargs,
    ) -> "WorkflowEvent":
        """
        Factory method to create a new event.

        Args:
            correlation_id: Workflow correlation ID
            event_type: Type of event
            tool_name: Claude Code tool name
            file_path: Target file path
            content: File content for hashing
            **kwargs: Additional event-specific attributes

        Returns:
            New WorkflowEvent instance
        """
        return cls(
            event_id=str(uuid.uuid4()),
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            tool_name=tool_name,
            file_path=file_path,
            content_hash=cls._hash_content(content),
            **kwargs,
        )

    @staticmethod
    def _hash_content(content: str) -> str:
        """Generate SHA-256 hash of content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        """
        Convert to dictionary for serialization.

        Returns:
            Dict representation suitable for JSON/storage
        """
        data = {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "tool_name": self.tool_name,
            "file_path": self.file_path,
            "content_hash": self.content_hash,
            "success": self.success,
            "iteration_number": self.iteration_number,
            "parent_event_id": self.parent_event_id,
            "metadata": self.metadata,
        }

        # Add optional fields if present
        if self.intent:
            data["intent"] = self.intent.to_dict()

        if self.violations:
            data["violations"] = [v.to_dict() for v in self.violations]

        if self.corrections:
            data["corrections"] = [c.to_dict() for c in self.corrections]

        if self.scores:
            data["scores"] = self.scores.to_dict()

        return data

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowEvent":
        """
        Create event from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            WorkflowEvent instance
        """
        # Convert timestamp string back to datetime
        timestamp = datetime.fromisoformat(data["timestamp"])

        # Convert event_type string back to enum
        event_type = EventType(data["event_type"])

        # Reconstruct optional complex objects
        intent = None
        if data.get("intent"):
            intent = IntentContextData(**data["intent"])

        violations = None
        if data.get("violations"):
            violations = [Violation(**v) for v in data["violations"]]

        corrections = None
        if data.get("corrections"):
            corrections = [Correction(**c) for c in data["corrections"]]

        scores = None
        if data.get("scores"):
            scores = AIQuorumScore(**data["scores"])

        return cls(
            event_id=data["event_id"],
            correlation_id=data["correlation_id"],
            timestamp=timestamp,
            event_type=event_type,
            tool_name=data["tool_name"],
            file_path=data["file_path"],
            content_hash=data["content_hash"],
            intent=intent,
            violations=violations,
            corrections=corrections,
            scores=scores,
            success=data.get("success"),
            iteration_number=data.get("iteration_number", 1),
            parent_event_id=data.get("parent_event_id"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class WorkflowSummary:
    """
    Summary of a complete workflow execution.

    Aggregates all events with the same correlation_id to provide
    a high-level view of the workflow outcome.

    Attributes:
        correlation_id: Workflow identifier
        start_time: First event timestamp
        end_time: Last event timestamp
        duration_ms: Total workflow duration
        tool_name: Claude Code tool used
        file_path: Target file
        intent_category: Primary intent classification
        total_events: Number of events in workflow
        success: Overall workflow success
        iterations: Number of correction attempts
        violations_count: Total violations detected
        corrections_applied: Number of corrections applied
        final_outcome: Description of final result
    """

    correlation_id: str
    start_time: datetime
    end_time: datetime
    duration_ms: float
    tool_name: str
    file_path: str
    intent_category: str
    total_events: int
    success: bool
    iterations: int
    violations_count: int
    corrections_applied: int
    final_outcome: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "correlation_id": self.correlation_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_ms": self.duration_ms,
            "tool_name": self.tool_name,
            "file_path": self.file_path,
            "intent_category": self.intent_category,
            "total_events": self.total_events,
            "success": self.success,
            "iterations": self.iterations,
            "violations_count": self.violations_count,
            "corrections_applied": self.corrections_applied,
            "final_outcome": self.final_outcome,
            "metadata": self.metadata,
        }
