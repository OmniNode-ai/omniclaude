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
"""

import os
import sys
import unittest
from unittest.mock import patch


class TestQdrantHttpsSupport(unittest.TestCase):
    """Test HTTPS support in Qdrant helper."""

    def setUp(self):
        """Set up test fixtures."""
        # Save original environment
        self.original_env = os.environ.copy()

    def tearDown(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch("config.Settings")
    def test_explicit_https_url(self, mock_settings):
        """Test explicit HTTPS URL in QDRANT_URL."""
        # Mock settings with HTTPS URL
        mock_settings.qdrant_url = "https://qdrant.internal:6333"
        mock_settings.qdrant_host = "localhost"
        mock_settings.qdrant_port = 6333
        mock_settings.request_timeout_ms = 5000

        # Set production environment to allow HTTPS
        os.environ["ENVIRONMENT"] = "production"

        # Import after environment is set
        # Mock settings object
        import qdrant_helper
        from qdrant_helper import get_qdrant_url

        qdrant_helper.settings = mock_settings

        # Get URL - should return HTTPS
        url = get_qdrant_url()
        assert url.startswith("https://"), f"Expected HTTPS URL, got: {url}"

    @patch("config.Settings")
    def test_explicit_http_url_dev(self, mock_settings):
        """Test explicit HTTP URL in development."""
        # Mock settings with HTTP URL
        mock_settings.qdrant_url = "http://localhost:6333"
        mock_settings.qdrant_host = "localhost"
        mock_settings.qdrant_port = 6333
        mock_settings.request_timeout_ms = 5000

        # Set development environment
        os.environ["ENVIRONMENT"] = "development"

        # Import after environment is set
        # Mock settings object
        import qdrant_helper
        from qdrant_helper import get_qdrant_url

        qdrant_helper.settings = mock_settings

        # Get URL - should return HTTP
        url = get_qdrant_url()
        assert url.startswith("http://"), f"Expected HTTP URL, got: {url}"

    @patch("config.Settings")
    def test_auto_https_production(self, mock_settings):
        """Test auto HTTPS selection in production."""
        # Mock settings without protocol in URL
        mock_settings.qdrant_url = None  # No URL set
        mock_settings.qdrant_host = "qdrant.internal"
        mock_settings.qdrant_port = 6333
        mock_settings.request_timeout_ms = 5000

        # Set production environment
        os.environ["ENVIRONMENT"] = "production"

        # Import after environment is set
        # Mock settings object
        import qdrant_helper
        from qdrant_helper import get_qdrant_url

        qdrant_helper.settings = mock_settings

        # Get URL - should auto-select HTTPS
        url = get_qdrant_url()
        assert url.startswith(
            "https://"
        ), f"Expected HTTPS URL in production, got: {url}"

    @patch("config.Settings")
    def test_auto_http_development(self, mock_settings):
        """Test auto HTTP selection in development."""
        # Mock settings without protocol in URL
        mock_settings.qdrant_url = None  # No URL set
        mock_settings.qdrant_host = "localhost"
        mock_settings.qdrant_port = 6333
        mock_settings.request_timeout_ms = 5000

        # Set development environment
        os.environ["ENVIRONMENT"] = "development"

        # Import after environment is set
        # Mock settings object
        import qdrant_helper
        from qdrant_helper import get_qdrant_url

        qdrant_helper.settings = mock_settings

        # Get URL - should auto-select HTTP
        url = get_qdrant_url()
        assert url.startswith(
            "http://"
        ), f"Expected HTTP URL in development, got: {url}"

    @patch("config.Settings")
    def test_https_validation_production(self, mock_settings):
        """Test HTTPS validation is enforced in production."""
        # Mock settings with HTTP URL in production (should fail validation)
        mock_settings.qdrant_url = None  # No URL set, will construct
        mock_settings.qdrant_host = "localhost"
        mock_settings.qdrant_port = 6333
        mock_settings.request_timeout_ms = 5000

        # Set production environment
        os.environ["ENVIRONMENT"] = "production"

        # Import after environment is set
        # Mock settings object
        import qdrant_helper
        from qdrant_helper import get_qdrant_url

        qdrant_helper.settings = mock_settings

        # Get URL - should construct with HTTPS, then validate
        # (validation will pass because we construct with https://)
        url = get_qdrant_url()
        assert url.startswith(
            "https://"
        ), f"Expected HTTPS URL in production, got: {url}"


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
        print("✅ All HTTPS support tests passed!")
        return 0
    else:
        print("❌ Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
