#!/usr/bin/env python3
"""
Test Interactive Checkpoints in Generation Pipeline

This test verifies that interactive checkpoints are properly integrated
into the generation pipeline.

SKIP REASON: Missing external dependency 'omnibase_core' module
-----------------------------------------------------------------------------
Status: BLOCKED - Cannot be fixed without external dependency
Priority: P1 - MVP Blocker
Tracking: Week 4 full pipeline integration

Root Cause:
    ModuleNotFoundError: No module named 'omnibase_core'

Import Chain:
    test → generation_pipeline → contract_builder_factory → generation/__init__.py
    → ComputeContractBuilder → omnibase_core.models.contracts (fails during collection)

Resolution:
    1. Install omnibase_core package (not available in pyproject.toml)
    2. Remove --ignore flag from pyproject.toml [tool.pytest.ini_options]
    3. Run: pytest agents/tests/test_interactive_pipeline.py -v

Alternative:
    The GenerationPipeline functionality works correctly when run directly
    outside of pytest's import collection phase.

Setup:
    Run with pytest from project root:

        cd /path/to/omniclaude
        pytest agents/tests/test_interactive_pipeline.py -v

    Or use PYTHONPATH:

        PYTHONPATH=/path/to/omniclaude pytest agents/tests/test_interactive_pipeline.py -v
"""

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest


# Skip entire test module due to missing omnibase_core dependency
# TODO(Week 4): Install omnibase_core package and remove --ignore from pyproject.toml
pytestmark = pytest.mark.skip(
    reason="Missing external dependency 'omnibase_core' - ModuleNotFoundError. "
    "Install omnibase_core package to enable these tests. "
    "Tracking: Week 4 pipeline integration"
)

from agents.lib.generation_pipeline import GenerationPipeline  # noqa: E402


async def test_non_interactive_mode():
    """Test that pipeline works in non-interactive mode (default)"""
    print("\n" + "=" * 60)
    print("TEST 1: Non-Interactive Mode")
    print("=" * 60)

    pipeline = GenerationPipeline(
        enable_compilation_testing=False,
        enable_intelligence_gathering=False,
        interactive_mode=False,  # Default
    )

    # Simple test prompt
    prompt = "Create an EFFECT node called EmailSender for sending emails in the notification domain"

    print(f"\nPrompt: {prompt}")
    print("\nRunning pipeline in non-interactive mode...")

    try:
        result = await pipeline.execute(
            prompt=prompt,
            output_directory=str(Path(tempfile.gettempdir()) / "test_node_gen"),
        )

        print(f"\n✓ Pipeline completed: {result.status}")
        print(f"  Duration: {result.duration_seconds:.2f}s")
        print(f"  Node type: {result.node_type}")
        print(f"  Service name: {result.service_name}")
        print(f"  Validation passed: {result.validation_passed}")

        return result.status == "success"

    except Exception as e:
        print(f"\n✗ Pipeline failed: {e}")
        return False

    finally:
        await pipeline.cleanup_async()


async def test_interactive_mode_structure():
    """Test that interactive mode initializes correctly"""
    print("\n" + "=" * 60)
    print("TEST 2: Interactive Mode Structure")
    print("=" * 60)

    pipeline = GenerationPipeline(
        enable_compilation_testing=False,
        enable_intelligence_gathering=False,
        interactive_mode=True,
    )

    # Check validator is created
    print("\n✓ Pipeline initialized with interactive_mode=True")
    print(f"  Validator type: {type(pipeline.validator).__name__}")
    print(f"  Interactive mode: {pipeline.interactive_mode}")

    # Check validator has checkpoint method
    assert hasattr(
        pipeline.validator, "checkpoint"
    ), "Validator missing checkpoint method"
    print("  Validator has checkpoint method: ✓")

    await pipeline.cleanup_async()
    return True


async def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("INTERACTIVE PIPELINE INTEGRATION TESTS")
    print("=" * 60)

    results = {
        "non_interactive": await test_non_interactive_mode(),
        "interactive_structure": await test_interactive_mode_structure(),
    }

    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)

    for test_name, passed in results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"  {test_name}: {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'✓ ALL TESTS PASSED' if all_passed else '✗ SOME TESTS FAILED'}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
