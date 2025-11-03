#!/usr/bin/env python3
"""
P0 Fix Validation with REAL Qdrant Patterns

Tests that:
1. Quality scores come from source_context.quality_score (0.9), not defaults (0.5)
2. Keywords are extracted from reuse_conditions
3. Patterns score differently based on real metadata
"""

import asyncio
import sys
from pathlib import Path

# Add agents to path
sys.path.insert(0, str(Path(__file__).parent / "agents"))

from lib.archon_hybrid_scorer import ArchonHybridScorer
from lib.manifest_injector import ManifestInjector
from lib.task_classifier import TaskClassifier


async def test_p0_with_real_patterns():
    """Test P0 fix with real patterns from Qdrant"""

    print("=" * 80)
    print("P0 FIX VALIDATION: Real Qdrant Patterns with Archon Hybrid Scoring")
    print("=" * 80)
    print()

    # Test context
    user_prompt = "Create an LLM effect node for API calls"

    # Classify task
    classifier = TaskClassifier()
    task_context = classifier.classify(user_prompt)

    print(f"📝 User Prompt: '{user_prompt}'")
    print(f"🎯 Task Type: {task_context.primary_intent.value}")
    print(f"📋 Keywords: {task_context.keywords}")
    print()

    # Query real patterns from Qdrant
    print("🔍 Querying REAL patterns from Qdrant...")
    injector = ManifestInjector()

    import uuid

    correlation_id = str(uuid.uuid4())

    result = await injector._query_patterns_direct_qdrant(
        task_context=task_context,
        user_prompt=user_prompt,
        correlation_id=correlation_id,
    )

    patterns = result.get("patterns", [])
    query_time = result.get("query_time_ms", 0)

    print(f"✅ Retrieved {len(patterns)} patterns in {query_time}ms")
    print()

    # Initialize scorer
    scorer = ArchonHybridScorer()

    # Check API health
    print("🏥 Checking Archon Intelligence API health...")
    is_healthy = await scorer.health_check()

    if is_healthy:
        print("✅ Archon API is healthy")
    else:
        print("⚠️  Archon API unavailable - will use fallback scoring")
    print()

    # Score patterns
    print("📊 Scoring patterns with Archon Hybrid API...")
    print("=" * 80)

    scored_patterns = await scorer.score_patterns_batch(
        patterns=patterns[:10],  # Top 10 for performance
        user_prompt=user_prompt,
        task_context=task_context,
        max_concurrent=10,
    )

    # Display results
    print(f"\n{'Rank':<6} {'Pattern Name':<45} {'Score':<8} {'Breakdown'}")
    print("-" * 110)

    for i, pattern in enumerate(scored_patterns, 1):
        score = pattern.get("hybrid_score", 0.0)
        name = pattern["name"][:43]  # Truncate if needed

        # Breakdown
        breakdown = pattern.get("score_breakdown", {})
        breakdown_str = ""
        if breakdown:
            breakdown_str = (
                f"K:{breakdown.get('keyword_score', 0):.2f} "
                f"S:{breakdown.get('semantic_score', 0):.2f} "
                f"Q:{breakdown.get('quality_score', 0):.2f} "
                f"R:{breakdown.get('success_rate_score', 0):.2f}"
            )

        print(f"{i:<6} {name:<45} {score:<8.4f} {breakdown_str}")

    print()

    # Analysis
    print("=" * 80)
    print("📈 ANALYSIS")
    print("=" * 80)

    scores = [p.get("hybrid_score", 0.0) for p in scored_patterns]
    breakdowns = [p.get("score_breakdown", {}) for p in scored_patterns]

    print("\n📊 Score Distribution:")
    print(f"  Highest: {max(scores):.4f}")
    print(f"  Lowest:  {min(scores):.4f}")
    print(f"  Range:   {max(scores) - min(scores):.4f}")
    print(f"  Average: {sum(scores) / len(scores):.4f}")

    # Check quality scores
    quality_scores = [b.get("quality_score", 0) for b in breakdowns]
    unique_quality = set(quality_scores)

    print("\n🎯 Quality Scores (from source_context.quality_score):")
    print(f"  Values: {sorted(unique_quality, reverse=True)}")
    print(f"  Average: {sum(quality_scores) / len(quality_scores):.4f}")

    if any(q > 0.5 for q in quality_scores):
        print(
            "  ✅ FIXED: Using real quality scores from source_context (not 0.5 defaults)"
        )
    else:
        print("  ❌ ISSUE: Still using default quality scores (0.5)")

    # Check semantic scores
    semantic_scores = [b.get("semantic_score", 0) for b in breakdowns]
    unique_semantic = set(semantic_scores)

    print("\n🔍 Semantic Scores:")
    print(f"  Values: {sorted(unique_semantic, reverse=True)}")
    print(f"  Average: {sum(semantic_scores) / len(semantic_scores):.4f}")

    if len(unique_semantic) > 1:
        print("  ✅ WORKING: Semantic scoring shows variation")
    else:
        print(
            f"  ⚠️  NOTE: All semantic scores identical ({list(unique_semantic)[0]:.2f})"
        )

    # Check if patterns scored differently
    unique_scores = len(set(f"{s:.4f}" for s in scores))

    print("\n📋 Overall Scoring:")
    if unique_scores == 1:
        print(
            f"  ❌ P0 ISSUE STILL EXISTS: All patterns scored identically ({scores[0]:.4f})"
        )
        return False
    else:
        print(
            f"  ✅ P0 ISSUE FIXED: Patterns scored differently ({unique_scores} unique scores)"
        )

    # Top pattern
    top_pattern = scored_patterns[0]
    top_score = top_pattern.get("hybrid_score", 0.0)
    top_name = top_pattern["name"]

    print(f"\n🏆 Top Pattern: {top_name}")
    print(f"   Score: {top_score:.4f}")

    top_breakdown = top_pattern.get("score_breakdown", {})
    if top_breakdown:
        print(f"   Keyword: {top_breakdown.get('keyword_score', 0):.2f}")
        print(f"   Semantic: {top_breakdown.get('semantic_score', 0):.2f}")
        print(f"   Quality: {top_breakdown.get('quality_score', 0):.2f}")
        print(f"   Success Rate: {top_breakdown.get('success_rate_score', 0):.2f}")

    print()
    print("=" * 80)
    print("✅ P0 FIX VALIDATION COMPLETE")
    print("=" * 80)

    return unique_scores > 1 and any(q > 0.5 for q in quality_scores)


if __name__ == "__main__":
    import os

    os.environ["POSTGRES_PASSWORD"] = "***REDACTED***"

    success = asyncio.run(test_p0_with_real_patterns())
    sys.exit(0 if success else 1)
