#!/usr/bin/env python3
"""
Unit tests for Event Memory Store - Phase 1.2

Tests complete workflow tracking from intent detection through
validation, correction, and final outcome.

Run with: pytest tests/test_event_memory_store.py -v
"""

import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
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


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def event_store(temp_db):
    """Create EventStore instance for testing."""
    store = EventStore(
        storage_path=temp_db,
        qdrant_url="http://localhost:6333",
        ollama_url="http://192.168.86.200:11434",
        retention_days=90,
    )
    return store


@pytest.fixture
def sample_intent():
    """Create sample intent context."""
    return IntentContextData(
        primary_intent="file_modification",
        confidence=0.85,
        suggested_agents=["agent-code-quality-analyzer"],
        validators=["naming_validator"],
        onex_rules=["naming_conventions"],
        secondary_intents=[],
    )


@pytest.fixture
def sample_violations():
    """Create sample violations."""
    return [
        Violation(
            rule="naming_convention",
            severity="error",
            message="Function name should be snake_case",
            line_number=10,
            suggested_fix="Rename myFunction to my_function",
        ),
        Violation(
            rule="missing_docstring",
            severity="warning",
            message="Function missing docstring",
            line_number=10,
        ),
    ]


@pytest.fixture
def sample_corrections():
    """Create sample corrections."""
    return [
        Correction(
            source="rag",
            confidence=0.82,
            original_content="def myFunction():",
            corrected_content="def my_function():",
            reasoning="Convert to snake_case naming",
            applied=True,
        ),
        Correction(
            source="quorum",
            confidence=0.75,
            original_content="def my_function():",
            corrected_content='def my_function():\n    """Function description."""',
            reasoning="Add missing docstring",
            applied=True,
        ),
    ]


@pytest.fixture
def sample_quorum_score():
    """Create sample AI quorum score."""
    return AIQuorumScore(
        consensus_score=0.85,
        model_votes={"flash": 0.80, "codestral": 0.90, "pro": 0.85},
        decision="auto_apply",
        reasoning="High confidence consensus to apply correction",
    )


class TestEventModels:
    """Test event data models."""

    def test_workflow_event_creation(self, sample_intent):
        """Test creating a workflow event."""
        correlation_id = str(uuid.uuid4())

        event = WorkflowEvent.create(
            correlation_id=correlation_id,
            event_type=EventType.INTENT_DETECTED,
            tool_name="Write",
            file_path="/test/file.py",
            content="test content",
            intent=sample_intent,
        )

        assert event.correlation_id == correlation_id
        assert event.event_type == EventType.INTENT_DETECTED
        assert event.tool_name == "Write"
        assert event.intent == sample_intent
        assert len(event.content_hash) == 16  # SHA-256 truncated

    def test_event_serialization(self, sample_intent, sample_violations):
        """Test event to_dict and from_dict."""
        event = WorkflowEvent.create(
            correlation_id="test-123",
            event_type=EventType.VALIDATION_FAILED,
            tool_name="Edit",
            file_path="/test/file.py",
            content="content",
            intent=sample_intent,
            violations=sample_violations,
            success=False,
        )

        # Serialize
        event_dict = event.to_dict()

        # Deserialize
        restored_event = WorkflowEvent.from_dict(event_dict)

        assert restored_event.event_id == event.event_id
        assert restored_event.event_type == event.event_type
        assert restored_event.intent.primary_intent == event.intent.primary_intent
        assert len(restored_event.violations) == len(event.violations)


