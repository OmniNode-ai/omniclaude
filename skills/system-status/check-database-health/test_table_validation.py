#!/usr/bin/env python3
"""
Test table name validation for SQL injection prevention.

Tests the whitelist validation logic to ensure:
1. Valid table names are accepted
2. Invalid/malicious table names are rejected
3. SQL injection attempts are blocked
4. Clear error messages are provided

Created: 2025-11-12
"""

import sys
import unittest
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent))

from execute import VALID_TABLES, validate_table_name


class TestTableNameValidation(unittest.TestCase):
    """Test table name validation against SQL injection."""

    def test_valid_table_names(self):
        """Test that valid table names are accepted."""
        valid_tables = [
            "agent_routing_decisions",
            "agent_manifest_injections",
            "agent_execution_logs",
            "agent_actions",
            "workflow_steps",
            "llm_calls",
            "error_events",
        ]

        for table in valid_tables:
            with self.subTest(table=table):
                result = validate_table_name(table)
                assert result == table

    def test_valid_table_with_whitespace(self):
        """Test that valid table names with whitespace are accepted."""
        test_cases = [
            ("  agent_actions  ", "agent_actions"),
            ("\tagent_routing_decisions\n", "agent_routing_decisions"),
            (" workflow_steps ", "workflow_steps"),
        ]

        for input_table, expected in test_cases:
            with self.subTest(input=input_table):
                result = validate_table_name(input_table)
                assert result == expected

    def test_empty_table_name(self):
        """Test that empty table names are rejected."""
        test_cases = ["", "   ", "\t", "\n"]

        for table in test_cases:
            with self.subTest(table=repr(table)):
                with pytest.raises(ValueError, match=r"(?i)cannot be empty"):
                    validate_table_name(table)

    def test_invalid_table_name(self):
        """Test that invalid table names are rejected."""
        invalid_tables = [
            "nonexistent_table",
            "users",
            "accounts",
            "pg_shadow",
            "information_schema",
        ]

        for table in invalid_tables:
            with self.subTest(table=table):
                with pytest.raises(ValueError, match=r"Invalid table name.*" + table):
                    validate_table_name(table)

    def test_sql_injection_attempts(self):
        """Test that SQL injection attempts are blocked."""
        injection_attempts = [
            # Classic SQL injection patterns
            "agent_actions; DROP TABLE users; --",
            "agent_actions' OR '1'='1",
            "agent_actions'; DELETE FROM agent_routing_decisions; --",
            "agent_actions UNION SELECT * FROM pg_shadow",
            # Command injection attempts
            "agent_actions; $(rm -rf /)",
            "agent_actions`; whoami`",
            # Path traversal attempts
            "../../../etc/passwd",
            "agent_actions/../users",
            # Special characters
            "agent_actions' --",
            "agent_actions;",
            "agent_actions/**/",
            "agent_actions' OR 1=1--",
            # Encoded attempts
            "agent_actions%27",
            "agent_actions%3B%20DROP%20TABLE",
        ]

        for malicious_input in injection_attempts:
            with self.subTest(input=malicious_input):
                with pytest.raises(ValueError, match=r"Invalid table name"):
                    validate_table_name(malicious_input)

    def test_case_sensitivity(self):
        """Test that table names are case-sensitive."""
        # PostgreSQL table names are case-sensitive in queries
        case_variations = [
            "AGENT_ACTIONS",
            "Agent_Actions",
            "AgentActions",
            "agent_ACTIONS",
        ]

        for table in case_variations:
            with self.subTest(table=table):
                with pytest.raises(ValueError, match=r"Invalid table name"):
                    validate_table_name(table)

    def test_whitelist_completeness(self):
        """Test that VALID_TABLES contains expected core tables."""
        required_tables = {
            "agent_routing_decisions",
            "agent_manifest_injections",
            "agent_execution_logs",
            "agent_actions",
            "agent_transformation_events",
            "workflow_steps",
            "llm_calls",
            "error_events",
            "success_events",
        }

        missing = required_tables - VALID_TABLES
        assert len(missing) == 0, f"Required tables missing from whitelist: {missing}"

    def test_error_message_helpful(self):
        """Test that error messages provide helpful information."""
        with pytest.raises(
            ValueError, match=r"Invalid table name.*invalid_table.*Must be one of:"
        ) as cm:
            validate_table_name("invalid_table")

        error_msg = str(cm.value)
        # Should contain at least some valid table names
        assert "agent_actions" in error_msg


class TestTableValidationIntegration(unittest.TestCase):
    """Integration tests for table validation in execute.py."""

    def test_all_valid_tables_pass_validation(self):
        """Test that all tables in whitelist pass validation."""
        for table in VALID_TABLES:
            with self.subTest(table=table):
                result = validate_table_name(table)
                assert result == table

    def test_whitelist_no_duplicates(self):
        """Test that whitelist contains no duplicates.

        Note: VALID_TABLES is currently a set, so this test will always pass.
        However, this test provides defensive programming value:
        - If someone changes VALID_TABLES to a list (e.g., for ordering),
          this test will catch duplicate entries
        - Documents the invariant that duplicates are not allowed
        - Acts as a regression test for data integrity
        """
        # Convert to list and check if set conversion changes length
        whitelist_list = list(VALID_TABLES)
        assert len(whitelist_list) == len(
            set(whitelist_list)
        ), "VALID_TABLES contains duplicate entries"

    def test_whitelist_no_empty_strings(self):
        """Test that whitelist contains no empty strings."""
        assert "" not in VALID_TABLES, "VALID_TABLES contains empty string"
        assert None not in VALID_TABLES, "VALID_TABLES contains None"


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
