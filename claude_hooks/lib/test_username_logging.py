#!/usr/bin/env python3
"""
Test script for username logging enhancements.

Tests:
1. Username capture with fallback handling
2. Metadata capture (hostname, platform, UID, full name, domain)
3. Security considerations (no sensitive data leakage)
4. Windows domain capture via USERDOMAIN (mocked)
"""

import os
import sys
from unittest.mock import patch


# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from session_intelligence import get_environment_metadata


def test_username_fallback():
    """
    Test username fallback mechanism when USER not set.

    Verifies that the username capture falls back to alternative
    methods when the USER environment variable is not available.
    Tests three scenarios: USER set, only USERNAME set, and neither set.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If fallback mechanism fails or username capture
            does not follow expected priority (USER -> USERNAME -> 'unknown')

    Example:
        >>> test_username_fallback()
        # Verifies fallback to USERNAME then 'unknown'
    """
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
    """
    Test that all expected metadata fields are captured.

    Verifies that get_environment_metadata() returns all required fields
    (user, hostname, platform, python_version) and handles optional
    platform-dependent fields (uid, user_fullname, domain) gracefully.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If any required metadata field is missing or None

    Example:
        >>> test_metadata_capture()
        # Validates all required fields present and non-None
    """
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
    """
    Test that sensitive information is handled appropriately.

    Verifies that the metadata capture includes necessary auditing
    information (username) while ensuring no sensitive environment
    variables (PASSWORD, SECRET, TOKEN, KEY) are leaked in metadata.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If username is not captured or if sensitive
            environment variables are found in metadata keys

    Example:
        >>> test_security_considerations()
        # Ensures username captured but no passwords/tokens leaked
    """
    print("=== Test 3: Security Considerations ===\n")

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


def test_windows_domain_capture():
    """
    Test Windows domain capture via USERDOMAIN environment variable.

    Verifies that get_environment_metadata() correctly captures the Windows
    domain from the USERDOMAIN environment variable when running on Windows,
    and does not capture domain information on non-Windows platforms.

    Uses mocking to simulate Windows environment without requiring actual
    Windows platform for testing. Simulates Windows by making the pwd module
    import fail (as it doesn't exist on Windows).

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If domain capture behavior differs from expected
            Windows vs non-Windows platform handling

    Example:
        >>> test_windows_domain_capture()
        # Validates Windows domain captured on Windows, not on Linux/Mac
    """
    print("=== Test 4: Windows Domain Capture ===\n")

    # Mock Windows environment with USERDOMAIN set
    test_domain = "TESTDOMAIN"
    # Patch platform.system and make pwd import fail (simulating Windows)
    with patch.dict(os.environ, {"USERDOMAIN": test_domain, "USER": "testuser"}):
        with patch("platform.system") as mock_system:
            # Mock pwd module to raise ImportError (simulating Windows where pwd doesn't exist)
            with patch.dict("sys.modules", {"pwd": None}):
                mock_system.return_value = "Windows"
                metadata = get_environment_metadata()

                # Verify domain is captured
                assert "domain" in metadata, "Domain should be captured on Windows"
                assert (
                    metadata["domain"] == test_domain
                ), f"Domain should be '{test_domain}', got '{metadata.get('domain')}'"
                print(f"✅ Windows domain captured: {metadata['domain']}")

    # Mock non-Windows environment (domain should not be captured)
    # Even if pwd import fails, domain should only be captured on Windows
    with patch.dict(os.environ, {"USER": "testuser"}):
        with patch("platform.system") as mock_system:
            with patch.dict("sys.modules", {"pwd": None}):
                mock_system.return_value = "Linux"
                metadata = get_environment_metadata()

                # Verify domain is NOT captured on non-Windows
                assert (
                    "domain" not in metadata
                ), "Domain should not be captured on non-Windows platforms"
                print("✅ Domain not captured on non-Windows platform")

    print()


def main():
    """
    Run all username logging enhancement tests.

    Executes test_username_fallback(), test_metadata_capture(),
    test_security_considerations(), and test_windows_domain_capture()
    in sequence. Reports overall pass/fail status with detailed error
    messages on failure.

    Args:
        None

    Returns:
        int: Exit code (0 for success, 1 for failure)

    Raises:
        AssertionError: Caught and reported with test failure message
        Exception: Caught and reported with traceback for unexpected errors

    Example:
        >>> exit_code = main()
        >>> assert exit_code == 0  # All tests passed
    """
    print("=" * 60)
    print("Username Logging Enhancement Tests")
    print("=" * 60)
    print()

    try:
        test_username_fallback()
        test_metadata_capture()
        test_security_considerations()
        test_windows_domain_capture()

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
