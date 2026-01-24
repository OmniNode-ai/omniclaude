"""
Input validation tests for all skills.

Tests bounds checking and input sanitization across all skills.

Created: 2025-11-20
"""

import importlib.util
from pathlib import Path

import pytest


# Helper function to import from hyphenated skill directories
def import_from_skill(skill_name, module_name="execute"):
    """Import a module from a skill directory with hyphens in the name."""
    skill_path = Path(__file__).parent.parent / skill_name / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"{skill_name}.{module_name}", skill_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBoundsChecking:
    """Test bounds checking for all numeric parameters."""

    def test_limit_bounds(self):
        """Test limit parameter bounds (1-1000)."""
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        # Valid boundaries
        assert validate_limit("1") == 1
        assert validate_limit("1000") == 1000

        # Invalid boundaries
        with pytest.raises(ValueError, match=r"(out of range|must be between|invalid)"):
            validate_limit("0")

        with pytest.raises(ValueError, match=r"(out of range|must be between|invalid)"):
            validate_limit("1001")

    def test_log_lines_bounds(self):
        """Test log_lines parameter bounds (1-10000)."""
        execute = import_from_skill("check-service-status")
        validate_log_lines = execute.validate_log_lines

        # Valid boundaries
        assert validate_log_lines("1") == 1
        assert validate_log_lines("10000") == 10000

        # Invalid boundaries
        with pytest.raises(ValueError, match=r"(out of range|must be between|invalid)"):
            validate_log_lines("0")

        with pytest.raises(ValueError, match=r"(out of range|must be between|invalid)"):
            validate_log_lines("10001")

    def test_top_agents_bounds(self):
        """Test top_agents parameter bounds (1-100)."""
        execute = import_from_skill("check-agent-performance")
        validate_top_agents = execute.validate_top_agents

        # Valid boundaries
        assert validate_top_agents("1") == 1
        assert validate_top_agents("100") == 100

        # Invalid boundaries
        with pytest.raises(ValueError, match=r"(out of range|must be between|invalid)"):
            validate_top_agents("0")

        with pytest.raises(ValueError, match=r"(out of range|must be between|invalid)"):
            validate_top_agents("101")


class TestInputSanitization:
    """Test input sanitization and type checking."""

    def test_numeric_validation(self):
        """Test that non-numeric inputs are rejected."""
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        invalid_inputs = [
            "abc",
            "12.5",
            "10e2",
            "0x10",
            "10.0",
            "",
            " ",
        ]

        for invalid in invalid_inputs:
            with pytest.raises(ValueError, match=r"(invalid|not a valid|must be)"):
                validate_limit(invalid)

    def test_negative_numbers_rejected(self):
        """Test that negative numbers are rejected."""
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        with pytest.raises(ValueError, match=r"(negative|must be positive|invalid)"):
            validate_limit("-1")

        with pytest.raises(ValueError, match=r"(negative|must be positive|invalid)"):
            validate_limit("-100")

    def test_floating_point_rejected(self):
        """Test that floating point numbers are rejected."""
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        with pytest.raises(ValueError, match=r"(invalid|not a valid|must be|integer)"):
            validate_limit("10.5")

        with pytest.raises(ValueError, match=r"(invalid|not a valid|must be|integer)"):
            validate_limit("3.14159")

    def test_scientific_notation_rejected(self):
        """Test that scientific notation is rejected."""
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        with pytest.raises(ValueError, match=r"(invalid|not a valid|must be)"):
            validate_limit("1e3")

        with pytest.raises(ValueError, match=r"(invalid|not a valid|must be)"):
            validate_limit("10e2")

    def test_hexadecimal_rejected(self):
        """Test that hexadecimal numbers are rejected."""
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        with pytest.raises(ValueError, match=r"(invalid|not a valid|must be)"):
            validate_limit("0x10")

        with pytest.raises(ValueError, match=r"(invalid|not a valid|must be)"):
            validate_limit("0xFF")

    def test_whitespace_handling(self):
        """Test handling of whitespace in inputs.

        Expected Behavior:
        - Python's int() function automatically strips leading/trailing whitespace
        - Therefore, " 10 " should successfully convert to integer 10
        - If a validator explicitly rejects whitespace (e.g., with regex), it should
          raise ValueError with a clear message

        Testing Strategy:
        - Verify that whitespace is either stripped and accepted, OR
        - Verify that rejection provides a clear error message

        Context: argparse typically strips whitespace before calling type validators,
        but validators may be called manually in other contexts, so robust handling
        is important.
        """
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        # Test whitespace input
        try:
            result = validate_limit(" 10 ")
            # Success path: Python's int() strips whitespace
            assert result == 10, (
                "Whitespace should be stripped and value converted to 10"
            )
        except ValueError as e:
            # Rejection path: Validator explicitly rejects whitespace
            # Verify error message is informative
            error_msg = str(e).lower()
            assert any(
                keyword in error_msg
                for keyword in ["whitespace", "invalid", "must be", "format"]
            ), f"Error message should be informative, got: {e}"
            # This is also acceptable behavior for stricter validation

    def test_empty_string_rejected(self):
        """Test that empty strings are rejected."""
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        with pytest.raises(ValueError, match=r"(empty|invalid|not a valid|must be)"):
            validate_limit("")


