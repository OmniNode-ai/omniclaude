"""
Unit tests for timeframe parsing helper.

Tests parse_timeframe() function with:
- Valid shorthand codes (5m, 15m, 1h, 24h, 7d, 30d)
- Invalid inputs
- Edge cases

Created: 2025-11-20
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

from timeframe_helper import parse_timeframe


class TestParseTimeframe:
    """Test timeframe parsing functionality."""

    def test_valid_minutes(self):
        """Test minute-based timeframes."""
        assert parse_timeframe("5m") == "5 minutes"
        assert parse_timeframe("15m") == "15 minutes"

    def test_valid_hours(self):
        """Test hour-based timeframes."""
        assert parse_timeframe("1h") == "1 hour"
        assert parse_timeframe("24h") == "24 hours"

    def test_valid_days(self):
        """Test day-based timeframes."""
        assert parse_timeframe("7d") == "7 days"
        assert parse_timeframe("30d") == "30 days"

    def test_invalid_timeframe(self):
        """Test invalid timeframe codes."""
        with pytest.raises(ValueError, match="Unsupported timeframe") as exc_info:
            parse_timeframe("10s")
        assert "Unsupported timeframe" in str(exc_info.value)
        assert "Valid options" in str(exc_info.value)

    def test_invalid_format(self):
        """Test malformed timeframe codes."""
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            parse_timeframe("5minutes")

        with pytest.raises(ValueError, match="Unsupported timeframe"):
            parse_timeframe("1 hour")

        with pytest.raises(ValueError, match="Unsupported timeframe"):
            parse_timeframe("invalid")

    def test_case_sensitive(self):
        """Test that parsing is case-sensitive."""
        # Uppercase should fail
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            parse_timeframe("5M")

        with pytest.raises(ValueError, match="Unsupported timeframe"):
            parse_timeframe("1H")

        with pytest.raises(ValueError, match="Unsupported timeframe"):
            parse_timeframe("7D")

    def test_empty_string(self):
        """Test empty timeframe."""
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            parse_timeframe("")

    def test_none_value(self):
        """Test None value handling."""
        # Should raise an exception (ValueError, AttributeError, or TypeError)
        with pytest.raises((ValueError, AttributeError, TypeError)):
            parse_timeframe(None)
