"""
SQL Injection attack prevention tests.

Attempts various SQL injection patterns and verifies they are properly rejected.

**IMPORTANT**: These tests validate that input validators correctly reject malicious input.
All tests should PASS. If they fail, validators need to be strengthened.

Test coverage:
  - UNION-based injection
  - Boolean-based blind injection
  - Time-based blind injection
  - SQL comment injection
  - Stacked queries
  - URL/hex encoded injection
  - Second-order injection

Created: 2025-11-20
"""

import sys
from pathlib import Path

import pytest


# Import load_skill_module from conftest
conftest_path = Path(__file__).parent / "conftest.py"
import importlib.util


spec = importlib.util.spec_from_file_location("conftest", conftest_path)
conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conftest)
load_skill_module = conftest.load_skill_module


class TestSQLInjectionAttacks:
    """Test resistance to common SQL injection attacks."""

    @pytest.fixture
    def validators(self):
        """Import all validators."""
        # Load check-recent-activity module which has validate_limit
        execute = load_skill_module("check-recent-activity")

        # Import timeframe_helper from _shared
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
        from timeframe_helper import parse_timeframe

        return {
            "limit": execute.validate_limit,
            "timeframe": parse_timeframe,
        }

    def test_union_based_injection(self, validators):
        """Test UNION-based SQL injection attempts."""
        attacks = [
            "10 UNION SELECT * FROM users",
            "10' UNION SELECT password FROM users--",
            "10/**/UNION/**/SELECT/**/1,2,3",
        ]

        for attack in attacks:
            with pytest.raises(Exception):
                validators["limit"](attack)

    def test_boolean_based_injection(self, validators):
        """Test boolean-based blind SQL injection."""
        attacks = [
            "10 OR 1=1",
            "10' OR '1'='1",
            "10) OR (1=1",
            "10' OR 'a'='a",
        ]

        for attack in attacks:
            with pytest.raises(Exception):
                validators["limit"](attack)

    def test_time_based_injection(self, validators):
        """Test time-based blind SQL injection."""
        attacks = [
            "10; WAITFOR DELAY '00:00:05'",
            "10'; IF (1=1) WAITFOR DELAY '00:00:05'--",
            "10' AND SLEEP(5)--",
        ]

        for attack in attacks:
            with pytest.raises(Exception):
                validators["limit"](attack)

    def test_comment_injection(self, validators):
        """Test SQL comment injection."""
        attacks = [
            "10--",
            "10; --",
            "10/*comment*/",
            "10'--",
        ]

        for attack in attacks:
            with pytest.raises(Exception):
                validators["limit"](attack)

    def test_stacked_queries(self, validators):
        """Test stacked query injection."""
        attacks = [
            "10; DROP TABLE agent_routing_decisions;",
            "10'; DELETE FROM agent_routing_decisions;--",
            "10; INSERT INTO users VALUES ('hacker', 'password');",
        ]

        for attack in attacks:
            with pytest.raises(Exception):
                validators["limit"](attack)

    def test_encoded_injection(self, validators):
        """Test URL/hex encoded injection attempts."""
        attacks = [
            "10%27%20OR%20%271%27%3D%271",  # '10' OR '1'='1' URL encoded
            "10%2527%2520OR%2520%25271%2527%253D%25271",  # Double URL encoded
        ]

        for attack in attacks:
            with pytest.raises(Exception):
                validators["limit"](attack)

    def test_timeframe_injection(self, validators):
        """Test SQL injection through timeframe parameter."""
        attacks = [
            "5m'; DROP TABLE agent_routing_decisions;--",
            "1h' OR '1'='1",
            "7d/**/UNION/**/SELECT",
        ]

        for attack in attacks:
            with pytest.raises(ValueError):
                validators["timeframe"](attack)

    def test_second_order_injection(self, validators):
        """Test second-order SQL injection (stored then executed)."""
        # These should all be rejected at input validation
        attacks = [
            "10'; UPDATE users SET role='admin' WHERE id=1;--",
            "10'; CREATE TABLE hacked (data TEXT);--",
        ]

        for attack in attacks:
            with pytest.raises(Exception):
                validators["limit"](attack)
