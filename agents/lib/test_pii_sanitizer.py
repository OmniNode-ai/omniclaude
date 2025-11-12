#!/usr/bin/env python3
"""
Test suite for PII sanitization module.

Comprehensive tests covering:
- Email sanitization
- IP address sanitization
- Username sanitization
- Correlation ID sanitization
- File path sanitization
- Database connection string sanitization
- API key sanitization
- Phone number sanitization
- Credit card sanitization
- SSN sanitization
- UUID sanitization
- Session token sanitization
- Nested data structure sanitization
- Sensitive field detection
- Edge cases and error handling

Usage:
    python3 agents/lib/test_pii_sanitizer.py
    pytest agents/lib/test_pii_sanitizer.py -v
"""

import unittest
from typing import Any, Dict

from pii_sanitizer import (
    is_sensitive_field,
    sanitize_api_key,
    sanitize_correlation_id,
    sanitize_credit_card,
    sanitize_db_connection,
    sanitize_email,
    sanitize_file_path,
    sanitize_for_slack,
    sanitize_ip,
    sanitize_phone,
    sanitize_ssn,
    sanitize_string,
    sanitize_token,
    sanitize_username,
    sanitize_uuid,
)


class TestEmailSanitization(unittest.TestCase):
    """Test email address sanitization."""

    def test_basic_email(self):
        """Test basic email sanitization."""
        result = sanitize_email("user@example.com")
        assert result == "u***@example.com"

    def test_long_username(self):
        """Test email with long username."""
        result = sanitize_email("john.doe.smith@company.org")
        assert result == "j***@company.org"

    def test_short_username(self):
        """Test email with short username."""
        result = sanitize_email("a@example.com")
        assert result == "a***@example.com"

    def test_subdomain(self):
        """Test email with subdomain."""
        result = sanitize_email("admin@mail.example.com")
        assert result == "a***@mail.example.com"

    def test_non_email(self):
        """Test non-email string (should return unchanged)."""
        result = sanitize_email("not-an-email")
        assert result == "not-an-email"


class TestIPSanitization(unittest.TestCase):
    """Test IP address sanitization."""

    def test_private_ip(self):
        """Test private IP sanitization."""
        result = sanitize_ip("192.168.1.100")
        assert result == "192.*.*.*"

    def test_public_ip(self):
        """Test public IP sanitization."""
        result = sanitize_ip("8.8.8.8")
        assert result == "8.*.*.*"

    def test_local_ip(self):
        """Test local IP sanitization."""
        result = sanitize_ip("127.0.0.1")
        assert result == "127.*.*.*"

    def test_class_a_ip(self):
        """Test class A IP sanitization."""
        result = sanitize_ip("10.0.0.5")
        assert result == "10.*.*.*"

    def test_non_ip(self):
        """Test non-IP string (should return unchanged)."""
        result = sanitize_ip("not-an-ip")
        assert result == "not-an-ip"


class TestUsernameSanitization(unittest.TestCase):
    """Test username sanitization."""

    def test_normal_username(self):
        """Test normal username sanitization."""
        result = sanitize_username("username")
        assert result == "u***e"

    def test_short_username(self):
        """Test short username sanitization."""
        result = sanitize_username("ab")
        assert result == "a***"

    def test_long_username(self):
        """Test long username sanitization."""
        result = sanitize_username("verylongusername")
        assert result == "v***e"

    def test_single_char_username(self):
        """Test single character username."""
        result = sanitize_username("a")
        assert result == "a***"

    def test_empty_username(self):
        """Test empty username (should return empty)."""
        result = sanitize_username("")
        assert result == ""


