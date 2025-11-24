#!/usr/bin/env python3
"""
Create a simple calculator app using parallel agent execution.

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/parallel_execution/run_calculator_tasks.py

    Or install the package in development mode:

        pip install -e .
"""

import asyncio
from pathlib import Path

from .agent_dispatcher import ParallelCoordinator
from .agent_model import AgentTask


# Calculator contract
CALCULATOR_CONTRACT = {
    "name": "Calculator",
    "description": "Simple calculator with basic operations",
    "operations": {
        "add": {
            "inputs": ["a: float", "b: float"],
            "output": "float",
            "description": "Add two numbers",
        },
        "subtract": {
            "inputs": ["a: float", "b: float"],
            "output": "float",
            "description": "Subtract b from a",
        },
        "multiply": {
            "inputs": ["a: float", "b: float"],
            "output": "float",
            "description": "Multiply two numbers",
        },
        "divide": {
            "inputs": ["a: float", "b: float"],
            "output": "float",
            "description": "Divide a by b, raises error if b is zero",
        },
    },
    "node_type": "Compute",
    "language": "python",
}


async def create_calculator():
    """Create calculator using parallel agents."""

    print("=" * 80)
    print("Creating Calculator App with Parallel Agent Dispatcher")
    print("=" * 80)
    print()

    coordinator = ParallelCoordinator()

    try:
        # Task 1: Generate calculator code
        tasks = [
            AgentTask(
                task_id="generate_calculator",
                description="Generate ONEX Compute node for calculator from contract",
                input_data={
                    "contract": CALCULATOR_CONTRACT,
                    "node_type": "Compute",
                    "language": "python",
                },
            )
        ]

        print("Dispatching tasks to agents...")
        results = await coordinator.execute_parallel(tasks)

        # Display results
        for task_id, result in results.items():
            print(f"\n{'=' * 80}")
            print(f"Task: {task_id}")
            print(f"Agent: {result.agent_name}")
            print(f"Success: {'✅' if result.success else '❌'}")
            print(f"Time: {result.execution_time_ms:.2f}ms")
            print(f"{'=' * 80}\n")

            if result.success and "generated_code" in result.output_data:
                print("Generated Code:")
                print("-" * 80)
                print(result.output_data["generated_code"])
                print("-" * 80)
                print(f"\nLines: {result.output_data.get('lines_generated', 0)}")
                print(f"Quality: {result.output_data.get('quality_score', 0):.2f}")
                print(f"Node Type: {result.output_data.get('node_type', 'Unknown')}")

                # Save to file
                output_file = Path(__file__).parent / "calculator.py"
                output_file.write_text(result.output_data["generated_code"])
                print(f"\n✅ Saved to: {output_file}")
            elif not result.success:
                print(f"❌ Error: {result.error}")

    finally:
        await coordinator.cleanup()
        print("\n✅ Complete")


if __name__ == "__main__":
    asyncio.run(create_calculator())
