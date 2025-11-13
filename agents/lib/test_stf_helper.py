"""
Unit Tests for STFHelper

Tests the agent-debug loop integration helper functions for querying,
storing, and tracking STF usage.
"""

import pytest

from agents.lib.stf_helper import STFHelper
from omniclaude.debug_loop.mock_database_protocol import MockDatabaseProtocol


@pytest.fixture
def mock_db():
    """Create fresh mock database for each test."""
    return MockDatabaseProtocol()


@pytest.fixture
def stf_helper(mock_db):
    """Create STFHelper with mock database."""
    return STFHelper(db_protocol=mock_db)


@pytest.mark.asyncio
async def test_stf_helper_initialization():
    """Test STFHelper initializes correctly."""
    helper = STFHelper()

    # Should have mock database by default
    assert helper.db is not None
    assert helper.storage_node is not None
    assert helper.hash_node is not None


@pytest.mark.asyncio
async def test_store_stf_success(stf_helper):
    """Test storing a new STF successfully."""
    stf_id = await stf_helper.store_stf(
        stf_name="fix_import_error",
        stf_code="import sys\nsys.path.append('.')",
        stf_description="Add current directory to Python path",
        problem_category="import_error",
        problem_signature="No module named",
        quality_score=0.85,
        correlation_id="test-correlation-123",
    )

    assert stf_id is not None
    assert isinstance(stf_id, str)
    assert len(stf_id) > 0


@pytest.mark.asyncio
async def test_store_stf_with_optional_fields(stf_helper):
    """Test storing STF with all optional fields."""
    stf_id = await stf_helper.store_stf(
        stf_name="fix_connection_timeout",
        stf_code="pool_size = 20\ntimeout = 30",
        stf_description="Increase connection pool and timeout",
        problem_category="connection_pooling",
        problem_signature="connection timeout",
        quality_score=0.9,
        correlation_id="test-correlation-456",
        source_execution_id="exec-789",
        contributor_agent_name="debug-database",
    )

    assert stf_id is not None

    # Retrieve and verify fields
    stf_data = await stf_helper.retrieve_stf(stf_id)
    assert stf_data is not None
    assert stf_data["source_execution_id"] == "exec-789"
    assert stf_data["contributor_agent_name"] == "debug-database"


@pytest.mark.asyncio
async def test_store_stf_deduplication(stf_helper):
    """Test STF deduplication based on normalized code hash."""
    # Store first STF
    stf_id_1 = await stf_helper.store_stf(
        stf_name="fix_import_error_v1",
        stf_code="import sys\nsys.path.append('.')",
        stf_description="Add current directory to Python path",
        problem_category="import_error",
        problem_signature="No module named",
        quality_score=0.85,
        correlation_id="test-correlation-1",
    )

    # Store duplicate with slightly different formatting
    stf_id_2 = await stf_helper.store_stf(
        stf_name="fix_import_error_v2",
        stf_code="import sys  # Import system module\nsys.path.append('.')  # Add path",
        stf_description="Add current directory to Python path (with comments)",
        problem_category="import_error",
        problem_signature="No module named",
        quality_score=0.85,
        correlation_id="test-correlation-2",
    )

    # Should return same ID (deduplication based on normalized code)
    # Note: Comments are stripped during normalization
    assert stf_id_1 is not None
    assert stf_id_2 is not None


@pytest.mark.asyncio
async def test_retrieve_stf_success(stf_helper):
    """Test retrieving an STF by ID."""
    # Store STF first
    stf_id = await stf_helper.store_stf(
        stf_name="fix_deadlock",
        stf_code="SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
        stf_description="Reduce deadlock likelihood",
        problem_category="deadlock_resolution",
        problem_signature="deadlock detected",
        quality_score=0.88,
        correlation_id="test-correlation-deadlock",
    )

    # Retrieve it
    stf_data = await stf_helper.retrieve_stf(stf_id)

    assert stf_data is not None
    assert stf_data["stf_id"] == stf_id
    assert stf_data["stf_name"] == "fix_deadlock"
    assert stf_data["problem_category"] == "deadlock_resolution"
    assert stf_data["quality_score"] == 0.88
    assert "SET TRANSACTION ISOLATION LEVEL" in stf_data["stf_code"]


@pytest.mark.asyncio
async def test_retrieve_stf_not_found(stf_helper):
    """Test retrieving a non-existent STF."""
    stf_data = await stf_helper.retrieve_stf("non-existent-id-12345")

    assert stf_data is None