class TestEventStore:
    """Test event storage and retrieval."""

    def test_event_store_initialization(self, event_store):
        """Test event store initializes correctly."""
        assert event_store.storage_path.exists()

        # Check stats on empty store
        stats = event_store.get_stats()
        assert stats["total_events"] == 0
        assert stats["unique_workflows"] == 0

    def test_record_single_event(self, event_store, sample_intent):
        """Test recording a single event."""
        event = WorkflowEvent.create(
            correlation_id="workflow-001",
            event_type=EventType.INTENT_DETECTED,
            tool_name="Write",
            file_path="/test/file.py",
            content="test content",
            intent=sample_intent,
        )

        # Record event
        success = event_store.record_event(event)
        assert success

        # Verify stored
        stats = event_store.get_stats()
        assert stats["total_events"] == 1

    def test_complete_workflow_tracking(
        self,
        event_store,
        sample_intent,
        sample_violations,
        sample_corrections,
        sample_quorum_score,
    ):
        """Test tracking a complete workflow from start to finish."""
        correlation_id = str(uuid.uuid4())
        file_path = "/test/example.py"
        content = "def myFunction(): pass"

        # Event 1: Intent Detected
        event1 = WorkflowEvent.create(
            correlation_id=correlation_id,
            event_type=EventType.INTENT_DETECTED,
            tool_name="Write",
            file_path=file_path,
            content=content,
            intent=sample_intent,
            iteration_number=1,
        )
        event_store.record_event(event1)

        # Event 2: Validation Failed
        event2 = WorkflowEvent.create(
            correlation_id=correlation_id,
            event_type=EventType.VALIDATION_FAILED,
            tool_name="Write",
            file_path=file_path,
            content=content,
            violations=sample_violations,
            success=False,
            iteration_number=1,
            parent_event_id=event1.event_id,
        )
        event_store.record_event(event2)

        # Event 3: Correction Generated
        event3 = WorkflowEvent.create(
            correlation_id=correlation_id,
            event_type=EventType.CORRECTION_GENERATED,
            tool_name="Write",
            file_path=file_path,
            content=content,
            corrections=sample_corrections,
            scores=sample_quorum_score,
            iteration_number=1,
            parent_event_id=event2.event_id,
        )
        event_store.record_event(event3)

        # Event 4: Correction Applied
        corrected_content = "def my_function():\n    pass"
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
        event_store.record_event(event4)

        # Event 5: Validation Passed
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
        event_store.record_event(event5)

        # Event 6: Write Success
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
        event_store.record_event(event6)

        # Verify complete workflow
        workflow = event_store.get_workflow(correlation_id)
        assert len(workflow) == 6

        # Verify event order
        assert workflow[0].event_type == EventType.INTENT_DETECTED
        assert workflow[1].event_type == EventType.VALIDATION_FAILED
        assert workflow[2].event_type == EventType.CORRECTION_GENERATED
        assert workflow[3].event_type == EventType.CORRECTION_APPLIED
        assert workflow[4].event_type == EventType.VALIDATION_PASSED
        assert workflow[5].event_type == EventType.WRITE_SUCCESS

        # Verify final success
        assert workflow[-1].success is True

        # Verify iterations tracked
        assert workflow[0].iteration_number == 1
        assert workflow[-1].iteration_number == 2

        # Verify parent linking
        assert workflow[1].parent_event_id == workflow[0].event_id
        assert workflow[5].parent_event_id == workflow[4].event_id

    def test_get_workflow_retrieval(self, event_store, sample_intent):
        """Test retrieving workflow by correlation ID."""
        correlation_id = "workflow-retrieve-test"

        # Create multiple events for same workflow
        for i in range(3):
            event = WorkflowEvent.create(
                correlation_id=correlation_id,
                event_type=EventType.INTENT_DETECTED,
                tool_name="Write",
                file_path=f"/test/file{i}.py",
                content=f"content {i}",
                intent=sample_intent,
            )
            event_store.record_event(event)

        # Retrieve workflow
        workflow = event_store.get_workflow(correlation_id)
        assert len(workflow) == 3

        # Verify chronological order
        for i in range(len(workflow) - 1):
            assert workflow[i].timestamp <= workflow[i + 1].timestamp

    def test_recent_workflows(self, event_store, sample_intent):
        """Test getting recent workflow correlation IDs."""
        # Create workflows
        for i in range(5):
            correlation_id = f"workflow-{i}"
            event = WorkflowEvent.create(
                correlation_id=correlation_id,
                event_type=EventType.WRITE_SUCCESS,
                tool_name="Write",
                file_path=f"/test/file{i}.py",
                content=f"content {i}",
                intent=sample_intent,
                success=True,
            )
            event_store.record_event(event)

        # Get recent workflows
        recent = event_store.get_recent_workflows(days=7)
        assert len(recent) >= 5

        # Get successful only
        successful = event_store.get_recent_workflows(days=7, success_only=True)
        assert len(successful) >= 5

    def test_event_cleanup(self, event_store, sample_intent):
        """Test cleanup of old events."""
        # Create old event (91 days ago)
        old_event = WorkflowEvent.create(
            correlation_id="old-workflow",
            event_type=EventType.INTENT_DETECTED,
            tool_name="Write",
            file_path="/test/old.py",
            content="old content",
            intent=sample_intent,
        )
        # Manually set old timestamp
        old_event.timestamp = datetime.utcnow() - timedelta(days=91)
        event_store.record_event(old_event)

        # Create recent event
        recent_event = WorkflowEvent.create(
            correlation_id="recent-workflow",
            event_type=EventType.INTENT_DETECTED,
            tool_name="Write",
            file_path="/test/recent.py",
            content="recent content",
            intent=sample_intent,
        )
        event_store.record_event(recent_event)

        # Should have 2 events
        stats_before = event_store.get_stats()
        assert stats_before["total_events"] == 2

        # Cleanup old events
        event_store.cleanup_old_events()

        # Should have 1 event remaining
        stats_after = event_store.get_stats()
        assert stats_after["total_events"] == 1


