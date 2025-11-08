"""
Comprehensive Unit Tests for Memory Client

Tests cover:
- Store/retrieve/update/delete operations
- Category management
- Error handling and fallback
- Filesystem backend
- Deep merge and list concatenation
- Edge cases and error conditions
- Performance characteristics
"""

import asyncio
import json
import pytest
import pytest_asyncio
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from claude_hooks.lib.memory_client import (
    MemoryClient,
    FilesystemMemoryBackend,
    MemoryBackend,
    get_memory_client,
    reset_memory_client
)


@pytest_asyncio.fixture
async def temp_dir():
    """Create temporary directory for tests"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest_asyncio.fixture
async def filesystem_backend(temp_dir):
    """Create filesystem backend with temp directory"""
    return FilesystemMemoryBackend(base_path=temp_dir)


@pytest_asyncio.fixture
async def memory_client(filesystem_backend):
    """Create memory client with filesystem backend"""
    return MemoryClient(backend=filesystem_backend, enable_fallback=False)


class TestFilesystemMemoryBackend:
    """Test filesystem storage backend"""

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, filesystem_backend):
        """Test basic store and retrieve"""
        # Store a value
        await filesystem_backend.store("test_category", "test_key", {"data": "value"})

        # Retrieve it
        value = await filesystem_backend.retrieve("test_category", "test_key")

        assert value == {"data": "value"}

    @pytest.mark.asyncio
    async def test_retrieve_nonexistent(self, filesystem_backend):
        """Test retrieving non-existent key"""
        value = await filesystem_backend.retrieve("category", "nonexistent")
        assert value is None

    @pytest.mark.asyncio
    async def test_update_dict(self, filesystem_backend):
        """Test updating dictionary with deep merge"""
        # Store initial value
        await filesystem_backend.store("category", "key", {"a": 1, "b": {"c": 2}})

        # Update with delta
        await filesystem_backend.update("category", "key", {"b": {"d": 3}, "e": 4})

        # Retrieve updated value
        value = await filesystem_backend.retrieve("category", "key")

        assert value == {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}

    @pytest.mark.asyncio
    async def test_update_list(self, filesystem_backend):
        """Test updating list with concatenation"""
        # Store initial list
        await filesystem_backend.store("category", "key", [1, 2, 3])

        # Update with additional items
        await filesystem_backend.update("category", "key", [4, 5])

        # Retrieve updated list
        value = await filesystem_backend.retrieve("category", "key")

        assert value == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, filesystem_backend):
        """Test updating non-existent key creates it"""
        await filesystem_backend.update("category", "new_key", {"data": "value"})

        value = await filesystem_backend.retrieve("category", "new_key")
        assert value == {"data": "value"}

    @pytest.mark.asyncio
    async def test_delete(self, filesystem_backend):
        """Test deleting a key"""
        # Store value
        await filesystem_backend.store("category", "key", {"data": "value"})

        # Delete it
        await filesystem_backend.delete("category", "key")

        # Verify it's gone
        value = await filesystem_backend.retrieve("category", "key")
        assert value is None

    @pytest.mark.asyncio
    async def test_list_keys(self, filesystem_backend):
        """Test listing keys in a category"""
        # Store multiple values
        await filesystem_backend.store("category", "key1", "value1")
        await filesystem_backend.store("category", "key2", "value2")
        await filesystem_backend.store("category", "key3", "value3")

        # List keys
        keys = await filesystem_backend.list_keys("category")

        assert len(keys) == 3
        assert "key1" in keys
        assert "key2" in keys
        assert "key3" in keys

    @pytest.mark.asyncio
    async def test_list_categories(self, filesystem_backend):
        """Test listing all categories"""
        # Store in multiple categories
        await filesystem_backend.store("category1", "key", "value")
        await filesystem_backend.store("category2", "key", "value")
        await filesystem_backend.store("category3", "key", "value")

        # List categories
        categories = await filesystem_backend.list_categories()

        assert len(categories) == 3
        assert "category1" in categories
        assert "category2" in categories
        assert "category3" in categories

    @pytest.mark.asyncio
    async def test_safe_filename_handling(self, filesystem_backend):
        """Test that problematic characters in keys are handled"""
        # Store with problematic key name
        await filesystem_backend.store("category", "key/with/slashes", "value")

        # Should be retrievable
        value = await filesystem_backend.retrieve("category", "key/with/slashes")
        assert value == "value"

    @pytest.mark.asyncio
    async def test_metadata_storage(self, filesystem_backend):
        """Test that metadata is stored"""
        await filesystem_backend.store(
            "category",
            "key",
            {"data": "value"},
            metadata={"author": "test", "version": 1}
        )

        # Verify file contains metadata
        file_path = filesystem_backend._get_file_path("category", "key")
        with open(file_path, 'r') as f:
            data = json.load(f)

        assert "metadata" in data
        assert data["metadata"]["author"] == "test"


class TestMemoryClient:
    """Test memory client high-level API"""

    @pytest.mark.asyncio
    async def test_store_memory(self, memory_client):
        """Test storing memory"""
        success = await memory_client.store_memory("key", {"data": "value"}, "category")
        assert success is True

        # Verify it was stored
        value = await memory_client.get_memory("key", "category")
        assert value == {"data": "value"}

    @pytest.mark.asyncio
    async def test_get_memory_with_default(self, memory_client):
        """Test getting memory with default value"""
        value = await memory_client.get_memory("nonexistent", "category", default="default_value")
        assert value == "default_value"

    @pytest.mark.asyncio
    async def test_update_memory(self, memory_client):
        """Test updating memory"""
        # Store initial value
        await memory_client.store_memory("key", {"a": 1}, "category")

        # Update it
        success = await memory_client.update_memory("key", {"b": 2}, "category")
        assert success is True

        # Verify update
        value = await memory_client.get_memory("key", "category")
        assert value == {"a": 1, "b": 2}

    @pytest.mark.asyncio
    async def test_delete_memory(self, memory_client):
        """Test deleting memory"""
        # Store value
        await memory_client.store_memory("key", "value", "category")

        # Delete it
        success = await memory_client.delete_memory("key", "category")
        assert success is True

        # Verify it's gone
        value = await memory_client.get_memory("key", "category")
        assert value is None

    @pytest.mark.asyncio
    async def test_list_memory(self, memory_client):
        """Test listing memory keys"""
        # Store multiple items
        await memory_client.store_memory("key1", "value1", "category")
        await memory_client.store_memory("key2", "value2", "category")

        # List them
        keys = await memory_client.list_memory("category")

        assert len(keys) == 2
        assert "key1" in keys
        assert "key2" in keys

    @pytest.mark.asyncio
    async def test_list_categories(self, memory_client):
        """Test listing categories"""
        # Store in multiple categories
        await memory_client.store_memory("key", "value", "category1")
        await memory_client.store_memory("key", "value", "category2")

        # List categories
        categories = await memory_client.list_categories()

        assert len(categories) == 2
        assert "category1" in categories
        assert "category2" in categories

    @pytest.mark.asyncio
    async def test_fallback_on_error(self):
        """Test fallback to correlation manager on error"""
        # Create client with failing backend
        failing_backend = Mock(spec=MemoryBackend)
        failing_backend.store = AsyncMock(side_effect=Exception("Backend error"))

        client = MemoryClient(backend=failing_backend, enable_fallback=True)

        # Mock correlation manager
        with patch('claude_hooks.lib.memory_client.set_correlation_id') as mock_set:
            success = await client.store_memory("key", "value", "category")
            # Should fall back
            mock_set.assert_called_once()


class TestMemoryClientSingleton:
    """Test global singleton pattern"""

    def test_get_memory_client_singleton(self):
        """Test that get_memory_client returns same instance"""
        reset_memory_client()  # Reset first

        client1 = get_memory_client()
        client2 = get_memory_client()

        assert client1 is client2

    def test_reset_memory_client(self):
        """Test resetting global client"""
        client1 = get_memory_client()
        reset_memory_client()
        client2 = get_memory_client()

        assert client1 is not client2


class TestEdgeCases:
    """Test edge cases and error conditions"""

    @pytest.mark.asyncio
    async def test_empty_value(self, memory_client):
        """Test storing empty values"""
        await memory_client.store_memory("key", "", "category")
        value = await memory_client.get_memory("key", "category")
        assert value == ""

    @pytest.mark.asyncio
    async def test_none_value(self, memory_client):
        """Test storing None value"""
        await memory_client.store_memory("key", None, "category")
        value = await memory_client.get_memory("key", "category")
        assert value is None

    @pytest.mark.asyncio
    async def test_complex_nested_structure(self, memory_client):
        """Test storing complex nested structure"""
        complex_value = {
            "level1": {
                "level2": {
                    "level3": {
                        "data": "value",
                        "list": [1, 2, 3],
                        "nested_list": [[1, 2], [3, 4]]
                    }
                }
            },
            "array": [{"a": 1}, {"b": 2}]
        }

        await memory_client.store_memory("key", complex_value, "category")
        retrieved = await memory_client.get_memory("key", "category")

        assert retrieved == complex_value

    @pytest.mark.asyncio
    async def test_unicode_values(self, memory_client):
        """Test storing unicode values"""
        unicode_value = {"text": "Hello 世界 🌍 مرحبا"}

        await memory_client.store_memory("key", unicode_value, "category")
        retrieved = await memory_client.get_memory("key", "category")

        assert retrieved == unicode_value

    @pytest.mark.asyncio
    async def test_large_value(self, memory_client):
        """Test storing large value"""
        large_value = {"data": "x" * 10000}  # 10KB of data

        await memory_client.store_memory("key", large_value, "category")
        retrieved = await memory_client.get_memory("key", "category")

        assert retrieved == large_value


class TestPerformance:
    """Test performance characteristics"""

    @pytest.mark.asyncio
    async def test_store_performance(self, memory_client):
        """Test store operation performance"""
        import time

        start = time.time()
        await memory_client.store_memory("key", {"data": "value"}, "category")
        duration_ms = (time.time() - start) * 1000

        # Should be under 50ms
        assert duration_ms < 50, f"Store took {duration_ms}ms (target: <50ms)"

    @pytest.mark.asyncio
    async def test_retrieve_performance(self, memory_client):
        """Test retrieve operation performance"""
        import time

        # Store first
        await memory_client.store_memory("key", {"data": "value"}, "category")

        # Measure retrieve
        start = time.time()
        await memory_client.get_memory("key", "category")
        duration_ms = (time.time() - start) * 1000

        # Should be under 10ms
        assert duration_ms < 10, f"Retrieve took {duration_ms}ms (target: <10ms)"

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, memory_client):
        """Test concurrent operations don't interfere"""
        # Store multiple items concurrently
        tasks = [
            memory_client.store_memory(f"key{i}", f"value{i}", "category")
            for i in range(10)
        ]

        await asyncio.gather(*tasks)

        # Verify all were stored
        keys = await memory_client.list_memory("category")
        assert len(keys) == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
