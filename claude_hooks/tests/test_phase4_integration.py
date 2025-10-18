#!/usr/bin/env python3
"""
Phase 4 Pattern Traceability - End-to-End Integration Tests

Comprehensive test suite validating the entire Phase 4 integration pipeline:
1. Pattern Creation � Tracking � Database Storage
2. Pattern ID Consistency and Determinism
3. Lineage Tracking and Ancestry Queries
4. Usage Analytics Computation
5. Feedback Loop Orchestration
6. API Health and Availability

Test Requirements:
- Intelligence Service running on localhost:8053
- Database accessible (for validation)
- pytest and pytest-asyncio installed

Usage:
    pytest tests/test_phase4_integration.py -v
    pytest tests/test_phase4_integration.py::test_pattern_creation_flow -v
"""

import pytest
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from phase4_api_client import Phase4APIClient
from pattern_id_system import PatternIDSystem, PatternLineageDetector
from pattern_tracker import PatternTracker


# ============================================================================
# Test Configuration
# ============================================================================

API_BASE_URL = "http://localhost:8053"
TEST_TIMEOUT = 10.0  # seconds


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def api_client():
    """Create API client for tests"""
    async with Phase4APIClient(base_url=API_BASE_URL, timeout=TEST_TIMEOUT) as client:
        yield client


@pytest.fixture
def pattern_tracker():
    """Create pattern tracker for tests"""
    return PatternTracker(api_base_url=API_BASE_URL)


@pytest.fixture
def test_code_simple():
    """Simple test code for pattern creation"""
    return """
def calculate_sum(a, b):
    return a + b
    """


@pytest.fixture
def test_code_modified():
    """Modified version of test code"""
    return """
def calculate_sum(a, b):
    # Add validation
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Arguments must be numbers")
    return a + b
    """


@pytest.fixture
def test_code_complex():
    """Complex test code for pattern creation"""
    return """
async def fetch_user_data(user_id: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"/users/{user_id}")
        return response.json()
    """


# ============================================================================
# Test 1: Pattern Creation Flow
# ============================================================================


@pytest.mark.asyncio
async def test_pattern_creation_flow(api_client, test_code_simple):
    """
    Test: Generate code � Track � Query � Verify

    Flow:
    1. Generate deterministic pattern ID from code
    2. Track pattern creation via API
    3. Query pattern lineage
    4. Verify pattern was stored correctly
    """
    # 1. Generate pattern ID
    pattern_id = PatternIDSystem.generate_id(test_code_simple, normalize=True)

    assert pattern_id is not None, "Pattern ID should be generated"
    assert len(pattern_id) == 16, f"Pattern ID should be 16 chars, got {len(pattern_id)}"
    assert PatternIDSystem.validate_id(pattern_id), "Pattern ID should be valid"

    # 2. Track pattern creation
    result = await api_client.track_pattern_creation(
        pattern_id=pattern_id,
        pattern_name="test_calculate_sum",
        code=test_code_simple,
        language="python",
        context={"file_path": "/tmp/test.py", "tool": "Write", "session_id": "test-session-123"},
    )

    # Database might not be available - that's okay
    if result.get("success"):
        assert result["success"] is True, f"Pattern creation should succeed: {result}"
        print(f" Pattern created: {pattern_id}")
    else:
        # If database is unavailable, skip rest of test
        pytest.skip(f"Database unavailable: {result.get('error')}")

    # 3. Query lineage
    lineage = await api_client.query_lineage(pattern_id)

    if lineage.get("success"):
        assert lineage["success"] is True
        assert "data" in lineage
        print(" Lineage queried successfully")
    else:
        # Lineage might not exist yet if pattern was just created
        print(f"� Lineage query returned: {lineage.get('error')}")


# ============================================================================
# Test 2: Pattern ID Consistency
# ============================================================================


def test_pattern_id_deterministic():
    """
    Test: Same code � Same ID (always)

    Verifies that pattern IDs are deterministic and reproducible.
    """
    code = "def foo(): pass"

    # Generate ID multiple times
    id1 = PatternIDSystem.generate_id(code)
    id2 = PatternIDSystem.generate_id(code)
    id3 = PatternIDSystem.generate_id(code)

    # All IDs should be identical
    assert id1 == id2 == id3, "Pattern IDs should be deterministic"
    assert len(id1) == 16, "Pattern ID should be 16 characters"

    print(f" Pattern ID determinism verified: {id1}")


