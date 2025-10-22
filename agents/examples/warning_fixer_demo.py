#!/usr/bin/env python3
"""
Warning Fixer Demo

Demonstrates automatic fixes for G12, G13, G14 validation warnings.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.lib.warning_fixer import WarningFixer, apply_automatic_fixes


def demo_g12_pydantic_fixes():
    """Demonstrate G12: Pydantic v2 ConfigDict fixes."""
    print("\n" + "=" * 60)
    print("DEMO: G12 - Pydantic v2 ConfigDict Fixes")
    print("=" * 60)

    code_before = '''from pydantic import BaseModel, Field

class ModelUserInput(BaseModel):
    """Input model for user operations."""

    username: str = Field(..., description="Username")
    email: str = Field(..., description="Email address")

class ModelUserOutput(BaseModel):
    """Output model for user operations."""

    user_id: str
    success: bool

# Using Pydantic v1 patterns
user = ModelUserInput(username="john", email="john@example.com")
data = user.dict()
'''

    print("\nBEFORE:")
    print(code_before)

    # Apply fixes
    fixer = WarningFixer()
    result = fixer.fix_g12_pydantic_config(code_before)

    print("\nAFTER:")
    print(result.fixed_code)

    print("\nFIXES APPLIED:")
    for fix in result.fixes_applied:
        print(f"  ✅ {fix}")


def demo_g13_type_hint_fixes():
    """Demonstrate G13: Type hint additions."""
    print("\n" + "=" * 60)
    print("DEMO: G13 - Type Hint Fixes")
    print("=" * 60)

    code_before = """class NodeUserServiceEffect:
    def __init__(self, container):
        self.container = container

    def _validate_input(self, user_data):
        if not user_data.get("username"):
            raise ValueError("Username required")

    async def _execute_business_logic(self, input_data):
        return {"status": "success", "user_id": "123"}

    def _is_valid_email(self, email):
        return "@" in email
"""

    print("\nBEFORE:")
    print(code_before)

    # Apply fixes
    fixer = WarningFixer()
    result = fixer.fix_g13_type_hints(code_before)

    print("\nAFTER:")
    print(result.fixed_code)

    print("\nFIXES APPLIED:")
    for fix in result.fixes_applied:
        print(f"  ✅ {fix}")


def demo_g14_import_fixes():
    """Demonstrate G14: Import error fixes."""
    print("\n" + "=" * 60)
    print("DEMO: G14 - Import Error Fixes")
    print("=" * 60)

    code_before = '''#!/usr/bin/env python3
"""
ONEX Effect Node: User Service

Handles user creation and management.
"""

class NodeUserServiceEffect(NodeEffect):
    """
    User service effect node.

    This node handles user operations

    def __init__(self, container):
        self.container = container

    async def process(self, input_data):
        return {"status": "success"}
'''

    print("\nBEFORE:")
    print(code_before)

    # Apply fixes
    fixer = WarningFixer()
    result = fixer.fix_g14_imports(code_before)

    print("\nAFTER:")
    print(result.fixed_code)

    print("\nFIXES APPLIED:")
    for fix in result.fixes_applied:
        print(f"  ✅ {fix}")


def demo_full_pipeline():
    """Demonstrate full fix pipeline on production-like code."""
    print("\n" + "=" * 60)
    print("DEMO: Full Fix Pipeline (All Warnings)")
    print("=" * 60)

    code_before = '''#!/usr/bin/env python3
"""
ONEX Compute Node: Data Processor

Processes and transforms user data.
"""

from pydantic import BaseModel

class ModelDataProcessorInput(BaseModel):
    data: str
    operation_type: str

class ModelDataProcessorOutput(BaseModel):
    result: str
    success: bool

class NodeDataProcessorCompute:
    def __init__(self, container):
        self.container = container

    def _validate_input(self, input_data):
        if not input_data.data:
            raise ValueError("Data required")

    async def _execute_computation(self, input_data):
        # Process data
        result = input_data.data.upper()
        return {"result": result}

    async def process(self, input_data):
        self._validate_input(input_data)
        result = await self._execute_computation(input_data)

        output = ModelDataProcessorOutput(
            result=result["result"],
            success=True
        )
        return output.dict()
'''

    print("\nBEFORE:")
    print(code_before)

    # Apply all fixes
    result = apply_automatic_fixes(code_before)

    print("\nAFTER:")
    print(result.fixed_code)

    print("\nFIXES APPLIED:")
    for fix in result.fixes_applied:
        print(f"  ✅ {fix}")

    print(f"\nTOTAL FIXES: {result.fix_count}")
    print(f"WARNINGS FIXED: {result.warnings_fixed}")
    print(f"SUCCESS: {result.success}")


def demo_performance():
    """Demonstrate performance characteristics."""
    print("\n" + "=" * 60)
    print("DEMO: Performance Benchmark")
    print("=" * 60)

    import time

    # Generate sample code
    sample_code = """from pydantic import BaseModel

class ModelTest(BaseModel):
    value: str
"""

    fixer = WarningFixer()

    # Benchmark
    iterations = 100
    start_time = time.time()

    for _ in range(iterations):
        _ = fixer.fix_all_warnings(sample_code)

    end_time = time.time()
    duration = end_time - start_time
    avg_time_ms = (duration / iterations) * 1000

    print(f"\nBenchmark Results ({iterations} iterations):")
    print(f"  Total time: {duration:.3f}s")
    print(f"  Average time: {avg_time_ms:.2f}ms")
    print(f"  Throughput: {iterations / duration:.0f} fixes/second")
    print("\nComparison:")
    print(f"  Automatic fixes: ~{avg_time_ms:.1f}ms")
    print("  AI refinement: ~2000-5000ms")
    print(f"  Speed advantage: {2000 / avg_time_ms:.0f}x faster")


def main():
    """Run all demos."""
    print("\n" + "=" * 60)
    print("WARNING FIXER DEMONSTRATION")
    print("Automatic fixes for G12, G13, G14 validation warnings")
    print("=" * 60)

    # Run individual demos
    demo_g12_pydantic_fixes()
    demo_g13_type_hint_fixes()
    demo_g14_import_fixes()
    demo_full_pipeline()
    demo_performance()

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Review fixes in each demo")
    print("  2. Run unit tests: pytest agents/tests/test_warning_fixer.py")
    print("  3. Integrate with generation pipeline")
    print("  4. Monitor fix success rates in production")
    print("\n")


if __name__ == "__main__":
    main()