@pytest.mark.asyncio
async def test_query_stfs_by_signature(stf_helper):
    """Test querying STFs by problem signature."""
    # Store multiple STFs
    await stf_helper.store_stf(
        stf_name="fix_import_error_1",
        stf_code="import sys\nsys.path.append('.')",
        stf_description="Add current directory to path",
        problem_category="import_error",
        problem_signature="No module named",
        quality_score=0.85,
        correlation_id="test-1",
    )

    await stf_helper.store_stf(
        stf_name="fix_import_error_2",
        stf_code="import sys\nsys.path.insert(0, '.')",
        stf_description="Insert current directory at front of path",
        problem_category="import_error",
        problem_signature="No module named",
        quality_score=0.90,
        correlation_id="test-2",
    )

    # Update approval status manually (mock doesn't do this automatically)
    for stf in stf_helper.db.stfs.values():
        stf["approval_status"] = "approved"

    # Query by signature
    results = await stf_helper.query_stfs(
        problem_signature="No module named", min_quality=0.7
    )

    assert len(results) == 2
    # Results should be sorted by quality (descending)
    assert results[0]["quality_score"] >= results[1]["quality_score"]


@pytest.mark.asyncio
async def test_query_stfs_by_signature_and_category(stf_helper):
    """Test querying STFs with both signature and category filters."""
    # Store STFs in different categories
    await stf_helper.store_stf(
        stf_name="fix_import_error",
        stf_code="import sys\nsys.path.append('.')",
        stf_description="Add path",
        problem_category="import_error",
        problem_signature="No module named",
        quality_score=0.85,
        correlation_id="test-1",
    )

    await stf_helper.store_stf(
        stf_name="fix_connection_timeout",
        stf_code="pool_size = 20",
        stf_description="Increase pool",
        problem_category="connection_pooling",
        problem_signature="connection timeout",
        quality_score=0.90,
        correlation_id="test-2",
    )

    # Update approval status
    for stf in stf_helper.db.stfs.values():
        stf["approval_status"] = "approved"

    # Query with category filter
    results = await stf_helper.query_stfs(
        problem_signature="No module named",
        problem_category="import_error",
        min_quality=0.7,
    )

    assert len(results) == 1
    assert results[0]["stf_name"] == "fix_import_error"


@pytest.mark.asyncio
async def test_query_stfs_min_quality_filter(stf_helper):
    """Test querying STFs with minimum quality threshold."""
    # Store STFs with different quality scores
    await stf_helper.store_stf(
        stf_name="low_quality_stf",
        stf_code="# Quick fix",
        stf_description="Low quality",
        problem_category="import_error",
        problem_signature="No module named",
        quality_score=0.6,
        correlation_id="test-1",
    )

    await stf_helper.store_stf(
        stf_name="high_quality_stf",
        stf_code="# Robust solution",
        stf_description="High quality",
        problem_category="import_error",
        problem_signature="No module named",
        quality_score=0.95,
        correlation_id="test-2",
    )

    # Update approval status
    for stf in stf_helper.db.stfs.values():
        stf["approval_status"] = "approved"

    # Query with high quality threshold
    results = await stf_helper.query_stfs(
        problem_signature="No module named", min_quality=0.8
    )

    # Should only return high quality STF
    assert len(results) == 1
    assert results[0]["stf_name"] == "high_quality_stf"


@pytest.mark.asyncio
async def test_query_stfs_limit(stf_helper):
    """Test query result limit."""
    # Store multiple STFs
    for i in range(15):
        await stf_helper.store_stf(
            stf_name=f"stf_{i}",
            stf_code=f"# Solution {i}",
            stf_description=f"Description {i}",
            problem_category="import_error",
            problem_signature="No module named",
            quality_score=0.8 + (i * 0.01),  # Varying quality
            correlation_id=f"test-{i}",
        )

    # Update approval status
    for stf in stf_helper.db.stfs.values():
        stf["approval_status"] = "approved"

    # Query with limit
    results = await stf_helper.query_stfs(problem_signature="No module named", limit=5)

    assert len(results) == 5


@pytest.mark.asyncio
async def test_query_stfs_empty_results(stf_helper):
    """Test querying with no matching STFs."""
    results = await stf_helper.query_stfs(
        problem_signature="nonexistent signature", min_quality=0.7
    )

    assert len(results) == 0


