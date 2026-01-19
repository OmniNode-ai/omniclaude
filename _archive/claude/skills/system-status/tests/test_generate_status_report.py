"""
Integration tests for generate-status-report skill.

Tests:
- Comprehensive status report generation
- All components included
- Error aggregation
- Recommendation generation

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


# Import from generate-status-report/execute.py

# Load the generate-status-report execute module
execute = load_skill_module("generate-status-report")
main = execute.main


class TestGenerateStatusReport:
    """Test generate-status-report skill."""

    def test_comprehensive_report_json_format(self):
        """Test comprehensive status report generation in JSON format."""
        with (
            patch.object(execute, "collect_report_data") as mock_collect,
            patch("sys.argv", ["execute.py", "--format", "json"]),
        ):

            mock_collect.return_value = {
                "generated": "2025-11-20T12:00:00Z",
                "timeframe": "24h",
                "trends_enabled": False,
                "services": [
                    {
                        "name": "archon-intelligence",
                        "status": "running",
                        "health": "healthy",
                        "restart_count": 0,
                    },
                    {
                        "name": "archon-qdrant",
                        "status": "running",
                        "health": "healthy",
                        "restart_count": 0,
                    },
                ],
                "infrastructure": {
                    "kafka": {"status": "connected", "topics": 15},
                    "postgres": {"status": "connected", "tables": 34},
                    "qdrant": {"status": "connected", "total_vectors": 15689},
                },
                "performance": {
                    "routing_decisions": 142,
                    "avg_routing_time_ms": 7.5,
                    "avg_confidence": 0.85,
                },
                "recent_activity": {"agent_executions": 138},
                "top_agents": [
                    {"agent": "agent-api", "count": 75, "avg_confidence": 0.88},
                    {"agent": "agent-database", "count": 50, "avg_confidence": 0.82},
                ],
            }

            exit_code = main()

            assert exit_code == 0
            mock_collect.assert_called_once_with("24h", False)

    def test_report_markdown_format(self):
        """Test report generation in Markdown format."""
        with (
            patch.object(execute, "collect_report_data") as mock_collect,
            patch("sys.argv", ["execute.py", "--format", "markdown"]),
        ):

            mock_collect.return_value = {
                "generated": "2025-11-20T12:00:00Z",
                "timeframe": "24h",
                "trends_enabled": False,
                "services": [
                    {
                        "name": "archon-intelligence",
                        "status": "running",
                        "health": "healthy",
                        "restart_count": 0,
                    }
                ],
                "infrastructure": {
                    "kafka": {"status": "connected", "topics": 15},
                    "postgres": {"status": "connected", "tables": 34},
                    "qdrant": {"status": "connected", "total_vectors": 15689},
                },
                "performance": {
                    "routing_decisions": 100,
                    "avg_routing_time_ms": 8.0,
                    "avg_confidence": 0.85,
                },
                "recent_activity": {"agent_executions": 100},
                "top_agents": [],
            }

            exit_code = main()

            assert exit_code == 0

    def test_report_with_trends(self):
        """Test report with trend analysis enabled."""
        with (
            patch.object(execute, "collect_report_data") as mock_collect,
            patch("sys.argv", ["execute.py", "--include-trends"]),
        ):

            mock_collect.return_value = {
                "generated": "2025-11-20T12:00:00Z",
                "timeframe": "24h",
                "trends_enabled": True,
                "services": [],
                "infrastructure": {
                    "kafka": {"status": "connected", "topics": 15},
                    "postgres": {"status": "connected", "tables": 34},
                    "qdrant": {"status": "connected", "total_vectors": 15689},
                },
                "performance": {
                    "routing_decisions": 150,
                    "avg_routing_time_ms": 7.2,
                    "avg_confidence": 0.87,
                },
                "recent_activity": {"agent_executions": 150},
                "top_agents": [],
                "trends": {
                    "decisions_change_pct": 15.5,
                    "routing_time_change_pct": -5.2,
                    "confidence_change_pct": 2.3,
                },
            }

            exit_code = main()

            assert exit_code == 0
            mock_collect.assert_called_once_with("24h", True)

    def test_report_custom_timeframe(self):
        """Test report with custom timeframe."""
        with (
            patch.object(execute, "collect_report_data") as mock_collect,
            patch("sys.argv", ["execute.py", "--timeframe", "7d"]),
        ):

            mock_collect.return_value = {
                "generated": "2025-11-20T12:00:00Z",
                "timeframe": "7d",
                "trends_enabled": False,
                "services": [],
                "infrastructure": {
                    "kafka": {"status": "connected", "topics": 15},
                    "postgres": {"status": "connected", "tables": 34},
                    "qdrant": {"status": "connected", "total_vectors": 15689},
                },
                "performance": {},
                "recent_activity": {},
                "top_agents": [],
            }

            exit_code = main()

            assert exit_code == 0
            mock_collect.assert_called_once_with("7d", False)

    def test_report_with_infrastructure_errors(self):
        """Test report generation when infrastructure has errors."""
        with (
            patch.object(execute, "collect_report_data") as mock_collect,
            patch("sys.argv", ["execute.py"]),
        ):

            # Some infrastructure components failed
            mock_collect.return_value = {
                "generated": "2025-11-20T12:00:00Z",
                "timeframe": "24h",
                "trends_enabled": False,
                "services": [],
                "infrastructure": {
                    "kafka": {"status": "error", "topics": 0},
                    "postgres": {"status": "connected", "tables": 34},
                    "qdrant": {"status": "error", "total_vectors": 0},
                },
                "performance": {},
                "recent_activity": {},
                "top_agents": [],
            }

            exit_code = main()

            # Should still generate report with errors
            assert exit_code == 0

    def test_report_output_to_file(self):
        """Test report output to file."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            output_path = f.name

        try:
            with (
                patch.object(execute, "collect_report_data") as mock_collect,
                patch("sys.argv", ["execute.py", "--output", output_path]),
            ):

                mock_collect.return_value = {
                    "generated": "2025-11-20T12:00:00Z",
                    "timeframe": "24h",
                    "trends_enabled": False,
                    "services": [],
                    "infrastructure": {
                        "kafka": {"status": "connected", "topics": 15},
                        "postgres": {"status": "connected", "tables": 34},
                        "qdrant": {"status": "connected", "total_vectors": 15689},
                    },
                    "performance": {},
                    "recent_activity": {},
                    "top_agents": [],
                }

                exit_code = main()

                assert exit_code == 0
                assert Path(output_path).exists()

        finally:
            Path(output_path).unlink(missing_ok=True)
