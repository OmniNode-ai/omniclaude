#!/usr/bin/env python3
"""
Test script to verify check_docker_services handles failures correctly.

Tests:
1. Normal operation (Docker working)
2. Docker CLI unavailable
3. Docker permission denied
4. Services stopped or unhealthy
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

# Import the function we're testing
from execute import check_docker_services


def test_normal_operation():
    """Test when Docker is working normally."""
    print("Test 1: Normal operation (Docker working)")
    result = check_docker_services(verbose=False)

    assert (
        result["success"] == True
    ), "Should return success=True when Docker is working"
    assert "total" in result, "Should include total count"
    assert "running" in result, "Should include running count"
    assert "stopped" in result, "Should include stopped count"
    assert "unhealthy" in result, "Should include unhealthy count"
    assert "healthy" in result, "Should include healthy count"
    print("✓ PASS: Normal operation works correctly")
    print(
        f"  Total: {result['total']}, Running: {result['running']}, Stopped: {result['stopped']}"
    )
    print()


def test_docker_unavailable():
    """Test when Docker CLI is unavailable."""
    print("Test 2: Docker CLI unavailable")

    # Mock get_service_summary to return failure
    with patch("execute.get_service_summary") as mock_summary:
        mock_summary.return_value = {
            "success": False,
            "error": "Docker command failed: command not found",
            "containers": [],
            "count": 0,
        }

        result = check_docker_services(verbose=False)

        assert (
            result["success"] == False
        ), "Should return success=False when Docker is unavailable"
        assert "error" in result, "Should include error message"
        assert result["total"] == 0, "Should set total to 0"
        assert result["running"] == 0, "Should set running to 0"
        assert result["stopped"] == 0, "Should set stopped to 0"
        print("✓ PASS: Docker unavailable is handled correctly")
        print(f"  Error: {result['error']}")
        print()


def test_permission_denied():
    """Test when Docker has permission issues."""
    print("Test 3: Docker permission denied")

    with patch("execute.get_service_summary") as mock_summary:
        mock_summary.return_value = {
            "success": False,
            "error": "permission denied while trying to connect to Docker daemon",
            "containers": [],
            "count": 0,
        }

        result = check_docker_services(verbose=False)

        assert (
            result["success"] == False
        ), "Should return success=False when permission denied"
        assert "error" in result, "Should include error message"
        assert (
            "permission denied" in result["error"].lower()
        ), "Error should mention permission denied"
        print("✓ PASS: Permission denied is handled correctly")
        print(f"  Error: {result['error']}")
        print()


def test_exception_handling():
    """Test exception handling."""
    print("Test 4: Exception handling")

    with patch("execute.get_service_summary") as mock_summary:
        mock_summary.side_effect = Exception("Unexpected error")

        result = check_docker_services(verbose=False)

        assert (
            result["success"] == False
        ), "Should return success=False when exception occurs"
        assert "error" in result, "Should include error message"
        print("✓ PASS: Exception handling works correctly")
        print(f"  Error: {result['error']}")
        print()


def test_determine_overall_status_integration():
    """Test that determine_overall_status correctly handles Docker failure."""
    print("Test 5: Integration with determine_overall_status")

    from execute import determine_overall_status

    # Simulate Docker failure
    services = {
        "success": False,
        "error": "Docker CLI unavailable",
        "total": 0,
        "running": 0,
        "stopped": 0,
        "unhealthy": 0,
        "healthy": 0,
    }

    infrastructure = {
        "kafka": {"status": "connected", "reachable": True},
        "postgres": {"status": "connected"},
        "qdrant": {"status": "connected", "reachable": True},
    }

    status, issues, recommendations = determine_overall_status(services, infrastructure)

    assert status == "critical", "Overall status should be critical when Docker fails"
    assert len(issues) > 0, "Should have at least one issue"

    docker_issues = [i for i in issues if i["component"] == "docker"]
    assert len(docker_issues) > 0, "Should have Docker-related issue"
    assert (
        docker_issues[0]["severity"] == "critical"
    ), "Docker failure should be critical"

    print("✓ PASS: Integration with determine_overall_status works correctly")
    print(f"  Status: {status}")
    print(f"  Issues: {len(issues)}")
    print(f"  Docker issue: {docker_issues[0]['issue']}")
    print()


def main():
    print("=" * 60)
    print("Testing check_docker_services() failure handling")
    print("=" * 60)
    print()

    try:
        # Test 1: Normal operation (uses real Docker)
        test_normal_operation()

        # Tests 2-4: Mock Docker failures
        test_docker_unavailable()
        test_permission_denied()
        test_exception_handling()

        # Test 5: Integration test
        test_determine_overall_status_integration()

        print("=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        return 0

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
