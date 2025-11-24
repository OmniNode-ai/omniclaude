"""
Integration tests for tracing models with PostgreSQL client.

Tests the complete workflow of creating, storing, and retrieving
execution traces and hook executions using Pydantic models.
"""

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4


# Test imports
try:
    import sys
    from pathlib import Path

    from .models import (
        HookMetadata,
        TraceContext,
        create_new_hook_execution,
        create_new_trace,
        parse_trace_from_row,
    )
    from .postgres_client import PostgresTracingClient

    IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"Import error: {e}")
    IMPORTS_AVAILABLE = False


async def test_basic_model_creation():
    """Test basic model creation and validation"""
    print("\n=== Test 1: Basic Model Creation ===")

    # Create a new trace
    session_id = uuid4()
    trace = create_new_trace(
        source="test_suite",
        session_id=session_id,
        prompt_text="Test prompt for validation",
        tags=["test", "validation", "integration"],
    )

    assert trace.status == "in_progress"
    assert trace.success is None
    assert trace.tags == ["test", "validation", "integration"]
    print(f"✓ Created trace with correlation_id: {trace.correlation_id}")

    # Create a hook execution
    hook = create_new_hook_execution(
        trace_id=trace.correlation_id,
        hook_type="PreToolUse",
        hook_name="test_hook",
        execution_order=1,
        tool_name="Write",
        file_path="/test/file.py",
    )

    assert hook.hook_type == "PreToolUse"
    assert hook.execution_order == 1
    assert hook.status == "in_progress"
    print(f"✓ Created hook execution: {hook.hook_name}")

    # Test completion
    trace.mark_completed(success=True)
    assert trace.status == "completed"
    assert trace.success is True
    assert trace.completed_at is not None
    print(f"✓ Marked trace as completed, duration: {trace.duration_ms}ms")

    hook.mark_completed(success=True)
    assert hook.status == "completed"
    print(f"✓ Marked hook as completed, duration: {hook.duration_ms}ms")


async def test_model_validation():
    """Test model validation and error handling"""
    print("\n=== Test 2: Model Validation ===")

    # Test valid status values
    trace = create_new_trace(source="test", session_id=uuid4())
    trace.status = "in_progress"
    trace.status = "completed"
    trace.status = "failed"
    trace.status = "cancelled"
    print("✓ All valid statuses accepted")

    # Test invalid status (should raise ValidationError)
    try:
        trace.status = "invalid_status"
        print("✗ Invalid status should have raised ValidationError")
    except ValueError as e:
        print(f"✓ Invalid status rejected: {e}")

    # Test valid hook types
    hook = create_new_hook_execution(
        trace_id=trace.correlation_id,
        hook_type="PreToolUse",
        hook_name="test",
        execution_order=1,
    )

    valid_types = [
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "Stop",
        "SessionStart",
        "SessionEnd",
    ]
    for hook_type in valid_types:
        hook.hook_type = hook_type
    print(f"✓ All valid hook types accepted ({len(valid_types)} types)")

    # Test invalid hook type
    try:
        hook.hook_type = "InvalidHookType"
        print("✗ Invalid hook type should have raised ValidationError")
    except ValueError as e:
        print(f"✓ Invalid hook type rejected: {e}")


