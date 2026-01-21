#!/usr/bin/env python3
"""
Test Manifest Generation with Pattern Inclusion

Validates that the task classifier fix properly includes patterns section
in manifest generation for implementation tasks.

Usage:
    python3 scripts/test_manifest_generation_with_patterns.py
    python3 scripts/test_manifest_generation_with_patterns.py --prompt "custom prompt"
    python3 scripts/test_manifest_generation_with_patterns.py --verbose
"""

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.lib.manifest_injector import ManifestInjector
from agents.lib.task_classifier import TaskClassifier, TaskIntent


def setup_logging(verbose: bool = False):
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s:%(name)s:%(message)s")


async def test_task_classifier(prompt: str) -> tuple[TaskIntent, float]:
    """Test task classifier with given prompt."""
    classifier = TaskClassifier()
    result = classifier.classify(prompt)
    return result.primary_intent, result.confidence


async def test_manifest_generation(prompt: str, verbose: bool = False) -> dict:
    """
    Generate manifest and analyze results.

    Returns:
        dict with keys:
            - manifest: Full manifest text
            - patterns_included: bool
            - pattern_count: int
            - sections_included: list[str]
            - intent: TaskIntent
            - confidence: float
    """
    # Test classifier first
    intent, confidence = await test_task_classifier(prompt)

    # Generate manifest
    injector = ManifestInjector()
    correlation_id = str(uuid.uuid4())

    manifest = await injector.generate_dynamic_manifest_async(
        correlation_id=correlation_id,
        user_prompt=prompt,
        force_refresh=True,
    )

    # Analyze manifest structure (it's a dict, not formatted text)
    manifest_text = str(manifest)

    # Check if patterns key exists and has patterns
    patterns_included = False
    pattern_count = 0
    if isinstance(manifest, dict) and "patterns" in manifest:
        patterns_data = manifest.get("patterns", {})
        if isinstance(patterns_data, dict):
            available_patterns = patterns_data.get("available", [])
            if available_patterns and len(available_patterns) > 0:
                patterns_included = True
                pattern_count = len(available_patterns)

    # Extract sections (if present in manifest)
    sections_included = []
    if "Selected sections:" in manifest_text:
        # Parse from manifest text
        pass

    return {
        "manifest": manifest,
        "manifest_text": manifest_text,
        "patterns_included": patterns_included,
        "pattern_count": pattern_count,
        "sections_included": sections_included,
        "intent": intent,
        "confidence": confidence,
    }


def print_results(prompt: str, results: dict, verbose: bool = False):
    """Print test results in a formatted way."""
    print("=" * 70)
    print("MANIFEST GENERATION TEST")
    print("=" * 70)

    print(f"\n📝 User Prompt: '{prompt}'")
    print("\n🤖 Task Classification:")
    print(f"   Intent: {results['intent'].value}")
    print(f"   Confidence: {results['confidence']:.2f}")

    print("\n📊 Manifest Analysis:")
    patterns_status = "✅" if results["patterns_included"] else "❌"
    print(
        f"   {patterns_status} Patterns section included: {results['patterns_included']}"
    )
    print(f"   📈 Pattern references found: {results['pattern_count']}")

    if verbose:
        print("\n📄 Full Manifest Preview:")
        print("-" * 70)
        manifest_preview = results["manifest_text"][:2000]
        print(manifest_preview)
        if len(results["manifest_text"]) > 2000:
            print(
                f"\n... (truncated, total length: {len(results['manifest_text'])} chars)"
            )
        print("-" * 70)

    print("\n" + "=" * 70)
    if results["patterns_included"]:
        print("✅ TEST PASSED: Patterns section included in manifest!")
        print(
            f"   Task classifier: {results['intent'].value} (confidence: {results['confidence']:.2f})"
        )
        print(f"   Pattern references: {results['pattern_count']}")
    else:
        print("❌ TEST FAILED: Patterns section missing from manifest")
        print(
            f"   Task classifier: {results['intent'].value} (confidence: {results['confidence']:.2f})"
        )
        print("   Expected: IMPLEMENT/REFACTOR/TEST intent for patterns inclusion")
    print("=" * 70)


async def main():
    """Main test execution."""
    parser = argparse.ArgumentParser(
        description="Test manifest generation with pattern inclusion"
    )
    parser.add_argument(
        "--prompt",
        default="ONEX authentication system",
        help="User prompt to test (default: 'ONEX authentication system')",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output including full manifest preview",
    )
    parser.add_argument(
        "--test-cases",
        action="store_true",
        help="Run multiple test cases instead of single prompt",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.test_cases:
        # Test multiple cases
        test_cases = [
            ("ONEX authentication system", TaskIntent.IMPLEMENT),
            ("user authentication component", TaskIntent.IMPLEMENT),
            ("API endpoint for orders", TaskIntent.IMPLEMENT),
            ("create user service", TaskIntent.IMPLEMENT),
            ("test authentication system", TaskIntent.TEST),
            ("fix authentication error", TaskIntent.DEBUG),
            ("what is the architecture", TaskIntent.RESEARCH),
        ]

        print("=" * 70)
        print("RUNNING MULTIPLE TEST CASES")
        print("=" * 70)

        passed = 0
        failed = 0

        for prompt, expected_intent in test_cases:
            print(f"\n📝 Testing: '{prompt}'")
            results = await test_manifest_generation(prompt, verbose=False)

            # For IMPLEMENT/REFACTOR/TEST, patterns should be included
            should_have_patterns = expected_intent in [
                TaskIntent.IMPLEMENT,
                TaskIntent.REFACTOR,
                TaskIntent.TEST,
            ]

            is_correct = (
                results["intent"] == expected_intent
                and results["patterns_included"] == should_have_patterns
            )

            status = "✅" if is_correct else "❌"
            print(
                f"{status} Intent: {results['intent'].value}, Patterns: {results['patterns_included']}"
            )

            if is_correct:
                passed += 1
            else:
                failed += 1

        print("\n" + "=" * 70)
        print(f"RESULTS: {passed}/{len(test_cases)} tests passed")
        print("=" * 70)

        return 0 if failed == 0 else 1

    else:
        # Single test case
        results = await test_manifest_generation(args.prompt, args.verbose)
        print_results(args.prompt, results, args.verbose)

        return 0 if results["patterns_included"] else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️ Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
