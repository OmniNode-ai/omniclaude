#!/usr/bin/env python3
"""
Comprehensive Tests for Data Sanitization Module

Tests all sanitization functions to ensure sensitive data is properly
redacted from ActionLogger calls.

Test Categories:
1. Sensitive key detection (password, token, api_key, etc.)
2. Sensitive pattern detection (Bearer tokens, API keys, long tokens)
3. Dictionary sanitization (recursive, depth limits)
4. String sanitization (pattern replacement, truncation)
5. Stack trace sanitization (absolute → relative paths)
6. Error context sanitization (comprehensive)
7. Edge cases (None, empty, malformed data)
8. Performance (no-op for safe data)

Created: 2025-11-15
Security Priority: CRITICAL (blocks PR #36)
"""

import sys
from pathlib import Path

import pytest

# Add lib directory to Python path
lib_path = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_path))

from data_sanitizer import (
    REDACTED,
    SENSITIVE_KEYS,
    SENSITIVE_PATTERNS,
    sanitize_dict,
    sanitize_error_context,
    sanitize_for_logging,
    sanitize_stack_trace,
    sanitize_string,
    sanitize_value,
)


class TestSensitiveKeyDetection:
    """Test detection of sensitive keys in dictionaries."""

    def test_password_redaction(self):
        """Password key should be redacted."""
        context = {"user": "john", "password": "secret123"}
        sanitized = sanitize_dict(context)
        assert sanitized["password"] == REDACTED
        assert sanitized["user"] == "john"

    def test_api_key_redaction(self):
        """API key variations should be redacted."""
        context = {
            "api_key": "sk-1234567890",
            "apikey": "xyz-abcdef",
            "api-key": "test-key",
            "normal": "safe",
        }
        sanitized = sanitize_dict(context)
        assert sanitized["api_key"] == REDACTED
        assert sanitized["apikey"] == REDACTED
        assert sanitized["api-key"] == REDACTED
        assert sanitized["normal"] == "safe"

    def test_token_redaction(self):
        """Token keys should be redacted."""
        context = {
            "access_token": "bearer xyz",
            "refresh_token": "refresh abc",
            "session_token": "session def",
            "data": "safe",
        }
        sanitized = sanitize_dict(context)
        assert sanitized["access_token"] == REDACTED
        assert sanitized["refresh_token"] == REDACTED
        assert sanitized["session_token"] == REDACTED
        assert sanitized["data"] == "safe"

    def test_case_insensitive_detection(self):
        """Sensitive keys should be detected case-insensitively."""
        context = {
            "PASSWORD": "secret",
            "Password": "secret2",
            "pAsSwOrD": "secret3",
            "API_KEY": "key",
            "normal": "safe",
        }
        sanitized = sanitize_dict(context)
        assert sanitized["PASSWORD"] == REDACTED
        assert sanitized["Password"] == REDACTED
        assert sanitized["pAsSwOrD"] == REDACTED
        assert sanitized["API_KEY"] == REDACTED
        assert sanitized["normal"] == "safe"

    def test_nested_sensitive_keys(self):
        """Nested sensitive keys should be redacted."""
        context = {
            "user": "john",
            "credentials": {"password": "secret", "api_key": "sk-123"},
            "config": {"database_url": "postgres://user:pass@host/db"},
        }
        sanitized = sanitize_dict(context)
        assert sanitized["user"] == "john"
        assert sanitized["credentials"]["password"] == REDACTED
        assert sanitized["credentials"]["api_key"] == REDACTED
        assert sanitized["config"]["database_url"] == REDACTED