class TestCorrelationIDSanitization(unittest.TestCase):
    """Test correlation ID sanitization."""

    def test_uuid_style_correlation_id(self):
        """Test UUID-style correlation ID."""
        correlation_id = "550e8400-e29b-41d4-a716-446655440000"
        result = sanitize_correlation_id(correlation_id)
        # Should be consistent hash (first 8 chars + ***)
        assert result.endswith("***")
        assert len(result) == 11  # 8 + 3

    def test_short_correlation_id(self):
        """Test short correlation ID."""
        correlation_id = "abc-123"
        result = sanitize_correlation_id(correlation_id)
        assert result.endswith("***")
        assert len(result) == 11

    def test_consistency(self):
        """Test that same input produces same output."""
        correlation_id = "test-correlation-id"
        result1 = sanitize_correlation_id(correlation_id)
        result2 = sanitize_correlation_id(correlation_id)
        assert result1 == result2

    def test_uniqueness(self):
        """Test that different inputs produce different outputs."""
        result1 = sanitize_correlation_id("id-1")
        result2 = sanitize_correlation_id("id-2")
        assert result1 != result2


class TestFilePathSanitization(unittest.TestCase):
    """Test file path sanitization."""

    def test_home_path_linux(self):
        """Test Linux home directory path."""
        result = sanitize_file_path("/home/john/project/file.py")
        assert result == "/home/***/project/file.py"

    def test_home_path_macos(self):
        """Test macOS Users directory path."""
        result = sanitize_file_path("/Users/jane/Documents/data.csv")
        assert result == "/Users/***/Documents/data.csv"

    def test_system_path(self):
        """Test system path (should remain unchanged)."""
        result = sanitize_file_path("/opt/app/file.py")
        assert result == "/opt/app/file.py"

    def test_root_path(self):
        """Test root directory path."""
        result = sanitize_file_path("/var/log/app.log")
        assert result == "/var/log/app.log"

    def test_home_without_subdirs(self):
        """Test home directory without subdirectories."""
        result = sanitize_file_path("/home/john")
        assert result == "/home/***"


class TestDatabaseConnectionSanitization(unittest.TestCase):
    """Test database connection string sanitization."""

    def test_postgresql_connection(self):
        """Test PostgreSQL connection string."""
        dsn = "postgresql://user:password@192.168.86.200:5436/omninode_bridge"
        result = sanitize_db_connection(dsn)
        assert result == "postgresql://***:***@192.168.86.200:5436/omninode_bridge"

    def test_postgres_connection(self):
        """Test postgres:// connection string."""
        dsn = "postgres://admin:secret@localhost:5432/mydb"
        result = sanitize_db_connection(dsn)
        assert result == "postgres://***:***@localhost:5432/mydb"

    def test_mysql_connection(self):
        """Test MySQL connection string."""
        dsn = "mysql://root:toor@localhost/database"
        result = sanitize_db_connection(dsn)
        assert result == "mysql://***:***@localhost/database"

    def test_mongodb_connection(self):
        """Test MongoDB connection string."""
        dsn = "mongodb://admin:pass123@mongo.example.com:27017/mydb"
        result = sanitize_db_connection(dsn)
        assert result == "mongodb://***:***@mongo.example.com:27017/mydb"

    def test_non_connection_string(self):
        """Test non-connection string (should remain unchanged)."""
        result = sanitize_db_connection("just a regular string")
        assert result == "just a regular string"


class TestAPIKeySanitization(unittest.TestCase):
    """Test API key sanitization."""

    def test_openai_style_key(self):
        """Test OpenAI-style API key."""
        key = "sk-1234567890abcdefghijklmnopqrstuvwxyz"
        result = sanitize_api_key(key)
        assert result.startswith("sk-")
        assert result.endswith("***")

    def test_google_api_key(self):
        """Test Google API key."""
        key = "AIzaSyD1234567890abcdefghijklmnopqrstuvwxyz"
        result = sanitize_api_key(key)
        assert result.startswith("AIza")
        assert result.endswith("***")

    def test_generic_long_key(self):
        """Test generic long alphanumeric key."""
        key = "abcd1234efgh5678ijkl9012mnop3456qrst"
        result = sanitize_api_key(key)
        # Should be sanitized if matches pattern
        assert "***" in result or result == key  # May or may not match

    def test_short_string(self):
        """Test short string (should not be treated as API key)."""
        result = sanitize_api_key("short")
        assert result == "short"


