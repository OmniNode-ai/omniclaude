#!/usr/bin/env python3
"""
Test SSRF Protection in Qdrant Helper

This script verifies that the SSRF protection mechanisms work correctly
by testing various attack vectors and valid scenarios.

Usage:
    python3 test_qdrant_ssrf_protection.py

Expected Results:
    - All malicious URLs should be blocked (ValueError raised)
    - All valid URLs should be accepted
    - HTTPS should be enforced in production

Created: 2025-11-20
"""

import os
import sys
from typing import List, Tuple


# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from qdrant_helper import validate_qdrant_url


def test_valid_urls() -> List[Tuple[str, bool, str]]:
    """Test valid URLs that should pass validation."""
    results = []

    # Set development environment for testing
    original_env = os.getenv("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "development"

    test_cases = [
        ("http://localhost:6333", "Localhost HTTP (dev)"),
        ("http://127.0.0.1:6333", "Loopback IPv4"),
        ("http://[::1]:6333", "Loopback IPv6"),
        ("http://192.168.86.101:6333", "Archon server IP"),
        ("http://qdrant.internal:6333", "Internal DNS name"),
    ]

    for url, description in test_cases:
        try:
            result = validate_qdrant_url(url)
            results.append((description, True, f"✅ PASS: {result}"))
        except ValueError as e:
            results.append((description, False, f"❌ FAIL: {e}"))

    # Restore original environment
    if original_env:
        os.environ["ENVIRONMENT"] = original_env
    else:
        del os.environ["ENVIRONMENT"]

    return results


def test_https_enforcement() -> List[Tuple[str, bool, str]]:
    """Test HTTPS enforcement in production."""
    results = []

    # Set production environment
    original_env = os.getenv("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "production"

    test_cases = [
        ("https://qdrant.internal:6333", True, "HTTPS in production (should pass)"),
        ("http://localhost:6333", False, "HTTP in production (should fail)"),
        ("https://localhost:6333", True, "HTTPS localhost in production (should pass)"),
    ]

    for url, should_pass, description in test_cases:
        try:
            result = validate_qdrant_url(url)
            if should_pass:
                results.append((description, True, f"✅ PASS: {result}"))
            else:
                results.append(
                    (description, False, f"❌ FAIL: Should have blocked but allowed")
                )
        except ValueError as e:
            if not should_pass:
                results.append((description, True, f"✅ PASS: Correctly blocked - {e}"))
            else:
                results.append(
                    (description, False, f"❌ FAIL: Incorrectly blocked - {e}")
                )

    # Restore original environment
    if original_env:
        os.environ["ENVIRONMENT"] = original_env
    else:
        del os.environ["ENVIRONMENT"]

    return results


def test_malicious_urls() -> List[Tuple[str, bool, str]]:
    """Test malicious URLs that should be blocked."""
    results = []

    # Set development environment (more permissive, but still blocks attacks)
    original_env = os.getenv("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "development"

    test_cases = [
        ("http://internal-admin:80", "Non-whitelisted host (internal admin)"),
        ("http://169.254.169.254:80", "AWS metadata endpoint"),
        ("http://metadata.google.internal:80", "GCP metadata endpoint"),
        ("http://localhost:22", "SSH port (dangerous)"),
        ("http://localhost:3389", "RDP port (dangerous)"),
        ("http://localhost:5432", "PostgreSQL port (dangerous)"),
        ("http://localhost:6379", "Redis port (dangerous)"),
        ("http://localhost:9092", "Kafka port (dangerous)"),
        ("http://localhost:3306", "MySQL port (dangerous)"),
        ("http://evil.com:6333", "External domain not in whitelist"),
        ("http://10.0.0.1:6333", "Private IP not in whitelist"),
    ]

    for url, description in test_cases:
        try:
            result = validate_qdrant_url(url)
            results.append(
                (description, False, f"❌ FAIL: Should have blocked {url} but allowed")
            )
        except ValueError as e:
            results.append((description, True, f"✅ PASS: Correctly blocked - {e}"))

    # Restore original environment
    if original_env:
        os.environ["ENVIRONMENT"] = original_env
    else:
        del os.environ["ENVIRONMENT"]

    return results


def test_port_validation() -> List[Tuple[str, bool, str]]:
    """Test port validation."""
    results = []

    original_env = os.getenv("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "development"

    test_cases = [
        ("http://localhost:6333", True, "Valid port 6333"),
        ("http://localhost:80", True, "Valid port 80"),
        ("http://localhost:8080", True, "Valid port 8080"),
        ("http://localhost:0", False, "Invalid port 0"),
        ("http://localhost:65536", False, "Invalid port 65536 (out of range)"),
        ("http://localhost:-1", False, "Invalid port -1 (negative)"),
    ]

    for url, should_pass, description in test_cases:
        try:
            result = validate_qdrant_url(url)
            if should_pass:
                results.append((description, True, f"✅ PASS: {result}"))
            else:
                results.append(
                    (description, False, f"❌ FAIL: Should have blocked but allowed")
                )
        except (ValueError, Exception) as e:
            if not should_pass:
                results.append((description, True, f"✅ PASS: Correctly blocked - {e}"))
            else:
                results.append(
                    (description, False, f"❌ FAIL: Incorrectly blocked - {e}")
                )

    # Restore original environment
    if original_env:
        os.environ["ENVIRONMENT"] = original_env
    else:
        del os.environ["ENVIRONMENT"]

    return results


def test_additional_allowed_hosts() -> List[Tuple[str, bool, str]]:
    """Test QDRANT_ALLOWED_HOSTS environment variable."""
    results = []

    original_env = os.getenv("ENVIRONMENT")
    original_hosts = os.getenv("QDRANT_ALLOWED_HOSTS")

    os.environ["ENVIRONMENT"] = "development"
    os.environ["QDRANT_ALLOWED_HOSTS"] = "custom-qdrant.example.com,10.0.0.50"

    test_cases = [
        ("http://custom-qdrant.example.com:6333", True, "Custom allowed host"),
        ("http://10.0.0.50:6333", True, "Custom allowed IP"),
        ("http://not-allowed.com:6333", False, "Host not in whitelist"),
    ]

    for url, should_pass, description in test_cases:
        try:
            result = validate_qdrant_url(url)
            if should_pass:
                results.append((description, True, f"✅ PASS: {result}"))
            else:
                results.append(
                    (description, False, f"❌ FAIL: Should have blocked but allowed")
                )
        except ValueError as e:
            if not should_pass:
                results.append((description, True, f"✅ PASS: Correctly blocked - {e}"))
            else:
                results.append(
                    (description, False, f"❌ FAIL: Incorrectly blocked - {e}")
                )

    # Restore original environment
    if original_env:
        os.environ["ENVIRONMENT"] = original_env
    else:
        del os.environ["ENVIRONMENT"]

    if original_hosts:
        os.environ["QDRANT_ALLOWED_HOSTS"] = original_hosts
    elif "QDRANT_ALLOWED_HOSTS" in os.environ:
        del os.environ["QDRANT_ALLOWED_HOSTS"]

    return results


def print_results(title: str, results: List[Tuple[str, bool, str]]):
    """Print test results."""
    print(f"\n{'=' * 70}")
    print(f"{title}")
    print(f"{'=' * 70}")

    passed = sum(1 for _, success, _ in results if success)
    total = len(results)

    for description, success, message in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} | {description}")
        print(f"       {message}")

    print(f"\nResults: {passed}/{total} tests passed")


def main():
    """Run all tests."""
    print("=" * 70)
    print("QDRANT HELPER - SSRF PROTECTION TESTS")
    print("=" * 70)
    print("\nTesting SSRF protection mechanisms...")

    # Run all test suites
    valid_results = test_valid_urls()
    https_results = test_https_enforcement()
    malicious_results = test_malicious_urls()
    port_results = test_port_validation()
    custom_hosts_results = test_additional_allowed_hosts()

    # Print results
    print_results("1. VALID URLs (Development)", valid_results)
    print_results("2. HTTPS ENFORCEMENT (Production)", https_results)
    print_results("3. MALICIOUS URLs (SSRF Attacks)", malicious_results)
    print_results("4. PORT VALIDATION", port_results)
    print_results("5. CUSTOM ALLOWED HOSTS", custom_hosts_results)

    # Calculate overall results
    all_results = (
        valid_results
        + https_results
        + malicious_results
        + port_results
        + custom_hosts_results
    )
    total_passed = sum(1 for _, success, _ in all_results if success)
    total_tests = len(all_results)

    print("\n" + "=" * 70)
    print("OVERALL RESULTS")
    print("=" * 70)
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {total_passed}")
    print(f"Failed: {total_tests - total_passed}")
    print(f"Success Rate: {(total_passed / total_tests * 100):.1f}%")

    if total_passed == total_tests:
        print("\n✅ ALL TESTS PASSED - SSRF protection is working correctly!")
        return 0
    else:
        print(
            f"\n❌ SOME TESTS FAILED - {total_tests - total_passed} test(s) need attention"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
