#!/usr/bin/env python3
"""
Test Archon Pattern Scoring P0 Fix

Verifies that:
1. Quality scores are extracted from source_context.quality_score (0.9, not 0.0)
2. Semantic scores are extracted from Qdrant vector search (point.score)
3. Patterns score differently based on relevance
4. ArchonHybridScorer produces meaningful differentiation

Usage:
    python3 test_archon_pattern_scoring_fix.py
"""

import asyncio
import sys
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"✅ Loaded environment from {env_path}")
else:
    print(f"⚠️  .env file not found at {env_path}, using existing environment")

# Add agents/lib to path
lib_path = Path(__file__).parent / "agents" / "lib"
sys.path.insert(0, str(lib_path))

from manifest_injector import ManifestInjector  # noqa: E402
from task_classifier import TaskClassifier  # noqa: E402


async def test_pattern_scoring():
    """Test pattern scoring with real Qdrant patterns"""
    print("=" * 80)
    print("ARCHON PATTERN SCORING P0 FIX TEST")
    print("=" * 80)
    print()

    # Test user prompts with different relevance levels
    test_cases = [
        {
            "prompt": "Create an LLM effect node for making API calls",
            "expected_keywords": ["llm", "effect", "node", "api"],
            "description": "Should match Effect node patterns with high semantic score",
        },
        {
            "prompt": "Implement error handling for database operations",
            "expected_keywords": ["error", "handling", "database"],
            "description": "Should match error handling patterns",
        },
        {
            "prompt": "Write unit tests for a Python function",
            "expected_keywords": ["test", "unit", "python"],
            "description": "Should match testing patterns",
        },
    ]

    classifier = TaskClassifier()
    injector = ManifestInjector()

    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest Case {i}: {test_case['description']}")
        print(f"Prompt: \"{test_case['prompt']}\"")
        print("-" * 80)

        # Classify task
        task_context = classifier.classify(test_case["prompt"])
        print(f"Task Classification: {task_context.primary_intent.value}")
        print(f"Context Keywords: {task_context.keywords}")

        # Query patterns with semantic search
        correlation_id = f"test-{i}"
        patterns_result = await injector._query_patterns_direct_qdrant(
            correlation_id=correlation_id,
            collections=["archon_vectors"],
            limit_per_collection=10,
            task_context=task_context,
            user_prompt=test_case["prompt"],
        )

        patterns = patterns_result.get("patterns", [])
        query_time = patterns_result.get("query_time_ms", 0)

        print("\nQuery Results:")
        print(f"  Patterns Retrieved: {len(patterns)}")
        print(f"  Query Time: {query_time}ms")

        if not patterns:
            print("  ⚠️  No patterns found!")
            continue

        # Show top 5 patterns with scoring details
        print("\nTop 5 Patterns (sorted by semantic similarity):")
        for j, pattern in enumerate(patterns[:5], 1):
            metadata = pattern.get("metadata", {})
            print(f"\n  {j}. {pattern.get('name', 'Unknown')}")
            print(f"     Pattern Type: {pattern.get('pattern_type', 'N/A')}")
            print(f"     Node Type: {metadata.get('node_type', 'N/A')}")
            print(f"     Keywords: {pattern.get('keywords', [])[:5]}")
            print("     Scoring:")
            print(
                f"       • Quality Score: {metadata.get('quality_score', 0.0):.3f} (from source_context)"
            )
            print(
                f"       • Semantic Score: {metadata.get('semantic_score', 0.0):.3f} (from vector search)"
            )
            print(f"       • Success Rate: {metadata.get('success_rate', 0.0):.3f}")
            print(f"       • Confidence: {metadata.get('confidence_score', 0.0):.3f}")

        # Verify differentiation
        semantic_scores = [
            p.get("metadata", {}).get("semantic_score", 0.0) for p in patterns
        ]
        quality_scores = [
            p.get("metadata", {}).get("quality_score", 0.0) for p in patterns
        ]

        unique_semantic = len(set(semantic_scores))
        unique_quality = len(set(quality_scores))

        print("\n  Score Differentiation:")
        print(f"    • Unique Semantic Scores: {unique_semantic}/{len(patterns)}")
        print(f"    • Unique Quality Scores: {unique_quality}/{len(patterns)}")
        print(
            f"    • Semantic Score Range: {min(semantic_scores):.3f} - {max(semantic_scores):.3f}"
        )
        print(
            f"    • Quality Score Range: {min(quality_scores):.3f} - {max(quality_scores):.3f}"
        )

        # Check if scoring is working
        if unique_semantic > 1:
            print("    ✅ Patterns differentiated by semantic score")
        else:
            print("    ❌ All patterns have identical semantic scores")

        if unique_quality > 1:
            print("    ✅ Patterns have varying quality scores")
        else:
            print("    ⚠️  All patterns have identical quality scores")

        # Check if quality scores are extracted correctly (not 0.0)
        non_zero_quality = sum(1 for q in quality_scores if q > 0.1)
        if non_zero_quality > 0:
            print(
                f"    ✅ {non_zero_quality}/{len(patterns)} patterns have non-zero quality scores"
            )
        else:
            print("    ❌ All patterns have zero quality scores")

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


