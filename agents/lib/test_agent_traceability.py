"""
Test Agent Traceability System - Complete Example

Demonstrates complete traceability for a simulated agent execution:
1. Prompt logging
2. File operation logging
3. Intelligence usage logging
4. Complete trace retrieval

Run:
    python3 agents/lib/test_agent_traceability.py
"""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

from omnibase_core.enums.enum_operation_status import EnumOperationStatus

from agents.lib.agent_execution_logger import log_agent_execution
from agents.lib.agent_traceability_logger import create_traceability_logger
from agents.lib.traceability_events import get_traceability_publisher

# Portable path resolution
# Use environment variable if set, otherwise compute relative path
PROJECT_ROOT = os.getenv("PROJECT_ROOT")
if not PROJECT_ROOT:
    # This file is in agents/lib/, so project root is 2 levels up
    PROJECT_ROOT = str(Path(__file__).parent.parent.parent.resolve())

# Example test project path (configurable via environment)
TEST_PROJECT_PATH = os.getenv("TEST_PROJECT_PATH", f"{PROJECT_ROOT}/../Omniarchon")
TEST_PROJECT_NAME = os.getenv("TEST_PROJECT_NAME", "Omniarchon")


async def test_complete_traceability():
    """
    Test complete traceability system with simulated agent execution.
    """
    print("=" * 80)
    print("AGENT TRACEABILITY SYSTEM TEST")
    print("=" * 80)
    print()

    # 1. Generate correlation ID
    correlation_id = uuid4()
    print(f"✅ Correlation ID: {correlation_id}")
    print()

    # 2. Initialize execution logger
    print("📝 Initializing execution logger...")
    exec_logger = await log_agent_execution(
        agent_name="test-agent",
        user_prompt="Create a new ONEX Effect node for database operations",
        correlation_id=correlation_id,
        project_path=TEST_PROJECT_PATH,
        project_name=TEST_PROJECT_NAME,
    )
    print(f"   Execution ID: {exec_logger.execution_id}")
    print()

    # 3. Initialize traceability logger
    print("🔍 Initializing traceability logger...")
    tracer = await create_traceability_logger(
        agent_name="test-agent",
        correlation_id=correlation_id,
        execution_id=exec_logger.execution_id,
        project_path=TEST_PROJECT_PATH,
        project_name=TEST_PROJECT_NAME,
    )
    print("   Traceability logger ready")
    print()

    # 4. Log user prompt
    print("💬 Logging user prompt...")
    agent_instructions = """
    # System Manifest

    Available Patterns:
    - Node State Management Pattern (95% confidence)
    - Async Event Bus Communication (92% confidence)

    Infrastructure:
    - PostgreSQL: 192.168.86.200:5436
    - Kafka: 192.168.86.200:9092

    Task: Create a new ONEX Effect node for database operations
    """

    prompt_id = await tracer.log_prompt(
        user_prompt="Create a new ONEX Effect node for database operations",
        agent_instructions=agent_instructions,
        manifest_injection_id=uuid4(),  # Simulated manifest ID
        manifest_sections=["patterns", "infrastructure", "models"],
        system_context={
            "cwd": TEST_PROJECT_PATH,
            "git_branch": "main",
            "git_status": "clean",
        },
        attached_files=None,
    )
    print(f"   ✅ Prompt logged: {prompt_id}")
    print()

    # 5. Simulate file operations
    print("📂 Simulating file operations...")

    # Read operation
    read_content = """
    class NodeDatabaseWriterEffect:
        async def execute_effect(self, contract):
            pass
    """

    file_op_id_1 = await tracer.log_file_operation(
        operation_type="read",
        file_path=f"{TEST_PROJECT_PATH}/services/core/nodes/node_database_writer_effect.py",
        content_before=read_content,
        content_after=read_content,
        tool_name="Read",
        intelligence_file_id=uuid4(),  # Simulated Archon file ID
        matched_pattern_ids=[uuid4(), uuid4()],  # Simulated pattern IDs
        success=True,
        duration_ms=45,
    )
    print(f"   ✅ File read logged: {file_op_id_1}")

    # Write operation
    new_content = """
    class NodeDatabaseWriterEffect:
        async def execute_effect(self, contract: ModelContractEffect):
            async with self.transaction_manager.begin():
                result = await self._write_to_database(contract)
                return ModelResult(success=True, data=result)
    """

    file_op_id_2 = await tracer.log_file_operation(
        operation_type="edit",
        file_path=f"{TEST_PROJECT_PATH}/services/core/nodes/node_database_writer_effect.py",
        content_before=read_content,
        content_after=new_content,
        tool_name="Edit",
        line_range={"start": 1, "end": 5},
        operation_params={
            "old_string": "pass",
            "new_string": "async with self.transaction_manager.begin():\n        result = await self._write_to_database(contract)\n        return ModelResult(success=True, data=result)",
        },
        intelligence_file_id=uuid4(),
        matched_pattern_ids=[uuid4()],
        success=True,
        duration_ms=123,
    )
    print(f"   ✅ File edit logged: {file_op_id_2}")
    print()

    # 6. Log intelligence usage
    print("🧠 Logging intelligence usage...")

    # Pattern usage
    pattern_id = uuid4()
    intel_usage_id_1 = await tracer.log_intelligence_usage(
        intelligence_type="pattern",
        intelligence_source="qdrant",
        intelligence_id=pattern_id,
        intelligence_name="Node State Management Pattern",
        collection_name="execution_patterns",
        usage_context="implementation",
        confidence_score=0.95,
        intelligence_snapshot={
            "name": "Node State Management Pattern",
            "file_path": "node_state_manager_effect.py",
            "node_types": ["EFFECT", "REDUCER"],
            "use_cases": ["State persistence", "Transaction management"],
        },
        intelligence_summary="Pattern for ONEX state management in Effect nodes",
        query_used="state management ONEX effect",
        query_time_ms=450,
        query_results_rank=1,
        was_applied=True,
        application_details={
            "applied_to": f"{TEST_PROJECT_PATH}/services/core/nodes/node_database_writer_effect.py",
            "lines_added": 3,
            "functions_created": 1,
        },
        file_operations_using_this=[file_op_id_1, file_op_id_2],
        contributed_to_success=True,
        quality_impact=0.85,
    )
    print(f"   ✅ Pattern usage logged: {intel_usage_id_1}")

    # Schema usage
    intel_usage_id_2 = await tracer.log_intelligence_usage(
        intelligence_type="schema",
        intelligence_source="postgres",
        intelligence_name="agent_execution_logs",
        collection_name="omninode_bridge.public",
        usage_context="reference",
        was_applied=True,
        application_details={
            "columns_used": ["execution_id", "correlation_id", "status"],
            "query_type": "SELECT",
        },
        contributed_to_success=True,
        quality_impact=0.65,
    )
    print(f"   ✅ Schema usage logged: {intel_usage_id_2}")

    # Debug intelligence usage
    intel_usage_id_3 = await tracer.log_intelligence_usage(
        intelligence_type="debug_intelligence",
        intelligence_source="archon-intelligence",
        intelligence_name="Successful workflow: Read before Edit pattern",
        usage_context="inspiration",
        confidence_score=0.88,
        was_applied=True,
        application_details={
            "pattern": "Always read file before editing",
            "avoided_error": "Edit without context",
        },
        contributed_to_success=True,
        quality_impact=0.75,
    )
    print(f"   ✅ Debug intelligence logged: {intel_usage_id_3}")
    print()

    # 7. Publish Kafka events (optional)
    print("📡 Publishing Kafka events...")
    try:
        publisher = get_traceability_publisher()

        await publisher.publish_prompt_event(
            correlation_id=correlation_id,
            agent_name="test-agent",
            user_prompt="Create a new ONEX Effect node for database operations",
            prompt_id=prompt_id,
            user_prompt_length=55,
            agent_instructions_length=len(agent_instructions),
        )

        await publisher.publish_file_operation_event(
            correlation_id=correlation_id,
            agent_name="test-agent",
            operation_type="edit",
            file_path=f"{TEST_PROJECT_PATH}/services/core/nodes/node_database_writer_effect.py",
            file_op_id=file_op_id_2,
            content_changed=True,
            matched_pattern_count=1,
            duration_ms=123,
        )

        await publisher.publish_intelligence_usage_event(
            correlation_id=correlation_id,
            agent_name="test-agent",
            intelligence_type="pattern",
            intelligence_source="qdrant",
            intelligence_name="Node State Management Pattern",
            intel_usage_id=intel_usage_id_1,
            was_applied=True,
            confidence_score=0.95,
            quality_impact=0.85,
        )

        publisher.flush()
        print("   ✅ Kafka events published")
    except Exception as e:
        print(f"   ⚠️  Kafka events skipped (not enabled or error): {e}")
    print()

    # 8. Complete execution
    print("✅ Completing execution...")
    await exec_logger.complete(status=EnumOperationStatus.SUCCESS, quality_score=0.85)
    print("   Execution completed")
    print()

    # 9. Retrieve complete trace
    print("🔍 Retrieving complete trace...")
    trace_data = await tracer.get_complete_trace()

    if trace_data:
        print("   ✅ Complete trace retrieved")
        print()
        print("📊 Trace Summary:")
        print(f"   - Prompts: {len(trace_data.get('prompt', []))}")
        print(f"   - File Operations: {len(trace_data.get('file_operation', []))}")
        print(
            f"   - Intelligence Usage: {len(trace_data.get('intelligence_usage', []))}"
        )
        print(f"   - Manifests: {len(trace_data.get('manifest', []))}")
        print(f"   - Executions: {len(trace_data.get('execution', []))}")
        print()

        # Print detailed trace
        print("📋 Detailed Trace:")
        print()

        if trace_data.get("prompt"):
            print("   💬 Prompts:")
            for prompt in trace_data["prompt"]:
                print(f"      - ID: {prompt.get('id')}")
                print(f"        User Prompt Length: {prompt.get('user_prompt_length')}")
                print(
                    f"        Agent Instructions Length: {prompt.get('agent_instructions_length')}"
                )
            print()

        if trace_data.get("file_operation"):
            print("   📂 File Operations:")
            for file_op in trace_data["file_operation"]:
                print(f"      - Operation: {file_op.get('operation_type')}")
                print(f"        File: {file_op.get('file_name')}")
                print(f"        Content Changed: {file_op.get('content_changed')}")
                print(
                    f"        Patterns Matched: {len(file_op.get('matched_pattern_ids') or [])}"
                )
            print()

        if trace_data.get("intelligence_usage"):
            print("   🧠 Intelligence Usage:")
            for intel in trace_data["intelligence_usage"]:
                print(f"      - Type: {intel.get('intelligence_type')}")
                print(f"        Name: {intel.get('intelligence_name')}")
                print(f"        Was Applied: {intel.get('was_applied')}")
                print(f"        Quality Impact: {intel.get('quality_impact')}")
            print()

    else:
        print("   ⚠️  Failed to retrieve complete trace")

    # 10. Summary
    print("=" * 80)
    print("✅ TRACEABILITY TEST COMPLETE")
    print("=" * 80)
    print()
    print(f"Correlation ID: {correlation_id}")
    print(f"Execution ID: {exec_logger.execution_id}")
    print(f"Prompt ID: {prompt_id}")
    print("File Operations: 2")
    print("Intelligence Usage: 3")
    print()
    print("Query Examples:")
    print()
    # Note: These are example queries for documentation purposes only (not executed)
    # Using literal values in examples to show actual correlation_id
    print(  # nosec B608 - Not executing SQL, just printing examples
        f"  # Get complete trace\n  SELECT * FROM get_complete_trace('{correlation_id}');"
    )
    print()
    print(  # nosec B608 - Not executing SQL, just printing examples
        f"  # Get execution summary\n  SELECT * FROM v_complete_execution_trace WHERE correlation_id = '{correlation_id}';"
    )
    print()
    print(  # nosec B608 - Not executing SQL, just printing examples
        f"  # Get file operations\n  SELECT * FROM agent_file_operations WHERE correlation_id = '{correlation_id}';"
    )
    print()
    print(  # nosec B608 - Not executing SQL, just printing examples
        f"  # Get intelligence usage\n  SELECT * FROM agent_intelligence_usage WHERE correlation_id = '{correlation_id}';"
    )
    print()


