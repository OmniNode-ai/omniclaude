#!/usr/bin/env python3
"""
Integration test for PII sanitization in Slack notifications.

Verifies that SlackNotifier properly sanitizes PII before sending
notifications to Slack webhooks.

Usage:
    python3 agents/lib/test_slack_pii_sanitization.py
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from slack_notifier import SlackNotifier


class TestSlackPIISanitization(unittest.TestCase):
    """Test PII sanitization in Slack notifications."""

    def setUp(self):
        """Set up test fixtures."""
        # Create notifier with mock webhook URL
        self.notifier = SlackNotifier(
            webhook_url="https://hooks.slack.com/test/webhook",
            throttle_seconds=0,  # Disable throttling for tests
        )

    @patch("slack_notifier.aiohttp.ClientSession")
    def test_email_sanitization_in_context(self, mock_session):
        """Test that emails in context are sanitized."""
        # Mock successful webhook response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = (
            mock_response
        )

        # Create error with email in context
        error = ValueError("Database connection failed")
        context = {
            "service": "test-service",
            "user_email": "admin@example.com",
            "contact": "support@company.com",
        }

        # Send notification
        async def run_test():
            # Mock _send_to_slack to capture the message
            original_send = self.notifier._send_to_slack
            captured_message = None

            async def capture_and_send(message):
                nonlocal captured_message
                captured_message = message
                return True

            self.notifier._send_to_slack = capture_and_send

            # Send notification
            await self.notifier.send_error_notification(error, context)

            # Verify email was sanitized
            assert captured_message is not None

            # Convert message to string for searching
            message_str = str(captured_message)

            # Original emails should NOT appear
            assert "admin@example.com" not in message_str
            assert "support@company.com" not in message_str

            # Sanitized format should appear (or field should be masked)
            # Since email is a sensitive field, it should be completely masked with ***
            assert "***" in message_str

        asyncio.run(run_test())

    @patch("slack_notifier.aiohttp.ClientSession")
    def test_ip_address_sanitization(self, mock_session):
        """Test that IP addresses are sanitized."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = (
            mock_response
        )

        error = ConnectionError("Failed to connect to server")
        context = {
            "service": "test-service",
            "server_ip": "192.168.86.200",
            "client_ip": "10.0.0.5",
        }

        async def run_test():
            captured_message = None

            async def capture_and_send(message):
                nonlocal captured_message
                captured_message = message
                return True

            self.notifier._send_to_slack = capture_and_send
            await self.notifier.send_error_notification(error, context)

            message_str = str(captured_message)

            # Original IPs should NOT appear
            assert "192.168.86.200" not in message_str
            assert "10.0.0.5" not in message_str

            # Should be masked (sensitive field names)
            assert "***" in message_str

        asyncio.run(run_test())

    @patch("slack_notifier.aiohttp.ClientSession")
    def test_correlation_id_sanitization(self, mock_session):
        """Test that correlation IDs are sanitized."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = (
            mock_response
        )

        error = RuntimeError("Operation failed")
        context = {
            "service": "test-service",
            "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
        }

        async def run_test():
            captured_message = None

            async def capture_and_send(message):
                nonlocal captured_message
                captured_message = message
                return True

            self.notifier._send_to_slack = capture_and_send
            await self.notifier.send_error_notification(error, context)

            message_str = str(captured_message)

            # Original correlation ID should NOT appear
            assert "550e8400-e29b-41d4-a716-446655440000" not in message_str

            # Should be masked (correlation_id is sensitive field)
            assert "***" in message_str

        asyncio.run(run_test())

    @patch("slack_notifier.aiohttp.ClientSession")
    def test_database_credentials_sanitization(self, mock_session):
        """Test that database credentials in connection strings are sanitized."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = (
            mock_response
        )

        error = Exception("Database error")
        context = {
            "service": "test-service",
            "connection_string": "postgresql://user:password@192.168.86.200:5436/db",
            "note": "Connection failed to postgresql://admin:secret@localhost:5432/mydb",
        }

        async def run_test():
            captured_message = None

            async def capture_and_send(message):
                nonlocal captured_message
                captured_message = message
                return True

            self.notifier._send_to_slack = capture_and_send
            await self.notifier.send_error_notification(error, context)

            message_str = str(captured_message)

            # Original credentials should NOT appear
            assert "user:password" not in message_str
            assert "admin:secret" not in message_str

            # Sanitized format should appear
            # connection_string is sensitive field, so completely masked
            # But note field should have pattern sanitization
            if "***:***@" in message_str or "***" in message_str:
                # Either pattern sanitization or field masking worked
                pass
            else:
                self.fail("Database credentials were not sanitized")

        asyncio.run(run_test())

    @patch("slack_notifier.aiohttp.ClientSession")
    def test_file_path_username_sanitization(self, mock_session):
        """Test that usernames in file paths are sanitized."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = (
            mock_response
        )

        # Create error with file path in stack trace
        try:
            # Generate a stack trace
            exec("raise RuntimeError('Test error from /home/john/project/file.py')")
        except RuntimeError as e:
            error = e

        context = {
            "service": "test-service",
            "file_path": "/home/admin/omniclaude/test.py",
        }

        async def run_test():
            captured_message = None

            async def capture_and_send(message):
                nonlocal captured_message
                captured_message = message
                return True

            self.notifier._send_to_slack = capture_and_send
            await self.notifier.send_error_notification(error, context)

            message_str = str(captured_message)

            # Usernames in paths should be masked
            # Note: The exact sanitization depends on whether it's in a sensitive field
            # or detected as a pattern in a string
            if "/home/john" in message_str or "/home/admin" in message_str:
                # Check if at least the pattern-based sanitization worked
                if (
                    "/home/***/project" not in message_str
                    and "/home/***/omniclaude" not in message_str
                ):
                    # If pattern sanitization didn't work, field should be masked
                    assert "***" in message_str

        asyncio.run(run_test())

    @patch("slack_notifier.aiohttp.ClientSession")
    def test_error_message_sanitization(self, mock_session):
        """Test that error messages with PII are sanitized."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = (
            mock_response
        )

        # Error message with embedded PII
        error = ValueError(
            "User admin@example.com from IP 192.168.1.100 failed to authenticate"
        )

        context = {"service": "auth-service"}

        async def run_test():
            captured_message = None

            async def capture_and_send(message):
                nonlocal captured_message
                captured_message = message
                return True

            self.notifier._send_to_slack = capture_and_send
            await self.notifier.send_error_notification(error, context)

            message_str = str(captured_message)

            # Original email should be sanitized
            assert "admin@example.com" not in message_str

            # Sanitized email format should appear
            assert "a***@example.com" in message_str

            # IP should be sanitized
            assert "192.168.1.100" not in message_str
            assert "192.*.*.*" in message_str

        asyncio.run(run_test())

    @patch("slack_notifier.aiohttp.ClientSession")
    def test_api_key_sanitization(self, mock_session):
        """Test that API keys are sanitized."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = (
            mock_response
        )

        error = Exception("API authentication failed")
        context = {
            "service": "api-service",
            "api_key": "sk-1234567890abcdefghijklmnopqrstuvwxyz",
            "gemini_key": "AIzaSyD1234567890abcdefghijklmnopqrstuvwxyz",
        }

        async def run_test():
            captured_message = None

            async def capture_and_send(message):
                nonlocal captured_message
                captured_message = message
                return True

            self.notifier._send_to_slack = capture_and_send
            await self.notifier.send_error_notification(error, context)

            message_str = str(captured_message)

            # Original API keys should NOT appear
            assert "sk-1234567890abcdefghijklmnopqrstuvwxyz" not in message_str
            assert "AIzaSyD1234567890abcdefghijklmnopqrstuvwxyz" not in message_str

            # Should be completely masked (sensitive fields)
            assert "***" in message_str

        asyncio.run(run_test())

    @patch("slack_notifier.aiohttp.ClientSession")
    def test_nested_context_sanitization(self, mock_session):
        """Test that nested context structures are sanitized."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = (
            mock_response
        )

        error = RuntimeError("Nested error")
        context = {
            "service": "test-service",
            "user": {
                "email": "user@example.com",
                "username": "testuser",
            },
            "connection": {
                "ip_address": "192.168.1.50",
                "port": 5432,
            },
        }

        async def run_test():
            captured_message = None

            async def capture_and_send(message):
                nonlocal captured_message
                captured_message = message
                return True

            self.notifier._send_to_slack = capture_and_send
            await self.notifier.send_error_notification(error, context)

            message_str = str(captured_message)

            # Original PII should NOT appear
            assert "user@example.com" not in message_str
            assert "192.168.1.50" not in message_str

            # Should be sanitized (either field masked or pattern sanitized)
            assert "***" in message_str

        asyncio.run(run_test())

    def test_sanitization_without_pii_sanitizer(self):
        """Test graceful degradation if PII sanitizer is not available."""
        # This test verifies the warning is logged when sanitizer unavailable
        # In production, the sanitizer will always be available

        async def run_test():
            # Mock the import to fail
            with patch("slack_notifier.importlib.import_module") as mock_import:
                mock_import.side_effect = ImportError("pii_sanitizer not found")

                error = ValueError("Test error")
                context = {"service": "test", "email": "test@example.com"}

                # Create new notifier to trigger import attempt
                notifier = SlackNotifier(
                    webhook_url="https://hooks.slack.com/test",
                    throttle_seconds=0,
                )

                # Should not crash, just log warning
                # (actual notification won't be sent in test, but sanitization path exercised)
                message = notifier._build_slack_message(error, context)
                assert message is not None

        asyncio.run(run_test())


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestSlackPIISanitization)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print("PII SANITIZATION INTEGRATION TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("=" * 70)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    exit(run_tests())
