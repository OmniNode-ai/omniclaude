#!/usr/bin/env python3
"""
P0 Fix Validation: Archon Hybrid Scoring Integration

Tests that patterns now score differently based on multi-dimensional relevance,
fixing the "all patterns = 0.360" problem.

Expected Results:
- Highly relevant patterns: 0.80-0.95
- Moderately relevant: 0.50-0.79
- Low relevance: 0.10-0.49
- NOT all patterns scoring identically!

Reference:
- Archon API: See omniarchon repository - docs/api/PATTERN_LEARNING_API_FOR_OMNICLAUDE.md
- Research: ARCHON_CAPABILITIES_RESEARCH.md
"""

import asyncio
import sys
from pathlib import Path

# Add agents to path
sys.path.insert(0, str(Path(__file__).parent / "agents"))

from lib.archon_hybrid_scorer import ArchonHybridScorer
from lib.task_classifier import TaskClassifier


async def test_p0_fix():
    """Test P0 fix: patterns should score differently"""

    print("=" * 80)
    print("P0 FIX VALIDATION: Archon Hybrid Scoring")
    print("=" * 80)
    print()

    # Test context: "Create an LLM effect node"
    user_prompt = "Create an LLM effect node for API calls"

    # Classify task
    classifier = TaskClassifier()
    task_context = classifier.classify(user_prompt)

    print(f"📝 User Prompt: '{user_prompt}'")
    print(f"🎯 Task Type: {task_context.primary_intent.value}")
    print(f"📋 Keywords: {task_context.keywords}")
    print()

    # Sample patterns (same as before)
    patterns = [
        {
            "name": "ONEX LLM Effect Node Pattern",
            "keywords": ["llm", "api", "effect", "node", "openai"],
            "metadata": {
                "quality_score": 0.92,
                "success_rate": 0.88,
                "confidence_score": 0.90,
            },
        },
        {
            "name": "ONEX Effect Node Pattern",
            "keywords": ["effect", "node", "api", "external"],
            "metadata": {
                "quality_score": 0.90,
                "success_rate": 0.85,
                "confidence_score": 0.88,
            },
        },
        {
            "name": "HTTP Effect Node Pattern",
            "keywords": ["http", "client", "api", "requests", "async"],
            "metadata": {
                "quality_score": 0.85,
                "success_rate": 0.80,
                "confidence_score": 0.82,
            },
        },
        {
            "name": "Event Bus Effect Pattern",
            "keywords": ["event", "bus", "kafka", "async", "publish"],
            "metadata": {
                "quality_score": 0.88,
                "success_rate": 0.82,
                "confidence_score": 0.85,
            },
        },
        {
            "name": "Model Contract Effect Pattern",
            "keywords": ["contract", "effect", "validation", "types"],
            "metadata": {
                "quality_score": 0.85,
                "success_rate": 0.78,
                "confidence_score": 0.80,
            },
        },
        {
            "name": "Database Query Pattern",
            "keywords": ["database", "sql", "query", "transaction"],
            "metadata": {
                "quality_score": 0.80,
                "success_rate": 0.75,
                "confidence_score": 0.78,
            },
        },
        {
            "name": "React Component Pattern",
            "keywords": ["react", "component", "jsx", "frontend", "ui"],
            "metadata": {
                "quality_score": 0.80,
                "success_rate": 0.75,
                "confidence_score": 0.20,
            },
        },
        {
            "name": "Data Processing Pipeline",
            "keywords": ["pipeline", "etl", "transform", "data"],
            "metadata": {
                "quality_score": 0.65,
                "success_rate": 0.70,
                "confidence_score": 0.60,
            },
        },
    ]

    # Initialize scorer
    scorer = ArchonHybridScorer()

    # Check API health first
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
        patterns=patterns,
        user_prompt=user_prompt,
        task_context=task_context,
        max_concurrent=10,
    )

    # Display results
    print(
        f"\n{'Rank':<6} {'Pattern Name':<35} {'Score':<8} {'Status':<12} {'Breakdown'}"
    )
    print("-" * 100)

    for i, pattern in enumerate(scored_patterns, 1):
        score = pattern.get("hybrid_score", 0.0)
        name = pattern["name"]

        # Color coding
        if score >= 0.8:
            status = "🟢 EXCELLENT"
        elif score >= 0.6:
            status = "🟡 GOOD"
        elif score >= 0.4:
            status = "🟠 MODERATE"
        elif score >= 0.3:
            status = "🔵 ACCEPTABLE"
        else:
            status = "❌ LOW"

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

        print(f"{i:<6} {name:<35} {score:<8.4f} {status:<12} {breakdown_str}")

    print()

    # Analysis
    print("=" * 80)
    print("📈 ANALYSIS")
    print("=" * 80)

    scores = [p.get("hybrid_score", 0.0) for p in scored_patterns]

    print("\n📊 Score Distribution:")
    print(f"  Highest: {max(scores):.4f}")
    print(f"  Lowest:  {min(scores):.4f}")
    print(f"  Range:   {max(scores) - min(scores):.4f}")
    print(f"  Average: {sum(scores) / len(scores):.4f}")

    # Check for P0 issue (all scores identical)
    unique_scores = len(set(f"{s:.4f}" for s in scores))
    if unique_scores == 1:
        print(
            f"\n❌ P0 ISSUE STILL EXISTS: All patterns scored identically ({scores[0]:.4f})"
        )
        print("   This means the hybrid scoring is not working correctly!")
        return False
    else:
        print(
            f"\n✅ P0 ISSUE FIXED: Patterns scored differently ({unique_scores} unique scores)"
        )
        print("   Hybrid scoring is working correctly!")

    # Check score range
    score_range = max(scores) - min(scores)
    if score_range < 0.2:
        print(f"\n⚠️  WARNING: Score range is small ({score_range:.4f})")
        print("   Patterns may not be differentiated enough")
    elif score_range >= 0.5:
        print(
            f"\n✅ EXCELLENT: Score range is {score_range:.4f} (good differentiation)"
        )

    # Check top pattern relevance
    top_pattern = scored_patterns[0]
    top_score = top_pattern.get("hybrid_score", 0.0)
    top_name = top_pattern["name"]

    print(f"\n🏆 Top Pattern: {top_name} (score: {top_score:.4f})")

    if "LLM" in top_name and top_score >= 0.8:
        print("   ✅ CORRECT: LLM pattern scored highest and has excellent score")
    elif "Effect" in top_name and top_score >= 0.7:
        print("   ✅ GOOD: Effect pattern scored high (relevant)")
    else:
        print("   ⚠️  UNEXPECTED: Expected LLM or Effect pattern to score highest")

    # Check bottom patterns
    bottom_patterns = scored_patterns[-3:]
    print("\n📉 Bottom 3 Patterns:")
    for pattern in bottom_patterns:
        score = pattern.get("hybrid_score", 0.0)
        name = pattern["name"]
        print(f"   • {name}: {score:.4f}")

    # Check if irrelevant patterns scored low
    irrelevant_patterns = [
        p
        for p in scored_patterns
        if any(word in p["name"].lower() for word in ["react", "pipeline", "database"])
    ]

    if all(p.get("hybrid_score", 1.0) < 0.5 for p in irrelevant_patterns):
        print(
            "\n✅ VALIDATION: Irrelevant patterns (React, Pipeline, Database) scored low (<0.5)"
        )
    else:
        print("\n⚠️  WARNING: Some irrelevant patterns scored too high")

    # Filter by threshold
    threshold = 0.3
    relevant_patterns = [
        p for p in scored_patterns if p.get("hybrid_score", 0.0) > threshold
    ]

    print(f"\n🔍 Filtering by Threshold (>{threshold}):")
    print(f"   Before: {len(patterns)} patterns")
    print(
        f"   After:  {len(relevant_patterns)} patterns ({len(relevant_patterns)/len(patterns)*100:.1f}%)"
    )

    if len(relevant_patterns) < len(patterns):
        print(
            f"   ✅ Filtering worked: {len(patterns) - len(relevant_patterns)} irrelevant patterns removed"
        )
    else:
        print("   ⚠️  No patterns filtered - threshold may be too low")

    print()
    print("=" * 80)
    print("✅ P0 FIX VALIDATION COMPLETE")
    print("=" * 80)

    return unique_scores > 1  # Success if patterns scored differently


if __name__ == "__main__":
    success = asyncio.run(test_p0_fix())
    sys.exit(0 if success else 1)
