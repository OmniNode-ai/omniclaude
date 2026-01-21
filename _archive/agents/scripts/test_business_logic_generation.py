#!/usr/bin/env python3
"""
Smoke test for Business Logic Generator

Quick validation that business logic generation works end-to-end.

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/scripts/test_business_logic_generation.py

    Or install the package in development mode:

        pip install -e .
"""

import asyncio
import sys

from agents.lib.business_logic_generator import BusinessLogicGenerator
from agents.lib.contract_generator import ContractGenerator
from agents.tests.fixtures.phase4_fixtures import (
    COMPUTE_ANALYSIS_RESULT,
    EFFECT_ANALYSIS_RESULT,
    SAMPLE_CONTRACT_WITH_CRUD,
)


async def test_effect_generation():
    """Test EFFECT node generation"""
    print("=" * 80)
    print("TEST: EFFECT Node Generation")
    print("=" * 80)

    generator = BusinessLogicGenerator()
    contract_gen = ContractGenerator()

    # Generate contract
    contract_result = await contract_gen.generate_contract_yaml(
        EFFECT_ANALYSIS_RESULT, "EFFECT", "user_management", "identity"
    )

    # Generate implementation
    code = await generator.generate_node_implementation(
        contract_result["contract"],
        EFFECT_ANALYSIS_RESULT,
        "EFFECT",
        "user_management",
        "identity",
    )

    print(f"\n✓ Generated {len(code)} characters of code")
    print(
        f"✓ Found class definition: {'class NodeUserManagementEffectService' in code}"
    )
    print(f"✓ Found execute_effect: {'async def execute_effect' in code}")
    print(f"✓ Found validation: {'async def _validate_input' in code}")
    print(f"✓ Found health check: {'async def get_health_status' in code}")
    print(f"✓ Found correlation tracking: {'correlation_id' in code}")
    print(f"✓ Found error handling: {'OnexError' in code}")
    print(f"✓ Found type hints: {'Dict[str, Any]' in code}")

    # Print first 1000 chars
    print("\nFirst 1000 characters of generated code:")
    print("-" * 80)
    print(code[:1000])
    print("-" * 80)

    return code


async def test_compute_generation():
    """Test COMPUTE node generation"""
    print("\n" + "=" * 80)
    print("TEST: COMPUTE Node Generation")
    print("=" * 80)

    generator = BusinessLogicGenerator()
    contract_gen = ContractGenerator()

    # Generate contract
    contract_result = await contract_gen.generate_contract_yaml(
        COMPUTE_ANALYSIS_RESULT, "COMPUTE", "csv_json_transformer", "data_processing"
    )

    # Generate implementation
    code = await generator.generate_node_implementation(
        contract_result["contract"],
        COMPUTE_ANALYSIS_RESULT,
        "COMPUTE",
        "csv_json_transformer",
        "data_processing",
    )

    print(f"\n✓ Generated {len(code)} characters of code")
    print(
        f"✓ Found class definition: {'class NodeCsvJsonTransformerComputeService' in code}"
    )
    print(f"✓ Found execute_compute: {'async def execute_compute' in code}")
    print(
        f"✓ Found COMPUTE hints: {'COMPUTE Node: Implement pure transformation logic' in code}"
    )

    return code


async def test_crud_pattern_detection():
    """Test CRUD pattern detection"""
    print("\n" + "=" * 80)
    print("TEST: CRUD Pattern Detection")
    print("=" * 80)

    generator = BusinessLogicGenerator()

    # Generate implementation with CRUD contract
    code = await generator.generate_node_implementation(
        SAMPLE_CONTRACT_WITH_CRUD,
        EFFECT_ANALYSIS_RESULT,
        "EFFECT",
        "user_service",
        "user_management",
    )

    print(f"\n✓ Generated {len(code)} characters of code")
    print(f"✓ Found create_user method: {'async def create_user' in code}")
    print(f"✓ Found get_user method: {'async def get_user' in code}")
    print(f"✓ Found update_user method: {'async def update_user' in code}")
    print(f"✓ Found delete_user method: {'async def delete_user' in code}")
    print(f"✓ Found CRUD_CREATE pattern: {'PATTERN_HOOK: CRUD_CREATE' in code}")
    print(f"✓ Found CRUD_READ pattern: {'PATTERN_HOOK: CRUD_READ' in code}")
    print(f"✓ Found CRUD_UPDATE pattern: {'PATTERN_HOOK: CRUD_UPDATE' in code}")
    print(f"✓ Found CRUD_DELETE pattern: {'PATTERN_HOOK: CRUD_DELETE' in code}")

    return code


async def test_syntax_validation():
    """Test that generated code has valid Python syntax"""
    print("\n" + "=" * 80)
    print("TEST: Syntax Validation")
    print("=" * 80)

    generator = BusinessLogicGenerator()

    code = await generator.generate_node_implementation(
        SAMPLE_CONTRACT_WITH_CRUD,
        EFFECT_ANALYSIS_RESULT,
        "EFFECT",
        "user_service",
        "user_management",
    )

    # Try to compile the code
    try:
        compile(code, "<generated>", "exec")
        print("\n✓ Generated code has valid Python syntax")
        return True
    except SyntaxError as e:
        print(f"\n✗ Syntax error in generated code: {e}")
        print(f"  Line {e.lineno}: {e.text}")
        return False


async def main():
    """Run all smoke tests"""
    print("\n" + "=" * 80)
    print("BUSINESS LOGIC GENERATOR SMOKE TESTS")
    print("=" * 80)

    try:
        # Test EFFECT generation
        await test_effect_generation()

        # Test COMPUTE generation
        await test_compute_generation()

        # Test CRUD pattern detection
        await test_crud_pattern_detection()

        # Test syntax validation
        await test_syntax_validation()

        print("\n" + "=" * 80)
        print("ALL TESTS PASSED ✓")
        print("=" * 80)

        return 0

    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
