"""
Integration tests for check-agent-performance skill.

Tests:
- Top performing agents query
- Performance metrics calculation
- Timeframe filtering
- Top N limiting

Created: 2025-11-20
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# Import load_skill_module from conftest
conftest_path = Path(__file__).parent / "conftest.py"
import importlib.util


spec = importlib.util.spec_from_file_location("conftest", conftest_path)
conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conftest)
load_skill_module = conftest.load_skill_module


# Load the check-agent-performance execute module
execute = load_skill_module("check-agent-performance")
main = execute.main
validate_top_agents = execute.validate_top_agents


class TestCheckAgentPerformance:
    """Test check-agent-performance skill."""

    def test_top_agents_query(self):
        """Test top performing agents query."""
        with (
            patch.object(execute, "execute_query") as mock_query,
            patch(
                "sys.argv", ["execute.py", "--top-agents", "5", "--timeframe", "24h"]
            ),
        ):

            # Mock returns data for multiple queries: routing stats, top agents, transformations
            mock_query.side_effect = [
                {  # Routing stats query
                    "success": True,
                    "rows": [
                        {
                            "total_decisions": 1000,
                            "avg_routing_time_ms": 45.5,
                            "avg_confidence": 0.92,
                            "threshold_violations": 5,
                        }
                    ],
                },
                {  # Top agents query
                    "success": True,
                    "rows": [
                        {"agent": "agent-api", "count": 150, "avg_confidence": 0.98},
                        {
                            "agent": "agent-database",
                            "count": 120,
                            "avg_confidence": 0.99,
                        },
                        {"agent": "agent-onex", "count": 95, "avg_confidence": 0.96},
                    ],
                },
                {  # Transformation stats query
                    "success": True,
                    "rows": [
                        {
                            "total": 50,
                            "success_rate": 0.95,
                            "avg_duration_ms": 120.5,
                        }
                    ],
                },
            ]

            exit_code = main()

            assert exit_code == 0
            # Verify query was called with top=5
            assert mock_query.call_count == 3
            call_params = mock_query.call_args_list[1][1][
                "params"
            ]  # Second call (top agents query)
            assert 5 in call_params

    def test_timeframe_parameter(self):
        """Test timeframe parameter is properly used."""
        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py", "--timeframe", "7d"]),
        ):

            # Mock returns empty but successful results for all queries
            mock_query.side_effect = [
                {
                    "success": True,
                    "rows": [
                        {
                            "total_decisions": 0,
                            "avg_routing_time_ms": 0,
                            "avg_confidence": 0,
                            "threshold_violations": 0,
                        }
                    ],
                },
                {"success": True, "rows": []},
                {"success": True, "rows": []},
            ]

            exit_code = main()

            # Verify query was called with 7d interval
            call_params = mock_query.call_args_list[0][1]["params"]  # First call
            assert "7 days" in call_params

    def test_empty_results(self):
        """Test handling of empty results."""
        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py"]),
        ):

            # Mock returns empty but successful results for all queries
            mock_query.side_effect = [
                {
                    "success": True,
                    "rows": [
                        {
                            "total_decisions": 0,
                            "avg_routing_time_ms": 0,
                            "avg_confidence": 0,
                            "threshold_violations": 0,
                        }
                    ],
                },
                {"success": True, "rows": []},
                {"success": True, "rows": []},
            ]

            exit_code = main()

            assert exit_code == 0

    def test_database_error(self):
        """Test error handling for database failures."""
        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_query.return_value = {
                "success": False,
                "error": "Connection timeout",
                "rows": [],
            }

            exit_code = main()

            # Skills use graceful degradation - still exit 0 even with DB errors
            assert exit_code == 0

    def test_validate_top_agents_bounds(self):
        """Test top_agents parameter validation."""
        import argparse

        # Valid (MIN_TOP_AGENTS=1, MAX_TOP_AGENTS=100)
        assert validate_top_agents("1") == 1
        assert validate_top_agents("10") == 10
        assert validate_top_agents("50") == 50
        assert validate_top_agents("100") == 100  # MAX is 100, so this is valid

        # Invalid - raises argparse.ArgumentTypeError
        with pytest.raises(argparse.ArgumentTypeError):
            validate_top_agents("0")  # Below MIN

        with pytest.raises(argparse.ArgumentTypeError):
            validate_top_agents("101")  # Above MAX

        with pytest.raises(argparse.ArgumentTypeError):
            validate_top_agents("invalid")  # Not an integer