async def test_query_examples():
    """
    Test query examples for retrieving traceability data.
    """
    print()
    print("=" * 80)
    print("QUERY EXAMPLES TEST")
    print("=" * 80)
    print()

    from db import get_pg_pool

    try:
        pool = await get_pg_pool()
        if not pool:
            print("❌ Database pool unavailable")
            return

        async with pool.acquire() as conn:
            # Query 1: Recent prompts
            print("1️⃣  Recent Prompts (Last 5):")
            rows = await conn.fetch(
                """
                SELECT
                    correlation_id,
                    agent_name,
                    user_prompt_length,
                    agent_instructions_length,
                    created_at
                FROM agent_prompts
                ORDER BY created_at DESC
                LIMIT 5
            """
            )

            for row in rows:
                print(f"   - {row['agent_name']}: {row['user_prompt_length']} chars")
                print(f"     Correlation: {row['correlation_id']}")
            print()

            # Query 2: File operation summary
            print("2️⃣  File Operation Summary:")
            rows = await conn.fetch(
                """
                SELECT
                    operation_type,
                    COUNT(*) as count,
                    AVG(duration_ms) as avg_duration_ms
                FROM agent_file_operations
                GROUP BY operation_type
                ORDER BY count DESC
            """
            )

            for row in rows:
                print(
                    f"   - {row['operation_type']}: {row['count']} operations (avg {row['avg_duration_ms']}ms)"
                )
            print()

            # Query 3: Intelligence effectiveness
            print("3️⃣  Intelligence Effectiveness:")
            rows = await conn.fetch(
                """
                SELECT
                    intelligence_type,
                    COUNT(*) as total_uses,
                    SUM(CASE WHEN was_applied THEN 1 ELSE 0 END) as applied_count,
                    AVG(quality_impact) FILTER (WHERE was_applied) as avg_quality_impact
                FROM agent_intelligence_usage
                GROUP BY intelligence_type
                ORDER BY applied_count DESC
            """
            )

            for row in rows:
                print(
                    f"   - {row['intelligence_type']}: {row['applied_count']}/{row['total_uses']} applied"
                )
                if row["avg_quality_impact"]:
                    print(
                        f"     Avg Quality Impact: {float(row['avg_quality_impact']):.2f}"
                    )
            print()

    except Exception as e:
        print(f"❌ Query test failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    print()
    print("🚀 Starting Agent Traceability System Test...")
    print()

    # Run main test
    asyncio.run(test_complete_traceability())

    # Run query examples
    asyncio.run(test_query_examples())

    print()
    print("🎉 All tests complete!")
    print()
