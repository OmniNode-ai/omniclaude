#!/usr/bin/env python3
"""
Event Memory Store Demo - Phase 1.2

Demonstrates complete workflow tracking from intent detection
through validation, correction, and final outcome.

Run: python examples/event_memory_demo.py
"""

# Add parent directory to path for imports
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.memory import (
    AIQuorumScore,
    Correction,
    EventAnalytics,
    EventStore,
    EventType,
    IntentContextData,
    Violation,
    WorkflowEvent,
)


def demo_complete_workflow():
    """
    Demonstrate tracking a complete workflow with event-sourcing.
    """
    print("=" * 80)
    print("Event Memory Store Demo - Phase 1.2")
    print("=" * 80)
    print()

    # Initialize event store
    db_path = Path.home() / ".claude/hooks/data/demo_events.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    store = EventStore(
        storage_path=db_path,
        qdrant_url="http://localhost:6333",
        ollama_url="http://192.168.86.200:11434",
    )

    print(f"✅ Event Store initialized: {db_path}")
    print()

    # Create workflow context
    correlation_id = str(uuid.uuid4())
    file_path = "/example/user_service.py"
    print(f"🔄 Starting Workflow: {correlation_id[:8]}...")
    print(f"📄 File: {file_path}")
    print()

    # Event 1: Intent Detected
    print("1️⃣  INTENT DETECTED")
    intent = IntentContextData(
        primary_intent="api_design",
        confidence=0.92,
        suggested_agents=["agent-api-architect", "agent-python-fastapi-expert"],
        validators=["api_compliance_validator", "parameter_validator"],
        onex_rules=["api_naming", "response_structure"],
        secondary_intents=["file_modification"],
    )

    event1 = WorkflowEvent.create(
        correlation_id=correlation_id,
        event_type=EventType.INTENT_DETECTED,
        tool_name="Write",
        file_path=file_path,
        content="def GetUser(): pass",
        intent=intent,
        iteration_number=1,
    )
    store.record_event(event1)
    print(f"   Intent: {intent.primary_intent} (confidence: {intent.confidence})")
    print(f"   Agents: {', '.join(intent.suggested_agents)}")
    print(f"   ONEX Rules: {', '.join(intent.onex_rules)}")
    print()

    # Event 2: Validation Failed
    print("2️⃣  VALIDATION FAILED")
    violations = [
        Violation(
            rule="api_naming",
            severity="error",
            message="API endpoint function should use snake_case",
            line_number=1,
            suggested_fix="Rename GetUser to get_user",
        ),
        Violation(
            rule="missing_docstring",
            severity="warning",
            message="API function missing docstring",
            line_number=1,
            suggested_fix="Add docstring describing endpoint",
        ),
    ]

    event2 = WorkflowEvent.create(
        correlation_id=correlation_id,
        event_type=EventType.VALIDATION_FAILED,
        tool_name="Write",
        file_path=file_path,
        content="def GetUser(): pass",
        violations=violations,
        success=False,
        iteration_number=1,
        parent_event_id=event1.event_id,
    )
    store.record_event(event2)
    print(f"   Violations Found: {len(violations)}")
    for v in violations:
        print(f"   - [{v.severity.upper()}] {v.rule}: {v.message}")
    print()

    # Event 3: Correction Generated
    print("3️⃣  CORRECTION GENERATED")
    corrections = [
        Correction(
            source="rag",
            confidence=0.85,
            original_content="def GetUser():",
            corrected_content="def get_user():",
            reasoning="Convert function name to snake_case per ONEX naming conventions",
            applied=True,
        ),
        Correction(
            source="quorum",
            confidence=0.88,
            original_content="def get_user():",
            corrected_content='def get_user():\n    """Get user by ID from database."""',
            reasoning="Add descriptive docstring for API endpoint documentation",
            applied=True,
        ),
    ]

    quorum_score = AIQuorumScore(
        consensus_score=0.86,
        model_votes={"flash": 0.82, "codestral": 0.90, "pro": 0.86},
        decision="auto_apply",
        reasoning="High confidence consensus across all models - safe to auto-apply",
    )

    event3 = WorkflowEvent.create(
        correlation_id=correlation_id,
        event_type=EventType.CORRECTION_GENERATED,
        tool_name="Write",
        file_path=file_path,
        content="def GetUser(): pass",
        corrections=corrections,
        scores=quorum_score,
        iteration_number=1,
        parent_event_id=event2.event_id,
    )
    store.record_event(event3)
    print(f"   Corrections Generated: {len(corrections)}")
    for c in corrections:
        print(f"   - {c.source.upper()} (confidence: {c.confidence:.2f})")
        print(f"     {c.reasoning}")
    print(
        f"   Quorum Decision: {quorum_score.decision} (consensus: {quorum_score.consensus_score:.2f})"
    )
    print()

    # Event 4: Correction Applied
    print("4️⃣  CORRECTION APPLIED")
    corrected_content = (
        'def get_user():\n    """Get user by ID from database."""\n    pass'
    )

    event4 = WorkflowEvent.create(
        correlation_id=correlation_id,
        event_type=EventType.CORRECTION_APPLIED,
        tool_name="Write",
        file_path=file_path,
        content=corrected_content,
        success=True,
        iteration_number=2,
        parent_event_id=event3.event_id,
    )
    store.record_event(event4)
    print("   Both corrections successfully applied")
    print("   Iteration: 2")
    print()

    # Event 5: Validation Passed
    print("5️⃣  VALIDATION PASSED")
    event5 = WorkflowEvent.create(
        correlation_id=correlation_id,
        event_type=EventType.VALIDATION_PASSED,
        tool_name="Write",
        file_path=file_path,
        content=corrected_content,
        success=True,
        iteration_number=2,
        parent_event_id=event4.event_id,
    )
    store.record_event(event5)
    print("   All validation rules passed ✓")
    print()

    # Event 6: Write Success
    print("6️⃣  WRITE SUCCESS")
    event6 = WorkflowEvent.create(
        correlation_id=correlation_id,
        event_type=EventType.WRITE_SUCCESS,
        tool_name="Write",
        file_path=file_path,
        content=corrected_content,
        success=True,
        iteration_number=2,
        parent_event_id=event5.event_id,
    )
    store.record_event(event6)
    print("   File written successfully ✓")
    print()

    # Demonstrate workflow retrieval
    print("=" * 80)
    print("WORKFLOW RETRIEVAL")
    print("=" * 80)
    print()

    workflow = store.get_workflow(correlation_id)
    print(f"Retrieved workflow: {len(workflow)} events")
    print()

    for i, event in enumerate(workflow, 1):
        print(
            f"{i}. {event.event_type.value:30} [iter: {event.iteration_number}, success: {event.success}]"
        )
    print()

    # Demonstrate analytics
    print("=" * 80)
    print("ANALYTICS & INSIGHTS")
    print("=" * 80)
    print()

    analytics = EventAnalytics(store)

    # Workflow summary
    summary = analytics.create_workflow_summary(correlation_id)
    print("📊 Workflow Summary:")
    print(f"   Duration: {summary.duration_ms:.0f}ms")
    print(f"   Total Events: {summary.total_events}")
    print(f"   Iterations: {summary.iterations}")
    print(f"   Violations: {summary.violations_count}")
    print(f"   Corrections Applied: {summary.corrections_applied}")
    print(f"   Success: {'✅ Yes' if summary.success else '❌ No'}")
    print(f"   Outcome: {summary.final_outcome}")
    print()

    # Overall metrics
    metrics = analytics.get_workflow_metrics(days=7)
    print("📈 Overall Metrics (Last 7 Days):")
    print(f"   Total Workflows: {metrics.total_workflows}")
    print(f"   Success Rate: {metrics.success_rate:.1%}")
    print(f"   Avg Duration: {metrics.avg_duration_ms:.0f}ms")
    print(f"   Avg Iterations: {metrics.avg_iterations:.1f}")
    print(f"   Avg Violations: {metrics.avg_violations:.1f}")
    print()

    # Correction effectiveness
    correction_stats = analytics.get_correction_stats(days=7)
    if correction_stats:
        print("🔧 Correction Effectiveness:")
        for source, stats in correction_stats.items():
            print(f"   {source.upper()}:")
            print(f"     Success Rate: {stats.success_rate:.1%}")
            print(f"     Avg Confidence: {stats.avg_confidence:.2f}")
            print(f"     Avg Iterations: {stats.avg_iterations:.1f}")
        print()

    # Store stats
    stats = store.get_stats()
    print("💾 Storage Statistics:")
    print(f"   Total Events: {stats['total_events']}")
    print(f"   Successful Events: {stats['success_count']}")
    print(f"   Success Rate: {stats['success_rate']:.1%}")
    print(f"   Unique Workflows: {stats['unique_workflows']}")
    print()

    print("=" * 80)
    print("✅ Event Memory Store Demo Complete!")
    print("=" * 80)


if __name__ == "__main__":
    demo_complete_workflow()