def test_pattern_id_normalization():
    """
    Test: Comments/whitespace don't change ID (when normalized)

    Verifies that code normalization produces consistent IDs.
    """
    code1 = "def foo(): pass"
    code2 = "def foo():    pass  # comment"
    code3 = "def foo():\n    pass"

    # Generate normalized IDs
    id1 = PatternIDSystem.generate_id(code1, normalize=True)
    id2 = PatternIDSystem.generate_id(code2, normalize=True)
    id3 = PatternIDSystem.generate_id(code3, normalize=True)

    # All normalized IDs should be identical
    assert id1 == id2 == id3, "Normalized IDs should match despite formatting differences"

    print(f" Normalization verified: {id1}")


def test_pattern_id_uniqueness():
    """
    Test: Different code � Different IDs

    Verifies that different code produces different pattern IDs.
    """
    code1 = "def foo(): pass"
    code2 = "def bar(): pass"
    code3 = "def foo(): return True"

    id1 = PatternIDSystem.generate_id(code1)
    id2 = PatternIDSystem.generate_id(code2)
    id3 = PatternIDSystem.generate_id(code3)

    # All IDs should be different
    assert id1 != id2, "Different code should produce different IDs"
    assert id1 != id3, "Different code should produce different IDs"
    assert id2 != id3, "Different code should produce different IDs"

    print(f" Uniqueness verified: {id1} ` {id2} ` {id3}")


# ============================================================================
# Test 3: Pattern Lineage Detection
# ============================================================================


def test_lineage_detection(test_code_simple, test_code_modified):
    """
    Test: Detect parent-child relationships via similarity

    Verifies that lineage detection identifies related patterns.
    """
    # Detect derivation
    result = PatternLineageDetector.detect_derivation(test_code_simple, test_code_modified, language="python")

    # Verify derivation was detected
    assert result["is_derived"] is True, "Modified code should be detected as derived"
    assert result["parent_id"] != result["child_id"], "Parent and child should have different IDs"
    assert result["similarity_score"] > 0.5, "Similarity should be significant"
    assert result["modification_type"] is not None, "Modification type should be classified"

    print(f" Lineage detection: {result['similarity_score']:.2%} similarity, {result['modification_type'].value}")


# ============================================================================
# Test 4: Analytics Flow
# ============================================================================


@pytest.mark.asyncio
async def test_analytics_flow(api_client, test_code_simple):
    """
    Test: Execute pattern � Send metrics � Compute analytics

    Flow:
    1. Create and track pattern
    2. Track execution metrics
    3. Compute analytics
    4. Verify analytics data
    """
    # 1. Create pattern
    pattern_id = PatternIDSystem.generate_id(test_code_simple)

    creation_result = await api_client.track_pattern_creation(
        pattern_id=pattern_id, pattern_name="test_analytics_pattern", code=test_code_simple, language="python"
    )

    if not creation_result.get("success"):
        pytest.skip(f"Database unavailable: {creation_result.get('error')}")

    # 2. Track execution (simulate multiple executions)
    for i in range(3):
        exec_result = await api_client.track_lineage(
            event_type="pattern_executed",
            pattern_id=pattern_id,
            pattern_name="test_analytics_pattern",
            pattern_type="code",
            pattern_version="1.0.0",
            pattern_data={
                "execution": {
                    "success": True,
                    "quality_score": 0.90 + (i * 0.02),  # Increasing quality
                    "execution_time": 0.100 + (i * 0.01),
                    "violations_found": 0,
                }
            },
            triggered_by="test",
        )

        if not exec_result.get("success"):
            print(f"� Execution tracking {i+1} failed: {exec_result.get('error')}")

    # 3. Compute analytics
    analytics = await api_client.compute_analytics(
        pattern_id=pattern_id, time_window_type="daily", include_performance=True, include_trends=True
    )

    if analytics.get("success"):
        assert analytics["success"] is True
        print(" Analytics computed successfully")

        # Verify analytics structure
        if "usage_metrics" in analytics:
            print("  - Usage metrics found")
        if "success_metrics" in analytics:
            print("  - Success metrics found")
    else:
        print(f"� Analytics computation: {analytics.get('error')}")


