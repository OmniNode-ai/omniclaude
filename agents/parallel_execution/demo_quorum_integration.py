#!/usr/bin/env python3
"""
Demo: Quorum Validation Integration in Dispatch Runner

Shows how the quorum validation system catches the PostgreSQL adapter failure.

This is a simplified demonstration that shows:
1. How quorum validation is integrated into dispatch_runner.py
2. The PostgreSQL adapter failure case that motivated this feature
3. How to use the --enable-quorum flag

NOTE: Full test requires GEMINI_API_KEY and Ollama models to be running.
"""

import json
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))


def demonstrate_failure_case():
    """Show the PostgreSQL adapter failure that quorum catches"""

    print("=" * 70)
    print("DEMONSTRATION: PostgreSQL Adapter Failure Detection")
    print("=" * 70)
    print()

    print("User Request:")
    print("  'Build a postgres adapter effect node that takes kafka event")
    print("   bus events and turns them into postgres api calls'")
    print()

    print("Bad Breakdown Generated (Without Validation):")
    bad_breakdown = {
        "node_type": "Compute",  # WRONG! Should be Effect
        "name": "UserAuthentication",  # WRONG! Should be PostgreSQLAdapter
        "description": "Contract for user authentication operations",  # WRONG domain
        "input_model": {
            "username": {"type": "str"},
            "password": {"type": "str"},
        },
    }
    print(json.dumps(bad_breakdown, indent=2))
    print()

    print("Issues with this breakdown:")
    print("  ✗ Node Type: Compute (should be Effect - PostgreSQL is I/O)")
    print("  ✗ Name: UserAuthentication (should be PostgreSQLAdapter)")
    print("  ✗ Description: User auth (should be database operations)")
    print("  ✗ Missing: Kafka event bus integration")
    print()

    print("Without Quorum Validation:")
    print("  → dispatch_runner.py would execute this bad breakdown")
    print("  → agent-coder would generate wrong code")
    print("  → Result: UserAuthentication code instead of PostgreSQLAdapter")
    print("  → Wasted time: ~5-10 minutes of parallel execution")
    print()

    print("With Quorum Validation (--enable-quorum):")
    print("  → Phase 1: Quorum validates breakdown vs user intent")
    print("  → 5 AI models analyze alignment")
    print("  → Decision: RETRY or FAIL (depending on confidence)")
    print("  → Result: Execution aborted or warnings logged")
    print("  → Time saved: ~5-10 minutes + debugging time")
    print()


def demonstrate_correct_case():
    """Show what a correct breakdown looks like"""

    print("=" * 70)
    print("CORRECT BREAKDOWN (Passes Validation)")
    print("=" * 70)
    print()

    correct_breakdown = {
        "node_type": "Effect",
        "name": "PostgreSQLAdapter",
        "description": "Effect node for PostgreSQL database operations via Kafka events",
        "input_model": {
            "event_type": {"type": "str"},
            "kafka_payload": {"type": "dict"},
            "connection_params": {"type": "dict"},
        },
    }

    print("Correct Breakdown:")
    print(json.dumps(correct_breakdown, indent=2))
    print()

    print("Why this passes validation:")
    print("  ✓ Node Type: Effect (correct - database I/O)")
    print("  ✓ Name: PostgreSQLAdapter (matches user request)")
    print("  ✓ Description: Mentions both PostgreSQL and Kafka")
    print("  ✓ Input: Includes event handling (event_type, kafka_payload)")
    print()


def demonstrate_usage():
    """Show how to use the quorum validation feature"""

    print("=" * 70)
    print("USAGE EXAMPLES")
    print("=" * 70)
    print()

    print("1. Basic Dispatch (No Validation - Fast):")
    print("   echo '{\"tasks\": [...]}' | python dispatch_runner.py")
    print("   → No validation overhead")
    print("   → Use for simple/trusted tasks")
    print()

    print("2. With Quorum Validation (Recommended):")
    print("   echo '{\"tasks\": [...]}' | python dispatch_runner.py --enable-quorum")
    print("   → ~2-3s validation overhead")
    print("   → Catches intent misalignment")
    print("   → Saves time on bad breakdowns")
    print()

    print("3. Full Stack (Context + Quorum):")
    print("   python dispatch_runner.py --enable-context --enable-quorum < tasks.json")
    print("   → Phase 0: Gather global context")
    print("   → Phase 1: Validate with quorum")
    print("   → Phase 3: Filter context per task")
    print("   → Phase 4: Execute in parallel")
    print()

    print("4. Upstream Validation (Recommended for complex tasks):")
    print("   python validated_task_architect.py \"<user_prompt>\"")
    print("   → Validates AND retries automatically")
    print("   → Max 3 attempts with feedback")
    print("   → Returns validated breakdown")
    print()


def demonstrate_architecture():
    """Show the architecture of the quorum validation system"""

    print("=" * 70)
    print("ARCHITECTURE")
    print("=" * 70)
    print()

    print("Quorum Models (Total Weight: 7.5):")
    print("  1. Gemini Flash (1.0)      - Cloud baseline")
    print("  2. Codestral (1.5)         - Code specialist @ Mac Studio")
    print("  3. Mixtral 8x7B (2.0)      - Advanced reasoning")
    print("  4. Llama 3.2 (1.2)         - General validation")
    print("  5. Yi 34B (1.8)            - High-quality decisions")
    print()

    print("Decision Thresholds:")
    print("  PASS:  ≥60% weighted consensus → Proceed")
    print("  RETRY: 40-60% consensus      → Continue with warnings")
    print("  FAIL:  <40% consensus        → Abort execution")
    print()

    print("Performance:")
    print("  - All models queried in parallel")
    print("  - Total time: ~2-3 seconds")
    print("  - Overhead acceptable for quality gain")
    print()

    print("Integration Points:")
    print("  1. dispatch_runner.py        - Phase 1 validation checkpoint")
    print("  2. validated_task_architect  - Upstream validation with retry")
    print("  3. quorum_minimal.py         - Core validation logic")
    print()


def main():
    """Run demonstration"""

    print("\n" + "=" * 70)
    print("QUORUM VALIDATION INTEGRATION DEMONSTRATION")
    print("=" * 70)
    print()

    # Show the failure case
    demonstrate_failure_case()

    # Show the correct case
    demonstrate_correct_case()

    # Show usage examples
    demonstrate_usage()

    # Show architecture
    demonstrate_architecture()

    print("=" * 70)
    print("NEXT STEPS")
    print("=" * 70)
    print()
    print("1. Set up environment:")
    print("   export GEMINI_API_KEY='your-key-here'")
    print()
    print("2. Verify Ollama models are running:")
    print("   curl http://192.168.86.200:11434/api/tags")
    print()
    print("3. Run full integration test:")
    print("   python test_quorum_integration.py")
    print()
    print("4. Use in your workflow:")
    print("   python dispatch_runner.py --enable-quorum < your_tasks.json")
    print()
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