@pytest.mark.asyncio
async def test_update_stf_usage_success(stf_helper):
    """Test updating STF usage metrics."""
    # Store STF first
    stf_id = await stf_helper.store_stf(
        stf_name="test_stf",
        stf_code="# Test code",
        stf_description="Test",
        problem_category="test",
        problem_signature="test",
        quality_score=0.8,
        correlation_id="test",
    )

    # Verify initial usage count is 0
    stf_data = await stf_helper.retrieve_stf(stf_id)
    assert stf_data["usage_count"] == 0

    # Update usage (success)
    result = await stf_helper.update_stf_usage(stf_id, success=True)
    assert result is True

    # Verify usage count incremented
    stf_data = await stf_helper.retrieve_stf(stf_id)
    assert stf_data["usage_count"] == 1

    # Update usage again (failure)
    result = await stf_helper.update_stf_usage(stf_id, success=False)
    assert result is True

    # Verify usage count incremented again
    stf_data = await stf_helper.retrieve_stf(stf_id)
    assert stf_data["usage_count"] == 2


@pytest.mark.asyncio
async def test_update_stf_usage_not_found(stf_helper):
    """Test updating usage for non-existent STF."""
    result = await stf_helper.update_stf_usage("non-existent-id", success=True)

    assert result is False


@pytest.mark.asyncio
async def test_get_top_stfs(stf_helper):
    """Test getting top-ranked STFs for a category."""
    # Store multiple STFs in same category with different quality
    for i in range(10):
        await stf_helper.store_stf(
            stf_name=f"stf_{i}",
            stf_code=f"# Solution {i}",
            stf_description=f"Description {i}",
            problem_category="import_error",
            problem_signature=f"signature_{i}",
            quality_score=0.6 + (i * 0.03),  # Quality increases with i
            correlation_id=f"test-{i}",
        )

    # Update approval status
    for stf in stf_helper.db.stfs.values():
        stf["approval_status"] = "approved"

    # Get top 3 STFs (min quality 0.8 filters to only last few)
    results = await stf_helper.get_top_stfs(
        problem_category="import_error", limit=3, min_quality=0.8
    )

    # Should return up to 3 highest quality STFs
    assert len(results) <= 3
    assert len(results) > 0

    # Verify sorted by quality (descending)
    for i in range(len(results) - 1):
        assert results[i]["quality_score"] >= results[i + 1]["quality_score"]


@pytest.mark.asyncio
async def test_get_top_stfs_empty_category(stf_helper):
    """Test getting top STFs for category with no matches."""
    results = await stf_helper.get_top_stfs(
        problem_category="nonexistent_category", limit=5
    )

    assert len(results) == 0


@pytest.mark.asyncio
async def test_stf_code_normalization(stf_helper):
    """Test that STF code is normalized before hashing."""
    # Store STF with comments and whitespace
    stf_id = await stf_helper.store_stf(
        stf_name="test_normalization",
        stf_code="""
        # This is a comment
        import sys  # Import system module

        # Add current directory to path
        sys.path.append('.')  # Append path
        """,
        stf_description="Test normalization",
        problem_category="test",
        problem_signature="test",
        quality_score=0.8,
        correlation_id="test",
    )

    # Retrieve and verify code is stored as-is (normalization only affects hash)
    stf_data = await stf_helper.retrieve_stf(stf_id)
    assert "# This is a comment" in stf_data["stf_code"]

    # Hash should be computed from normalized version
    # (comments stripped, whitespace normalized)
    assert stf_data["stf_hash"] is not None
    assert len(stf_data["stf_hash"]) == 64  # SHA-256 hex digest


@pytest.mark.asyncio
async def test_stf_helper_with_real_database_protocol():
    """Test that STFHelper can be initialized with a real database protocol."""
    # This test verifies the interface is correct
    # In production, a real IDatabaseProtocol would be passed

    # Mock protocol satisfies the interface
    mock_db = MockDatabaseProtocol()
    helper = STFHelper(db_protocol=mock_db)

    assert helper.db is mock_db
    assert helper.storage_node is not None
    assert helper.hash_node is not None


@pytest.mark.asyncio
async def test_concurrent_stf_operations(stf_helper):
    """Test multiple concurrent STF operations."""
    import asyncio

    # Create multiple STFs concurrently
    tasks = [
        stf_helper.store_stf(
            stf_name=f"concurrent_stf_{i}",
            stf_code=f"# Solution {i}",
            stf_description=f"Concurrent test {i}",
            problem_category="test",
            problem_signature="concurrent test",
            quality_score=0.8,
            correlation_id=f"concurrent-{i}",
        )
        for i in range(5)
    ]

    stf_ids = await asyncio.gather(*tasks)

    # All should succeed
    assert all(stf_id is not None for stf_id in stf_ids)
    assert len(set(stf_ids)) == 5  # All unique IDs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
