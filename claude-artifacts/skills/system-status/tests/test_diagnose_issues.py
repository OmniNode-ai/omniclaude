"""
Integration tests for diagnose-issues skill.

Tests:
- Issue detection
- Severity classification
- Recommendation generation
- Multi-component analysis

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


# Import from diagnose-issues/execute.py

# Load the diagnose-issues execute module
execute = load_skill_module("diagnose-issues")
main = execute.main


class TestDiagnoseIssues:
    """Test diagnose-issues skill."""

    def test_detect_kafka_issues(self):
        """Test detection of Kafka issues."""
        with (
            patch.object(execute, "check_kafka_connection") as mock_kafka,
            patch.object(execute, "execute_query") as mock_db,
            patch.object(execute, "check_qdrant_connection") as mock_qdrant,
            patch.object(execute, "list_containers") as mock_containers,
            patch("sys.argv", ["execute.py"]),
        ):
            # Mock Kafka failure
            mock_kafka.return_value = {
                "reachable": False,
                "error": "Connection refused",
            }

            # Mock successful PostgreSQL and Qdrant
            mock_db.return_value = {"success": True, "rows": []}
            mock_qdrant.return_value = {"reachable": True}

            # Mock successful Docker
            mock_containers.return_value = {"success": True, "containers": []}

            exit_code = main()

            # Kafka issue is critical, expect exit code 2
            assert exit_code == 2

    def test_detect_postgres_issues(self):
        """Test detection of PostgreSQL issues."""
        with (
            patch.object(execute, "check_kafka_connection") as mock_kafka,
            patch.object(execute, "execute_query") as mock_db,
            patch.object(execute, "check_qdrant_connection") as mock_qdrant,
            patch.object(execute, "list_containers") as mock_containers,
            patch("sys.argv", ["execute.py"]),
        ):
            # Mock PostgreSQL failure
            mock_db.return_value = {
                "success": False,
                "error": "Connection timeout",
            }

            # Mock successful Kafka and Qdrant
            mock_kafka.return_value = {"reachable": True}
            mock_qdrant.return_value = {"reachable": True}

            # Mock successful Docker
            mock_containers.return_value = {"success": True, "containers": []}

            exit_code = main()

            # PostgreSQL issue is critical, expect exit code 2
            assert exit_code == 2

    def test_detect_qdrant_issues(self):
        """Test detection of Qdrant issues."""
        with (
            patch.object(execute, "check_kafka_connection") as mock_kafka,
            patch.object(execute, "execute_query") as mock_db,
            patch.object(execute, "check_qdrant_connection") as mock_qdrant,
            patch.object(execute, "list_containers") as mock_containers,
            patch("sys.argv", ["execute.py"]),
        ):
            # Mock Qdrant failure
            mock_qdrant.return_value = {
                "reachable": False,
                "error": "Service unavailable",
            }

            # Mock successful Kafka and PostgreSQL
            mock_kafka.return_value = {"reachable": True}
            mock_db.return_value = {"success": True, "rows": []}

            # Mock successful Docker
            mock_containers.return_value = {"success": True, "containers": []}

            exit_code = main()

            # Qdrant issue is critical, expect exit code 2
            assert exit_code == 2

    def test_no_issues_detected(self):
        """Test when no issues are detected."""
        with (
            patch.object(execute, "check_kafka_connection") as mock_kafka,
            patch.object(execute, "execute_query") as mock_db,
            patch.object(execute, "check_qdrant_connection") as mock_qdrant,
            patch.object(execute, "list_containers") as mock_containers,
            patch("sys.argv", ["execute.py"]),
        ):
            # Mock all services healthy
            mock_kafka.return_value = {"reachable": True}
            mock_db.return_value = {"success": True, "rows": []}
            mock_qdrant.return_value = {"reachable": True}
            mock_containers.return_value = {"success": True, "containers": []}

            exit_code = main()

            # No issues, expect exit code 0
            assert exit_code == 0

    def test_severity_classification(self):
        """Test issue severity classification."""
        with (
            patch.object(execute, "check_kafka_connection") as mock_kafka,
            patch.object(execute, "execute_query") as mock_db,
            patch.object(execute, "check_qdrant_connection") as mock_qdrant,
            patch.object(execute, "list_containers") as mock_containers,
            patch("sys.argv", ["execute.py"]),
        ):
            # Mock PostgreSQL failure (critical)
            mock_db.return_value = {
                "success": False,
                "error": "Connection refused",
            }

            # Mock successful Kafka and Qdrant
            mock_kafka.return_value = {"reachable": True}
            mock_qdrant.return_value = {"reachable": True}

            # Mock successful Docker
            mock_containers.return_value = {"success": True, "containers": []}

            exit_code = main()

            # Critical issue, expect exit code 2
            assert exit_code == 2
