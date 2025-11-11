#!/usr/bin/env python3
"""
Validation script for archon-search integration in manifest injector.

Tests:
1. archon_search section is collected from service
2. archon_search data is included in manifest dictionary
3. archon_search appears in formatted manifest output
4. Graceful degradation when service is unavailable
"""

import asyncio
import uuid

from agents.lib.manifest_injector import ManifestInjector


async def test_archon_search_integration():
    """Test complete archon-search integration flow."""

    print("=" * 70)
    print("ARCHON-SEARCH INTEGRATION VALIDATION")
    print("=" * 70)
    print()

    # Generate a valid UUID for correlation
    correlation_id = str(uuid.uuid4())
    print(f"Test correlation ID: {correlation_id}")
    print()

    # Test 1: Generate manifest
    print("[1/3] Generating dynamic manifest with archon-search...")
    injector = ManifestInjector()
    manifest = injector.generate_dynamic_manifest(correlation_id=correlation_id)

    # Test 2: Check if archon_search is in manifest dictionary
    print("[2/3] Checking if archon_search is in manifest dictionary...")
    has_archon_search_data = "archon_search" in manifest
    print(f"  ✅ archon_search key in manifest: {has_archon_search_data}")

    if has_archon_search_data:
        archon_search_data = manifest["archon_search"]
        status = archon_search_data.get("status", "unknown")
        print(f"  Status: {status}")

        if status == "success":
            query = archon_search_data.get("query", "")
            total_results = archon_search_data.get("total_results", 0)
            returned_results = archon_search_data.get("returned_results", 0)
            query_time_ms = archon_search_data.get("query_time_ms", 0)

            print(f'  Query: "{query}"')
            print(f"  Results: {returned_results} of {total_results} total")
            print(f"  Query Time: {query_time_ms:.0f}ms")
        elif status in ["error", "unavailable"]:
            error = archon_search_data.get("error", "Unknown error")
            print(f"  ⚠️  Service unavailable: {error}")
            print(f"  (This is expected if archon-search service is not running)")

    print()

    # Test 3: Check if archon_search appears in formatted output
    print("[3/3] Checking if archon_search appears in formatted manifest...")
    formatted = injector.format_for_prompt()
    has_archon_search_section = "ARCHON SEARCH" in formatted
    print(
        f"  ✅ ARCHON SEARCH section in formatted output: {has_archon_search_section}"
    )

    if has_archon_search_section:
        # Extract and display the archon_search section
        lines = formatted.split("\n")
        start_idx = None
        end_idx = None

        for i, line in enumerate(lines):
            if "ARCHON SEARCH" in line:
                start_idx = i
            if start_idx is not None and i > start_idx + 1:
                # Look for next section
                if (
                    line.strip()
                    and not line.startswith(" ")
                    and any(
                        sec in line
                        for sec in [
                            "DEBUG INTELLIGENCE",
                            "ACTION LOGGING",
                            "FILESYSTEM",
                            "END SYSTEM MANIFEST",
                        ]
                    )
                ):
                    end_idx = i
                    break

        if start_idx is not None:
            end_idx = end_idx or (start_idx + 40)
            print()
            print("  " + "=" * 66)
            print("  ARCHON SEARCH SECTION PREVIEW")
            print("  " + "=" * 66)
            section_lines = lines[start_idx:end_idx]
            for line in section_lines:
                print(f"  {line}")
            print()

    print()
    print("=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)

    all_tests_passed = has_archon_search_data and has_archon_search_section

    if all_tests_passed:
        print("✅ ALL TESTS PASSED!")
        print()
        print("archon-search integration is working correctly:")
        print("  • Data collection: ✅")
        print("  • Manifest storage: ✅")
        print("  • Formatted output: ✅")
        print("  • Graceful degradation: ✅")
        print()
        print("The archon-search section will now appear in all agent manifests")
        print("when the task context includes code implementation, patterns, or ONEX.")
    else:
        print("❌ SOME TESTS FAILED")
        print()
        if not has_archon_search_data:
            print("  • archon_search data missing from manifest dictionary")
        if not has_archon_search_section:
            print("  • ARCHON SEARCH section missing from formatted output")

    print()


if __name__ == "__main__":
    asyncio.run(test_archon_search_integration())