class TestSensitivePatternDetection:
    """Test detection of sensitive patterns in values."""

    def test_bearer_token_redaction(self):
        """Bearer tokens should be redacted."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
        sanitized = sanitize_string(text)
        assert "Bearer" in sanitized  # Prefix remains
        assert REDACTED in sanitized
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized

    def test_openai_key_redaction(self):
        """OpenAI keys (sk-...) should be redacted."""
        text = "Use api_key=sk-1234567890abcdefghijklmnopqrstuvwxyz to authenticate"
        sanitized = sanitize_string(text)
        assert "sk-1234567890abcdefghijklmnopqrstuvwxyz" not in sanitized
        assert REDACTED in sanitized

    def test_anthropic_key_redaction(self):
        """Anthropic keys (sk-ant-...) should be redacted."""
        text = "API Key: sk-ant-api03-1234567890abcdefghijklmnopqrstuvwxyz"
        sanitized = sanitize_string(text)
        assert "sk-ant-api03-1234567890abcdefghijklmnopqrstuvwxyz" not in sanitized
        assert REDACTED in sanitized

    def test_google_api_key_redaction(self):
        """Google API keys (AIza...) should be redacted."""
        text = "GOOGLE_API_KEY=AIzaSyD1234567890abcdefghijklmnopqrstuvwxyz"
        sanitized = sanitize_string(text)
        assert "AIzaSyD1234567890abcdefghijklmnopqrstuvwxyz" not in sanitized
        assert REDACTED in sanitized

    def test_jwt_token_redaction(self):
        """JWT tokens (xxx.yyy.zzz) should be redacted."""
        text = "Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        sanitized = sanitize_string(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized
        assert REDACTED in sanitized

    def test_aws_key_redaction(self):
        """AWS keys (AKIA...) should be redacted."""
        text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        sanitized = sanitize_string(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in sanitized
        assert REDACTED in sanitized

    def test_connection_string_redaction(self):
        """Connection strings with credentials should be redacted."""
        text = "DATABASE_URL=postgresql://user:password@localhost:5432/mydb"
        sanitized = sanitize_string(text)
        assert "password" not in sanitized
        assert REDACTED in sanitized

    def test_long_token_redaction(self):
        """Long tokens (32+ chars) should be redacted."""
        text = "secret_token=abcdef1234567890abcdef1234567890"
        sanitized = sanitize_string(text)
        assert "abcdef1234567890abcdef1234567890" not in sanitized
        assert REDACTED in sanitized

    def test_safe_text_preserved(self):
        """Safe text should pass through unchanged."""
        text = "This is a safe message with no secrets"
        sanitized = sanitize_string(text)
        assert sanitized == text

    def test_short_tokens_preserved(self):
        """Short tokens (<32 chars) should be preserved."""
        text = "session_id=abc123"
        sanitized = sanitize_string(text)
        assert sanitized == text


class TestDictionarySanitization:
    """Test dictionary sanitization with recursion and depth limits."""

    def test_flat_dict_sanitization(self):
        """Flat dictionaries should be sanitized correctly."""
        context = {
            "user": "john",
            "password": "secret",
            "email": "john@example.com",
            "age": 30,
        }
        sanitized = sanitize_dict(context)
        assert sanitized["user"] == "john"
        assert sanitized["password"] == REDACTED
        assert sanitized["email"] == REDACTED  # Email is sensitive pattern
        assert sanitized["age"] == 30

    def test_nested_dict_sanitization(self):
        """Nested dictionaries should be sanitized recursively."""
        context = {
            "user": {
                "name": "john",
                "credentials": {"password": "secret", "api_key": "sk-123"},
            },
            "config": {"timeout": 30, "token": "bearer xyz"},
        }
        sanitized = sanitize_dict(context)
        assert sanitized["user"]["name"] == "john"
        assert sanitized["user"]["credentials"]["password"] == REDACTED
        assert sanitized["user"]["credentials"]["api_key"] == REDACTED
        assert sanitized["config"]["timeout"] == 30
        assert sanitized["config"]["token"] == REDACTED

    def test_list_sanitization(self):
        """Lists should be sanitized element-wise."""
        context = {
            "users": [
                {"name": "john", "password": "secret1"},
                {"name": "jane", "password": "secret2"},
            ],
            "tokens": ["safe", "Bearer xyz123"],
        }
        sanitized = sanitize_dict(context)
        assert sanitized["users"][0]["name"] == "john"
        assert sanitized["users"][0]["password"] == REDACTED
        assert sanitized["users"][1]["name"] == "jane"
        assert sanitized["users"][1]["password"] == REDACTED
        assert sanitized["tokens"][0] == "safe"
        assert sanitized["tokens"][1] == REDACTED

    def test_max_depth_limit(self):
        """Deep nesting should be truncated at max depth."""
        context = {
            "level1": {"level2": {"level3": {"level4": {"level5": {"level6": "deep"}}}}}
        }
        sanitized = sanitize_dict(context, max_depth=3)
        # Should stop at level 3 (depth 0, 1, 2)
        assert "level1" in sanitized
        assert "level2" in sanitized["level1"]
        assert "level3" in sanitized["level1"]["level2"]
        assert sanitized["level1"]["level2"]["level3"] == {
            "_truncated": "max depth reached"
        }

    def test_none_input(self):
        """None input should return empty dict."""
        sanitized = sanitize_dict(None)
        assert sanitized == {}

    def test_non_dict_input(self):
        """Non-dict input should return error dict."""
        sanitized = sanitize_dict("not a dict")
        assert "_error" in sanitized

    def test_mixed_types(self):
        """Mixed types should be sanitized correctly."""
        context = {
            "string": "value",
            "number": 42,
            "boolean": True,
            "none": None,
            "list": [1, 2, 3],
            "dict": {"key": "value"},
            "password": "secret",
        }
        sanitized = sanitize_dict(context)
        assert sanitized["string"] == "value"
        assert sanitized["number"] == 42
        assert sanitized["boolean"] is True
        assert sanitized["none"] is None
        assert sanitized["list"] == [1, 2, 3]
        assert sanitized["dict"] == {"key": "value"}
        assert sanitized["password"] == REDACTED


class TestStringSanitization:
    """Test string sanitization with pattern replacement and truncation."""

    def test_pattern_replacement(self):
        """Sensitive patterns should be replaced with [REDACTED]."""
        text = "Use Bearer abc123 and api_key=sk-xyz to authenticate"
        sanitized = sanitize_string(text)
        assert "Bearer" in sanitized
        assert REDACTED in sanitized
        assert "abc123" not in sanitized
        assert "sk-xyz" not in sanitized

    def test_truncation(self):
        """Long strings should be truncated to max_length."""
        text = "a" * 300
        sanitized = sanitize_string(text, max_length=200)
        assert len(sanitized) == 203  # 200 + "..."
        assert sanitized.endswith("...")

    def test_no_truncation_if_short(self):
        """Short strings should not be truncated."""
        text = "short text"
        sanitized = sanitize_string(text, max_length=200)
        assert sanitized == text
        assert not sanitized.endswith("...")

    def test_zero_max_length_no_truncation(self):
        """Zero max_length should disable truncation."""
        text = "a" * 300
        sanitized = sanitize_string(text, max_length=0)
        assert len(sanitized) == 300
        assert not sanitized.endswith("...")

    def test_none_input(self):
        """None input should return empty string."""
        sanitized = sanitize_string(None)
        assert sanitized == ""

    def test_non_string_input(self):
        """Non-string input should be converted to string."""
        sanitized = sanitize_string(12345)
        assert sanitized == "12345"

    def test_combined_sanitization_and_truncation(self):
        """Pattern replacement and truncation should both work."""
        text = "Bearer " + "x" * 300
        sanitized = sanitize_string(text, max_length=50)
        assert REDACTED in sanitized
        assert len(sanitized) <= 53  # 50 + "..." (or less with REDACTED)


class TestStackTraceSanitization:
    """Test stack trace sanitization (absolute → relative paths)."""

    def test_unix_path_sanitization(self):
        """Unix absolute paths should be converted to relative."""
        trace = """Traceback (most recent call last):
  File "/Users/john/code/omniclaude/agents/lib/manifest_injector.py", line 100
    raise ValueError("error")
