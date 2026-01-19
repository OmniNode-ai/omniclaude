"""
Integration tests for check-pattern-discovery skill.

Tests:
- Qdrant collection statistics
- Pattern counts
- Vector counts
- Collection filtering

Created: 2025-11-20
"""

from pathlib import Path
from unittest.mock import patch

# Import load_skill_module from conftest
conftest_path = Path(__file__).parent / "conftest.py"
import importlib.util

spec = importlib.util.spec_from_file_location("conftest", conftest_path)
conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conftest)
load_skill_module = conftest.load_skill_module


# Load the check-pattern-discovery execute module
execute = load_skill_module("check-pattern-discovery")
main = execute.main


class TestCheckPatternDiscovery:
    """Test check-pattern-discovery skill."""

    def test_get_all_collections(self):
        """Test retrieving all Qdrant collections."""
        with (
            patch.object(execute, "get_all_collections_stats") as mock_stats,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_stats.return_value = {
                "success": True,
                "collection_count": 2,
                "total_vectors": 15689,
                "collections": {
                    "archon_vectors": {
                        "vectors_count": 7118,
                        "indexed_vectors_count": 7118,
                        "points_count": 7118,
                    },
                    "code_generation_patterns": {
                        "vectors_count": 8571,
                        "indexed_vectors_count": 8571,
                        "points_count": 8571,
                    },
                },
            }

            exit_code = main()

            assert exit_code == 0

    def test_empty_collections(self):
        """Test handling of empty collections."""

        with (
            patch.object(execute, "get_all_collections_stats") as mock_stats,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_stats.return_value = {
                "success": True,
                "collection_count": 0,
                "total_vectors": 0,
                "collections": {},
            }

            exit_code = main()

            assert exit_code == 0

    def test_qdrant_unavailable(self):
        """Test handling when Qdrant is unavailable."""
        with (
            patch.object(execute, "get_all_collections_stats") as mock_stats,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_stats.return_value = {
                "success": False,
                "error": "Connection timeout",
                "collection_count": 0,
                "total_vectors": 0,
                "collections": {},
            }

            exit_code = main()

            assert exit_code == 1

    def test_collection_statistics(self):
        """Test collection statistics calculation."""
        with (
            patch.object(execute, "get_all_collections_stats") as mock_stats,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_stats.return_value = {
                "success": True,
                "collection_count": 4,
                "total_vectors": 15689,
                "collections": {
                    "archon_vectors": {"vectors_count": 7118},
                    "code_generation_patterns": {"vectors_count": 8571},
                    "archon-intelligence": {"vectors_count": 0},
                    "quality_vectors": {"vectors_count": 0},
                },
            }

            exit_code = main()

            assert exit_code == 0
