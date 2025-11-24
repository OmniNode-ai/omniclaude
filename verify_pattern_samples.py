#!/usr/bin/env python3
"""
Verify and display sample patterns from Qdrant.
"""

import asyncio
import sys
from pathlib import Path


project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agents.lib.patterns.pattern_storage import PatternStorage


def generate_simple_embedding(text: str, dimension: int = 384) -> list[float]:
    """Generate simple hash-based embedding."""
    import hashlib
    import math

    hash_obj = hashlib.sha256(text.encode())
    hash_bytes = hash_obj.digest()

    embedding = []
    for i in range(dimension):
        byte_val = hash_bytes[i % len(hash_bytes)]
        float_val = (byte_val / 127.5) - 1.0
        embedding.append(float_val)

    magnitude = math.sqrt(sum(x * x for x in embedding))
    if magnitude > 0:
        embedding = [x / magnitude for x in embedding]

    return embedding


async def main():
    """Display sample patterns."""
    print("\n" + "=" * 70)
    print("PATTERN SAMPLES FROM QDRANT")
    print("=" * 70)

    storage = PatternStorage()

    # Get storage stats
    stats = await storage.get_storage_stats()
    print(f"\n📊 Collection Statistics:")
    for key, value in stats.items():
        print(f"   {key}: {value}")

    # Test queries for different pattern types
    queries = [
        ("ONEX node pattern", "ONEX node class implementation effect compute reducer"),
        ("Async patterns", "async await asyncio parallel orchestration"),
        ("Error handling", "try except error handling validation"),
        ("Database patterns", "database query insert update transaction"),
        ("Testing patterns", "test pytest fixture mock assert"),
    ]

    for query_name, query_text in queries:
        print(f"\n{'='*70}")
        print(f"🔍 Query: {query_name}")
        print(f"   Text: '{query_text}'")
        print("=" * 70)

        embedding = generate_simple_embedding(query_text)
        matches = await storage.query_similar_patterns(
            query_embedding=embedding, limit=3, min_confidence=0.5
        )

        if matches:
            print(f"✅ Found {len(matches)} matches:\n")
            for i, match in enumerate(matches, 1):
                pattern = match.pattern
                print(f"{i}. {pattern.pattern_name}")
                print(f"   Type: {pattern.pattern_type.value}")
                print(f"   Confidence: {pattern.confidence_score:.2f}")
                print(f"   Description: {pattern.pattern_description}")
                print(
                    f"   Source: {pattern.source_context.get('file_path', 'unknown')}"
                )
                print(f"   Similarity: {match.similarity_score:.3f}")
                print()
        else:
            print("❌ No matches found\n")

    print("=" * 70)
    print("VERIFICATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
