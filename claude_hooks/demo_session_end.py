#!/usr/bin/env python3
"""
Demo script showcasing SessionEnd hook capabilities

Demonstrates:
- Session statistics aggregation
- Workflow pattern classification
- Quality score calculation
- Database integration
"""

import sys
import os
import json
from datetime import datetime

# Add hooks lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

from session_intelligence import query_session_statistics, classify_workflow_pattern, log_session_end

def demo_statistics():
    """Demonstrate session statistics aggregation."""
    print("=" * 60)
    print("Session Statistics Aggregation Demo")
    print("=" * 60)
    print()

    # Query current session statistics
    stats = query_session_statistics()

    print(f"Session Duration: {stats['duration_seconds']}s ({stats['duration_seconds'] // 60} minutes)")
    print(f"Total Prompts: {stats['total_prompts']}")
    print(f"Total Tools: {stats['total_tools']}")
    print()

    if stats['agents_invoked']:
        print(f"Agents Invoked: {', '.join(stats['agents_invoked'])}")
        print("\nAgent Usage Breakdown:")
        for agent, count in stats['agent_usage'].items():
            print(f"  - {agent}: {count} invocations")
        print()

    if stats['tool_breakdown']:
        print("Tool Usage Breakdown:")
        for tool, count in sorted(stats['tool_breakdown'].items(), key=lambda x: x[1], reverse=True):
            print(f"  - {tool}: {count} uses")
        print()

    return stats


def demo_workflow_classification(stats):
    """Demonstrate workflow pattern classification."""
    print("=" * 60)
    print("Workflow Pattern Classification Demo")
    print("=" * 60)
    print()

    pattern = classify_workflow_pattern(stats)

    print(f"Detected Workflow Pattern: {pattern}")
    print()

    # Explain classification
    explanations = {
        "debugging": "Session involves debugging/testing activities",
        "feature_development": "Session focused on implementing new features",
        "refactoring": "Session dedicated to code refactoring/optimization",
        "specialized_task": "Single-agent specialized workflow",
        "exploratory": "Multi-agent exploratory session",
        "exploration": "Code browsing and exploration (read-heavy)",
        "direct_interaction": "Direct code editing (write-heavy)"
    }

    print(f"Explanation: {explanations.get(pattern, 'Unknown pattern')}")
    print()

    return pattern


def demo_quality_score(stats):
    """Demonstrate quality score calculation."""
    print("=" * 60)
    print("Session Quality Score Demo")
    print("=" * 60)
    print()

    # Calculate quality score (same logic as log_session_end)
    quality_score = 0.5  # baseline

    if stats["total_prompts"] > 0:
        tools_per_prompt = stats["total_tools"] / stats["total_prompts"]
        print(f"Tools per Prompt: {tools_per_prompt:.2f}")

        if tools_per_prompt < 3:
            quality_score += 0.2
            print("  ✓ Efficient tool usage (+0.2)")
        elif tools_per_prompt < 5:
            quality_score += 0.1
            print("  ✓ Moderate tool usage (+0.1)")
        else:
            print("  ⚠ High tool usage (no bonus)")

    if len(stats.get("agents_invoked", [])) > 1:
        quality_score += 0.2
        print("  ✓ Multi-agent coordination (+0.2)")

    quality_score = min(1.0, quality_score)

    print()
    print(f"Final Quality Score: {quality_score:.2f} / 1.00")
    print()

    # Quality interpretation
    if quality_score >= 0.8:
        print("Interpretation: Excellent session efficiency")
    elif quality_score >= 0.6:
        print("Interpretation: Good session productivity")
    elif quality_score >= 0.4:
        print("Interpretation: Average session performance")
    else:
        print("Interpretation: Room for improvement")

    print()

    return quality_score


def demo_full_session_end():
    """Demonstrate complete session end logging."""
    print("=" * 60)
    print("Full Session End Logging Demo")
    print("=" * 60)
    print()

    print("Logging session end to database...")
    event_id = log_session_end(
        session_id="demo-session-001",
        additional_metadata={"demo_mode": True, "timestamp": datetime.now().isoformat()}
    )

    if event_id:
        print(f"\n✅ Session successfully logged with ID: {event_id}")
        print("\nVerify in database:")
        print(f"  SELECT * FROM hook_events WHERE id = '{event_id}';")
    else:
        print("\n❌ Failed to log session")

    print()


def main():
    """Run all demos."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "SessionEnd Hook - Feature Demo" + " " * 18 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    try:
        # Demo 1: Statistics
        stats = demo_statistics()

        # Demo 2: Classification
        pattern = demo_workflow_classification(stats)

        # Demo 3: Quality Score
        quality = demo_quality_score(stats)

        # Demo 4: Full Logging
        demo_full_session_end()

        # Summary
        print("=" * 60)
        print("Demo Summary")
        print("=" * 60)
        print()
        print(f"  Session Duration: {stats['duration_seconds']}s")
        print(f"  Total Prompts: {stats['total_prompts']}")
        print(f"  Total Tools: {stats['total_tools']}")
        print(f"  Workflow Pattern: {pattern}")
        print(f"  Quality Score: {quality:.2f}")
        print()
        print("✅ All SessionEnd hook features demonstrated successfully!")
        print()

    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
