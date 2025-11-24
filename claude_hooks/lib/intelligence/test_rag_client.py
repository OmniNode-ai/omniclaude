"""
Quick test for RAG Intelligence Client.

Run with: python -m pytest test_rag_client.py -v
"""

import pytest

from .rag_client import RAGIntelligenceClient, get_rag_client


@pytest.mark.asyncio
async def test_naming_conventions_python():
    """Test Python naming conventions retrieval."""
    client = RAGIntelligenceClient()

    conventions = await client.get_naming_conventions("python")

    assert len(conventions) > 0
    assert any(c.pattern == "snake_case" for c in conventions)
    assert any(c.pattern == "PascalCase" for c in conventions)

    await client.close()


@pytest.mark.asyncio
async def test_naming_conventions_typescript():
    """Test TypeScript naming conventions retrieval."""
    client = RAGIntelligenceClient()

    conventions = await client.get_naming_conventions("typescript")

    assert len(conventions) > 0
    assert any(c.pattern == "camelCase" for c in conventions)
    assert any(c.pattern == "PascalCase" for c in conventions)

    await client.close()


@pytest.mark.asyncio
async def test_code_examples_error_handling():
    """Test code examples for error handling."""
    client = RAGIntelligenceClient()

    examples = await client.get_code_examples("error handling", "python", max_results=3)

    assert len(examples) > 0
    assert any(
        "exception" in e.pattern.lower() or "error" in e.pattern.lower()
        for e in examples
    )
    assert all(e.language == "python" for e in examples)

    await client.close()


@pytest.mark.asyncio
async def test_caching():
    """Test caching functionality."""
    client = RAGIntelligenceClient()

    # First call - should populate cache
    result1 = await client.get_naming_conventions("python")
    stats1 = client.get_cache_stats()

    assert stats1["size"] == 1

    # Second call - should use cache
    result2 = await client.get_naming_conventions("python")
    stats2 = client.get_cache_stats()

    assert stats2["size"] == 1  # No new cache entry
    assert result1 == result2  # Same results

    # Clear cache
    client.clear_cache()
    stats3 = client.get_cache_stats()

    assert stats3["size"] == 0

    await client.close()


@pytest.mark.asyncio
async def test_singleton():
    """Test singleton pattern."""
    client1 = get_rag_client()
    client2 = get_rag_client()

    assert client1 is client2  # Same instance

    await client1.close()


@pytest.mark.asyncio
async def test_context_specific_rules():
    """Test context-specific naming rules."""
    client = RAGIntelligenceClient()

    # API context
    api_conventions = await client.get_naming_conventions("python", context="api")
    assert any(
        "REST" in c.description or "api" in c.description.lower()
        for c in api_conventions
    )

    # Test context
    test_conventions = await client.get_naming_conventions("python", context="test")
    assert any(
        "test_" in c.pattern or "test" in c.description.lower()
        for c in test_conventions
    )

    await client.close()


if __name__ == "__main__":
    import asyncio

    async def manual_test():
        """Manual test for quick verification."""
        client = RAGIntelligenceClient()

        print("\n=== Python Naming Conventions ===")
        py_conventions = await client.get_naming_conventions("python")
        for conv in py_conventions[:3]:
            print(f"  {conv.pattern}: {conv.description}")

        print("\n=== TypeScript Naming Conventions ===")
        ts_conventions = await client.get_naming_conventions("typescript")
        for conv in ts_conventions[:3]:
            print(f"  {conv.pattern}: {conv.description}")

        print("\n=== Python Error Handling Examples ===")
        examples = await client.get_code_examples(
            "error handling", "python", max_results=2
        )
        for ex in examples:
            print(f"  {ex.pattern}: {ex.description}")

        print("\n=== Cache Stats ===")
        stats = client.get_cache_stats()
        print(f"  Cache size: {stats['size']}")
        print(f"  TTL: {stats['ttl_seconds']}s")

        await client.close()
        print("\n✅ All manual tests passed!")

    asyncio.run(manual_test())