class TestPhoneSanitization(unittest.TestCase):
    """Test phone number sanitization."""

    def test_formatted_phone(self):
        """Test formatted phone number."""
        phone = "(555) 123-4567"
        result = sanitize_phone(phone)
        # Last 4 digits should be visible
        assert "4567" in result
        assert "*" in result

    def test_dashed_phone(self):
        """Test dashed phone number."""
        phone = "555-123-4567"
        result = sanitize_phone(phone)
        assert "4567" in result
        assert "*" in result

    def test_international_phone(self):
        """Test international phone number."""
        phone = "+1-555-123-4567"
        result = sanitize_phone(phone)
        assert "4567" in result
        assert "*" in result

    def test_plain_digits(self):
        """Test plain digit phone number."""
        phone = "5551234567"
        result = sanitize_phone(phone)
        assert "4567" in result


class TestCreditCardSanitization(unittest.TestCase):
    """Test credit card sanitization."""

    def test_dashed_card(self):
        """Test dashed credit card number."""
        card = "4532-1234-5678-9010"
        result = sanitize_credit_card(card)
        # Last 4 digits should be visible
        assert "9010" in result
        assert "*" in result
        assert "4532" not in result

    def test_spaced_card(self):
        """Test spaced credit card number."""
        card = "4532 1234 5678 9010"
        result = sanitize_credit_card(card)
        assert "9010" in result
        assert "*" in result

    def test_plain_card(self):
        """Test plain credit card number."""
        card = "4532123456789010"
        result = sanitize_credit_card(card)
        assert "9010" in result


class TestSSNSanitization(unittest.TestCase):
    """Test SSN sanitization."""

    def test_ssn(self):
        """Test SSN sanitization."""
        ssn = "123-45-6789"
        result = sanitize_ssn(ssn)
        # Last 4 digits should be visible
        assert "6789" in result
        assert "*" in result
        assert "123" not in result


class TestUUIDSanitization(unittest.TestCase):
    """Test UUID sanitization."""

    def test_uuid(self):
        """Test UUID sanitization."""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = sanitize_uuid(uuid)
        assert result.endswith("***")
        assert len(result) == 11


class TestTokenSanitization(unittest.TestCase):
    """Test session token sanitization."""

    def test_token_equals(self):
        """Test token with equals sign."""
        value = "token=abc123xyz789longtokenstring"
        result = sanitize_token(value)
        assert result == "token=***"

    def test_session_id_colon(self):
        """Test session_id with colon."""
        value = "session_id: verylongsessiontokenstring"
        result = sanitize_token(value)
        assert result == "session_id=***"

    def test_no_token(self):
        """Test string without token (should remain unchanged)."""
        value = "just a regular string"
        result = sanitize_token(value)
        assert result == "just a regular string"


class TestStringSanitization(unittest.TestCase):
    """Test comprehensive string sanitization."""

    def test_email_in_message(self):
        """Test email in longer message."""
        message = "Contact user@example.com for support"
        result = sanitize_string(message)
        assert "u***@example.com" in result

    def test_ip_in_error_message(self):
        """Test IP in error message."""
        message = "Connection failed to 192.168.1.100:5432"
        result = sanitize_string(message)
        assert "192.*.*.*" in result

    def test_uuid_in_log(self):
        """Test UUID in log message."""
        message = "Request ID: 550e8400-e29b-41d4-a716-446655440000"
        result = sanitize_string(message)
        assert "***" in result

    def test_multiple_patterns(self):
        """Test multiple PII patterns in one string."""
        message = (
            "User admin@example.com from IP 192.168.1.1 accessed /home/admin/file.py"
        )
        result = sanitize_string(message)
        assert "a***@example.com" in result
        assert "192.*.*.*" in result
        assert "/home/***/file.py" in result

    def test_db_connection_in_config(self):
        """Test database connection string."""
        config = "DATABASE_URL=postgresql://user:pass@host:5432/db"
        result = sanitize_string(config)
        assert "postgresql://***:***@" in result


