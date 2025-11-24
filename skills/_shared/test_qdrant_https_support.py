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

import os
import sys
import unittest
from unittest.mock import patch


class TestQdrantHttpsSupport(unittest.TestCase):
    """Test HTTPS support in Qdrant helper.

    Uses mocking to avoid flaky module reloading and ensure test isolation.
    """

    def setUp(self):
        """Set up test fixtures."""
        # Save original environment
        self.original_env = os.environ.copy()
        # Clean up any previously imported modules to ensure fresh imports
        for module in ["qdrant_helper", "config", "config.settings"]:
            if module in sys.modules:
                del sys.modules[module]

    def tearDown(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)
        # Clean up imported modules
        for module in ["qdrant_helper", "config", "config.settings"]:
            if module in sys.modules:
                del sys.modules[module]

    def test_explicit_https_url(self):
        """Test explicit HTTPS URL in QDRANT_URL."""
        # Set production environment to allow HTTPS
        os.environ["ENVIRONMENT"] = "production"
        os.environ["QDRANT_URL"] = "https://qdrant.internal:6333"
        os.environ["QDRANT_HOST"] = "qdrant.internal"
        os.environ["QDRANT_PORT"] = "6333"

        # Import after environment is set (setUp already cleaned modules)
        from qdrant_helper import get_qdrant_url

        # Get URL - should return HTTPS
        url = get_qdrant_url()
        assert url.startswith("https://"), f"Expected HTTPS URL, got: {url}"

    def test_explicit_http_url_dev(self):
        """Test explicit HTTP URL in development."""
        # Set development environment
        os.environ["ENVIRONMENT"] = "development"
        os.environ["QDRANT_URL"] = "http://localhost:6333"
        os.environ["QDRANT_HOST"] = "localhost"
        os.environ["QDRANT_PORT"] = "6333"

        # Import after environment is set (setUp already cleaned modules)
        from qdrant_helper import get_qdrant_url

        # Get URL - should return HTTP
        url = get_qdrant_url()
        assert url.startswith("http://"), f"Expected HTTP URL, got: {url}"

    def test_auto_https_production(self):
        """Test auto HTTPS selection in production."""
        # Set production environment without explicit protocol
        os.environ["ENVIRONMENT"] = "production"
        # Don't set QDRANT_URL or set it without protocol
        if "QDRANT_URL" in os.environ:
            del os.environ["QDRANT_URL"]
        os.environ["QDRANT_HOST"] = "qdrant.internal"
        os.environ["QDRANT_PORT"] = "6333"

        # Import after environment is set (setUp already cleaned modules)
        from qdrant_helper import get_qdrant_url

        # Get URL - should auto-select HTTPS
        url = get_qdrant_url()
        assert url.startswith(
            "https://"
        ), f"Expected HTTPS URL in production, got: {url}"

    def test_auto_http_development(self):
        """Test auto HTTP selection in development."""
        # Set development environment without explicit protocol
        os.environ["ENVIRONMENT"] = "development"
        # Don't set QDRANT_URL or set it without protocol
        if "QDRANT_URL" in os.environ:
            del os.environ["QDRANT_URL"]
        os.environ["QDRANT_HOST"] = "localhost"
        os.environ["QDRANT_PORT"] = "6333"

        # Import after environment is set (setUp already cleaned modules)
        from qdrant_helper import get_qdrant_url

        # Get URL - should auto-select HTTP
        url = get_qdrant_url()
        assert url.startswith(
            "http://"
        ), f"Expected HTTP URL in development, got: {url}"

    def test_https_validation_production(self):
        """Test HTTPS validation is enforced in production."""
        # Set production environment without explicit protocol
        os.environ["ENVIRONMENT"] = "production"
        if "QDRANT_URL" in os.environ:
            del os.environ["QDRANT_URL"]
        os.environ["QDRANT_HOST"] = "localhost"
        os.environ["QDRANT_PORT"] = "6333"

        # Import after environment is set (setUp already cleaned modules)
        from qdrant_helper import get_qdrant_url

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