async def test_serialization():
    """Test serialization and deserialization"""
    print("\n=== Test 3: Serialization ===")

    # Create trace with all fields
    trace = create_new_trace(
        source="test",
        session_id=uuid4(),
        prompt_text="Test prompt",
        user_id="test_user_123",
        context={"env": "test", "version": "1.0"},
        tags=["test", "serialization"],
    )

    # Test to_db_dict
    db_dict = trace.to_db_dict()
    assert isinstance(db_dict, dict)
    assert "correlation_id" in db_dict
    assert "session_id" in db_dict
    print(f"✓ Serialized trace to DB dict ({len(db_dict)} fields)")

    # Test model_dump
    json_dict = trace.model_dump()
    assert isinstance(json_dict, dict)
    print(f"✓ Serialized trace to JSON dict ({len(json_dict)} fields)")

    # Test parsing from row (simulating database return)
    row_data = {
        "id": uuid4(),
        "correlation_id": uuid4(),
        "root_id": uuid4(),
        "parent_id": None,
        "session_id": uuid4(),
        "user_id": "test_user",
        "source": "test",
        "prompt_text": "Test",
        "started_at": datetime.now(timezone.utc),
        "completed_at": None,
        "duration_ms": None,
        "status": "in_progress",
        "success": None,
        "error_message": None,
        "error_type": None,
        "context": {"test": "data"},
        "tags": ["test"],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    parsed_trace = parse_trace_from_row(row_data)
    assert parsed_trace.status == "in_progress"
    assert parsed_trace.tags == ["test"]
    print("✓ Parsed trace from database row")


async def test_trace_context():
    """Test TraceContext helper model"""
    print("\n=== Test 4: TraceContext ===")

    trace = create_new_trace(source="test", session_id=uuid4())
    context = TraceContext.from_trace(trace)

    assert context.correlation_id == trace.correlation_id
    assert context.root_id == trace.root_id
    assert context.session_id == trace.session_id
    print("✓ Created TraceContext from ExecutionTrace")

    # Test to_dict for headers
    context_dict = context.to_dict()
    assert isinstance(context_dict["correlation_id"], str)
    assert isinstance(context_dict["session_id"], str)
    print("✓ Converted TraceContext to dict with string UUIDs")


async def test_hook_metadata():
    """Test HookMetadata helper model"""
    print("\n=== Test 5: HookMetadata ===")

    metadata = HookMetadata(
        violations_found=5,
        corrections_applied=3,
        quality_score=0.87,
        rag_matches=10,
        rag_confidence=0.92,
        processing_time_ms=245,
    )

    assert metadata.quality_score == 0.87
    assert metadata.violations_found == 5
    print("✓ Created HookMetadata with quality metrics")

    # Test serialization
    metadata_dict = metadata.to_dict()
    assert metadata_dict["quality_score"] == 0.87
    assert metadata_dict["violations_found"] == 5
    print(f"✓ Serialized HookMetadata to dict ({len(metadata_dict)} fields)")


async def test_database_integration():
    """Test full database integration (requires database)"""
    print("\n=== Test 6: Database Integration ===")

    # Skip if no database connection
    if not os.getenv("SUPABASE_URL") and not os.getenv("POSTGRES_HOST"):
        print("⊘ Skipped: No database connection configured")
        return

    # Initialize client
    client = PostgresTracingClient()
    await client.initialize()

    if not client._initialized:
        print("⊘ Skipped: Database connection failed")
        return

    try:
        # Create and insert trace
        session_id = uuid4()
        trace = create_new_trace(
            source="integration_test",
            session_id=session_id,
            prompt_text="Integration test prompt",
            tags=["integration", "test"],
        )

        trace_id = await client.insert_trace(trace)
        if trace_id:
            print(f"✓ Inserted trace to database: {trace_id}")
        else:
            print("✗ Failed to insert trace")
            return

        # Create and insert hook
        hook = create_new_hook_execution(
            trace_id=trace.correlation_id,
            hook_type="PreToolUse",
            hook_name="integration_test_hook",
            execution_order=1,
            tool_name="Write",
        )
        hook.rag_query_performed = True
        hook.rag_results = {"matches": 5, "confidence": 0.89}
        hook.mark_completed(success=True)

        hook_id = await client.insert_hook(hook)
        if hook_id:
            print(f"✓ Inserted hook execution to database: {hook_id}")
        else:
            print("✗ Failed to insert hook")
            return

        # Complete trace
        trace.mark_completed(success=True)
        await client.update_trace(trace)
        print("✓ Updated trace to completed status")

        # Retrieve trace as model
        retrieved_trace = await client.get_trace_model(trace.correlation_id)
        if retrieved_trace:
            print(
                f"✓ Retrieved trace: status={retrieved_trace.status}, duration={retrieved_trace.duration_ms}ms"
            )
            assert retrieved_trace.correlation_id == trace.correlation_id
            assert retrieved_trace.status == "completed"
        else:
            print("✗ Failed to retrieve trace")

        # Retrieve hooks as models
        hooks = await client.get_hook_models(trace.correlation_id)
        if hooks:
            print(f"✓ Retrieved {len(hooks)} hook execution(s)")
            for h in hooks:
                print(f"  - {h.hook_name}: {h.status} ({h.duration_ms}ms)")
        else:
            print("⚠ No hooks retrieved")

    finally:
        await client.close()
        print("✓ Closed database connection")


async def test_complete_workflow():
    """Test complete end-to-end workflow"""
    print("\n=== Test 7: Complete Workflow ===")

    # Create a trace
    session_id = uuid4()
    trace = create_new_trace(
        source="workflow_test",
        session_id=session_id,
        prompt_text="Complete workflow test",
        user_id="test_user",
        tags=["workflow", "end-to-end"],
    )
    print(f"✓ Step 1: Created trace {trace.correlation_id}")

    # Create multiple hook executions
    hooks = []
    for i in range(3):
        hook = create_new_hook_execution(
            trace_id=trace.correlation_id,
            hook_type="PreToolUse" if i == 0 else "PostToolUse",
            hook_name=f"hook_{i+1}",
            execution_order=i + 1,
            tool_name="Write" if i < 2 else "Edit",
        )

        # Simulate hook execution
        if i == 0:
            hook.rag_query_performed = True
            hook.rag_results = {"matches": 8, "top_source": "docs.anthropic.com"}
        if i == 1:
            hook.quality_check_performed = True
            hook.quality_results = {"score": 0.91, "violations": []}

        hook.mark_completed(success=True)
        hooks.append(hook)

    print(f"✓ Step 2: Created {len(hooks)} hook executions")

    # Complete trace
    trace.mark_completed(success=True)
    print(f"✓ Step 3: Completed trace (duration: {trace.duration_ms}ms)")

    # Verify data
    assert trace.status == "completed"
    assert trace.success is True
    assert all(h.status == "completed" for h in hooks)
    print("✓ Step 4: Verified all components completed successfully")


async def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("TRACING MODELS INTEGRATION TEST SUITE")
    print("=" * 60)

    if not IMPORTS_AVAILABLE:
        print("\n✗ Cannot run tests: Import errors")
        return

    tests = [
        test_basic_model_creation,
        test_model_validation,
        test_serialization,
        test_trace_context,
        test_hook_metadata,
        test_complete_workflow,
        test_database_integration,  # Last because it requires database
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n✗ Test failed: {test.__name__}")
            print(f"  Error: {e}")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"TEST RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
