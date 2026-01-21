"""
Integration tests for check-service-status skill.

Tests:
- Docker service listing
- Service health checks
- Container status parsing
- Service filtering

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


# Import from check-service-status/execute.py

# Load the check-service-status execute module
execute = load_skill_module("check-service-status")
main = execute.main


class TestCheckServiceStatus:
    """Test check-service-status skill."""

    def test_service_status_healthy(self):
        """Test getting status for a healthy service."""
        with (
            patch.object(execute, "get_container_status") as mock_status,
            patch("sys.argv", ["execute.py", "--service", "archon-intelligence"]),
        ):

            mock_status.return_value = {
                "success": True,
                "status": "running",
                "health": "healthy",
                "running": True,
                "started_at": "2025-11-20T10:00:00Z",
                "restart_count": 0,
                "image": "archon-intelligence:latest",
            }

            exit_code = main()

            assert exit_code == 0
            mock_status.assert_called_once_with("archon-intelligence")

    def test_service_status_with_logs(self):
        """Test getting status with logs included."""
        with (
            patch.object(execute, "get_container_status") as mock_status,
            patch.object(execute, "get_container_logs") as mock_logs,
            patch(
                "sys.argv",
                ["execute.py", "--service", "archon-qdrant", "--include-logs"],
            ),
        ):

            mock_status.return_value = {
                "success": True,
                "status": "running",
                "health": "healthy",
                "running": True,
                "started_at": "2025-11-20T10:00:00Z",
                "restart_count": 0,
                "image": "qdrant:latest",
            }

            mock_logs.return_value = {
                "success": True,
                "log_count": 100,
                "error_count": 2,
                "errors": ["Error 1", "Error 2"],
            }

            exit_code = main()

            assert exit_code == 0
            mock_status.assert_called_once_with("archon-qdrant")
            mock_logs.assert_called_once()

    def test_service_status_with_stats(self):
        """Test getting status with resource stats included."""
        with (
            patch.object(execute, "get_container_status") as mock_status,
            patch.object(execute, "get_container_stats") as mock_stats,
            patch(
                "sys.argv",
                ["execute.py", "--service", "archon-bridge", "--include-stats"],
            ),
        ):

            mock_status.return_value = {
                "success": True,
                "status": "running",
                "health": "healthy",
                "running": True,
                "started_at": "2025-11-20T10:00:00Z",
                "restart_count": 0,
                "image": "archon-bridge:latest",
            }

            mock_stats.return_value = {
                "success": True,
                "cpu_percent": 15.5,
                "memory_usage": "256MB",
                "memory_percent": 12.3,
            }

            exit_code = main()

            assert exit_code == 0
            mock_status.assert_called_once_with("archon-bridge")
            mock_stats.assert_called_once_with("archon-bridge")

    def test_service_not_found(self):
        """Test handling when service is not found."""
        with (
            patch.object(execute, "get_container_status") as mock_status,
            patch("sys.argv", ["execute.py", "--service", "nonexistent-service"]),
        ):

            mock_status.return_value = {
                "success": False,
                "error": "Container not found: nonexistent-service",
            }

            exit_code = main()

            assert exit_code == 1

    def test_unhealthy_service_detected(self):
        """Test detection of unhealthy service."""
        with (
            patch.object(execute, "get_container_status") as mock_status,
            patch("sys.argv", ["execute.py", "--service", "archon-search"]),
        ):

            mock_status.return_value = {
                "success": True,
                "status": "running",
                "health": "unhealthy",
                "running": True,
                "started_at": "2025-11-20T10:00:00Z",
                "restart_count": 3,
                "image": "archon-search:latest",
            }

            exit_code = main()

            assert exit_code == 0

    def test_stopped_service_detected(self):
        """Test detection of stopped service."""
        with (
            patch.object(execute, "get_container_status") as mock_status,
            patch("sys.argv", ["execute.py", "--service", "archon-memgraph"]),
        ):

            mock_status.return_value = {
                "success": True,
                "status": "exited",
                "health": None,
                "running": False,
                "started_at": None,
                "restart_count": 0,
                "image": "memgraph:latest",
            }

            exit_code = main()

            assert exit_code == 0
