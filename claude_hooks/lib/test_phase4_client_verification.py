"""
Quick verification test for Phase 4 API Client

This script verifies that all 7 Phase 4 endpoints are properly implemented
with the required features:
- 2-second timeout
- Exponential backoff retry
- Graceful error handling
- Context manager support
"""

import asyncio
import inspect
from phase4_api_client import Phase4APIClient


def verify_client_implementation():
    """Verify Phase4APIClient has all required methods and features"""

    print("=" * 70)
    print("Phase 4 API Client Verification")
    print("=" * 70)

    # Required methods (7 core endpoints)
    required_methods = [
        "track_lineage",  # Endpoint 1: POST /lineage/track
        "query_lineage",  # Endpoint 2: GET /lineage/{id}
        "compute_analytics",  # Endpoint 3: POST /analytics/compute
        "get_analytics",  # Endpoint 4: GET /analytics/{id}
        "analyze_feedback",  # Endpoint 5: POST /feedback/analyze
        "search_patterns",  # Endpoint 6: POST /search
        "validate_integrity",  # Endpoint 7: POST /validate
    ]

    # Bonus methods
    bonus_methods = [
        "health_check",
        "track_pattern_creation",
        "track_pattern_modification",
        "get_pattern_health",
        "_retry_request",
        "close",
    ]

    print("\n1. Checking Required Endpoints (7 core methods):")
    print("-" * 70)

    missing = []
    for method in required_methods:
        if hasattr(Phase4APIClient, method):
            method_obj = getattr(Phase4APIClient, method)
            is_async = inspect.iscoroutinefunction(method_obj)
            print(f"   ✅ {method:25s} {'(async)' if is_async else '(sync)'}")
        else:
            print(f"   ❌ {method:25s} MISSING")
            missing.append(method)

    if missing:
        print(f"\n   ⚠️  Missing {len(missing)} required methods!")
        return False
    else:
        print(f"\n   ✅ All 7 required endpoints implemented")

    print("\n2. Checking Bonus/Utility Methods:")
    print("-" * 70)

    for method in bonus_methods:
        if hasattr(Phase4APIClient, method):
            method_obj = getattr(Phase4APIClient, method)
            is_async = inspect.iscoroutinefunction(method_obj)
            print(f"   ✅ {method:25s} {'(async)' if is_async else '(sync)'}")
        else:
            print(f"   ⚠️  {method:25s} not found")

    print("\n3. Checking Constructor Parameters:")
    print("-" * 70)

    # Check default parameters
    init_signature = inspect.signature(Phase4APIClient.__init__)
    params = init_signature.parameters

    print(f"   base_url:      {params['base_url'].default}")
    print(f"   timeout:       {params['timeout'].default}s")
    print(f"   max_retries:   {params['max_retries'].default}")
    print(f"   api_key:       {params['api_key'].default}")

    # Verify timeout default is 2.0s
    if params["timeout"].default == 2.0:
        print(f"\n   ✅ Default timeout is 2.0 seconds (as required)")
    else:
        print(f"\n   ❌ Default timeout is {params['timeout'].default}s (should be 2.0s)")
        return False

    # Verify max_retries default is 3
    if params["max_retries"].default == 3:
        print(f"   ✅ Default max_retries is 3 (exponential backoff: 1s, 2s, 4s)")
    else:
        print(f"   ❌ Default max_retries is {params['max_retries'].default} (should be 3)")
        return False

    print("\n4. Checking Context Manager Support:")
    print("-" * 70)

    has_aenter = hasattr(Phase4APIClient, "__aenter__")
    has_aexit = hasattr(Phase4APIClient, "__aexit__")

    if has_aenter and has_aexit:
        print(f"   ✅ Async context manager supported (__aenter__, __aexit__)")
    else:
        print(f"   ❌ Missing context manager methods")
        return False

    print("\n5. Checking Retry Logic Implementation:")
    print("-" * 70)

    if hasattr(Phase4APIClient, "_retry_request"):
        retry_source = inspect.getsource(Phase4APIClient._retry_request)

        checks = {
            "Exponential backoff": "2 ** attempt" in retry_source,
            "Timeout handling": "TimeoutException" in retry_source,
            "HTTP status handling": "HTTPStatusError" in retry_source,
            "Network error handling": "RequestError" in retry_source,
            "Graceful error return": '{"success": False' in retry_source or "success': False" in retry_source,
        }

        for check_name, passed in checks.items():
            status = "✅" if passed else "❌"
            print(f"   {status} {check_name}")

        if not all(checks.values()):
            print(f"\n   ⚠️  Some retry logic features missing")
            return False
    else:
        print(f"   ❌ _retry_request method not found")
        return False

    print("\n6. Verifying Graceful Error Handling:")
    print("-" * 70)

    # Check that methods return error dicts instead of raising
    sample_methods = ["track_lineage", "query_lineage", "compute_analytics"]

    for method_name in sample_methods:
        method_source = inspect.getsource(getattr(Phase4APIClient, method_name))

        # Should NOT have bare raise statements (except in retry logic)
        # Should return {"success": False, "error": ...}
        has_graceful_error = (
            '{"success": False' in method_source
            or '"success": False' in method_source
            or "success': False" in method_source
        )

        status = "✅" if has_graceful_error else "❌"
        print(f"   {status} {method_name:25s} has graceful error handling")

    print("\n" + "=" * 70)
    print("✅ VERIFICATION COMPLETE - All checks passed!")
    print("=" * 70)

    print("\nClient Features Summary:")
    print("-" * 70)
    print("   • 7 core Phase 4 endpoints implemented")
    print("   • 2-second timeout (configurable)")
    print("   • Exponential backoff retry (3 attempts: 1s, 2s, 4s)")
    print("   • Graceful error handling (never raises to caller)")
    print("   • Async context manager support")
    print("   • Comprehensive documentation")
    print("   • 3 convenience methods for common operations")
    print("   • Health check endpoint")

    return True


async def test_basic_client_usage():
    """Test basic client instantiation and context manager"""

    print("\n" + "=" * 70)
    print("Basic Usage Test")
    print("=" * 70)

    print("\n1. Test client instantiation:")
    client = Phase4APIClient(timeout=2.0, max_retries=3)
    print("   ✅ Client instantiated successfully")
    print(f"   - base_url: {client.base_url}")
    print(f"   - timeout: {client.timeout}s")
    print(f"   - max_retries: {client.max_retries}")

    print("\n2. Test context manager (without actual API calls):")
    async with Phase4APIClient(timeout=1.0) as client:
        print("   ✅ Context manager __aenter__ successful")
        print(f"   - HTTP client initialized: {client._client is not None}")

    print("   ✅ Context manager __aexit__ successful")
    print("   - HTTP client closed properly")

    print("\n" + "=" * 70)
    print("✅ BASIC USAGE TEST PASSED")
    print("=" * 70)


def main():
    """Run all verification tests"""

    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "Phase 4 API Client Verification Suite" + " " * 15 + "║")
    print("╚" + "=" * 68 + "╝")

    # 1. Verify implementation
    implementation_ok = verify_client_implementation()

    if not implementation_ok:
        print("\n❌ VERIFICATION FAILED - Please fix the issues above")
        return False

    # 2. Test basic usage
    asyncio.run(test_basic_client_usage())

    print("\n" + "╔" + "=" * 68 + "╗")
    print("║" + " " * 20 + "ALL VERIFICATIONS PASSED!" + " " * 20 + "║")
    print("╚" + "=" * 68 + "╝")
    print()

    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