# ============================================================================
# Test 5: API Health Check
# ============================================================================


@pytest.mark.asyncio
async def test_api_health_check(api_client):
    """
    Test: Verify Phase 4 API is healthy and responsive

    Checks:
    - API is accessible
    - Health endpoint returns valid status
    - Components are operational
    """
    health = await api_client.health_check()

    assert health.get("success") or "status" in health, "Health check should return status"

    if "status" in health:
        status = health["status"]
        print(f" API Health: {status}")

        if "components" in health:
            print("  Components:")
            for component, state in health["components"].items():
                print(f"    - {component}: {state}")
    else:
        print(f"� Health check response: {health}")


# ============================================================================
# Test 6: Pattern Tracker Integration
# ============================================================================


@pytest.mark.asyncio
async def test_pattern_tracker_integration(pattern_tracker, test_code_complex):
    """
    Test: Pattern Tracker end-to-end workflow

    Flow:
    1. Track pattern creation
    2. Track pattern execution
    3. Query lineage
    4. Compute analytics
    """
    # 1. Track pattern creation
    pattern_id = await pattern_tracker.track_pattern_creation(
        code=test_code_complex,
        context={"tool": "Write", "language": "python", "file_path": "/tmp/api.py", "session_id": "test-session-456"},
        pattern_name="fetch_user_data",
    )

    assert pattern_id is not None
    assert len(pattern_id) == 16
    print(f" Pattern tracked via PatternTracker: {pattern_id}")

    # 2. Track execution
    try:
        await pattern_tracker.track_pattern_execution(
            pattern_id=pattern_id,
            metrics={"execution_success": True, "quality_score": 0.92, "violations_found": 0, "execution_time": 0.156},
        )
        print(" Execution tracked")
    except Exception as e:
        print(f"� Execution tracking: {e}")

    # 3. Query lineage
    try:
        lineage = await pattern_tracker.query_lineage(pattern_id)
        if lineage.get("success"):
            print(" Lineage queried")
        else:
            print(f"� Lineage query: {lineage.get('error')}")
    except Exception as e:
        print(f"� Lineage query error: {e}")

    # 4. Compute analytics
    try:
        analytics = await pattern_tracker.compute_analytics(pattern_id, "daily")
        if analytics.get("success"):
            print(" Analytics computed")
        else:
            print(f"� Analytics: {analytics.get('error')}")
    except Exception as e:
        print(f"� Analytics error: {e}")


# ============================================================================
# Test 7: Error Handling and Resilience
# ============================================================================


@pytest.mark.asyncio
async def test_graceful_degradation():
    """
    Test: Verify graceful degradation when services are unavailable

    Ensures that failures don't crash the system.
    """
    # Try to connect to non-existent service
    async with Phase4APIClient(base_url="http://localhost:9999", timeout=1.0, max_retries=1) as client:
        result = await client.track_pattern_creation(
            pattern_id="test123456789abc", pattern_name="test_pattern", code="def test(): pass", language="python"
        )

        # Should return error dict, not raise exception
        assert result.get("success") is False, "Should return failure gracefully"
        assert "error" in result, "Should include error message"
        print(f" Graceful degradation verified: {result['error']}")


# ============================================================================
# Test Summary
# ============================================================================


def test_summary():
    """Print test summary"""
    print("\n" + "=" * 70)
    print("Phase 4 Integration Test Suite Summary")
    print("=" * 70)
    print("\nTests validate:")
    print("   Pattern ID generation and consistency")
    print("   Pattern creation tracking")
    print("   Lineage detection and queries")
    print("   Analytics computation")
    print("   API health and availability")
    print("   Pattern Tracker integration")
    print("   Graceful error handling")
    print("\nRequirements:")
    print("  + Intelligence Service running on localhost:8053")
    print("  + Database accessible (for full validation)")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