class TestEventAnalytics:
    """Test event analytics and pattern discovery."""

    def test_analytics_initialization(self, event_store):
        """Test analytics engine initialization."""
        analytics = EventAnalytics(event_store)
        assert analytics.event_store == event_store

    def test_workflow_metrics_empty(self, event_store):
        """Test metrics on empty store."""
        analytics = EventAnalytics(event_store)
        metrics = analytics.get_workflow_metrics(days=7)

        assert metrics.total_workflows == 0
        assert metrics.success_rate == 0.0

    def test_workflow_metrics_with_data(
        self, event_store, sample_intent, sample_violations, sample_corrections
    ):
        """Test workflow metrics calculation with real data."""
        # Create successful workflow
        correlation_id = str(uuid.uuid4())

        events = [
            (EventType.INTENT_DETECTED, sample_intent, None, None, None),
            (EventType.VALIDATION_FAILED, None, sample_violations, None, False),
            (EventType.CORRECTION_GENERATED, None, None, sample_corrections, None),
            (EventType.CORRECTION_APPLIED, None, None, None, True),
            (EventType.WRITE_SUCCESS, None, None, None, True),
        ]

        for i, (event_type, intent, violations, corrections, success) in enumerate(
            events
        ):
            event = WorkflowEvent.create(
                correlation_id=correlation_id,
                event_type=event_type,
                tool_name="Write",
                file_path="/test/metrics.py",
                content=f"content {i}",
                intent=intent,
                violations=violations,
                corrections=corrections,
                success=success,
                iteration_number=1 if i < 3 else 2,
            )
            event_store.record_event(event)

        # Get metrics
        analytics = EventAnalytics(event_store)
        metrics = analytics.get_workflow_metrics(days=7)

        assert metrics.total_workflows >= 1
        assert metrics.success_rate > 0
        assert metrics.avg_violations >= 2  # We had 2 violations
        assert metrics.most_common_intent == "file_modification"

    def test_correction_effectiveness(
        self, event_store, sample_corrections, sample_quorum_score
    ):
        """Test correction effectiveness analysis."""
        # Create workflow with corrections
        correlation_id = str(uuid.uuid4())

        event = WorkflowEvent.create(
            correlation_id=correlation_id,
            event_type=EventType.CORRECTION_GENERATED,
            tool_name="Write",
            file_path="/test/correction.py",
            content="content",
            corrections=sample_corrections,
            scores=sample_quorum_score,
        )
        event_store.record_event(event)

        # Mark workflow as successful
        success_event = WorkflowEvent.create(
            correlation_id=correlation_id,
            event_type=EventType.WRITE_SUCCESS,
            tool_name="Write",
            file_path="/test/correction.py",
            content="corrected content",
            success=True,
        )
        event_store.record_event(success_event)

        # Analyze
        analytics = EventAnalytics(event_store)
        stats = analytics.get_correction_stats(days=7)

        # Should have stats for both correction sources
        assert "rag" in stats or "quorum" in stats
        if "rag" in stats:
            assert stats["rag"].total_attempts >= 1
            assert stats["rag"].success_rate > 0

    def test_violation_patterns(self, event_store, sample_violations):
        """Test violation pattern detection."""
        # Create multiple workflows with similar violations
        for i in range(3):
            correlation_id = f"violation-workflow-{i}"
            event = WorkflowEvent.create(
                correlation_id=correlation_id,
                event_type=EventType.VALIDATION_FAILED,
                tool_name="Write",
                file_path=f"/test/file{i}.py",
                content=f"content {i}",
                violations=sample_violations,
                success=False,
            )
            event_store.record_event(event)

        # Analyze patterns
        analytics = EventAnalytics(event_store)
        patterns = analytics.find_violation_patterns(days=7, min_occurrences=2)

        # Should find the naming_convention pattern
        pattern_rules = [p.rule for p in patterns]
        assert "naming_convention" in pattern_rules

        # Check pattern details
        naming_pattern = next(p for p in patterns if p.rule == "naming_convention")
        assert naming_pattern.occurrences >= 3

    def test_workflow_summary(self, event_store, sample_intent):
        """Test creating workflow summary."""
        correlation_id = str(uuid.uuid4())

        # Create simple workflow
        events = [
            EventType.INTENT_DETECTED,
            EventType.VALIDATION_PASSED,
            EventType.WRITE_SUCCESS,
        ]

        for event_type in events:
            event = WorkflowEvent.create(
                correlation_id=correlation_id,
                event_type=event_type,
                tool_name="Write",
                file_path="/test/summary.py",
                content="content",
                intent=(
                    sample_intent if event_type == EventType.INTENT_DETECTED else None
                ),
                success=event_type == EventType.WRITE_SUCCESS,
            )
            event_store.record_event(event)

        # Create summary
        analytics = EventAnalytics(event_store)
        summary = analytics.create_workflow_summary(correlation_id)

        assert summary is not None
        assert summary.correlation_id == correlation_id
        assert summary.success is True
        assert summary.total_events == 3
        assert summary.intent_category == "file_modification"

    def test_improvement_opportunities(self, event_store):
        """Test identifying improvement opportunities."""
        analytics = EventAnalytics(event_store)
        opportunities = analytics.find_improvement_opportunities(days=7)

        # Should return dict (may be empty on new store)
        assert isinstance(opportunities, dict)

    def test_generate_report(self, event_store, sample_intent):
        """Test generating analytics report."""
        # Add some sample data
        event = WorkflowEvent.create(
            correlation_id="report-test",
            event_type=EventType.WRITE_SUCCESS,
            tool_name="Write",
            file_path="/test/report.py",
            content="content",
            intent=sample_intent,
            success=True,
        )
        event_store.record_event(event)

        # Generate report
        analytics = EventAnalytics(event_store)
        report = analytics.generate_report(days=7)

        # Verify report content
        assert "Event Memory Analytics Report" in report
        assert "WORKFLOW METRICS" in report
        assert "CORRECTION EFFECTIVENESS" in report
        assert "VIOLATION PATTERNS" in report
        assert "IMPROVEMENT OPPORTUNITIES" in report


