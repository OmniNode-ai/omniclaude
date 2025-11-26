#!/usr/bin/env python3
"""
Test script to validate polymorphic-agent.md updates.

Verifies that mandatory routing workflow is present and properly documented.
"""

from pathlib import Path


def test_polymorphic_agent_updates():
    """Test that all required sections are present in polymorphic-agent.md"""

    file_path = str(Path(__file__).parent / "polymorphic-agent.md")

    with open(file_path, "r") as f:
        content = f.read()

    # Test 1: Check for MANDATORY ROUTING WORKFLOW section
    assert (
        "MANDATORY ROUTING WORKFLOW" in content
    ), "❌ Missing: MANDATORY ROUTING WORKFLOW section"
    print("✅ Test 1 passed: MANDATORY ROUTING WORKFLOW section present")

    # Test 2: Check for AgentRouter usage
    assert "AgentRouter" in content, "❌ Missing: AgentRouter reference"
    assert (
        "from agent_router import AgentRouter" in content
    ), "❌ Missing: AgentRouter import statement"
    print("✅ Test 2 passed: AgentRouter properly documented")

    # Test 3: Check for selected_agent variable
    assert "selected_agent" in content, "❌ Missing: selected_agent variable"
    assert (
        "Save the `selected_agent` variable" in content
    ), "❌ Missing: Instruction to save selected_agent variable"
    print("✅ Test 3 passed: selected_agent variable documented")

    # Test 4: Check for validation checks
    assert "CRITICAL CHECK" in content, "❌ Missing: CRITICAL CHECK section"
    assert (
        'If both are "polymorphic-agent", you skipped routing!' in content
    ), "❌ Missing: Warning about skipping routing"
    print("✅ Test 4 passed: Validation checks present")

    # Test 5: Check for correct examples
    assert "✅" in content, "❌ Missing: Success checkmark in examples"
    assert "Frontend Task" in content, "❌ Missing: Frontend Task in examples"
    assert (
        "agent-frontend-developer" in content
    ), "❌ Missing: Frontend developer example"
    assert "agent-api-architect" in content, "❌ Missing: API architect example"
    assert (
        "agent-database-architect" in content
    ), "❌ Missing: Database architect example"
    print("✅ Test 5 passed: Correct transformation examples present")

    # Test 6: Check for incorrect example with warning
    assert "DO NOT DO THIS" in content, "❌ Missing: DO NOT DO THIS warning"
    assert (
        "--from-agent polymorphic-agent --to-agent polymorphic-agent" in content
    ), "❌ Missing: Incorrect self-transformation example"
    assert (
        "Why this is wrong" in content
    ), "❌ Missing: Explanation of why self-transformation is wrong"
    print("✅ Test 6 passed: Incorrect transformation warning present")

    # Test 7: Check for PRE-CHECK section in Logging Workflow
    assert (
        "PRE-CHECK (MANDATORY)" in content
    ), "❌ Missing: PRE-CHECK section in Logging Workflow"
    assert (
        "Did you complete the Mandatory Routing Workflow" in content
    ), "❌ Missing: Reference to Mandatory Routing Workflow in pre-check"
    print("✅ Test 7 passed: PRE-CHECK section in Logging Workflow")

    # Test 8: Check for validation in transformation logging
    assert (
        "VALIDATION: Ensure <target_agent_name> is from routing decision" in content
    ), "❌ Missing: Validation comment in transformation logging"
    assert (
        "NEVER log: --to-agent polymorphic-agent" in content
    ), "❌ Missing: Never log self-transformation warning"
    print("✅ Test 8 passed: Validation in transformation logging present")

    # Test 9: Check for Step 1, 2, 3 structure
    assert (
        "Step 1: Analyze Request and Route to Specialized Agent" in content
    ), "❌ Missing: Step 1 heading"
    assert (
        "Step 2: Log Transformation (Required)" in content
    ), "❌ Missing: Step 2 heading"
    assert "Step 3: Execute as Selected Agent" in content, "❌ Missing: Step 3 heading"
    print("✅ Test 9 passed: Three-step workflow structure present")

    # Test 10: Check for self-transformation acceptable conditions
    assert (
        "When is self-transformation acceptable?" in content
    ), "❌ Missing: Self-transformation acceptable conditions"
    assert (
        "Only after router explicitly returns no better match" in content
    ), "❌ Missing: Router no-match condition"
    print("✅ Test 10 passed: Self-transformation acceptable conditions documented")

    # Test 11: Verify markdown syntax is valid (basic check)
    # Check for balanced code fences
    python_fences = content.count("```python")
    bash_fences = content.count("```bash")
    closing_fences = content.count("```\n")

    # Note: This is a simple check - closing fences should be >= opening fences
    assert (
        closing_fences >= python_fences + bash_fences
    ), f"❌ Unbalanced code fences: {python_fences} python + {bash_fences} bash, but only {closing_fences} closing"
    print("✅ Test 11 passed: Markdown code fences balanced")

    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED!")
    print("=" * 60)
    print("\nSummary:")
    print(f"  - File: {file_path}")
    print(f"  - Total size: {len(content)} characters")
    print("  - All 11 validation checks passed")
    print("\nThe polymorphic-agent.md file has been successfully updated with:")
    print("  1. Mandatory routing workflow section")
    print("  2. Three-step routing process (Analyze → Log → Execute)")
    print("  3. Validation checks for transformation logging")
    print("  4. Correct and incorrect transformation examples")
    print("  5. PRE-CHECK section in Logging Workflow")
    print("  6. Clear warnings against self-transformation")


if __name__ == "__main__":
    try:
        test_polymorphic_agent_updates()
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        exit(1)
