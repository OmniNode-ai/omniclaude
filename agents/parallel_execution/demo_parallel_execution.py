#!/usr/bin/env python3
"""
Demo: Parallel Agent Execution POC

Demonstrates real agents executing in parallel with trace logging.
"""

import asyncio
import sys
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import agent_model
import agent_dispatcher
import trace_logger

AgentTask = agent_model.AgentTask
ParallelCoordinator = agent_dispatcher.ParallelCoordinator
get_trace_logger = trace_logger.get_trace_logger


# Sample Python code with bugs for debugging
BUGGY_CODE = """
def calculate_total(items):
    total = 0
    for item in items:
        if item["active"]:
            total += item["price"]
    return total

class UserManager:
    def __init__(self):
        self.users = []

    def add_user(self, user):
        self.users.append(user)
        return True

    def get_user(self, user_id):
        for user in self.users:
            if user["id"] == user_id:
                return user
        return None
"""

# Contract for code generation
SAMPLE_CONTRACT = {
    "name": "UserAuthentication",
    "description": "Contract for user authentication operations",
    "input_model": {
        "username": {"type": "str", "description": "User's username"},
        "password": {"type": "str", "description": "User's password"},
    },
    "output_model": {
        "success": {"type": "bool", "description": "Authentication success status"},
        "token": {"type": "str | None", "description": "JWT token if successful"},
        "error_message": {"type": "str | None", "description": "Error message if failed"},
    },
}


async def run_demo():
    """Run parallel agent execution demo."""

    print("=" * 80)
    print("Parallel Agent Execution POC Demo")
    print("=" * 80)
    print()

    # Create coordinator
    coordinator = ParallelCoordinator()
    trace_logger = get_trace_logger()

    try:
        # Create tasks for parallel execution
        tasks = [
            AgentTask(
                task_id="task1",
                description="Generate code from contract",
                input_data={"contract": SAMPLE_CONTRACT, "node_type": "Effect", "language": "python"},
                dependencies=[],  # No dependencies, can run immediately
            ),
            AgentTask(
                task_id="task2",
                description="Debug code with intelligence",
                input_data={
                    "code": BUGGY_CODE,
                    "file_path": "user_manager.py",
                    "language": "python",
                    "error": "AttributeError: 'NoneType' object has no attribute 'id'",
                },
                dependencies=[],  # No dependencies, runs in parallel with task1
            ),
        ]

        print(f"Created {len(tasks)} tasks:")
        for task in tasks:
            print(f"  - {task.task_id}: {task.description}")
            if task.dependencies:
                print(f"    Dependencies: {task.dependencies}")
        print()

        # Execute in parallel
        print("Executing agents in parallel...")
        print()

        results = await coordinator.execute_parallel(tasks)

        # Print results
        print("=" * 80)
        print("Execution Results")
        print("=" * 80)
        print()

        for task_id, result in results.items():
            print(f"Task: {task_id}")
            print(f"  Agent: {result.agent_name}")
            print(f"  Success: {result.success}")
            print(f"  Execution Time: {result.execution_time_ms:.2f}ms")
            print(f"  Trace ID: {result.trace_id}")

            if result.success:
                print("  Output Summary:")

                # Contract-driven generator results
                if "generated_code" in result.output_data:
                    lines = result.output_data.get("lines_generated", 0)
                    quality = result.output_data.get("quality_score", 0)
                    validation = result.output_data.get("validation_passed", False)
                    print(f"    - Lines Generated: {lines}")
                    print(f"    - Quality Score: {quality:.2f}")
                    print(f"    - Validation Passed: {'✅' if validation else '❌'}")
                    print(f"    - Node Type: {result.output_data.get('node_type', 'Unknown')}")

                # Debug intelligence results
                if "root_cause" in result.output_data:
                    confidence = result.output_data.get("root_cause_confidence", 0)
                    improvement = result.output_data.get("quality_improvement", {})
                    sources = result.output_data.get("intelligence_sources", 0)
                    print(f"    - Root Cause Confidence: {confidence:.2%}")
                    print(f"    - Quality Improvement: {improvement.get('delta', 0):.2f}")
                    print(f"    - Intelligence Sources: {sources}")
                    print("    - Solution Generated: ✅")
            else:
                print(f"  Error: {result.error}")

            print()

        # Print trace summary
        print("=" * 80)
        print("Trace Summary")
        print("=" * 80)
        print()

        # Get coordinator trace ID from results
        if coordinator._coordinator_trace_id:
            await trace_logger.print_trace_summary(coordinator._coordinator_trace_id)

        # Show trace file location
        print("\n📁 Trace files saved in: agents/parallel_execution/traces/")
        print(f"   Coordinator trace: {coordinator._coordinator_trace_id}.json")
        print()

        # Calculate parallel efficiency
        total_sequential_time = sum(r.execution_time_ms for r in results.values())
        actual_time = max(r.execution_time_ms for r in results.values())
        speedup = total_sequential_time / actual_time if actual_time > 0 else 1.0
        efficiency = (speedup / len(tasks)) * 100 if len(tasks) > 0 else 0

        print("=" * 80)
        print("Parallel Execution Metrics")
        print("=" * 80)
        print(f"Total Tasks: {len(tasks)}")
        print(f"Sequential Time (estimated): {total_sequential_time:.2f}ms")
        print(f"Parallel Time (actual): {actual_time:.2f}ms")
        print(f"Speedup: {speedup:.2f}x")
        print(f"Efficiency: {efficiency:.1f}%")
        print(
            f"Time Saved: {total_sequential_time - actual_time:.2f}ms ({((total_sequential_time - actual_time) / total_sequential_time * 100):.1f}%)"
        )
        print()

    except Exception as e:
        print(f"❌ Demo failed: {str(e)}")
        import traceback

        traceback.print_exc()

    finally:
        # Cleanup
        await coordinator.cleanup()
        print("✅ Demo complete")


if __name__ == "__main__":
    # Run async demo
    asyncio.run(run_demo())
