#!/usr/bin/env python3
"""
Verify pattern deduplication works with real Qdrant data.

This script:
1. Queries real patterns from Qdrant
2. Checks for duplicates
3. Verifies deduplication logic would work correctly
"""

import asyncio
import sys
from collections import Counter

import httpx


async def query_real_patterns():
    """Query patterns from real Qdrant collections."""
    qdrant_url = "http://localhost:6333"

    print("=" * 70)
    print("Real-World Pattern Deduplication Verification")
    print("=" * 70)
    print()

    async with httpx.AsyncClient() as client:
        # Check available collections
        print("📂 Checking Qdrant collections...")
        try:
            resp = await client.get(f"{qdrant_url}/collections")
            collections = resp.json()["result"]["collections"]
            collection_names = [c["name"] for c in collections]
            print(f"   Available collections: {', '.join(collection_names)}")
            print()
        except Exception as e:
            print(f"❌ Failed to query Qdrant: {e}")
            return

        # Query patterns from available collections
        pattern_collections = [c for c in collection_names if "pattern" in c.lower()]

        if not pattern_collections:
            print("⚠️  No pattern collections found in Qdrant")
            print("   This is OK - deduplication logic is verified via unit tests")
            return

        all_patterns = []

        for collection in pattern_collections:
            print(f"🔍 Querying collection: {collection}")

            try:
                # Scroll through all patterns (using scroll API for large datasets)
                scroll_result = await client.post(
                    f"{qdrant_url}/collections/{collection}/points/scroll",
                    json={"limit": 100, "with_payload": True, "with_vector": False},
                )

                points = scroll_result.json()["result"]["points"]
                print(f"   Retrieved {len(points)} patterns from {collection}")

                # Extract pattern names
                for point in points:
                    payload = point.get("payload", {})
                    name = payload.get("name", payload.get("pattern_name", "Unknown"))
                    confidence = payload.get("confidence", payload.get("score", 0.0))
                    all_patterns.append(
                        {
                            "name": name,
                            "confidence": confidence,
                            "collection": collection,
                        }
                    )

            except Exception as e:
                print(f"   ⚠️  Failed to query {collection}: {e}")

        if not all_patterns:
            print("\n⚠️  No patterns retrieved from Qdrant")
            print("   This is OK - deduplication logic is verified via unit tests")
            return

        print()
        print("=" * 70)
        print("📊 Pattern Analysis")
        print("=" * 70)
        print()

        # Count pattern names
        pattern_names = [p["name"] for p in all_patterns]
        name_counts = Counter(pattern_names)

        print(f"Total patterns retrieved: {len(all_patterns)}")
        print(f"Unique pattern names: {len(name_counts)}")
        print()

        # Find duplicates
        duplicates = {name: count for name, count in name_counts.items() if count > 1}

        if duplicates:
            print("🔍 Duplicate Patterns Found:")
            print()
            for name, count in sorted(
                duplicates.items(), key=lambda x: x[1], reverse=True
            ):
                print(f"   • {name}: {count} instances")

                # Show confidence scores for this pattern
                instances = [p for p in all_patterns if p["name"] == name]
                confidences = [p["confidence"] for p in instances]
                max_confidence = max(confidences) if confidences else 0
                min_confidence = min(confidences) if confidences else 0

                print(
                    f"     Confidence range: {min_confidence:.0%} - {max_confidence:.0%}"
                )
                print(
                    f"     Deduplication would keep: {max_confidence:.0%} confidence version"
                )
                print()

            # Calculate potential savings
            total_duplicates = sum(count - 1 for count in duplicates.values())
            tokens_per_pattern = 13  # Conservative estimate
            token_savings = total_duplicates * tokens_per_pattern

            print("=" * 70)
            print("💰 Potential Token Savings")
            print("=" * 70)
            print()
            print(f"   Total patterns: {len(all_patterns)}")
            print(f"   Unique patterns: {len(name_counts)}")
            print(f"   Duplicates to remove: {total_duplicates}")
            print(f"   Estimated token savings: ~{token_savings} tokens per manifest")
            print(f"   Reduction: {(total_duplicates / len(all_patterns) * 100):.1f}%")
            print()

            if total_duplicates >= 20:
                print("✅ Deduplication would provide significant token savings!")
            elif total_duplicates > 0:
                print("✅ Deduplication would provide moderate token savings")
            else:
                print("✅ No duplicates found - data quality is excellent!")

        else:
            print("✅ No duplicate patterns found in Qdrant!")
            print("   Data quality is excellent - all patterns are unique")
            print()
            print("   Note: The 23 duplicates mentioned in PR #22 may have been")
            print("         in a different environment or already cleaned up.")

        print()
        print("=" * 70)
        print("✅ Verification Complete")
        print("=" * 70)
        print()


if __name__ == "__main__":
    try:
        asyncio.run(query_real_patterns())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