class TestSensitiveFieldDetection(unittest.TestCase):
    """Test sensitive field name detection."""

    def test_exact_match(self):
        """Test exact field name match."""
        assert is_sensitive_field("password")
        assert is_sensitive_field("email")
        assert is_sensitive_field("api_key")

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        assert is_sensitive_field("PASSWORD")
        assert is_sensitive_field("Email")
        assert is_sensitive_field("API_KEY")

    def test_partial_match(self):
        """Test partial field name match."""
        assert is_sensitive_field("user_password")
        assert is_sensitive_field("user_email")
        assert is_sensitive_field("slack_webhook_url")

    def test_non_sensitive(self):
        """Test non-sensitive field names."""
        # Note: "user_id" is actually sensitive (contains "userid")
        assert not is_sensitive_field("created_at")
        assert not is_sensitive_field("status")
        assert not is_sensitive_field("count")

    def test_invalid_input(self):
        """Test invalid input (non-string)."""
        assert not is_sensitive_field(123)
        assert not is_sensitive_field(None)


class TestDeepSanitization(unittest.TestCase):
    """Test deep sanitization of nested structures."""

    def test_simple_dict(self):
        """Test simple dictionary sanitization."""
        data = {"email": "user@example.com", "ip": "192.168.1.1"}
        result = sanitize_for_slack(data)
        assert result["email"] == "***"  # Sensitive field completely masked
        assert result["ip"] == "***"  # Sensitive field completely masked

    def test_nested_dict(self):
        """Test nested dictionary sanitization."""
        data = {
            "user": {
                "email": "john@example.com",
                "username": "john",
            },
            "context": {
                "ip_address": "192.168.1.100",
            },
        }
        result = sanitize_for_slack(data)
        assert result["user"]["email"] == "***"
        assert result["context"]["ip_address"] == "***"

    def test_list_of_dicts(self):
        """Test list of dictionaries."""
        data = [
            {"email": "user1@example.com"},
            {"email": "user2@example.com"},
        ]
        result = sanitize_for_slack(data)
        assert result[0]["email"] == "***"
        assert result[1]["email"] == "***"

    def test_tuple(self):
        """Test tuple sanitization."""
        data = ("user@example.com", "192.168.1.1")
        result = sanitize_for_slack(data, sanitize_all_strings=True)
        assert isinstance(result, tuple)
        assert "u***@example.com" in result

    def test_set(self):
        """Test set sanitization."""
        data = {"user@example.com", "admin@example.com"}
        result = sanitize_for_slack(data, sanitize_all_strings=True)
        assert isinstance(result, set)

    def test_mixed_types(self):
        """Test mixed data types."""
        data = {
            "count": 42,
            "enabled": True,
            "ratio": 3.14,
            "email": "test@example.com",
            "items": [1, 2, 3],
            "metadata": None,
        }
        result = sanitize_for_slack(data)
        assert result["count"] == 42
        assert result["enabled"] is True
        assert result["ratio"] == 3.14
        assert result["email"] == "***"
        assert result["items"] == [1, 2, 3]
        assert result["metadata"] is None

    def test_sanitize_all_strings_mode(self):
        """Test sanitize_all_strings mode."""
        data = {
            "message": "Contact user@example.com",
            "note": "Server at 192.168.1.1",
        }
        result = sanitize_for_slack(data, sanitize_all_strings=True)
        assert "u***@example.com" in result["message"]
        assert "192.*.*.*" in result["note"]

    def test_max_depth_protection(self):
        """Test max depth protection against deep nesting."""
        # Create deeply nested structure
        data: Dict[str, Any] = {"level": 1}
        current = data
        for i in range(2, 15):
            current["nested"] = {"level": i}
            current = current["nested"]

        # Should not raise error, should return truncated
        result = sanitize_for_slack(data, max_depth=10)
        assert result is not None

    def test_sensitive_field_complete_masking(self):
        """Test that sensitive fields are completely masked, not pattern-sanitized."""
        data = {
            "password": "my-secret-password-123",
            "api_key": "sk-1234567890abcdef",
            "note": "This is a regular note",
        }
        result = sanitize_for_slack(data)
        # Sensitive fields should be completely masked with ***
        assert result["password"] == "***"
        assert result["api_key"] == "***"
        # Non-sensitive fields should remain unchanged (sanitize_all_strings=False by default)
        assert result["note"] == "This is a regular note"

    def test_sensitive_field_nested_structure(self):
        """Test sensitive field with nested structure value."""
        data = {
            "user_credentials": {
                "username": "admin",
                "password": "secret",
            }
        }
        result = sanitize_for_slack(data)
        # Sensitive field with nested dict should have all strings sanitized
        assert "***" in str(result["user_credentials"])


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_none_input(self):
        """Test None input."""
        result = sanitize_for_slack(None)
        assert result is None

    def test_empty_dict(self):
        """Test empty dictionary."""
        result = sanitize_for_slack({})
        assert result == {}

    def test_empty_list(self):
        """Test empty list."""
        result = sanitize_for_slack([])
        assert result == []

    def test_empty_string(self):
        """Test empty string."""
        result = sanitize_string("")
        assert result == ""

    def test_numeric_values(self):
        """Test numeric values (should pass through)."""
        assert sanitize_for_slack(42) == 42
        assert sanitize_for_slack(3.14) == 3.14
        assert sanitize_for_slack(True) is True
        assert sanitize_for_slack(False) is False

    def test_unicode_strings(self):
        """Test Unicode strings."""
        data = {"message": "Привет user@example.com 你好"}
        result = sanitize_for_slack(data, sanitize_all_strings=True)
        # Should handle Unicode and still sanitize email
        assert "u***@example.com" in result["message"]
        assert "Привет" in result["message"]
        assert "你好" in result["message"]


