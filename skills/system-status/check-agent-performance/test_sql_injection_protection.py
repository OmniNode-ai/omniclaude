#!/usr/bin/env python3
"""
Test SQL Injection Protection for check-agent-performance skill

This test verifies that the parse_timeframe() function properly validates
user input and prevents SQL injection attempts.

Created: 2025-11-20
"""

import sys
import unittest
from pathlib import Path

import pytest


# Add shared helper directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

from timeframe_helper import parse_timeframe


class TestSQLInjectionProtection(unittest.TestCase):
    """Test cases for SQL injection protection in timeframe validation."""

    def test_valid_timeframes(self):
        """Test that valid timeframes are accepted and converted correctly."""
        valid_cases = {
            "5m": "5 minutes",
            "15m": "15 minutes",
            "1h": "1 hour",
            "24h": "24 hours",
            "7d": "7 days",
            "30d": "30 days",
        }

        for input_value, expected_output in valid_cases.items():
            with self.subTest(timeframe=input_value):
                result = parse_timeframe(input_value)
                assert (
                    result == expected_output
                ), f"Expected '{expected_output}' for input '{input_value}', got '{result}'"

    def test_sql_injection_attempts(self):
        """Test that SQL injection attempts are rejected with clear error messages."""
        injection_attempts = [
            "1h'; DROP TABLE agent_routing_decisions; --",
            "1h' OR '1'='1",
            "1h'; DELETE FROM agent_routing_decisions WHERE '1'='1",
            "1h' UNION SELECT * FROM pg_user --",
            "5m'; UPDATE agent_routing_decisions SET confidence_score=0; --",
            '24h"; DROP DATABASE omninode_bridge; --',
            "../../../etc/passwd",
            "1h' AND 1=1 --",
            "'; EXEC xp_cmdshell('dir'); --",
        ]

        for malicious_input in injection_attempts:
            with self.subTest(injection=malicious_input):
                with pytest.raises(
                    ValueError, match=r"(Invalid|Unsupported) timeframe"
                ) as context:
                    parse_timeframe(malicious_input)

                error_message = str(context.value)
                assert (
                    "timeframe" in error_message.lower()
                ), f"Error message should indicate invalid timeframe for: {malicious_input}"
                assert (
                    "Valid options:" in error_message
                ), "Error message should include valid options"

    def test_invalid_but_benign_inputs(self):
        """Test that invalid but non-malicious inputs are also rejected."""
        invalid_inputs = [
            "10m",  # Not in whitelist
            "2h",  # Not in whitelist
            "1 hour",  # Correct output format, but not valid input
            "HOUR",  # Wrong case
            "1H",  # Wrong case
            "",  # Empty string
            " 1h ",  # Whitespace
            "1h\n",  # Newline
        ]

        for invalid_input in invalid_inputs:
            with self.subTest(invalid=invalid_input):
                with pytest.raises(
                    ValueError, match=r"(Invalid|Unsupported) timeframe"
                ) as context:
                    parse_timeframe(invalid_input)

                error_message = str(context.value)
                assert (
                    "timeframe" in error_message.lower()
                ), f"Error message should indicate invalid timeframe for: {invalid_input}"

    def test_error_message_quality(self):
        """Test that error messages are helpful and include valid options."""
        with pytest.raises(
            ValueError, match=r"(Invalid|Unsupported) timeframe"
        ) as context:
            parse_timeframe("invalid")

        error_message = str(context.value)

        # Should mention the invalid input
        assert "invalid" in error_message

        # Should include all valid options
        assert "5m" in error_message
        assert "15m" in error_message
        assert "1h" in error_message
        assert "24h" in error_message
        assert "7d" in error_message
        assert "30d" in error_message

    def test_case_sensitivity(self):
        """Test that timeframe validation is case-sensitive."""
        # Uppercase should be rejected
        with pytest.raises(ValueError, match=r"(Invalid|Unsupported) timeframe"):
            parse_timeframe("1H")

        with pytest.raises(ValueError, match=r"(Invalid|Unsupported) timeframe"):
            parse_timeframe("7D")

        # Lowercase should work
        assert parse_timeframe("1h") == "1 hour"
        assert parse_timeframe("7d") == "7 days"


def main():
    """Run the test suite."""
    # Run tests with verbose output
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSQLInjectionProtection)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 70)
    print("SQL INJECTION PROTECTION TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.wasSuccessful():
        print("\n✅ All SQL injection protection tests passed!")
        print("The parse_timeframe() function properly validates user input.")
        return 0
    else:
        print("\n❌ Some tests failed!")
        print("Review the output above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
