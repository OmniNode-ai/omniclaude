#!/usr/bin/env python3
"""
Test script for filesystem manifest injection feature.

Tests that the filesystem query is integrated into the manifest system
and produces the expected output format.
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4


# Add lib directory to path
lib_path = Path(__file__).parent
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from manifest_injector import ManifestInjector  # noqa: E402


async def test_filesystem_query():
    """Test filesystem query integration."""
    print("=" * 70)
    print("Testing Filesystem Manifest Injection")
    print("=" * 70)
    print()

    # Create injector with intelligence disabled (for local testing)
    # This will use the filesystem query but not the remote intelligence service
    injector = ManifestInjector(
        enable_intelligence=False,  # Use minimal manifest + filesystem only
        enable_storage=False,  # Don't store to database for testing
        enable_cache=False,  # Don't cache for testing
    )

    # Generate correlation ID
    correlation_id = str(uuid4())

    print(f"Correlation ID: {correlation_id}")
    print()

    # Test async filesystem query directly
    print("Testing direct filesystem query...")
    try:
        from intelligence_event_client import IntelligenceEventClient

        # Create a mock client (not actually used by filesystem query)
        client = IntelligenceEventClient(
            bootstrap_servers="localhost:9092",
            enable_intelligence=False,
        )

        # Query filesystem
        result = await injector._query_filesystem(client, correlation_id)

        print("✅ Filesystem query successful!")
        print(f"   Root: {result.get('root_path')}")
        print(f"   Files: {result.get('total_files', 0)}")
        print(f"   Directories: {result.get('total_directories', 0)}")
        print(f"   Query time: {result.get('query_time_ms', 0)}ms")
        print()

        # Check file types
        file_types = result.get("file_types", {})
        if file_types:
            print("   Top file types:")
            sorted_types = sorted(file_types.items(), key=lambda x: x[1], reverse=True)[
                :5
            ]
            for ext, count in sorted_types:
                print(f"     {ext}: {count} files")
            print()

        # Check ONEX files
        onex_files = result.get("onex_files", {})
        onex_total = sum(len(files) for files in onex_files.values())
        if onex_total > 0:
            print("   ONEX compliance:")
            for node_type, files in onex_files.items():
                if files:
                    print(f"     {node_type.upper()}: {len(files)} files")
            print()

    except Exception as e:
        print(f"❌ Filesystem query failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    # Test formatted output
    print("=" * 70)
    print("Testing formatted manifest output...")
    print("=" * 70)
    print()

    try:
        # Generate manifest (will use minimal manifest + filesystem)
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)

        # Check filesystem section exists
        if "filesystem" not in manifest:
            print("❌ Filesystem section missing from manifest!")
            return False

        print("✅ Filesystem section present in manifest")
        print()

        # Format for display
        formatted = injector.format_for_prompt(sections=["filesystem"])

        # Display formatted output
        print(formatted)
        print()

        # Verify key elements in formatted output
        required_elements = [
            "FILESYSTEM STRUCTURE:",
            "Root:",
            "Total Files:",
            "Total Directories:",
            "DUPLICATE PREVENTION GUIDANCE:",
        ]

        missing_elements = []
        for element in required_elements:
            if element not in formatted:
                missing_elements.append(element)

        if missing_elements:
            print("❌ Missing elements in formatted output:")
            for element in missing_elements:
                print(f"   - {element}")
            return False

        print("✅ All required elements present in formatted output")
        print()

        # Check performance
        query_times = injector._current_query_times
        filesystem_time = query_times.get("filesystem", 0)

        if filesystem_time > 500:
            print(f"⚠️  Filesystem query took {filesystem_time}ms (target: <500ms)")
        else:
            print(
                f"✅ Filesystem query performance good: {filesystem_time}ms (target: <500ms)"
            )
        print()

        return True

    except Exception as e:
        print(f"❌ Manifest generation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print()
    success = await test_filesystem_query()
    print()
    print("=" * 70)
    if success:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 70)
    print()

    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