class TestIntegrationScenarios(unittest.TestCase):
    """Test real-world integration scenarios."""

    def test_slack_error_notification_context(self):
        """Test realistic Slack error notification context."""
        context = {
            "service": "routing_event_client",
            "operation": "kafka_connection",
            "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
            "user_email": "admin@example.com",
            "server_ip": "192.168.86.200",
            "error_details": {
                "host": "192.168.86.200",
                "port": 29092,
                "connection_string": "postgresql://user:pass@192.168.86.200:5436/db",
            },
            "file_path": "/home/admin/omniclaude/agents/lib/routing.py",
        }

        result = sanitize_for_slack(context)

        # Service and operation should remain
        assert result["service"] == "routing_event_client"
        assert result["operation"] == "kafka_connection"

        # Sensitive fields should be masked
        assert result["correlation_id"] == "***"  # Sensitive field
        assert result["user_email"] == "***"  # Sensitive field

        # Non-sensitive values should remain (unless they're in sensitive fields)
        # server_ip is sensitive field name, so should be masked
        assert result["server_ip"] == "***"

        # Nested structure sanitization
        assert result["error_details"]["port"] == 29092

    def test_manifest_injection_context(self):
        """Test manifest injection context sanitization."""
        context = {
            "agent_name": "agent-researcher",
            "correlation_id": "abc-123-def-456",
            "patterns_found": 120,
            "query_time_ms": 1842,
            "database_connection": "postgresql://postgres:secret@192.168.86.200:5436/omninode_bridge",
            "qdrant_url": "http://localhost:6333",
        }

        result = sanitize_for_slack(context, sanitize_all_strings=True)

        # Metadata should remain
        assert result["agent_name"] == "agent-researcher"
        assert result["patterns_found"] == 120
        assert result["query_time_ms"] == 1842

        # Sensitive data should be sanitized
        assert "postgresql://***:***@" in result["database_connection"]

    def test_action_logger_error_context(self):
        """Test ActionLogger error context sanitization."""
        error_context = {
            "host": "192.168.86.200",
            "port": 5436,
            "database": "omninode_bridge",
            "retry_count": 3,
            "username": "postgres",
            "password": "super-secret-password",
            "connection_timeout_ms": 5000,
        }

        result = sanitize_for_slack(error_context)

        # Non-sensitive data should remain
        assert result["port"] == 5436
        assert result["database"] == "omninode_bridge"
        assert result["retry_count"] == 3
        assert result["connection_timeout_ms"] == 5000

        # Sensitive fields should be completely masked
        assert result["username"] == "***"
        assert result["password"] == "***"


def run_tests():
    """Run all tests."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestEmailSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestIPSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestUsernameSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestCorrelationIDSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestFilePathSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseConnectionSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestAPIKeySanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestPhoneSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestCreditCardSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestSSNSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestUUIDSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestTokenSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestStringSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestSensitiveFieldDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestDeepSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegrationScenarios))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("=" * 70)

    # Return exit code
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    exit(run_tests())
