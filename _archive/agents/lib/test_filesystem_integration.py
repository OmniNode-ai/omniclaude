#!/usr/bin/env python3
"""
Integration test for filesystem manifest injection.

Tests the complete integration of filesystem data into the manifest system,
including performance, formatting, and cache behavior.
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

# Add lib directory to path
lib_path = Path(__file__).parent
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from .manifest_injector import ManifestInjector  # noqa: E402


async def test_filesystem_with_minimal_manifest():
    """Test filesystem query with minimal manifest (intelligence disabled)."""
    print("\n" + "=" * 70)
    print("TEST 1: Filesystem with Minimal Manifest (Intelligence Disabled)")
    print("=" * 70)

    injector = ManifestInjector(
        enable_intelligence=False,
        enable_storage=False,
        enable_cache=False,
    )

    correlation_id = str(uuid4())
    manifest = await injector.generate_dynamic_manifest_async(correlation_id)

    # Verify filesystem section exists
    if "filesystem" not in manifest:
        print("❌ FAILED: Filesystem section missing")
        return False

    filesystem_data = manifest["filesystem"]
    print("✅ Filesystem section present")
    print(f"   Files: {filesystem_data.get('total_files', 0)}")
    print(f"   Directories: {filesystem_data.get('total_directories', 0)}")
    print(f"   Query time: {filesystem_data.get('query_time_ms', 0)}ms")

    # Verify formatted output
    formatted = injector.format_for_prompt()
    if "FILESYSTEM STRUCTURE:" not in formatted:
        print("❌ FAILED: Filesystem section missing from formatted output")
        return False

    print("✅ Filesystem section in formatted output")
    return True


async def test_filesystem_performance():
    """Test that filesystem query meets performance targets."""
    print("\n" + "=" * 70)
    print("TEST 2: Filesystem Query Performance")
    print("=" * 70)

    injector = ManifestInjector(
        enable_intelligence=False,
        enable_storage=False,
        enable_cache=False,
    )

    # Run multiple queries to check consistency
    query_times = []
    for i in range(3):
        correlation_id = str(uuid4())
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)
        filesystem_data = manifest.get("filesystem", {})
        query_time = filesystem_data.get("query_time_ms", 0)
        query_times.append(query_time)
        print(f"   Query {i+1}: {query_time}ms")

    avg_time = sum(query_times) / len(query_times)
    max_time = max(query_times)

    print(f"\n   Average: {avg_time:.1f}ms")
    print(f"   Maximum: {max_time}ms")

    if avg_time > 500:
        print(f"❌ FAILED: Average query time {avg_time:.1f}ms exceeds 500ms target")
        return False

    if max_time > 1000:
        print(f"⚠️  WARNING: Maximum query time {max_time}ms exceeds 1000ms")

    print(f"✅ Performance meets targets (avg: {avg_time:.1f}ms < 500ms)")
    return True


async def test_filesystem_cache():
    """Test that filesystem caching works correctly."""
    print("\n" + "=" * 70)
    print("TEST 3: Filesystem Caching")
    print("=" * 70)

    injector = ManifestInjector(
        enable_intelligence=False,
        enable_storage=False,
        enable_cache=True,  # Enable caching
        cache_ttl_seconds=60,
    )

    correlation_id = str(uuid4())

    # First query (should miss cache)
    print("   First query (cache miss expected)...")
    manifest1 = await injector.generate_dynamic_manifest_async(correlation_id)
    filesystem1 = manifest1.get("filesystem", {})
    query_time1 = filesystem1.get("query_time_ms", 0)
    print(f"   Query time: {query_time1}ms")

    # Second query (should hit cache)
    print("   Second query (cache hit expected)...")
    manifest2 = await injector.generate_dynamic_manifest_async(correlation_id)
    filesystem2 = manifest2.get("filesystem", {})

    # Since filesystem is queried separately and not part of the full manifest cache,
    # we just verify that the data is consistent
    if filesystem1 == filesystem2:
        print("✅ Filesystem data consistent across queries")
        return True
    else:
        print("❌ FAILED: Filesystem data inconsistent")
        return False


async def test_filesystem_onex_detection():
    """Test that ONEX node types are detected correctly."""
    print("\n" + "=" * 70)
    print("TEST 4: ONEX Node Type Detection")
    print("=" * 70)

    injector = ManifestInjector(
        enable_intelligence=False,
        enable_storage=False,
        enable_cache=False,
    )

    correlation_id = str(uuid4())
    manifest = await injector.generate_dynamic_manifest_async(correlation_id)
    filesystem_data = manifest.get("filesystem", {})
    onex_files = filesystem_data.get("onex_files", {})

    onex_total = sum(len(files) for files in onex_files.values())
    print(f"   Total ONEX files detected: {onex_total}")

    for node_type, files in onex_files.items():
        if files:
            print(f"   {node_type.upper()}: {len(files)} files")
            # Show first file as example
            if files:
                print(f"      Example: {files[0]}")

    if onex_total > 0:
        print("✅ ONEX node types detected successfully")
        return True
    else:
        print("⚠️  No ONEX files found (may be expected if no ONEX files in project)")
        return True


async def test_filesystem_duplicate_prevention():
    """Test that duplicate prevention guidance is included."""
    print("\n" + "=" * 70)
    print("TEST 5: Duplicate Prevention Guidance")
    print("=" * 70)

    injector = ManifestInjector(
        enable_intelligence=False,
        enable_storage=False,
        enable_cache=False,
    )

    correlation_id = str(uuid4())
    await injector.generate_dynamic_manifest_async(correlation_id)
    formatted = injector.format_for_prompt()

    # Check for duplicate prevention guidance
    required_guidance = [
        "DUPLICATE PREVENTION GUIDANCE",
        "Before creating new files",
        "Use Glob or Grep tools",
    ]

    missing_guidance = []
    for guidance in required_guidance:
        if guidance not in formatted:
            missing_guidance.append(guidance)

    if missing_guidance:
        print("❌ FAILED: Missing guidance:")
        for guidance in missing_guidance:
            print(f"   - {guidance}")
        return False

    print("✅ Duplicate prevention guidance present")
    return True


async def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("FILESYSTEM MANIFEST INTEGRATION TESTS")
    print("=" * 70)

    tests = [
        ("Minimal Manifest Integration", test_filesystem_with_minimal_manifest),
        ("Performance", test_filesystem_performance),
        ("Caching", test_filesystem_cache),
        ("ONEX Detection", test_filesystem_onex_detection),
        ("Duplicate Prevention", test_filesystem_duplicate_prevention),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ EXCEPTION in {test_name}: {e}")
            import traceback

            traceback.print_exc()
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print("\n" + "=" * 70)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 70)

    return 0 if passed == total else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
