#!/usr/bin/env python3
"""
Test script to verify agent routing pattern word boundary fixes.

This script tests that:
1. Legitimate agent invocations are matched correctly
2. False positives (like "misuse an agent") are rejected
3. Both TriggerMatcher and AgentRouter handle word boundaries correctly
"""

import sys
from pathlib import Path

# Add agents/lib to path
sys.path.insert(0, str(Path(__file__).parent / "agents" / "lib"))

from agent_router import AgentRouter
from trigger_matcher import TriggerMatcher


def test_trigger_matcher():
    """Test TriggerMatcher word boundary logic directly."""
    print("=" * 70)
    print("Testing TriggerMatcher Word Boundaries")
    print("=" * 70)

    # Load registry
    registry_path = (
        Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"
    )

    import yaml

    with open(registry_path) as f:
        registry = yaml.safe_load(f)

    matcher = TriggerMatcher(registry)

    # Test cases: (trigger, text, should_match, description)
    test_cases = [
        # Positive cases - should match
        (
            "use an agent",
            "please use an agent",
            True,
            "Legitimate 'use an agent' invocation",
        ),
        (
            "use an agent",
            "I want to use an agent",
            True,
            "Legitimate 'use an agent' at end",
        ),
        (
            "spawn an agent",
            "spawn an agent for this",
            True,
            "Legitimate 'spawn an agent' at start",
        ),
        (
            "spawn an agent",
            "I need to spawn an agent",
            True,
            "Legitimate 'spawn an agent' in middle",
        ),
        ("call an agent", "call an agent to help", True, "Legitimate 'call an agent'"),
        (
            "invoke an agent",
            "please invoke an agent",
            True,
            "Legitimate 'invoke an agent'",
        ),
        # Negative cases - should NOT match (false positives)
        ("use an agent", "misuse an agent", False, "False positive: 'misuse an agent'"),
        ("use an agent", "reuse an agent", False, "False positive: 'reuse an agent'"),
        ("use an agent", "abuse an agent", False, "False positive: 'abuse an agent'"),
        (
            "spawn an agent",
            "respawn an agent",
            False,
            "False positive: 'respawn an agent'",
        ),
        (
            "spawn an agent",
            "because an agent",
            False,
            "False positive: 'because an agent'",
        ),
        ("poly", "polymorphic", False, "False positive: 'poly' in 'polymorphic'"),
        ("poly", "pollyanna", False, "False positive: 'poly' in 'pollyanna'"),
        # Edge cases
        ("use an agent", "Use An Agent", True, "Case insensitive match"),
        ("use an agent", "use an agenta", False, "Should not match partial word"),
        ("use an agent", "ause an agent", False, "Should not match without word start"),
    ]

    passed = 0
    failed = 0

    for trigger, text, expected_match, description in test_cases:
        result = matcher._exact_match_with_word_boundaries(trigger, text.lower())

        if result == expected_match:
            status = "✓ PASS"
            passed += 1
        else:
            status = "✗ FAIL"
            failed += 1

        print(f"\n{status}: {description}")
        print(f"  Trigger: '{trigger}'")
        print(f"  Text: '{text}'")
        print(f"  Expected: {'match' if expected_match else 'no match'}")
        print(f"  Got: {'match' if result else 'no match'}")

    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed} tests")
    print("=" * 70)

    return failed == 0


def test_agent_router():
    """Test AgentRouter end-to-end."""
    print("\n" + "=" * 70)
    print("Testing AgentRouter End-to-End")
    print("=" * 70)

    registry_path = (
        Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"
    )
    router = AgentRouter(str(registry_path))

    # Test cases: (request, should_match_polymorphic, description)
    test_cases = [
        # Should trigger polymorphic-agent
        ("please use an agent", True, "Legitimate 'use an agent' request"),
        ("I want to spawn an agent", True, "Legitimate 'spawn an agent' request"),
        ("call an agent to help", True, "Legitimate 'call an agent' request"),
        # Should NOT trigger polymorphic-agent (false positives)
        ("don't misuse an agent", False, "Should not match 'misuse an agent'"),
        ("how to respawn an agent", False, "Should not match 'respawn an agent'"),
        ("because an agent failed", False, "Should not match 'because an agent'"),
    ]

    passed = 0
    failed = 0

    for request, should_match, description in test_cases:
        # Try to extract explicit agent
        extracted_agent = router._extract_explicit_agent(request)

        matched = extracted_agent == "polymorphic-agent"

        if matched == should_match:
            status = "✓ PASS"
            passed += 1
        else:
            status = "✗ FAIL"
            failed += 1

        print(f"\n{status}: {description}")
        print(f"  Request: '{request}'")
        print(f"  Expected: {'polymorphic-agent' if should_match else 'no match'}")
        print(f"  Got: {extracted_agent or 'no match'}")

    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed} tests")
    print("=" * 70)

    return failed == 0


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("AGENT ROUTING WORD BOUNDARY FIX - VALIDATION TESTS")
    print("=" * 70)
    print("\nThis test validates that agent routing patterns use word boundaries")
    print("to prevent false positives like 'misuse an agent' matching 'use an agent'.")
    print("")

    success = True

    try:
        # Test TriggerMatcher directly
        if not test_trigger_matcher():
            success = False
            print("\n⚠️  TriggerMatcher tests FAILED")
        else:
            print("\n✓ TriggerMatcher tests PASSED")

        # Test AgentRouter end-to-end
        if not test_agent_router():
            success = False
            print("\n⚠️  AgentRouter tests FAILED")
        else:
            print("\n✓ AgentRouter tests PASSED")

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback

        traceback.print_exc()
        success = False

    print("\n" + "=" * 70)
    if success:
        print("✓ ALL TESTS PASSED - Word boundary fix is working correctly!")
        print("=" * 70)
        return 0
    else:
        print("✗ SOME TESTS FAILED - Review output above for details")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