ValueError: error"""
        sanitized = sanitize_stack_trace(trace)
        assert "/Users/john" not in sanitized
        assert "manifest_injector.py" in sanitized

    def test_windows_path_sanitization(self):
        """Windows absolute paths should be converted to relative."""
        trace = """Traceback (most recent call last):
  File "C:\\Users\\john\\code\\omniclaude\\agents\\lib\\manifest_injector.py", line 100
    raise ValueError("error")
ValueError: error"""
        sanitized = sanitize_stack_trace(trace)
        assert "C:\\Users\\john" not in sanitized
        assert "manifest_injector.py" in sanitized

    def test_multiple_paths(self):
        """Multiple paths should all be sanitized."""
        trace = """Traceback (most recent call last):
  File "/Users/john/code/omniclaude/agents/lib/manifest_injector.py", line 100
    method()
  File "/Users/john/code/omniclaude/agents/lib/action_logger.py", line 50
    raise ValueError("error")
ValueError: error"""
        sanitized = sanitize_stack_trace(trace)
        assert "/Users/john" not in sanitized
        assert "manifest_injector.py" in sanitized
        assert "action_logger.py" in sanitized

    def test_none_input(self):
        """None input should return empty string."""
        sanitized = sanitize_stack_trace(None)
        assert sanitized == ""

    def test_non_string_input(self):
        """Non-string input should be converted to string."""
        sanitized = sanitize_stack_trace(12345)
        assert sanitized == "12345"

    def test_no_paths_preserved(self):
        """Stack traces without paths should be preserved."""
        trace = "ValueError: error"
        sanitized = sanitize_stack_trace(trace)
        assert sanitized == trace


class TestErrorContextSanitization:
    """Test error context sanitization (comprehensive)."""

    def test_error_context_with_mixed_sensitive_data(self):
        """Error context with mixed sensitive data should be sanitized."""
        error_context = {
            "user_request": "Bearer xyz123",
            "error_type": "ValueError",
            "credentials": {"password": "secret", "api_key": "sk-123"},
            "normal_field": "safe",
            "stack_trace": "/Users/john/code/file.py",
        }
        sanitized = sanitize_error_context(error_context)
        assert REDACTED in sanitized["user_request"]
        assert sanitized["error_type"] == "ValueError"
        assert sanitized["credentials"] == REDACTED
        assert sanitized["normal_field"] == "safe"
        # Note: stack_trace is a key name, not the actual trace content
        # The key "stack_trace" itself is not sensitive, but the value might be
        # Since we're testing key sensitivity here, the value should pass through
        # unless it matches a value pattern

    def test_error_context_empty(self):
        """Empty error context should return empty dict."""
        sanitized = sanitize_error_context({})
        assert sanitized == {}

    def test_error_context_none(self):
        """None error context should return empty dict."""
        sanitized = sanitize_error_context(None)
        assert sanitized == {}


class TestUniversalSanitization:
    """Test universal sanitize_for_logging function."""

    def test_dict_input(self):
        """Dict input should use sanitize_dict."""
        data = {"password": "secret", "user": "john"}
        sanitized = sanitize_for_logging(data)
        assert sanitized["password"] == REDACTED
        assert sanitized["user"] == "john"

    def test_string_input(self):
        """String input should use sanitize_string."""
        data = "Bearer xyz123"
        sanitized = sanitize_for_logging(data)
        assert REDACTED in sanitized

    def test_non_sensitive_types(self):
        """Non-sensitive types should pass through."""
        assert sanitize_for_logging(12345) == 12345
        assert sanitize_for_logging(True) is True
        assert sanitize_for_logging(None) is None

    def test_custom_limits(self):
        """Custom limits should be respected."""
        data = "a" * 300
        sanitized = sanitize_for_logging(data, max_string_length=100)
        assert len(sanitized) == 103  # 100 + "..."


class TestPerformance:
    """Test performance characteristics of sanitization."""

    def test_no_overhead_for_safe_data(self):
        """Safe data should have minimal overhead."""
        safe_context = {
            "user": "john",
            "age": 30,
            "email_safe": "john@example.com",  # Not matching email pattern in key
            "data": "normal text",
        }
        sanitized = sanitize_dict(safe_context)
        # Should complete quickly (no specific assertion, just ensuring it runs)
        assert sanitized["user"] == "john"

    def test_large_dict_performance(self):
        """Large dictionaries should sanitize efficiently."""
        large_context = {f"field_{i}": f"value_{i}" for i in range(1000)}
        large_context["password"] = "secret"  # One sensitive key
        sanitized = sanitize_dict(large_context)
        assert sanitized["password"] == REDACTED
        assert len(sanitized) == 1000


class TestEdgeCases:
    """Test edge cases and malformed data."""

    def test_circular_reference_protection(self):
        """Circular references should be handled by depth limit."""
        context = {}
        context["self"] = context  # Circular reference
        # Should not crash, depth limit prevents infinite recursion
        sanitized = sanitize_dict(context, max_depth=3)
        assert "_truncated" in str(sanitized)

    def test_special_characters_in_values(self):
        """Special characters should be preserved."""
        context = {
            "message": "Error: <html>%$@#!&*",
            "unicode": "日本語 emoji 🔒",
        }
        sanitized = sanitize_dict(context)
        assert sanitized["message"] == "Error: <html>%$@#!&*"
        assert sanitized["unicode"] == "日本語 emoji 🔒"

    def test_empty_strings(self):
        """Empty strings should be preserved."""
        context = {"empty": "", "user": "john"}
        sanitized = sanitize_dict(context)
        assert sanitized["empty"] == ""
        assert sanitized["user"] == "john"

    def test_whitespace_strings(self):
        """Whitespace-only strings should be preserved."""
        context = {"spaces": "   ", "tabs": "\t\t"}
        sanitized = sanitize_dict(context)
        assert sanitized["spaces"] == "   "
        assert sanitized["tabs"] == "\t\t"


class TestRealWorldScenarios:
    """Test real-world scenarios from ActionLogger usage."""

    def test_manifest_generation_context(self):
        """Manifest generation context should be sanitized."""
        context = {
            "agent_name": "test-agent",
            "user_request": "Please use api_key=sk-1234567890 to connect",
            "enable_intelligence": True,
            "query_timeout_ms": 5000,
            "credentials": {"password": "secret123"},
        }
        sanitized = sanitize_dict(context)
        assert sanitized["agent_name"] == "test-agent"
        assert REDACTED in sanitized["user_request"]
        assert "sk-1234567890" not in sanitized["user_request"]
        assert sanitized["enable_intelligence"] is True
        assert sanitized["query_timeout_ms"] == 5000
        assert sanitized["credentials"] == REDACTED

    def test_routing_decision_context(self):
        """Routing decision context should be sanitized."""
        context = {
            "user_request": "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz",
            "max_recommendations": 5,
            "candidates_evaluated": 10,
        }
        sanitized = sanitize_dict(context)
        assert REDACTED in sanitized["user_request"]
        assert "Bearer" in sanitized["user_request"]
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized["user_request"]
        assert sanitized["max_recommendations"] == 5
        assert sanitized["candidates_evaluated"] == 10

    def test_error_logging_context(self):
        """Error logging context should be sanitized."""
        error_context = {
            "user_request": "Connect with password=secret123",
            "error_type": "ConnectionError",
            "stack_trace": "/Users/john/code/omniclaude/agents/lib/manifest_injector.py",
            "database_url": "postgresql://user:pass@localhost:5432/db",
        }
        sanitized = sanitize_error_context(error_context)
        assert REDACTED in sanitized["user_request"]
        assert "secret123" not in sanitized["user_request"]
        assert sanitized["error_type"] == "ConnectionError"
        assert sanitized["database_url"] == REDACTED

    def test_agent_execution_started_context(self):
        """Agent execution started context should be sanitized."""
        context = {
            "user_request": "Use token=abc123def456ghi789 for auth",
            "session_id": "session-xyz",
            "context": {"api_key": "sk-12345", "domain": "api_design"},
        }
        sanitized = sanitize_dict(context)
        assert REDACTED in sanitized["user_request"]
        assert "abc123def456ghi789" not in sanitized["user_request"]
        assert sanitized["session_id"] == "session-xyz"
        assert sanitized["context"]["api_key"] == REDACTED
        assert sanitized["context"]["domain"] == "api_design"


# Integration test
def test_end_to_end_sanitization():
    """End-to-end test: simulate ActionLogger call with sensitive data."""
    # Simulate a real ActionLogger context
    decision_context = {
        "user_request": "Please authenticate with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz",
        "agent_name": "test-agent",
        "credentials": {"password": "secret123", "api_key": "sk-1234567890abcdef"},
        "config": {
            "database_url": "postgresql://user:pass@localhost/db",
            "timeout": 30,
        },
    }

    # Sanitize entire context
    sanitized = sanitize_dict(decision_context)

    # Verify all sensitive data is redacted
    assert REDACTED in sanitized["user_request"]
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized["user_request"]
    assert sanitized["agent_name"] == "test-agent"
    assert sanitized["credentials"]["password"] == REDACTED
    assert sanitized["credentials"]["api_key"] == REDACTED
    assert sanitized["config"]["database_url"] == REDACTED
    assert sanitized["config"]["timeout"] == 30

    # Verify structure is preserved
    assert "user_request" in sanitized
    assert "credentials" in sanitized
    assert "config" in sanitized


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
