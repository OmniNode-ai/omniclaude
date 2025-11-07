#!/usr/bin/env python3
"""
Test script for username logging enhancements.

Tests:
1. Username capture with fallback handling
2. Metadata capture (hostname, platform, UID, full name, domain)
3. Security considerations (no sensitive data leakage)
"""

import os
import sys
from unittest.mock import patch

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from session_intelligence import get_environment_metadata


def test_username_fallback():
    """Test username capture with different environment variable scenarios."""
    print("=== Test 1: Username Fallback Handling ===\n")

    # Test 1: USER environment variable set
    with patch.dict(os.environ, {"USER": "testuser1", "USERNAME": "ignored"}):
        metadata = get_environment_metadata()
        assert metadata["user"] == "testuser1", "Should use USER when available"
        print("✅ USER environment variable: PASSED")

    # Test 2: Only USERNAME environment variable set
    with patch.dict(os.environ, {"USERNAME": "testuser2"}, clear=True):
        metadata = get_environment_metadata()
        assert metadata["user"] == "testuser2", "Should use USERNAME as fallback"
        print("✅ USERNAME environment variable: PASSED")

    # Test 3: Neither USER nor USERNAME set
    with patch.dict(os.environ, {}, clear=True):
        metadata = get_environment_metadata()
        assert metadata["user"] == "unknown", "Should default to 'unknown'"
        print("✅ Fallback to 'unknown': PASSED")

    print()


def test_metadata_capture():
    """Test that all expected metadata fields are captured."""
    print("=== Test 2: Metadata Capture ===\n")

    metadata = get_environment_metadata()

    # Required fields
    required_fields = ["user", "hostname", "platform", "python_version"]
    for field in required_fields:
        assert field in metadata, f"Missing required field: {field}"
        assert metadata[field] is not None, f"Field {field} should not be None"
        print(f"✅ {field}: {metadata[field]}")

    # Optional fields (platform-dependent)
    if "uid" in metadata:
        print(f"✅ uid: {metadata['uid']}")
    if "user_fullname" in metadata:
        print(f"✅ user_fullname: {metadata['user_fullname']}")
    if "domain" in metadata:
        print(f"✅ domain: {metadata['domain']}")

    print()


def test_security_considerations():
    """Test that sensitive information is handled appropriately."""
    print("=== Test 4: Security Considerations ===\n")

    metadata = get_environment_metadata()

    # Verify username is captured (needed for debugging/auditing)
    assert "user" in metadata, "Username should be captured"
    print("✅ Username captured for auditing")

    # Verify no sensitive environment variables are leaked
    sensitive_vars = ["PASSWORD", "SECRET", "TOKEN", "KEY"]
    for key in metadata.keys():
        for sensitive in sensitive_vars:
            assert (
                sensitive not in key.upper()
            ), f"Should not capture sensitive var: {key}"

    print("✅ No sensitive environment variables captured")
    print()


def main():
    """Run all tests."""
    print("=" * 60)
    print("Username Logging Enhancement Tests")
    print("=" * 60)
    print()

    try:
        test_username_fallback()
        test_metadata_capture()
        test_security_considerations()

        print("=" * 60)
        print("✅ All tests PASSED")
        print("=" * 60)
        return 0

    except AssertionError as e:
        print(f"\n❌ Test FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
