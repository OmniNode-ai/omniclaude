#!/usr/bin/env python3
"""
Test script to verify trigger strategy false positive fix.

Tests that "poly" and "polly" triggers only match whole words,
not partial words in casual references.
"""

import sys
from pathlib import Path

# Add agents/lib to path
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from trigger_matcher import TriggerMatcher


def load_registry():
    """Load agent registry from standard location."""
    registry_path = (
        Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"
    )
    with open(registry_path) as f:
        return yaml.safe_load(f)


def test_trigger_matching():
    """Test trigger matching with false positive and true positive cases."""
    registry = load_registry()
    matcher = TriggerMatcher(registry)

    # Test cases: (query, should_match_polymorphic_agent, description)
    test_cases = [
        # FALSE POSITIVES (should NOT trigger polymorphic-agent)
        (
            "polymorphic architecture pattern",
            False,
            "❌ FALSE POSITIVE: 'polymorphic' is part of technical term, not agent reference",
        ),
        (
            "polly suggested this approach",
            False,
            "❌ FALSE POSITIVE: 'polly' is casual reference, not agent invocation",
        ),
        (
            "the polymorphic design is good",
            False,
            "❌ FALSE POSITIVE: 'polymorphic' is adjective, not agent trigger",
        ),
        (
            "pollyanna principle in UX",
            False,
            "❌ FALSE POSITIVE: 'pollyanna' contains 'polly' but is different word",
        ),
        (
            "using polymorphism in code",
            False,
            "❌ FALSE POSITIVE: 'polymorphism' contains 'poly' but is different word",
        ),
        # TRUE POSITIVES (SHOULD trigger polymorphic-agent)
        (
            "use poly agent to coordinate",
            True,
            "✅ TRUE POSITIVE: 'poly' as standalone word referencing agent",
        ),
        (
            "dispatch to polly for workflow",
            True,
            "✅ TRUE POSITIVE: 'polly' as standalone word referencing agent",
        ),
        (
            "spawn poly for multi-agent task",
            True,
            "✅ TRUE POSITIVE: 'spawn poly' is explicit trigger",
        ),
        (
            "use polymorphic agent",
            True,
            "✅ TRUE POSITIVE: 'polymorphic agent' is explicit trigger",
        ),
        (
            "coordinate with polly",
            True,
            "✅ TRUE POSITIVE: 'polly' as agent nickname",
        ),
        (
            "poly coordinate this workflow",
            True,
            "✅ TRUE POSITIVE: 'poly' at start as agent reference",
        ),
    ]

    print("=" * 80)
    print("TRIGGER MATCHING TEST - False Positive Fix Verification")
    print("=" * 80)
    print()

    passed = 0
    failed = 0
    failures = []

    for query, should_match, description in test_cases:
        matches = matcher.match(query)

        # Check if polymorphic-agent is in top 3 matches
        polymorphic_matched = any(
            agent_name == "polymorphic-agent" for agent_name, _, _ in matches[:3]
        )

        # Determine if test passed
        test_passed = polymorphic_matched == should_match

        # Format result
        status = "✅ PASS" if test_passed else "❌ FAIL"
        match_status = "MATCHED" if polymorphic_matched else "NOT MATCHED"

        print(f"{status} | Query: '{query}'")
        print(f"       | Expected: {'MATCH' if should_match else 'NO MATCH'}")
        print(f"       | Actual: {match_status}")
        print(f"       | {description}")

        if matches[:3]:
            print(
                f"       | Top matches: {', '.join([name for name, _, _ in matches[:3]])}"
            )
        else:
            print("       | Top matches: (none)")

        print()

        if test_passed:
            passed += 1
        else:
            failed += 1
            failures.append((query, should_match, polymorphic_matched, description))

    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Total tests: {passed + failed}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} ❌")
    print(f"Success rate: {passed / (passed + failed) * 100:.1f}%")
    print()

    if failures:
        print("FAILURES:")
        for query, expected_match, actual_match, description in failures:
            print(f"  • '{query}'")
            print(f"    Expected: {'MATCH' if expected_match else 'NO MATCH'}")
            print(f"    Actual: {'MATCHED' if actual_match else 'NOT MATCHED'}")
            print(f"    {description}")
            print()

    return failed == 0


if __name__ == "__main__":
    success = test_trigger_matching()
    sys.exit(0 if success else 1)