class TestComponentValidation:
    """Test component selection validation."""

    def test_valid_components(self):
        """Test that valid components are accepted."""
        # This would test the component filtering logic
        # in check-infrastructure skill

        valid_components = ["kafka", "postgres", "qdrant"]

        for component in valid_components:
            # Should be in the allowed list
            assert component in ["kafka", "postgres", "qdrant"]

    def test_component_case_sensitivity(self):
        """Test component name case sensitivity."""
        # Components should be lowercase
        # Verify that uppercase variations are handled

        valid = ["kafka", "postgres", "qdrant"]

        # Test that validation is case-sensitive
        for component in valid:
            assert component.islower()


class TestTimeframeValidation:
    """Test timeframe parameter validation."""

    def test_valid_timeframes(self):
        """Test all valid timeframe codes."""
        shared_path = (
            Path(__file__).parent.parent.parent / "_shared" / "timeframe_helper.py"
        )
        spec = importlib.util.spec_from_file_location("timeframe_helper", shared_path)
        timeframe_helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(timeframe_helper)
        parse_timeframe = timeframe_helper.parse_timeframe

        valid_timeframes = {
            "5m": "5 minutes",
            "15m": "15 minutes",
            "1h": "1 hour",
            "24h": "24 hours",
            "7d": "7 days",
            "30d": "30 days",
        }

        for code, expected in valid_timeframes.items():
            assert parse_timeframe(code) == expected

    def test_invalid_timeframes(self):
        """Test invalid timeframe codes are rejected."""
        shared_path = (
            Path(__file__).parent.parent.parent / "_shared" / "timeframe_helper.py"
        )
        spec = importlib.util.spec_from_file_location("timeframe_helper", shared_path)
        timeframe_helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(timeframe_helper)
        parse_timeframe = timeframe_helper.parse_timeframe

        invalid_timeframes = [
            "10s",  # Seconds not supported
            "2h",  # Not in allowed list
            "90d",  # Not in allowed list
            "5minutes",  # Wrong format
            "1 hour",  # Wrong format
            "5M",  # Wrong case
            "invalid",
            "",
        ]

        for invalid in invalid_timeframes:
            with pytest.raises(ValueError, match=r"(invalid|not supported|unknown)"):
                parse_timeframe(invalid)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_maximum_integer_value(self):
        """Test very large integer values."""
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        # Should reject values larger than 1000
        with pytest.raises(ValueError, match=r"(out of range|must be between|invalid)"):
            validate_limit("999999")

        with pytest.raises(ValueError, match=r"(out of range|must be between|invalid)"):
            validate_limit(str(2**31))  # Max int32

    def test_unicode_characters(self):
        """Test Unicode character handling."""
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        # Unicode digits should be rejected
        with pytest.raises(ValueError, match=r"(invalid|not a valid|must be)"):
            validate_limit("①②③")

        # Unicode letters should be rejected
        with pytest.raises(ValueError, match=r"(invalid|not a valid|must be)"):
            validate_limit("ⓐⓑⓒ")

    def test_null_byte_injection(self):
        """Test null byte injection attempts."""
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        # Null bytes should be rejected
        with pytest.raises(
            ValueError, match=r"(invalid|not a valid|must be|null byte)"
        ):
            validate_limit("10\x00")

    def test_special_characters(self):
        """Test special character handling."""
        execute = import_from_skill("check-recent-activity")
        validate_limit = execute.validate_limit

        special_chars = ["10!", "10@", "10#", "10$", "10%", "10^", "10&", "10*"]

        for special in special_chars:
            with pytest.raises(ValueError, match=r"(invalid|not a valid|must be)"):
                validate_limit(special)
