#!/usr/bin/env python3
"""
Generate ONEX-compliant calculator using agent_coder via parallel dispatcher.

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/parallel_execution/generate_calculator.py

    Or install the package in development mode:

        pip install -e .
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

import agent_dispatcher
import agent_model
import trace_logger


AgentTask = agent_model.AgentTask
ParallelCoordinator = agent_dispatcher.ParallelCoordinator
get_trace_logger = trace_logger.get_trace_logger


# Calculator contract following ONEX Compute node patterns
CALCULATOR_CONTRACT = {
    "name": "Calculator",
    "description": "ONEX Compute node for basic arithmetic operations",
    "architecture": "ONEX Compute",
    "input_model": {
        "operation": {
            "type": "str",
            "description": "Arithmetic operation: 'add', 'subtract', 'multiply', 'divide'",
            "required": True,
        },
        "operand_a": {
            "type": "float",
            "description": "First operand for calculation",
            "required": True,
        },
        "operand_b": {
            "type": "float",
            "description": "Second operand for calculation",
            "required": True,
        },
    },
    "output_model": {
        "result": {"type": "float", "description": "Calculated result"},
        "operation_performed": {
            "type": "str",
            "description": "Operation that was executed",
        },
        "error": {
            "type": "str | None",
            "description": "Error message if operation failed (e.g., division by zero)",
        },
    },
    "requirements": [
        "Pure transformation function (no side effects)",
        "Handle division by zero gracefully",
        "Support add, subtract, multiply, divide operations",
        "Return structured result with operation details",
        "Follow ONEX naming convention: NodeCalculatorCompute",
        "Include proper type hints and validation",
        "Include docstrings with examples",
    ],
    "quality_requirements": {
        "type_safety": "Full type hints required",
        "error_handling": "OnexError for all error cases",
        "validation": "Input validation with clear error messages",
        "documentation": "Complete docstrings with usage examples",
        "testing": "Include example test cases in docstring",
    },
}


async def generate_calculator():
    """Generate calculator using parallel dispatcher."""

    print("=" * 80)
    print("ONEX Calculator Generation via Parallel Dispatcher")
    print("=" * 80)
    print()

    # Create coordinator
    coordinator = ParallelCoordinator()
    get_trace_logger()

    try:
        # Create task for agent_coder
        task = AgentTask(
            task_id="calculator-generation",
            description="Generate ONEX Compute calculator from contract",
            input_data={
                "contract": CALCULATOR_CONTRACT,
                "target_type": "Compute",
                "context": "Generate a pure transformation calculator following ONEX architecture. "
                "Must be a Compute node (no I/O, no side effects). "
                "Include comprehensive error handling and validation.",
            },
        )

        print(f"Task: {task.task_id}")
        print(f"Description: {task.description}")
        print("Target Type: Compute")
        print()
        print("Contract Summary:")
        print(f"  Name: {CALCULATOR_CONTRACT['name']}")
        print("  Operations: add, subtract, multiply, divide")
        print(f"  Architecture: {CALCULATOR_CONTRACT['architecture']}")
        print()

        # Execute via parallel dispatcher
        print("Executing agent_coder...")
        print()

        results = await coordinator.execute_parallel([task])

        # Extract result
        result = results.get("calculator-generation")

        if not result:
            print("❌ No result returned from agent")
            return

        print("=" * 80)
        print("Generation Results")
        print("=" * 80)
        print()

        print(f"Agent: {result.agent_name}")
        print(f"Success: {'✅' if result.success else '❌'}")
        print(f"Execution Time: {result.execution_time_ms:.2f}ms")
        print(f"Trace ID: {result.trace_id}")
        print()

        if result.success:
            output = result.output_data

            print("Quality Metrics:")
            print(f"  Lines Generated: {output.get('lines_generated', 0)}")
            print(f"  Quality Score: {output.get('quality_score', 0):.2f}/100")
            print(
                f"  Validation Passed: {'✅' if output.get('validation_passed', False) else '❌'}"
            )
            print(f"  Node Type: {output.get('node_type', 'Unknown')}")
            print(
                f"  ONEX Compliant: {'✅' if output.get('onex_compliant', False) else '❌'}"
            )
            print()

            # Show validation results if available
            if "validation_results" in output:
                validation = output["validation_results"]
                print("Validation Details:")
                print(
                    f"  Type Safety: {'✅' if validation.get('type_safety', False) else '❌'}"
                )
                print(
                    f"  Error Handling: {'✅' if validation.get('error_handling', False) else '❌'}"
                )
                print(
                    f"  Documentation: {'✅' if validation.get('documentation', False) else '❌'}"
                )
                print(
                    f"  ONEX Naming: {'✅' if validation.get('onex_naming', False) else '❌'}"
                )
                print()

            # Show intelligence sources used
            if "intelligence_sources" in output:
                sources = output["intelligence_sources"]
                print(f"Intelligence Sources Used: {sources}")
                print()

            # Save generated code to file
            if "generated_code" in output:
                code = output["generated_code"]

                # Create output directory
                output_dir = Path(__file__).parent / "generated"
                output_dir.mkdir(exist_ok=True)

                # Save with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = output_dir / f"node_calculator_compute_{timestamp}.py"

                with open(output_file, "w") as f:
                    f.write(code)

                print("✅ Generated code saved to:")
                print(f"   {output_file}")
                print()

                # Show code preview
                print("=" * 80)
                print("Generated Code Preview")
                print("=" * 80)
                print()

                lines = code.split("\n")
                preview_lines = min(50, len(lines))

                for i, line in enumerate(lines[:preview_lines], 1):
                    print(f"{i:4d} | {line}")

                if len(lines) > preview_lines:
                    print(f"... ({len(lines) - preview_lines} more lines)")

                print()
                print("=" * 80)
                print()

        else:
            print("❌ Generation Failed:")
            print(f"   {result.error}")
            print()

        # Print trace summary
        print("=" * 80)
        print("Trace Information")
        print("=" * 80)
        print()

        if coordinator._coordinator_trace_id:
            trace_file = (
                Path(__file__).parent
                / "traces"
                / f"{coordinator._coordinator_trace_id}.json"
            )
            print(f"Trace File: {trace_file}")

            if trace_file.exists():
                with open(trace_file) as f:
                    trace_data = json.load(f)

                print(f"Coordinator ID: {trace_data.get('coordinator_id')}")
                print(f"Started: {trace_data.get('started_at')}")
                print(f"Total Duration: {trace_data.get('total_duration_ms', 0):.2f}ms")

                agents = trace_data.get("agents", {})
                print(f"Agents Executed: {len(agents)}")

                for agent_id, agent_data in agents.items():
                    print(f"  - {agent_data.get('agent_name', agent_id)}")
                    print(f"    Status: {agent_data.get('status', 'unknown')}")
                    print(
                        f"    Duration: {agent_data.get('execution_time_ms', 0):.2f}ms"
                    )

                    if agent_data.get("mcp_calls"):
                        print(f"    MCP Calls: {len(agent_data['mcp_calls'])}")

        print()

    except Exception as e:
        print(f"❌ Generation failed: {str(e)}")
        import traceback

        traceback.print_exc()

    finally:
        # Cleanup
        await coordinator.cleanup()
        print("✅ Generation complete")


if __name__ == "__main__":
    asyncio.run(generate_calculator())
