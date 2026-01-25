"""
Unit tests for input validators across all skills.

Tests validation functions for:
- Limit parameters (1-1000 range)
- Log line counts
- Top agent counts
- Component selection

Created: 2025-11-20
"""

import argparse
import importlib.util
from pathlib import Path

import pytest

# Import validators from specific skills using importlib
# This avoids ambiguity since all skills have execute.py

# Import validate_limit from check-recent-activity
spec = importlib.util.spec_from_file_location(
    "execute_recent_activity",
    Path(__file__).parent.parent / "check-recent-activity" / "execute.py",
)
execute_recent_activity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(execute_recent_activity)
validate_limit = execute_recent_activity.validate_limit

# Import validate_log_lines from check-service-status
spec = importlib.util.spec_from_file_location(
    "execute_service_status",
    Path(__file__).parent.parent / "check-service-status" / "execute.py",
)
execute_service_status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(execute_service_status)
validate_log_lines = execute_service_status.validate_log_lines

# Import validate_top_agents from check-agent-performance
spec = importlib.util.spec_from_file_location(
    "execute_agent_performance",
    Path(__file__).parent.parent / "check-agent-performance" / "execute.py",
)
execute_agent_performance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(execute_agent_performance)
validate_top_agents = execute_agent_performance.validate_top_agents


class TestLimitValidator:
    """Test validate_limit() function from check-recent-activity."""

    def test_valid_limits(self):
        """Test valid limit values."""
        assert validate_limit("1") == 1
        assert validate_limit("100") == 100
        assert validate_limit("500") == 500
        assert validate_limit("1000") == 1000

    def test_limit_below_minimum(self):
        """Test limit below 1."""
        with pytest.raises(argparse.ArgumentTypeError):
            validate_limit("0")

        with pytest.raises(argparse.ArgumentTypeError):
            validate_limit("-5")

    def test_limit_above_maximum(self):
        """Test limit above 1000."""
        with pytest.raises(argparse.ArgumentTypeError):
            validate_limit("1001")

        with pytest.raises(argparse.ArgumentTypeError):
            validate_limit("9999")

    def test_limit_invalid_type(self):
        """Test non-numeric limit."""
        with pytest.raises(ValueError, match="invalid literal for int"):
            validate_limit("abc")

        with pytest.raises(ValueError, match="invalid literal for int"):
            validate_limit("12.5")


class TestLogLinesValidator:
    """Test validate_log_lines() function from check-service-status."""

    def test_valid_log_lines(self):
        """Test valid log line counts."""
        assert validate_log_lines("10") == 10
        assert validate_log_lines("50") == 50
        assert validate_log_lines("100") == 100

    def test_log_lines_below_minimum(self):
        """Test log lines below 1."""
        with pytest.raises(argparse.ArgumentTypeError):
            validate_log_lines("0")

    def test_log_lines_above_maximum(self):
        """Test log lines above 10000."""
        with pytest.raises(argparse.ArgumentTypeError):
            validate_log_lines("10001")

        with pytest.raises(argparse.ArgumentTypeError):
            validate_log_lines("99999")


class TestTopAgentsValidator:
    """Test validate_top_agents() function from check-agent-performance."""

    def test_valid_top_agents(self):
        """Test valid top agent counts."""
        assert validate_top_agents("1") == 1
        assert validate_top_agents("5") == 5
        assert validate_top_agents("20") == 20

    def test_top_agents_below_minimum(self):
        """Test top agents below 1."""
        with pytest.raises(argparse.ArgumentTypeError):
            validate_top_agents("0")

    def test_top_agents_above_maximum(self):
        """Test top agents above 100."""
        with pytest.raises(argparse.ArgumentTypeError):
            validate_top_agents("101")

        with pytest.raises(argparse.ArgumentTypeError):
            validate_top_agents("999")
