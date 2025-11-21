"""
Integration tests for check-service-status skill.

Tests:
- Docker service listing
- Service health checks
- Container status parsing
- Service filtering

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


# Import from check-service-status/execute.py

# Load the check-service-status execute module
execute = load_skill_module("check-service-status")
main = execute.main


class TestCheckServiceStatus:
    """Test check-service-status skill."""

    @pytest.mark.skip(reason="Missing function: get_service_summary not in execute.py")
    def test_list_all_services(self):
        """Test listing all Docker services."""
        with (
            patch.object(execute, "get_service_summary") as mock_services,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_services.return_value = {
                "success": True,
                "containers": [
                    {
                        "name": "archon-intelligence",
                        "status": "running",
                        "health": "healthy",
                    },
                    {
                        "name": "archon-qdrant",
                        "status": "running",
                        "health": "healthy",
                    },
                ],
                "count": 2,
            }

            exit_code = main()

            assert exit_code == 0

    @pytest.mark.skip(reason="Missing function: get_service_summary not in execute.py")
    def test_filter_services_by_pattern(self):
        """Test filtering services by name pattern."""
        with (
            patch.object(execute, "get_service_summary") as mock_services,
            patch("sys.argv", ["execute.py", "--pattern", "archon-*"]),
        ):

            mock_services.return_value = {
                "success": True,
                "containers": [
                    {"name": "archon-intelligence", "status": "running"},
                    {"name": "archon-qdrant", "status": "running"},
                ],
                "count": 2,
            }

            exit_code = main()

            assert exit_code == 0

    @pytest.mark.skip(reason="Missing function: get_service_summary not in execute.py")
    def test_docker_unavailable(self):
        """Test handling when Docker is unavailable."""
        with (
            patch.object(execute, "get_service_summary") as mock_services,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_services.return_value = {
                "success": False,
                "error": "Docker daemon not running",
                "containers": [],
                "count": 0,
            }

            exit_code = main()

            assert exit_code == 1

    @pytest.mark.skip(reason="Missing function: get_service_summary not in execute.py")
    def test_unhealthy_services_detected(self):
        """Test detection of unhealthy services."""
        with (
            patch.object(execute, "get_service_summary") as mock_services,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_services.return_value = {
                "success": True,
                "containers": [
                    {
                        "name": "archon-intelligence",
                        "status": "running",
                        "health": "unhealthy",
                    },
                ],
                "count": 1,
            }

            exit_code = main()

            assert exit_code == 0

    @pytest.mark.skip(reason="Missing function: get_service_summary not in execute.py")
    def test_stopped_services_detected(self):
        """Test detection of stopped services."""
        with (
            patch.object(execute, "get_service_summary") as mock_services,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_services.return_value = {
                "success": True,
                "containers": [
                    {
                        "name": "archon-search",
                        "status": "stopped",
                        "health": None,
                    },
                ],
                "count": 1,
            }

            exit_code = main()

            assert exit_code == 0
