#!/usr/bin/env python3
"""
Problem Statement to Implementation Adapter

Takes a problem statement markdown file and:
1. Reads the document
2. Feeds to ValidatedTaskArchitect for breakdown
3. Uses QuorumValidator for multi-model validation
4. Optionally executes via dispatch_runner.py

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/parallel_execution/run_from_problem_statement.py /path/to/PROBLEM_STATEMENT.md [--execute]

    Or install the package in development mode:

        pip install -e .

Usage:
    python run_from_problem_statement.py /path/to/PROBLEM_STATEMENT.md [--execute]
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

from parallel_execution.validated_task_architect import ValidatedTaskArchitect


async def process_problem_statement(
    problem_statement_path: str, execute: bool = False
) -> Dict[str, Any]:
    """
    Process a problem statement document through validated task breakdown.

    Args:
        problem_statement_path: Path to the problem statement markdown file
        execute: If True, automatically execute via dispatch_runner.py

    Returns:
        Dictionary with breakdown and execution results
    """

    # Read problem statement
    ps_path = Path(problem_statement_path)
    if not ps_path.exists():
        raise FileNotFoundError(
            f"Problem statement not found: {problem_statement_path}"
        )

    print(f"📄 Reading problem statement: {ps_path.name}")
    problem_content = ps_path.read_text(encoding="utf-8")

    # Extract key sections for context
    print("🔍 Analyzing problem statement structure...")

    # Build enhanced prompt
    enhanced_prompt = f"""Based on this problem statement, create a complete implementation plan:

{problem_content}

Please break this down into concrete implementation tasks that can be executed in parallel.
Focus on:
1. Code generation tasks (handler implementation, models, enums)
2. Integration tasks (register handler, update configs)
3. Testing tasks (integration tests, validation)

Each task should be specific and actionable with clear inputs/outputs."""

    # Initialize validated task architect
    print("\n🏗️  Initializing Validated Task Architect with Quorum Validation...")
    architect = ValidatedTaskArchitect()

    # Get validated breakdown
    print(f"\n{'='*70}")
    print("TASK BREAKDOWN WITH QUORUM VALIDATION")
    print(f"{'='*70}\n")

    result = await architect.breakdown_tasks_with_validation(
        user_prompt=enhanced_prompt,
        global_context=None,  # Could add codebase context here
    )

    # Display results
    print(f"\n{'='*70}")
    print("VALIDATION RESULTS")
    print(f"{'='*70}\n")

    breakdown = result["breakdown"]
    validated = result["validated"]
    attempts = result["attempts"]
    quorum_result = result["quorum_result"]

    print(f"✓ Validated: {validated}")
    print(f"✓ Attempts: {attempts}")
    print(f"✓ Decision: {quorum_result['decision']}")
    print(f"✓ Confidence: {quorum_result['confidence']:.1%}")

    if "deficiencies" in quorum_result:
        print(f"\n⚠️  Deficiencies Found ({len(quorum_result['deficiencies'])}):")
        for deficiency in quorum_result["deficiencies"]:
            print(f"   - {deficiency}")

    # Display task breakdown
    print(f"\n{'='*70}")
    print(f"TASK BREAKDOWN ({len(breakdown['tasks'])} tasks)")
    print(f"{'='*70}\n")

    for i, task in enumerate(breakdown["tasks"], 1):
        task_id = task["task_id"]
        agent = task.get("agent", "unknown")
        description = task["description"]
        dependencies = task.get("dependencies", [])

        print(f"{i}. [{task_id}] ({agent})")
        print(f"   Description: {description}")
        if dependencies:
            print(f"   Dependencies: {', '.join(dependencies)}")
        print()

    # Save breakdown to file
    output_path = Path(__file__).parent / "breakdown_output.json"
    output_path.write_text(json.dumps(result, indent=2))
    print(f"💾 Breakdown saved to: {output_path}")

    # Optionally execute
    if execute:
        print(f"\n{'='*70}")
        print("EXECUTING TASKS VIA DISPATCH RUNNER")
        print(f"{'='*70}\n")

        # Save tasks for dispatch_runner
        tasks_file = Path(__file__).parent / "tasks_to_execute.json"
        tasks_file.write_text(json.dumps(breakdown, indent=2))

        print(f"💾 Tasks saved to: {tasks_file}")
        print("\n🚀 To execute, run:")
        print(f"   cd {Path(__file__).parent}")
        print("   python dispatch_runner.py < tasks_to_execute.json")
    else:
        print(f"\n{'='*70}")
        print("NEXT STEPS")
        print(f"{'='*70}\n")
        print("To execute this breakdown, run:")
        print(f"   python {__file__} {problem_statement_path} --execute")
        print("\nOr manually:")
        print(f"   cd {Path(__file__).parent}")
        print("   python dispatch_runner.py < breakdown_output.json")

    return result


async def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print(
            "Usage: python run_from_problem_statement.py /path/to/PROBLEM_STATEMENT.md [--execute]"
        )
        print("\nExample:")
        print(
            "  python run_from_problem_statement.py ../../../omniarchon/services/intelligence/PROBLEM_STATEMENT.md"
        )
        sys.exit(1)

    problem_statement_path = sys.argv[1]
    execute = "--execute" in sys.argv

    try:
        result = await process_problem_statement(problem_statement_path, execute)

        if result["validated"]:
            print("\n✅ SUCCESS: Task breakdown validated and ready for execution")
            sys.exit(0)
        else:
            print("\n⚠️  WARNING: Task breakdown not fully validated")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
