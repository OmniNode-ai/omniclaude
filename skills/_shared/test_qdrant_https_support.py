#!/usr/bin/env python3
"""
Test Qdrant HTTPS Support

Tests that qdrant_helper.py correctly supports both HTTP and HTTPS protocols
based on QDRANT_URL configuration and ENVIRONMENT settings.

Usage:
    python3 test_qdrant_https_support.py

Expected behavior:
1. QDRANT_URL with https:// → Use HTTPS
2. QDRANT_URL with http:// → Use HTTP (dev only)
3. ENVIRONMENT=production + no protocol → Auto HTTPS
4. ENVIRONMENT=development + no protocol → Auto HTTP

Created: 2025-11-20
Updated: 2025-11-24 - Fixed import/mocking patterns for stability
"""

import sys
import unittest
from unittest.mock import MagicMock, patch


class TestQdrantHttpsSupport(unittest.TestCase):
    """Test HTTPS support in Qdrant helper.

    Uses mocking of settings and os.getenv to avoid flaky module reloading
    and ensure test isolation. Tests target validate_qdrant_url and
    get_qdrant_url behavior through proper mocking.
    """

    def test_explicit_https_url(self):
        """Test explicit HTTPS URL in QDRANT_URL."""
        # Create mock settings with HTTPS URL
        mock_settings = MagicMock()
        mock_settings.qdrant_url = "https://qdrant.internal:6333"
        mock_settings.qdrant_host = "qdrant.internal"
        mock_settings.qdrant_port = 6333

        with (
            patch("skills._shared.qdrant_helper.settings", mock_settings),
            patch("skills._shared.qdrant_helper.os.getenv") as mock_getenv,
        ):
            # Set production environment
            mock_getenv.side_effect = lambda key, default="": {
                "ENVIRONMENT": "production",
                "QDRANT_ALLOWED_HOSTS": "",
            }.get(key, default)

            from .qdrant_helper import get_qdrant_url

            # Get URL - should return HTTPS
            url = get_qdrant_url()
            assert url.startswith("https://"), f"Expected HTTPS URL, got: {url}"

    def test_explicit_http_url_dev(self):
        """Test explicit HTTP URL in development."""
        # Create mock settings with HTTP URL
        mock_settings = MagicMock()
        mock_settings.qdrant_url = "http://localhost:6333"
        mock_settings.qdrant_host = "localhost"
        mock_settings.qdrant_port = 6333

        with (
            patch("skills._shared.qdrant_helper.settings", mock_settings),
            patch("skills._shared.qdrant_helper.os.getenv") as mock_getenv,
        ):
            # Set development environment
            mock_getenv.side_effect = lambda key, default="": {
                "ENVIRONMENT": "development",
                "QDRANT_ALLOWED_HOSTS": "",
            }.get(key, default)

            from .qdrant_helper import get_qdrant_url

            # Get URL - should return HTTP
            url = get_qdrant_url()
            assert url.startswith("http://"), f"Expected HTTP URL, got: {url}"

    def test_auto_https_production(self):
        """Test auto HTTPS selection in production."""
        # Create mock settings without explicit protocol in URL
        mock_settings = MagicMock()
        mock_settings.qdrant_url = None  # No URL, use host+port
        mock_settings.qdrant_host = "qdrant.internal"
        mock_settings.qdrant_port = 6333

        with (
            patch("skills._shared.qdrant_helper.settings", mock_settings),
            patch("skills._shared.qdrant_helper.os.getenv") as mock_getenv,
        ):
            # Set production environment
            mock_getenv.side_effect = lambda key, default="": {
                "ENVIRONMENT": "production",
                "QDRANT_ALLOWED_HOSTS": "",
            }.get(key, default)

            from .qdrant_helper import get_qdrant_url

            # Get URL - should auto-select HTTPS
            url = get_qdrant_url()
            assert url.startswith(
                "https://"
            ), f"Expected HTTPS URL in production, got: {url}"

    def test_auto_http_development(self):
        """Test auto HTTP selection in development."""
        # Create mock settings without explicit protocol in URL
        mock_settings = MagicMock()
        mock_settings.qdrant_url = None  # No URL, use host+port
        mock_settings.qdrant_host = "localhost"
        mock_settings.qdrant_port = 6333

        with (
            patch("skills._shared.qdrant_helper.settings", mock_settings),
            patch("skills._shared.qdrant_helper.os.getenv") as mock_getenv,
        ):
            # Set development environment
            mock_getenv.side_effect = lambda key, default="": {
                "ENVIRONMENT": "development",
                "QDRANT_ALLOWED_HOSTS": "",
            }.get(key, default)

            from .qdrant_helper import get_qdrant_url

            # Get URL - should auto-select HTTP
            url = get_qdrant_url()
            assert url.startswith(
                "http://"
            ), f"Expected HTTP URL in development, got: {url}"

    def test_https_validation_production(self):
        """Test HTTPS validation is enforced in production."""
        # Create mock settings without explicit protocol in URL
        mock_settings = MagicMock()
        mock_settings.qdrant_url = None  # No URL, use host+port
        mock_settings.qdrant_host = "localhost"
        mock_settings.qdrant_port = 6333

        with (
            patch("skills._shared.qdrant_helper.settings", mock_settings),
            patch("skills._shared.qdrant_helper.os.getenv") as mock_getenv,
        ):
            # Set production environment
            mock_getenv.side_effect = lambda key, default="": {
                "ENVIRONMENT": "production",
                "QDRANT_ALLOWED_HOSTS": "",
            }.get(key, default)

            from .qdrant_helper import get_qdrant_url

            # Get URL - should construct with HTTPS in production
            url = get_qdrant_url()
            assert url.startswith(
                "https://"
            ), f"Expected HTTPS URL in production, got: {url}"

    def test_http_rejected_in_production_explicit_url(self):
        """Test that HTTP URL from settings is rejected in production."""
        # Create mock settings with explicit HTTP URL
        mock_settings = MagicMock()
        mock_settings.qdrant_url = "http://localhost:6333"  # HTTP explicitly set
        mock_settings.qdrant_host = "localhost"
        mock_settings.qdrant_port = 6333

        with (
            patch("skills._shared.qdrant_helper.settings", mock_settings),
            patch("skills._shared.qdrant_helper.os.getenv") as mock_getenv,
        ):
            # Set production environment
            mock_getenv.side_effect = lambda key, default="": {
                "ENVIRONMENT": "production",
                "QDRANT_ALLOWED_HOSTS": "",
            }.get(key, default)

            from .qdrant_helper import get_qdrant_url

            # In production, HTTP URLs should fall through to HTTPS construction
            url = get_qdrant_url()
            assert url.startswith(
                "https://"
            ), f"Expected HTTPS URL in production (HTTP should be rejected), got: {url}"


def main():
    """Run tests."""
    print("Testing Qdrant HTTPS Support...")
    print("=" * 70)

    # Run tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestQdrantHttpsSupport)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print("All HTTPS support tests passed!")
        return 0
    else:
        print("Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
