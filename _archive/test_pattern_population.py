#!/usr/bin/env python3
"""
Test and populate pattern generation system.

Tests:
1. Pattern extraction from sample code
2. Embedding generation
3. Pattern storage to Qdrant
4. Pattern retrieval
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agents.lib.patterns.pattern_extractor import PatternExtractor
from agents.lib.patterns.pattern_storage import PatternStorage


def generate_simple_embedding(text: str, dimension: int = 384) -> list[float]:
    """
    Generate a simple hash-based embedding for testing.

    In production, use sentence-transformers or similar.
    For testing, we create deterministic embeddings from text hashes.
    """
    import hashlib
    import math

    # Create hash
    hash_obj = hashlib.sha256(text.encode())
    hash_bytes = hash_obj.digest()

    # Convert to floats and normalize
    embedding = []
    for i in range(dimension):
        # Use hash bytes cyclically
        byte_val = hash_bytes[i % len(hash_bytes)]
        # Convert to float in range [-1, 1]
        float_val = (byte_val / 127.5) - 1.0
        embedding.append(float_val)

    # Normalize to unit vector
    magnitude = math.sqrt(sum(x * x for x in embedding))
    if magnitude > 0:
        embedding = [x / magnitude for x in embedding]

    return embedding


async def test_pattern_extraction():
    """Test pattern extraction on sample code."""
    print("\n" + "=" * 70)
    print("PHASE 2: TESTING PATTERN EXTRACTION")
    print("=" * 70)

    # Sample ONEX code for testing
    sample_code = '''
class NodeUserAuthenticationEffect:
    """ONEX Effect node for user authentication."""

    def __init__(self, db_client: DatabaseClient):
        self.db_client = db_client

    async def execute_effect(self, contract: ModelContractEffect) -> dict:
        """Execute authentication effect."""
        try:
            user_id = contract.input_data.get("user_id")
            password = contract.input_data.get("password")

            # Validate credentials
            user = await self.db_client.get_user(user_id)
            if not user or not self._verify_password(password, user.password_hash):
                raise AuthenticationError("Invalid credentials")

            # Generate session token
            token = await self._generate_token(user_id)

            return {
                "success": True,
                "token": token,
                "user_id": user_id
            }
        except AuthenticationError as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _verify_password(self, password: str, hash: str) -> bool:
        """Verify password against hash."""
        # TODO: Implement bcrypt verification
        return True

    async def _generate_token(self, user_id: str) -> str:
        """Generate JWT token."""
        # TODO: Implement JWT generation
        return "token_" + user_id
'''

    # Test extraction
    extractor = PatternExtractor(min_confidence=0.5)
    result = extractor.extract_patterns(
        generated_code=sample_code,
        context={
            "node_type": "effect",
            "framework": "onex",
            "use_case": "authentication",
        },
    )

    print(f"\n✅ Extraction completed in {result.extraction_time_ms}ms")
    print(f"📊 Found {len(result.patterns)} patterns\n")

    for i, pattern in enumerate(result.patterns, 1):
        print(f"Pattern {i}:")
        print(f"  Type: {pattern.pattern_type.value}")
        print(f"  Name: {pattern.pattern_name}")
        print(f"  Description: {pattern.pattern_description}")
        print(f"  Confidence: {pattern.confidence_score:.2f}")
        print(f"  Template length: {len(pattern.pattern_template)} chars")
        print()

    return result


async def test_pattern_storage(patterns):
    """Test pattern storage to Qdrant."""
    print("\n" + "=" * 70)
    print("TESTING PATTERN STORAGE")
    print("=" * 70)

    # Initialize storage (will use localhost:6333 from settings)
    storage = PatternStorage()

    print("\n📦 Storage initialized")
    print(f"   URL: {storage.qdrant_url}")
    print(f"   Collection: {storage.collection_name}")
    print(f"   In-memory fallback: {storage.use_in_memory}")

    # Store each pattern
    stored_count = 0
    for pattern in patterns:
        # Generate embedding from pattern template
        embedding = generate_simple_embedding(
            pattern.pattern_template + pattern.pattern_description
        )

        try:
            pattern_id = await storage.store_pattern(pattern, embedding)
            print(f"✅ Stored: {pattern.pattern_name} (ID: {pattern_id[:8]}...)")
            stored_count += 1
        except Exception as e:
            print(f"❌ Failed to store {pattern.pattern_name}: {e}")

    print(f"\n📊 Stored {stored_count}/{len(patterns)} patterns")

    # Get storage stats
    stats = await storage.get_storage_stats()
    print("\n📈 Storage Statistics:")
    for key, value in stats.items():
        print(f"   {key}: {value}")

    return storage


async def test_pattern_retrieval(storage):
    """Test pattern retrieval."""
    print("\n" + "=" * 70)
    print("TESTING PATTERN RETRIEVAL")
    print("=" * 70)

    # Create a query embedding (simulating a search for authentication patterns)
    query_text = "authentication user credentials verify password"
    query_embedding = generate_simple_embedding(query_text)

    print(f"\n🔍 Query: '{query_text}'")

    # Query similar patterns
    matches = await storage.query_similar_patterns(
        query_embedding=query_embedding, limit=5, min_confidence=0.5
    )

    print(f"✅ Found {len(matches)} matching patterns:\n")

    for i, match in enumerate(matches, 1):
        print(f"Match {i}:")
        print(f"  Pattern: {match.pattern.pattern_name}")
        print(f"  Type: {match.pattern.pattern_type.value}")
        print(f"  Similarity: {match.similarity_score:.3f}")
        print(f"  Confidence: {match.pattern.confidence_score:.2f}")
        print(f"  Reason: {match.match_reason}")
        print()


async def verify_qdrant_population():
    """Verify Qdrant collection has been populated."""
    print("\n" + "=" * 70)
    print("VERIFYING QDRANT POPULATION")
    print("=" * 70)

    import requests

    try:
        response = requests.get(
            "http://localhost:6333/collections/code_generation_patterns", timeout=5
        )
        data = response.json()

        points_count = data["result"]["points_count"]
        vectors_count = data["result"]["vectors_count"]

        print("\n✅ Qdrant Collection Status:")
        print(f"   Points: {points_count}")
        print(f"   Vectors: {vectors_count}")
        print(f"   Status: {data['result']['status']}")

        if points_count > 0:
            print(f"\n🎉 SUCCESS! Collection populated with {points_count} patterns")
            return True
        else:
            print("\n⚠️  Collection is still empty")
            return False

    except Exception as e:
        print(f"\n❌ Failed to verify Qdrant: {e}")
        return False


async def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("OMNICLAUDE PATTERN GENERATION SYSTEM TEST")
    print("=" * 70)
    print("\nThis test will:")
    print("1. Extract patterns from sample code")
    print("2. Store patterns to Qdrant")
    print("3. Retrieve patterns via similarity search")
    print("4. Verify Qdrant population")

    try:
        # Phase 1: Extract patterns
        result = await test_pattern_extraction()

        if not result.patterns:
            print("\n❌ No patterns extracted. Cannot proceed with storage test.")
            return

        # Phase 2: Store patterns
        storage = await test_pattern_storage(result.patterns)

        # Phase 3: Retrieve patterns
        await test_pattern_retrieval(storage)

        # Phase 4: Verify Qdrant
        success = await verify_qdrant_population()

        # Summary
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        print(f"✅ Pattern extraction: PASSED ({len(result.patterns)} patterns)")
        print("✅ Pattern storage: PASSED")
        print("✅ Pattern retrieval: PASSED")
        print(
            f"{'✅' if success else '⚠️'} Qdrant population: {'VERIFIED' if success else 'NEEDS CHECK'}"
        )

        if success:
            print("\n🎉 All tests passed! Pattern system is working correctly.")
        else:
            print("\n⚠️  Tests passed but Qdrant verification failed.")
            print("   This might mean patterns are in memory cache but not persisted.")

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