class TestIntegrationScenarios:
    """Test complete integration scenarios."""

    def test_multiple_correction_iterations(
        self, event_store, sample_intent, sample_violations
    ):
        """Test workflow with multiple correction attempts."""
        correlation_id = str(uuid.uuid4())
        file_path = "/test/iterations.py"

        # Iteration 1: Failed
        for event_type in [
            EventType.INTENT_DETECTED,
            EventType.VALIDATION_FAILED,
            EventType.CORRECTION_GENERATED,
            EventType.CORRECTION_ATTEMPTED,
            EventType.VALIDATION_FAILED,  # Still failing
        ]:
            event = WorkflowEvent.create(
                correlation_id=correlation_id,
                event_type=event_type,
                tool_name="Write",
                file_path=file_path,
                content="iteration 1 content",
                intent=(
                    sample_intent if event_type == EventType.INTENT_DETECTED else None
                ),
                violations=(
                    sample_violations
                    if event_type == EventType.VALIDATION_FAILED
                    else None
                ),
                iteration_number=1,
            )
            event_store.record_event(event)

        # Iteration 2: Success
        for event_type in [
            EventType.CORRECTION_GENERATED,
            EventType.CORRECTION_APPLIED,
            EventType.VALIDATION_PASSED,
            EventType.WRITE_SUCCESS,
        ]:
            event = WorkflowEvent.create(
                correlation_id=correlation_id,
                event_type=event_type,
                tool_name="Write",
                file_path=file_path,
                content="iteration 2 content",
                success=event_type == EventType.WRITE_SUCCESS,
                iteration_number=2,
            )
            event_store.record_event(event)

        # Verify workflow
        workflow = event_store.get_workflow(correlation_id)
        assert len(workflow) == 9  # 5 + 4 events

        # Verify max iteration
        max_iteration = max(e.iteration_number for e in workflow)
        assert max_iteration == 2

        # Create summary
        analytics = EventAnalytics(event_store)
        summary = analytics.create_workflow_summary(correlation_id)
        assert summary.iterations == 2
        assert summary.success is True

    def test_performance_benchmarks(self, event_store, sample_intent):
        """Test that operations meet performance targets."""
        import time

        correlation_id = str(uuid.uuid4())

        # Test: Record event <100ms
        event = WorkflowEvent.create(
            correlation_id=correlation_id,
            event_type=EventType.INTENT_DETECTED,
            tool_name="Write",
            file_path="/test/perf.py",
            content="performance test content",
            intent=sample_intent,
        )

        start = time.time()
        event_store.record_event(event)
        record_time = (time.time() - start) * 1000

        assert record_time < 100, f"Record took {record_time:.1f}ms, target <100ms"

        # Test: Get workflow <50ms
        start = time.time()
        workflow = event_store.get_workflow(correlation_id)
        retrieve_time = (time.time() - start) * 1000

        assert retrieve_time < 50, f"Retrieve took {retrieve_time:.1f}ms, target <50ms"
        assert len(workflow) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
