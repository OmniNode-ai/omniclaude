#!/usr/bin/env python3
"""
Event Memory Store - Phase 1.2

Event-sourcing memory system for workflow tracking and pattern discovery.

Usage:
    from lib.memory import EventStore, EventAnalytics, WorkflowEvent, EventType

    # Initialize store
    store = EventStore(storage_path=Path("~/.claude/hooks/data/events.db"))

    # Record workflow events
    event = WorkflowEvent.create(
        correlation_id="workflow-123",
        event_type=EventType.INTENT_DETECTED,
        tool_name="Write",
        file_path="/path/to/file.py",
        content="code content here",
        intent=intent_context
    )
    store.record_event(event)

    # Retrieve workflow
    workflow = store.get_workflow("workflow-123")

    # Find similar successful patterns
    similar = store.find_similar_successes(event, limit=5)

    # Analytics
    analytics = EventAnalytics(store)
    metrics = analytics.get_workflow_metrics(days=7)
    report = analytics.generate_report(days=7)
"""

from .event_analytics import (
    CorrectionEffectiveness,
    EventAnalytics,
    ViolationPattern,
    WorkflowMetrics,
)
from .event_models import (
    AIQuorumScore,
    Correction,
    EventType,
    IntentContextData,
    Violation,
    WorkflowEvent,
    WorkflowSummary,
)
from .event_store import EventStore


__all__ = [
    # Enums
    "EventType",
    # Models
    "WorkflowEvent",
    "Violation",
    "Correction",
    "AIQuorumScore",
    "IntentContextData",
    "WorkflowSummary",
    # Storage
    "EventStore",
    # Analytics
    "EventAnalytics",
    "CorrectionEffectiveness",
    "ViolationPattern",
    "WorkflowMetrics",
]

__version__ = "1.2.0"