async def test_archon_hybrid_scoring():
    """Test integration with ArchonHybridScorer"""
    print("\n" + "=" * 80)
    print("ARCHON HYBRID SCORER INTEGRATION TEST")
    print("=" * 80)
    print()

    from archon_hybrid_scorer import ArchonHybridScorer

    scorer = ArchonHybridScorer()

    # Check API health
    print("Checking Archon Intelligence API health...")
    is_healthy = await scorer.health_check()
    if is_healthy:
        print("✅ Archon Intelligence API is healthy")
    else:
        print("❌ Archon Intelligence API is not responding")
        return

    # Test scoring with sample patterns
    prompt = "Create an LLM effect node for making API calls"
    classifier = TaskClassifier()
    task_context = classifier.classify(prompt)

    print(f'\nPrompt: "{prompt}"')
    print(f"Task Type: {task_context.primary_intent.value}")

    # Create test patterns with different metadata
    test_patterns = [
        {
            "name": "LLM Effect Node Pattern",
            "keywords": ["llm", "effect", "node", "api", "async"],
            "metadata": {
                "quality_score": 0.9,
                "success_rate": 0.85,
                "confidence_score": 0.8,
                "semantic_score": 0.75,  # High semantic similarity
            },
        },
        {
            "name": "Error Handling Pattern",
            "keywords": ["error", "handling", "exception", "try", "catch"],
            "metadata": {
                "quality_score": 0.8,
                "success_rate": 0.9,
                "confidence_score": 0.85,
                "semantic_score": 0.3,  # Low semantic similarity
            },
        },
        {
            "name": "Naming Convention Pattern",
            "keywords": ["naming", "convention", "method", "class"],
            "metadata": {
                "quality_score": 0.5,
                "success_rate": 1.0,
                "confidence_score": 0.75,
                "semantic_score": 0.2,  # Very low semantic similarity
            },
        },
    ]

    print("\nScoring patterns with ArchonHybridScorer...")
    scored_patterns = await scorer.score_patterns_batch(
        patterns=test_patterns, user_prompt=prompt, task_context=task_context
    )

    print("\nScoring Results:")
    for i, pattern in enumerate(scored_patterns, 1):
        print(f"\n  {i}. {pattern['name']}")
        print(f"     Hybrid Score: {pattern.get('hybrid_score', 0.0):.4f}")
        print("     Breakdown:")
        breakdown = pattern.get("score_breakdown", {})
        for key, value in breakdown.items():
            print(f"       • {key}: {value:.4f}")
        print(f"     Confidence: {pattern.get('score_confidence', 0.0):.4f}")

    # Verify scoring differentiation
    hybrid_scores = [p.get("hybrid_score", 0.0) for p in scored_patterns]
    print("\n  Score Statistics:")
    print(f"    • Range: {min(hybrid_scores):.4f} - {max(hybrid_scores):.4f}")
    print(f"    • Unique Scores: {len(set(hybrid_scores))}/{len(scored_patterns)}")

    if len(set(hybrid_scores)) == len(scored_patterns):
        print("    ✅ All patterns scored differently")
    else:
        print("    ⚠️  Some patterns have identical scores")

    print("\n" + "=" * 80)
    print("HYBRID SCORER TEST COMPLETE")
    print("=" * 80)


async def main():
    """Run all tests"""
    try:
        # Test 1: Pattern retrieval with semantic search
        await test_pattern_scoring()

        # Test 2: Archon hybrid scorer integration
        await test_archon_hybrid_scoring()

        print("\n" + "=" * 80)
        print("✅ ALL TESTS COMPLETE")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
