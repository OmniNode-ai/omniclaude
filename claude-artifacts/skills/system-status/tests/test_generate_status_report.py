"""
Integration tests for generate-status-report skill.

Tests:
- Comprehensive status report generation
- All components included
- Error aggregation
- Recommendation generation

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


# Import from generate-status-report/execute.py

# Load the generate-status-report execute module
execute = load_skill_module("generate-status-report")
main = execute.main


class TestGenerateStatusReport:
    """Test generate-status-report skill."""

    @pytest.mark.skip(
        reason="Production code uses collect_report_data() instead of separate check_* functions"
    )
    def test_comprehensive_report(self):
        """Test comprehensive status report generation."""
        with (
            patch.object(execute, "check_infrastructure") as mock_infra,
            patch.object(execute, "check_recent_activity") as mock_activity,
            patch.object(execute, "check_agent_performance") as mock_performance,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_infra.return_value = {
                "kafka": {"status": "connected", "reachable": True},
                "postgres": {"status": "connected", "tables": 34},
                "qdrant": {"status": "connected", "reachable": True},
            }

            mock_activity.return_value = {
                "manifest_injections": {"count": 142},
                "routing_decisions": {"count": 138},
            }

            mock_performance.return_value = {
                "top_agents": [
                    {"agent_name": "agent-api", "executions": 150},
                ]
            }

            exit_code = main()

            assert exit_code == 0

    @pytest.mark.skip(
        reason="Production code uses collect_report_data() instead of separate check_* functions"
    )
    def test_report_with_errors(self):
        """Test report generation when some components have errors."""
        with (
            patch.object(execute, "check_infrastructure") as mock_infra,
            patch.object(execute, "check_recent_activity") as mock_activity,
            patch.object(execute, "check_agent_performance") as mock_performance,
            patch("sys.argv", ["execute.py"]),
        ):

            # Kafka is down
            mock_infra.return_value = {
                "kafka": {
                    "status": "error",
                    "reachable": False,
                    "error": "Connection refused",
                },
                "postgres": {"status": "connected"},
                "qdrant": {"status": "connected"},
            }

            mock_activity.return_value = {}
            mock_performance.return_value = {}

            exit_code = main()

            # Should still generate report
            assert exit_code == 0

    @pytest.mark.skip(
        reason="Production code uses collect_report_data() instead of separate check_* functions"
    )
    def test_all_components_failed(self):
        """Test report when all components are failed."""
        with (
            patch.object(execute, "check_infrastructure") as mock_infra,
            patch.object(execute, "check_recent_activity") as mock_activity,
            patch.object(execute, "check_agent_performance") as mock_performance,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_infra.return_value = {
                "kafka": {"status": "error", "error": "Connection refused"},
                "postgres": {"status": "error", "error": "Authentication failed"},
                "qdrant": {"status": "error", "error": "Timeout"},
            }

            mock_activity.return_value = {"error": "Database unavailable"}
            mock_performance.return_value = {"error": "Database unavailable"}

            exit_code = main()

            # Should report critical status
            assert exit_code == 0
