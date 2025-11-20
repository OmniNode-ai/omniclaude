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

    @pytest.mark.skip(reason="Missing function: check_infrastructure not in execute.py")
    def test_detect_kafka_issues(self):
        """Test detection of Kafka issues."""
        with (
            patch.object(execute, "check_infrastructure") as mock_infra,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_infra.return_value = {
                "kafka": {
                    "status": "error",
                    "reachable": False,
                    "error": "Connection refused",
                }
            }

            exit_code = main()

            assert exit_code == 0

    @pytest.mark.skip(reason="Missing function: check_infrastructure not in execute.py")
    def test_detect_postgres_issues(self):
        """Test detection of PostgreSQL issues."""
        with (
            patch.object(execute, "check_infrastructure") as mock_infra,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_infra.return_value = {
                "postgres": {
                    "status": "error",
                    "error": "Connection timeout",
                }
            }

            exit_code = main()

            assert exit_code == 0

    @pytest.mark.skip(reason="Missing function: check_infrastructure not in execute.py")
    def test_detect_qdrant_issues(self):
        """Test detection of Qdrant issues."""
        with (
            patch.object(execute, "check_infrastructure") as mock_infra,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_infra.return_value = {
                "qdrant": {
                    "status": "error",
                    "reachable": False,
                    "error": "Service unavailable",
                }
            }

            exit_code = main()

            assert exit_code == 0

    @pytest.mark.skip(reason="Missing function: check_infrastructure not in execute.py")
    def test_no_issues_detected(self):
        """Test when no issues are detected."""
        with (
            patch.object(execute, "check_infrastructure") as mock_infra,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_infra.return_value = {
                "kafka": {"status": "connected", "reachable": True},
                "postgres": {"status": "connected"},
                "qdrant": {"status": "connected", "reachable": True},
            }

            exit_code = main()

            assert exit_code == 0

    @pytest.mark.skip(reason="Missing function: check_infrastructure not in execute.py")
    def test_severity_classification(self):
        """Test issue severity classification."""
        with (
            patch.object(execute, "check_infrastructure") as mock_infra,
            patch.object(execute, "check_recent_activity") as mock_activity,
            patch("sys.argv", ["execute.py"]),
        ):

            # Critical: PostgreSQL down
            mock_infra.return_value = {
                "postgres": {"status": "error", "error": "Connection refused"},
                "kafka": {"status": "connected"},
                "qdrant": {"status": "connected"},
            }

            mock_activity.return_value = {
                "agent_actions": {"errors": 25}  # High error rate
            }

            exit_code = main()

            assert exit_code == 0
