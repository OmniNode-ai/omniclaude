#!/usr/bin/env python3
"""
Test suite for Qdrant helper empty collection handling.

Validates that empty collections (0 vectors) are correctly treated as healthy
when Qdrant reports them as "green" or "yellow".
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent))

from qdrant_helper import get_collection_health


class MockResponse:
    """Mock HTTP response for testing."""

    def __init__(self, status: int, data: dict[str, Any]):
        self.status = status
        self._data = data

    def read(self):
        return json.dumps(self._data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_empty_collection_is_healthy():
    """
    Test that an empty collection (0 vectors) with green status is considered healthy.

    This is the PRIMARY test case for the PR #33 review concern.
    """
    print("Test 1: Empty collection with green status should be healthy...")

    # Mock Qdrant API response for an empty collection with green status
    mock_response = MockResponse(
        status=200,
        data={
            "result": {
                "points_count": 0,  # Empty collection
                "indexed_vectors_count": 0,
                "status": "green",  # Healthy according to Qdrant
                "optimizer_status": {"status": "ok"},
            }
        },
    )

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = get_collection_health("test_empty_collection")

    # Assertions
    assert result["success"] is True, "Should succeed"
    assert result["healthy"] is True, (
        "Empty collection with green status should be HEALTHY"
    )
    assert result["status"] == "green", "Status should be green"
    assert result["vectors_count"] == 0, "Should report 0 vectors"
    assert result["error"] is None, "Should have no error"

    print("  ✅ PASSED: Empty collection correctly marked as healthy")


def test_empty_collection_yellow_status():
    """
    Test that an empty collection with yellow status is still considered healthy.
    """
    print("Test 2: Empty collection with yellow status should be healthy...")

    mock_response = MockResponse(
        status=200,
        data={
            "result": {
                "points_count": 0,
                "indexed_vectors_count": 0,
                "status": "yellow",  # Still acceptable
                "optimizer_status": {"status": "optimizing"},
            }
        },
    )

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = get_collection_health("test_yellow_collection")

    assert result["success"] is True
    assert result["healthy"] is True, "Yellow status should be healthy"
    assert result["status"] == "yellow"

    print("  ✅ PASSED: Yellow status correctly treated as healthy")


def test_populated_collection_is_healthy():
    """
    Test that a populated collection with green status is healthy.
    """
    print("Test 3: Populated collection with green status should be healthy...")

    mock_response = MockResponse(
        status=200,
        data={
            "result": {
                "points_count": 1000,  # Populated collection
                "indexed_vectors_count": 1000,
                "status": "green",
                "optimizer_status": {"status": "ok"},
            }
        },
    )

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = get_collection_health("test_populated_collection")

    assert result["success"] is True
    assert result["healthy"] is True
    assert result["vectors_count"] == 1000

    print("  ✅ PASSED: Populated collection is healthy")


def test_collection_with_red_status_is_unhealthy():
    """
    Test that a collection with red status is unhealthy, regardless of vector count.
    """
    print("Test 4: Collection with red status should be unhealthy...")

    mock_response = MockResponse(
        status=200,
        data={
            "result": {
                "points_count": 1000,  # Even with vectors
                "indexed_vectors_count": 500,
                "status": "red",  # Unhealthy
                "optimizer_status": {"status": "error"},
            }
        },
    )

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = get_collection_health("test_red_collection")

    assert result["success"] is True
    assert result["healthy"] is False, "Red status should be unhealthy"
    assert result["status"] == "red"

    print("  ✅ PASSED: Red status correctly marked as unhealthy")


def test_missing_collection_is_unhealthy():
    """
    Test that a missing/unreachable collection is marked as unhealthy.
    """
    print("Test 5: Missing collection should be unhealthy...")

    # Mock HTTP 404 error
    mock_error = urllib.error.URLError("Collection not found")

    with patch("urllib.request.urlopen", side_effect=mock_error):
        result = get_collection_health("test_missing_collection")

    assert result["success"] is False, "Should fail"
    assert result["healthy"] is False, "Missing collection should be unhealthy"
    assert "error" in result, "Should have error message"

    print("  ✅ PASSED: Missing collection correctly marked as unhealthy")


def test_connection_error_is_unhealthy():
    """
    Test that connection errors result in unhealthy status.
    """
    print("Test 6: Connection error should be unhealthy...")

    # Mock connection error
    mock_error = urllib.error.URLError("Connection refused")

    with patch("urllib.request.urlopen", side_effect=mock_error):
        result = get_collection_health("test_unreachable")

    assert result["success"] is False
    assert result["healthy"] is False, "Connection error should be unhealthy"
    assert "Connection error" in result.get("error", "")

    print("  ✅ PASSED: Connection error correctly marked as unhealthy")


def test_empty_collection_unknown_status():
    """
    Test that an empty collection with unknown status is unhealthy.
    """
    print("Test 7: Empty collection with unknown status should be unhealthy...")

    mock_response = MockResponse(
        status=200,
        data={
            "result": {
                "points_count": 0,
                "indexed_vectors_count": 0,
                "status": "unknown",  # Unknown status
                "optimizer_status": {},
            }
        },
    )

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = get_collection_health("test_unknown_status")

    assert result["success"] is True
    assert result["healthy"] is False, "Unknown status should be unhealthy"
    assert result["status"] == "unknown"

    print("  ✅ PASSED: Unknown status correctly marked as unhealthy")


def main():
    """Run all tests."""
    print("=" * 70)
    print("QDRANT EMPTY COLLECTION HEALTH CHECK TESTS")
    print("=" * 70)
    print()
    print("Purpose: Validate that empty collections are correctly treated as healthy")
    print("Context: PR #33 review - ensuring empty collections aren't false negatives")
    print()

    tests = [
        test_empty_collection_is_healthy,
        test_empty_collection_yellow_status,
        test_populated_collection_is_healthy,
        test_collection_with_red_status_is_unhealthy,
        test_missing_collection_is_unhealthy,
        test_connection_error_is_unhealthy,
        test_empty_collection_unknown_status,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            failed += 1

    print()
    print("=" * 70)
    print(f"SUMMARY: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed > 0:
        print()
        print("❌ Some tests failed. Empty collection handling needs fixes.")
        return 1
    else:
        print()
        print("✅ All tests passed! Empty collections are correctly handled.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
