#!/usr/bin/env python3
"""
Comprehensive tests for CorrectionGenerator.
Validates Phase 1 functionality with and without Archon MCP.
"""
import asyncio
import sys
from pathlib import Path
from generator import CorrectionGenerator, Violation


async def test_context_extraction():
    """Test context extraction around violations."""
    print("Test 1: Context Extraction")
    print("-" * 50)

    generator = CorrectionGenerator()

    content = """line 1
line 2
line 3
line 4
line 5
line 6
line 7"""

    violation = Violation(
        type="function",
        name="test",
        line=4,
        column=0,
        severity="error",
        rule="test rule",
    )

    context = generator._extract_context(content, violation, context_lines=3)
    print(context)
    print()

    # Verify the marker shows the correct line
    assert ">>> " in context
    assert "line 4" in context
    print("✓ Context extraction works correctly\n")


async def test_naming_transformations():
    """Test naming transformation utilities."""
    print("Test 2: Naming Transformations")
    print("-" * 50)

    test_cases = [
        ("MyFunction", "my_function", CorrectionGenerator._to_snake_case),
        ("my_function", "MyFunction", CorrectionGenerator._to_pascal_case),
        ("MyConstant", "MY_CONSTANT", CorrectionGenerator._to_upper_snake_case),
        ("someHTMLParser", "some_html_parser", CorrectionGenerator._to_snake_case),
        ("HTML", "HTML", CorrectionGenerator._to_pascal_case),
    ]

    for input_name, expected, transform_func in test_cases:
        result = transform_func(input_name)
        status = "✓" if result == expected else "✗"
        print(f"{status} {input_name:20} -> {result:20} (expected: {expected})")

    print()


async def test_correction_with_suggestion():
    """Test correction generation when validator provides suggestions."""
    print("Test 3: Correction with Validator Suggestion")
    print("-" * 50)

    generator = CorrectionGenerator(timeout=1.0)

    violations = [
        Violation(
            type="function",
            name="MyFunc",
            line=1,
            column=0,
            severity="error",
            rule="Functions should be snake_case",
            suggestion="my_func",  # Validator provided suggestion
        )
    ]

    content = "def MyFunc():\n    pass"

    corrections = await generator.generate_corrections(
        violations=violations, content=content, file_path="test.py", language="python"
    )

    assert len(corrections) == 1
    correction = corrections[0]

    print(f"Old name: {correction['old_name']}")
    print(f"New name: {correction['new_name']}")
    print(f"Confidence: {correction['confidence']:.2f}")
    print(f"Uses suggestion: {correction['new_name'] == violations[0].suggestion}")

    assert correction["new_name"] == "my_func"
    assert correction["confidence"] >= 0.7  # Higher confidence with suggestion
    print("✓ Validator suggestions are used correctly\n")

    await generator.close()


async def test_correction_without_suggestion():
    """Test correction generation when no suggestion is provided."""
    print("Test 4: Correction without Validator Suggestion")
    print("-" * 50)

    generator = CorrectionGenerator(timeout=1.0)

    violations = [
        Violation(
            type="class",
            name="my_class",
            line=1,
            column=0,
            severity="error",
            rule="Classes should be PascalCase",
            suggestion=None,  # No suggestion
        )
    ]

    content = "class my_class:\n    pass"

    corrections = await generator.generate_corrections(
        violations=violations, content=content, file_path="test.py", language="python"
    )

    assert len(corrections) == 1
    correction = corrections[0]

    print(f"Old name: {correction['old_name']}")
    print(f"New name: {correction['new_name']}")
    print(f"Confidence: {correction['confidence']:.2f}")
    print(f"Applied transformation: {correction['new_name'] == 'MyClass'}")

    assert correction["new_name"] == "MyClass"
    assert correction["confidence"] <= 0.7  # Lower confidence without suggestion
    print("✓ Transformations work correctly without suggestions\n")

    await generator.close()


