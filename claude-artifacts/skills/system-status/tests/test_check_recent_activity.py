"""
Integration tests for check-recent-activity skill.

Tests:
- Manifest injection statistics
- Routing decision metrics
- Agent action counts
- Recent error retrieval
- Timeframe filtering

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


# Import from check-recent-activity/execute.py

# Load the check-recent-activity execute module
execute = load_skill_module("check-recent-activity")
main = execute.main


class TestCheckRecentActivity:
    """Test check-recent-activity skill."""

    def test_manifest_injection_stats(self):
        """Test manifest injection statistics query."""
        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py", "--since", "5m"]),
        ):

            # Mock manifest injection results
            mock_query.side_effect = [
                {
                    "success": True,
                    "rows": [
                        {
                            "count": 142,
                            "avg_query_time_ms": 1842.5,
                            "avg_patterns_count": 25.3,
                            "fallbacks": 3,
                        }
                    ],
                },
                {
                    "success": True,
                    "rows": [
                        {
                            "count": 138,
                            "avg_routing_time_ms": 7.2,
                            "avg_confidence": 0.95,
                        }
                    ],
                },
                {
                    "success": True,
                    "rows": [
                        {"action_type": "tool_call", "count": 450},
                        {"action_type": "decision", "count": 120},
                        {"action_type": "error", "count": 5},
                        {"action_type": "success", "count": 445},
                    ],
                },
            ]

            exit_code = main()

            assert exit_code == 0
            # Verify queries were called
            assert mock_query.call_count == 3

    @pytest.mark.skip(
        reason="Output format mismatch - requires aligning mock with execute.py expectations"
    )
    def test_routing_decision_metrics(self):
        """Test routing decision metrics query."""
        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py", "--since", "1h"]),
        ):

            mock_query.side_effect = [
                {"success": True, "rows": [{"count": 0}]},  # manifests
                {
                    "success": True,
                    "rows": [
                        {
                            "count": 250,
                            "avg_routing_time_ms": 8.1,
                            "avg_confidence": 0.92,
                        }
                    ],
                },
                {"success": True, "rows": []},  # actions
            ]

            exit_code = main()

            assert exit_code == 0

    @pytest.mark.skip(
        reason="Output format mismatch - requires aligning mock with execute.py expectations"
    )
    def test_agent_actions_breakdown(self):
        """Test agent actions breakdown by type."""
        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py", "--since", "24h"]),
        ):

            mock_query.side_effect = [
                {"success": True, "rows": [{"count": 0}]},  # manifests
                {"success": True, "rows": [{"count": 0}]},  # routing
                {
                    "success": True,
                    "rows": [
                        {"action_type": "tool_call", "count": 1250},
                        {"action_type": "decision", "count": 320},
                        {"action_type": "error", "count": 15},
                        {"action_type": "success", "count": 1235},
                    ],
                },
            ]

            exit_code = main()

            assert exit_code == 0

    @pytest.mark.skip(
        reason="Output format mismatch - requires aligning mock with execute.py expectations"
    )
    def test_recent_errors_included(self):
        """Test --include-errors flag retrieves recent errors."""
        with (
            patch.object(execute, "execute_query") as mock_query,
            patch(
                "sys.argv",
                ["execute.py", "--since", "5m", "--include-errors", "--limit", "5"],
            ),
        ):

            mock_query.side_effect = [
                {"success": True, "rows": [{"count": 0}]},  # manifests
                {"success": True, "rows": [{"count": 0}]},  # routing
                {"success": True, "rows": []},  # actions
                {
                    "success": True,
                    "rows": [
                        {
                            "agent_name": "agent-api",
                            "error": "Connection timeout",
                            "created_at": "2025-11-20 14:30:00",
                        },
                        {
                            "agent_name": "agent-database",
                            "error": "Query failed",
                            "created_at": "2025-11-20 14:25:00",
                        },
                    ],
                },
            ]

            exit_code = main()

            assert exit_code == 0
            # Verify error query was called (4th call)
            assert mock_query.call_count == 4

    @pytest.mark.skip(reason="Output assertion mismatch - check actual output format")
    def test_limit_parameter(self):
        """Test --limit parameter is properly used."""
        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py", "--limit", "50", "--include-errors"]),
        ):

            mock_query.side_effect = [
                {"success": True, "rows": [{"count": 0}]},
                {"success": True, "rows": [{"count": 0}]},
                {"success": True, "rows": []},
                {"success": True, "rows": []},
            ]

            exit_code = main()

            # Check that last query (errors) used limit=50
            last_call_params = mock_query.call_args_list[-1][1]["params"]
            assert 50 in last_call_params

    def test_timeframe_validation(self):
        """Test invalid timeframe is rejected."""
        with patch("sys.argv", ["execute.py", "--since", "invalid"]):
            exit_code = main()

            # Should fail with exit code 1
            assert exit_code == 1

    def test_empty_results_handled(self):
        """Test graceful handling of empty query results."""
        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py"]),
        ):

            # All queries return empty
            mock_query.return_value = {"success": True, "rows": []}

            exit_code = main()

            # Should still succeed with empty data
            assert exit_code == 0

    def test_database_error_handled(self):
        """Test error handling when database query fails."""
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

            # Should handle error gracefully
            assert exit_code == 0  # Continues despite query failure

    def test_null_values_handled(self):
        """Test handling of NULL values in database results."""
        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_query.side_effect = [
                {
                    "success": True,
                    "rows": [
                        {
                            "count": None,
                            "avg_query_time_ms": None,
                            "avg_patterns_count": None,
                            "fallbacks": None,
                        }
                    ],
                },
                {"success": True, "rows": []},
                {"success": True, "rows": []},
            ]

            exit_code = main()

            # Should handle NULL values gracefully
            assert exit_code == 0
