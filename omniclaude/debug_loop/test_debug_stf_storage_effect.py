"""
Unit Tests for NodeDebugSTFStorageEffect

Tests the STF storage Effect node using MockDatabaseProtocol.
Demonstrates ONEX compliance with type-safe contracts and error handling.
"""

from datetime import datetime
from uuid import uuid4

import pytest
from omnibase_core.models.container.model_onex_container import ModelONEXContainer

from .mock_database_protocol import MockDatabaseProtocol
from .node_debug_stf_storage_effect import NodeDebugSTFStorageEffect


class TestDebugSTFStorageEffect:
    """Test suite for STF storage operations."""

    @pytest.fixture
    def setup(self):
        """Setup mock database, container, and node instance."""
        mock_db = MockDatabaseProtocol()
        container = ModelONEXContainer()
        node = NodeDebugSTFStorageEffect(db_protocol=mock_db, container=container)
        return node, mock_db

    @pytest.mark.asyncio
    async def test_store_stf_success(self, setup):
        """Test storing a new STF."""
        node, mock_db = setup

        contract = {
            "operation": "store",
            "stf_data": {
                "stf_name": "fix_import_error_stf",
                "stf_code": "def fix_import(error): return 'import sys'",
                "stf_hash": "abc123def456",
                "stf_description": "Fixes missing import errors",
                "problem_category": "import_error",
                "quality_score": 0.85,
            },
        }

        result = await node.execute_effect(contract)

        assert result["success"] is True
        assert result["operation"] == "store"
        assert "stf_id" in result
        assert result.get("duplicate") is False
        assert "timestamp" in result

        # Verify stored in mock DB
        stats = mock_db.get_stats()
        assert stats["stfs_count"] == 1

    @pytest.mark.asyncio
    async def test_store_duplicate_stf(self, setup):
        """Test storing duplicate STF (same hash)."""
        node, mock_db = setup

        stf_data = {
            "stf_name": "fix_import_error_stf",
            "stf_code": "def fix_import(error): return 'import sys'",
            "stf_hash": "duplicate_hash_123",
            "quality_score": 0.85,
        }

        # Store first time
        contract1 = {"operation": "store", "stf_data": stf_data}
        result1 = await node.execute_effect(contract1)
        assert result1["success"] is True

        # Store again with same hash
        contract2 = {"operation": "store", "stf_data": stf_data}
        result2 = await node.execute_effect(contract2)
        assert result2["success"] is True
        assert result2.get("duplicate") is True

        # Verify only one STF stored
        stats = mock_db.get_stats()
        assert stats["stfs_count"] == 1

    @pytest.mark.asyncio
    async def test_retrieve_stf(self, setup):
        """Test retrieving an STF by ID."""
        node, mock_db = setup

        # First store an STF
        store_contract = {
            "operation": "store",
            "stf_data": {
                "stf_name": "test_stf",
                "stf_code": "def test(): pass",
                "stf_hash": "test_hash_456",
                "quality_score": 0.90,
            },
        }
        store_result = await node.execute_effect(store_contract)
        stf_id = store_result["stf_id"]

        # Now retrieve it
        retrieve_contract = {
            "operation": "retrieve",
            "stf_id": stf_id,
        }
        result = await node.execute_effect(retrieve_contract)

        assert result["success"] is True
        assert result["operation"] == "retrieve"
        assert result["stf_id"] == stf_id
        assert "stf_data" in result

        stf_data = result["stf_data"]
        assert stf_data["stf_name"] == "test_stf"
        assert stf_data["quality_score"] == 0.90

    @pytest.mark.asyncio
    async def test_search_stfs(self, setup):
        """Test searching STFs by criteria."""
        node, mock_db = setup

        # Store multiple STFs
        stfs = [
            {
                "stf_name": "high_quality_stf",
                "stf_code": "def hq(): pass",
                "stf_hash": "hq_hash_1",
                "problem_category": "import_error",
                "quality_score": 0.95,
            },
            {
                "stf_name": "medium_quality_stf",
                "stf_code": "def mq(): pass",
                "stf_hash": "mq_hash_2",
                "problem_category": "import_error",
                "quality_score": 0.75,
            },
            {
                "stf_name": "low_quality_stf",
                "stf_code": "def lq(): pass",
                "stf_hash": "lq_hash_3",
                "problem_category": "syntax_error",
                "quality_score": 0.60,
            },
        ]

        for stf_data in stfs:
            # Store and approve each STF
            store_contract = {"operation": "store", "stf_data": stf_data}
            result = await node.execute_effect(store_contract)
            stf_id = result["stf_id"]

            # Manually set approval status in mock DB
            mock_db.stfs[stf_id]["approval_status"] = "approved"

        # Search with quality filter
        search_contract = {
            "operation": "search",
            "search_criteria": {
                "problem_category": "import_error",
                "min_quality": 0.8,
                "approval_status": "approved",
                "limit": 10,
            },
        }
        result = await node.execute_effect(search_contract)

        assert result["success"] is True
        assert result["operation"] == "search"
        assert result["result_count"] == 1  # Only high_quality_stf matches
        assert len(result["search_results"]) == 1
        assert result["search_results"][0]["stf_name"] == "high_quality_stf"

    @pytest.mark.asyncio
    async def test_update_usage(self, setup):
        """Test incrementing usage counter."""
        node, mock_db = setup

        # Store STF
        store_contract = {
            "operation": "store",
            "stf_data": {
                "stf_name": "usage_test_stf",
                "stf_code": "def test(): pass",
                "stf_hash": "usage_hash",
                "quality_score": 0.80,
            },
        }
        store_result = await node.execute_effect(store_contract)
        stf_id = store_result["stf_id"]

        # Update usage 3 times
        for _ in range(3):
            update_contract = {
                "operation": "update_usage",
                "stf_id": stf_id,
            }
            result = await node.execute_effect(update_contract)
            assert result["success"] is True

        # Verify usage count in mock DB
        stf = mock_db.stfs[stf_id]
        assert stf["usage_count"] == 3
        assert stf["last_used_at"] is not None

    @pytest.mark.asyncio
    async def test_update_quality(self, setup):
        """Test updating quality scores."""
        node, mock_db = setup

        # Store STF
        store_contract = {
            "operation": "store",
            "stf_data": {
                "stf_name": "quality_test_stf",
                "stf_code": "def test(): pass",
                "stf_hash": "quality_hash",
                "quality_score": 0.70,
            },
        }
        store_result = await node.execute_effect(store_contract)
        stf_id = store_result["stf_id"]

        # Update quality
        update_contract = {
            "operation": "update_quality",
            "stf_id": stf_id,
            "quality_scores": {
                "quality_score": 0.92,
                "completeness_score": 0.95,
                "documentation_score": 0.90,
            },
        }
        result = await node.execute_effect(update_contract)

        assert result["success"] is True
        assert result["operation"] == "update_quality"

        # Verify in mock DB
        stf = mock_db.stfs[stf_id]
        assert stf["updated_at"] is not None

    @pytest.mark.asyncio
    async def test_missing_operation(self, setup):
        """Test error handling for missing operation."""
        node, _ = setup

        contract = {
            "stf_data": {"stf_name": "test"},
        }

        with pytest.raises(Exception, match="operation"):
            await node.execute_effect(contract)

    @pytest.mark.asyncio
    async def test_invalid_operation(self, setup):
        """Test error handling for invalid operation."""
        node, _ = setup

        contract = {
            "operation": "invalid_op",
            "stf_data": {},
        }

        with pytest.raises(Exception, match="invalid operation"):
            await node.execute_effect(contract)

    @pytest.mark.asyncio
    async def test_missing_required_fields(self, setup):
        """Test error handling for missing required fields."""
        node, _ = setup

        contract = {
            "operation": "store",
            "stf_data": {
                "stf_name": "incomplete_stf",
                # Missing stf_code and stf_hash
            },
        }

        with pytest.raises(Exception, match="missing required fields"):
            await node.execute_effect(contract)

    @pytest.mark.asyncio
    async def test_stf_not_found(self, setup):
        """Test error handling for non-existent STF."""
        node, _ = setup

        contract = {
            "operation": "retrieve",
            "stf_id": str(uuid4()),  # Random UUID that doesn't exist
        }

        with pytest.raises(Exception, match="not found"):
            await node.execute_effect(contract)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])