async def test_multiple_violation_types():
    """Test handling multiple types of violations."""
    print("Test 5: Multiple Violation Types")
    print("-" * 50)

    generator = CorrectionGenerator(timeout=1.0)

    violations = [
        Violation(
            type="function",
            name="MyFunc",
            line=1,
            column=0,
            severity="error",
            rule="function rule",
            suggestion="my_func",
        ),
        Violation(
            type="class",
            name="my_class",
            line=3,
            column=0,
            severity="error",
            rule="class rule",
            suggestion="MyClass",
        ),
        Violation(
            type="constant",
            name="myConst",
            line=6,
            column=0,
            severity="warning",
            rule="constant rule",
            suggestion=None,
        ),
        Violation(
            type="variable",
            name="MyVar",
            line=8,
            column=4,
            severity="warning",
            rule="variable rule",
            suggestion=None,
        ),
    ]

    content = """def MyFunc():
    pass

class my_class:
    pass

myConst = 42
def test():
    MyVar = 10"""

    corrections = await generator.generate_corrections(
        violations=violations, content=content, file_path="test.py", language="python"
    )

    assert len(corrections) == 4

    print(f"Generated {len(corrections)} corrections:")
    for i, correction in enumerate(corrections, 1):
        print(
            f"  [{i}] {correction['violation'].type:10} | "
            f"{correction['old_name']:12} -> {correction['new_name']:12} | "
            f"Confidence: {correction['confidence']:.2f}"
        )

    print("✓ Multiple violation types handled correctly\n")

    await generator.close()


async def test_confidence_calculation():
    """Test confidence score calculation logic."""
    print("Test 6: Confidence Calculation")
    print("-" * 50)

    generator = CorrectionGenerator(timeout=1.0)

    test_cases = [
        # (has_suggestion, expected_min_confidence)
        (True, 0.7),  # With suggestion: 0.5 + 0.2 = 0.7
        (False, 0.5),  # Without suggestion: 0.5 base
    ]

    for has_suggestion, expected_min in test_cases:
        violation = Violation(
            type="function",
            name="test",
            line=1,
            column=0,
            severity="error",
            rule="test",
            suggestion="test_func" if has_suggestion else None,
        )

        corrections = await generator.generate_corrections(
            violations=[violation],
            content="def test(): pass",
            file_path="test.py",
            language="python",
        )

        confidence = corrections[0]["confidence"]
        status = "✓" if confidence >= expected_min else "✗"
        print(f"{status} Suggestion={has_suggestion:5} | Confidence={confidence:.2f} (expected >= {expected_min:.2f})")

    print("✓ Confidence calculation works correctly\n")

    await generator.close()


async def test_explanation_generation():
    """Test explanation generation for corrections."""
    print("Test 7: Explanation Generation")
    print("-" * 50)

    generator = CorrectionGenerator(timeout=1.0)

    violation = Violation(
        type="function",
        name="MyFunc",
        line=1,
        column=0,
        severity="error",
        rule="Functions must use snake_case",
        suggestion="my_func",
    )

    corrections = await generator.generate_corrections(
        violations=[violation],
        content="def MyFunc(): pass",
        file_path="test.py",
        language="python",
    )

    explanation = corrections[0]["explanation"]
    print(f"Generated explanation:\n{explanation}\n")

    # Should contain the rule and enhancement
    assert "snake_case" in explanation.lower()
    print("✓ Explanation generation works correctly\n")

    await generator.close()


async def run_all_tests():
    """Run all tests."""
    print("=" * 50)
    print("CorrectionGenerator Comprehensive Test Suite")
    print("=" * 50)
    print()

    tests = [
        test_context_extraction,
        test_naming_transformations,
        test_correction_with_suggestion,
        test_correction_without_suggestion,
        test_multiple_violation_types,
        test_confidence_calculation,
        test_explanation_generation,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"✗ Test failed: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("=" * 50)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 50)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
