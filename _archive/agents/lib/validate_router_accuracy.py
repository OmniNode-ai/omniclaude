#!/usr/bin/env python3
"""
Validation script to demonstrate router improvement.

Simulates queries that previously caused false positive self-transformations
and shows that the new router correctly handles them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent_router import AgentRouter


def validate_improvement():
    """
    Validate that the improved router reduces false positive self-transformations.
    """
    print("=" * 80)
    print("ROUTER IMPROVEMENT VALIDATION")
    print("=" * 80)
    print()
    print("Testing queries that should NOT trigger polymorphic-agent:")
    print("(These would have been false positives before the fix)")
    print()

    router = AgentRouter()

    # Queries that should NOT trigger polymorphic-agent
    false_positive_queries = [
        "Implement polymorphic architecture pattern in the codebase",
        "Refactor using polymorphic design principles",
        "Based on what polly suggested earlier, let's proceed",
        "The polymorphic approach works well here",
        "Review polymorphism implementation in Python",
        "Pollyanna principle applies to UX design",
        "Using polymorphic relationships in database",
        "Create polymorphic serializer for Django",
        "Implement polymorphic associations in Rails",
        "The poly-fill library handles browser compatibility",
    ]

    false_positive_count = 0
    correct_handling_count = 0

    for query in false_positive_queries:
        recommendations = router.route(query, max_recommendations=3)

        # Check if polymorphic-agent is in top recommendation
        if recommendations and recommendations[0].agent_name == "polymorphic-agent":
            status = "❌ FALSE POSITIVE"
            false_positive_count += 1
        else:
            status = "✅ CORRECTLY HANDLED"
            correct_handling_count += 1

        print(f"{status}: '{query}'")
        if recommendations:
            print(
                f"  → Routed to: {recommendations[0].agent_name} ({recommendations[0].confidence.total:.1%})"
            )
        else:
            print("  → No match (correct - no specialized agent needed)")
        print()

    print("=" * 80)
    print("Testing queries that SHOULD trigger polymorphic-agent:")
    print("(These are legitimate agent invocations)")
    print()

    # Queries that SHOULD trigger polymorphic-agent
    true_positive_queries = [
        "use poly agent to coordinate this workflow",
        "spawn polly for multi-agent task",
        "dispatch to polymorphic agent",
        "coordinate with polly",
        "poly, please orchestrate this",
        "use polymorphic agent to handle coordination",
    ]

    true_positive_count = 0
    missed_count = 0

    for query in true_positive_queries:
        recommendations = router.route(query, max_recommendations=3)

        # Check if polymorphic-agent is in top recommendation
        if recommendations and recommendations[0].agent_name == "polymorphic-agent":
            status = "✅ CORRECTLY MATCHED"
            true_positive_count += 1
        else:
            status = "❌ MISSED"
            missed_count += 1

        print(f"{status}: '{query}'")
        if recommendations:
            print(
                f"  → Routed to: {recommendations[0].agent_name} ({recommendations[0].confidence.total:.1%})"
            )
        else:
            print("  → No match (incorrect - should match polymorphic-agent)")
        print()

    print("=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    print()

    total_false_positive_tests = len(false_positive_queries)
    total_true_positive_tests = len(true_positive_queries)

    print("False Positive Handling (should NOT trigger polymorphic-agent):")
    print(f"  Correct: {correct_handling_count}/{total_false_positive_tests}")
    print(f"  False Positives: {false_positive_count}/{total_false_positive_tests}")
    print(
        f"  Success Rate: {correct_handling_count / total_false_positive_tests * 100:.1f}%"
    )
    print()

    print("True Positive Matching (SHOULD trigger polymorphic-agent):")
    print(f"  Correct: {true_positive_count}/{total_true_positive_tests}")
    print(f"  Missed: {missed_count}/{total_true_positive_tests}")
    print(
        f"  Success Rate: {true_positive_count / total_true_positive_tests * 100:.1f}%"
    )
    print()

    overall_correct = correct_handling_count + true_positive_count
    overall_total = total_false_positive_tests + total_true_positive_tests

    print("Overall Performance:")
    print(f"  Correct: {overall_correct}/{overall_total}")
    print(f"  Accuracy: {overall_correct / overall_total * 100:.1f}%")
    print()

    # Estimate improvement
    print("Estimated Impact:")
    print("  Previous self-transformation rate: 48.78% (from database query)")
    print(
        f"  False positive elimination rate: {correct_handling_count / total_false_positive_tests * 100:.1f}%"
    )
    print(
        "  Expected new self-transformation rate: <10% (legitimate coordination only)"
    )
    print()

    if (
        correct_handling_count == total_false_positive_tests
        and true_positive_count == total_true_positive_tests
    ):
        print("✅ SUCCESS: Router improvements validated - all tests passed!")
        return True
    else:
        print("⚠️  WARNING: Some tests failed - router may need further tuning")
        return False


if __name__ == "__main__":
    success = validate_improvement()
    sys.exit(0 if success else 1)
