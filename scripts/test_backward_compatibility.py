#!/usr/bin/env python3
"""
Test Backward Compatibility for Phase 4 Manifest Relevance Features

This script verifies that Phase 4 changes maintain backward compatibility:
- manifest_injector.generate_dynamic_manifest_async() works WITHOUT optional parameters
- Existing code continues to function without modifications
- New features work correctly when explicitly requested

Usage:
    python3 scripts/test_backward_compatibility.py
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path


# Add agents directory to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "agents"))
sys.path.insert(0, str(repo_root))

from lib.manifest_injector import ManifestInjector

from config import settings


async def test_basic_backward_compatibility():
    """Test that basic manifest generation works without optional parameters"""
    print("\n=== Test 1: Basic Backward Compatibility ===")
    print("Testing: generate_dynamic_manifest_async(correlation_id=...)")

    injector = ManifestInjector()

    try:
        manifest = await injector.generate_dynamic_manifest_async(
            correlation_id=str(uuid.uuid4())
        )

        if manifest:
            print("✅ PASS: Basic manifest generation works")
            print(f"   Generated manifest sections: {list(manifest.keys())}")
            return True
        else:
            print("❌ FAIL: Manifest was empty or None")
            return False

    except Exception as e:
        print(f"❌ FAIL: Exception raised: {type(e).__name__}: {e}")
        return False


async def test_optional_user_prompt():
    """Test that user_prompt parameter works"""
    print("\n=== Test 2: Optional user_prompt Parameter ===")
    print(
        "Testing: generate_dynamic_manifest_async(correlation_id=..., user_prompt=...)"
    )

    injector = ManifestInjector()

    try:
        manifest = await injector.generate_dynamic_manifest_async(
            correlation_id=str(uuid.uuid4()),
            user_prompt="Fix PostgreSQL connection error in workflow",
        )

        if manifest:
            print("✅ PASS: user_prompt parameter accepted")
            print(f"   Generated manifest sections: {list(manifest.keys())}")
            return True
        else:
            print("❌ FAIL: Manifest was empty or None")
            return False

    except Exception as e:
        print(f"❌ FAIL: Exception raised: {type(e).__name__}: {e}")
        return False


async def test_optional_force_refresh():
    """Test that force_refresh parameter works"""
    print("\n=== Test 3: Optional force_refresh Parameter ===")
    print(
        "Testing: generate_dynamic_manifest_async(correlation_id=..., force_refresh=True)"
    )

    injector = ManifestInjector()

    try:
        manifest = await injector.generate_dynamic_manifest_async(
            correlation_id=str(uuid.uuid4()), force_refresh=True
        )

        if manifest:
            print("✅ PASS: force_refresh parameter accepted")
            print(f"   Generated manifest sections: {list(manifest.keys())}")
            return True
        else:
            print("❌ FAIL: Manifest was empty or None")
            return False

    except Exception as e:
        print(f"❌ FAIL: Exception raised: {type(e).__name__}: {e}")
        return False


async def test_all_optional_parameters():
    """Test that all optional parameters work together"""
    print("\n=== Test 4: All Optional Parameters Combined ===")
    print(
        "Testing: generate_dynamic_manifest_async(correlation_id=..., user_prompt=..., force_refresh=...)"
    )

    injector = ManifestInjector()

    try:
        manifest = await injector.generate_dynamic_manifest_async(
            correlation_id=str(uuid.uuid4()),
            user_prompt="Create a new database migration for user_sessions table",
            force_refresh=False,
        )

        if manifest:
            print("✅ PASS: All optional parameters work together")
            print(f"   Generated manifest sections: {list(manifest.keys())}")

            # Check if manifest contains expected sections
            checks = [
                ("patterns" in manifest, "Contains patterns section"),
                ("infrastructure" in manifest, "Contains infrastructure section"),
            ]

            for check_result, check_name in checks:
                status = "✅" if check_result else "⚠️"
                print(f"   {status} {check_name}")

            return True
        else:
            print("❌ FAIL: Manifest was empty or None")
            return False

    except Exception as e:
        print(f"❌ FAIL: Exception raised: {type(e).__name__}: {e}")
        return False


async def test_none_optional_parameters():
    """Test that explicitly passing None for optional parameters works"""
    print("\n=== Test 5: Explicit None for Optional Parameters ===")
    print(
        "Testing: generate_dynamic_manifest_async(correlation_id=..., user_prompt=None)"
    )

    injector = ManifestInjector()

    try:
        manifest = await injector.generate_dynamic_manifest_async(
            correlation_id=str(uuid.uuid4()), user_prompt=None
        )

        if manifest:
            print("✅ PASS: Explicit None values accepted")
            print(f"   Generated manifest sections: {list(manifest.keys())}")
            return True
        else:
            print("❌ FAIL: Manifest was empty or None")
            return False

    except Exception as e:
        print(f"❌ FAIL: Exception raised: {type(e).__name__}: {e}")
        return False


async def test_empty_user_prompt():
    """Test that empty user_prompt works"""
    print("\n=== Test 6: Empty user_prompt String ===")
    print(
        'Testing: generate_dynamic_manifest_async(correlation_id=..., user_prompt="")'
    )

    injector = ManifestInjector()

    try:
        manifest = await injector.generate_dynamic_manifest_async(
            correlation_id=str(uuid.uuid4()), user_prompt=""
        )

        if manifest:
            print("✅ PASS: Empty user_prompt accepted")
            print(f"   Generated manifest sections: {list(manifest.keys())}")
            return True
        else:
            print("❌ FAIL: Manifest was empty or None")
            return False

    except Exception as e:
        print(f"❌ FAIL: Exception raised: {type(e).__name__}: {e}")
        return False


async def main():
    """Run all backward compatibility tests"""
    print("=" * 80)
    print("BACKWARD COMPATIBILITY TEST SUITE")
    print("Phase 4: Manifest Task Relevance Implementation")
    print("=" * 80)

    # Check environment
    print("\n=== Environment Check ===")
    kafka_enabled = settings.kafka_enable_intelligence
    print(f"KAFKA_ENABLE_INTELLIGENCE: {kafka_enabled}")

    if not kafka_enabled:
        print("⚠️  WARNING: KAFKA_ENABLE_INTELLIGENCE is disabled")
        print("   Some tests may fall back to filesystem-based intelligence")

    # Run all tests
    tests = [
        ("Basic Backward Compatibility", test_basic_backward_compatibility),
        ("Optional user_prompt", test_optional_user_prompt),
        ("Optional force_refresh", test_optional_force_refresh),
        ("All Optional Parameters", test_all_optional_parameters),
        ("Explicit None Parameters", test_none_optional_parameters),
        ("Empty user_prompt", test_empty_user_prompt),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ CRITICAL ERROR in {test_name}: {type(e).__name__}: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")
    print(f"Success Rate: {100 * passed / total:.1f}%")

    if passed == total:
        print("\n✅ BACKWARD COMPATIBILITY VERIFIED")
        print("   All existing code will continue to work without modifications")
        return 0
    else:
        print("\n❌ BACKWARD COMPATIBILITY BROKEN")
        print(f"   {total - passed} test(s) failed - existing code may break")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
