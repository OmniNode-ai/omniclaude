#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Display manifest with detailed content from each section.
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.lib.manifest_injector import ManifestInjector


def print_json_preview(data: Any, max_chars: int = 1000, indent: int = 2):
    """Print a JSON preview with character limit."""
    try:
        json_str = json.dumps(data, indent=indent, default=str)
        if len(json_str) <= max_chars:
            print(json_str)
        else:
            print(json_str[:max_chars])
            remaining = len(json_str) - max_chars
            print(f"\n... ({remaining:,} more characters)")
    except Exception as e:
        print(f"<Error formatting: {e}>")


async def main():
    """Generate and display manifest with details."""
    print("=" * 80)
    print("DETAILED MANIFEST VIEW")
    print("=" * 80)
    print()

    # Generate manifest
    injector = ManifestInjector()
    correlation_id = str(uuid.uuid4())
    prompt = "ONEX authentication system"

    manifest = await injector.generate_dynamic_manifest_async(
        correlation_id=correlation_id,
        user_prompt=prompt,
        force_refresh=True,
    )

    # Show each section in detail
    for section_name, section_data in manifest.items():
        print("=" * 80)
        print(f"SECTION: {section_name}")
        print("=" * 80)
        print()

        if isinstance(section_data, dict):
            # Show dict structure
            print(f"Type: Dictionary with {len(section_data)} keys")
            print(f"Keys: {list(section_data.keys())}")
            print()

            # Show subsections
            for key, value in section_data.items():
                print("-" * 80)
                print(f"  {key}:")
                print("-" * 80)

                if isinstance(value, list):
                    print(f"    Type: List with {len(value)} items")
                    if value:
                        print(f"    First item type: {type(value[0]).__name__}")
                        print()
                        print("    First item preview:")
                        print_json_preview(value[0], max_chars=800, indent=6)
                    else:
                        print("    (empty list)")
                elif isinstance(value, dict):
                    print(f"    Type: Dictionary with {len(value)} keys")
                    print(f"    Keys: {list(value.keys())}")
                    print()
                    print("    Content preview:")
                    print_json_preview(value, max_chars=800, indent=6)
                else:
                    print(f"    Type: {type(value).__name__}")
                    print(f"    Value: {value}")
                print()

        elif isinstance(section_data, list):
            print(f"Type: List with {len(section_data)} items")
            if section_data:
                print(f"First item type: {type(section_data[0]).__name__}")
                print()
                print("First item preview:")
                print_json_preview(section_data[0], max_chars=800, indent=2)
        else:
            print(f"Type: {type(section_data).__name__}")
            print(f"Value: {section_data}")

        print()

    print("=" * 80)
    print("END OF MANIFEST")
    print("=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
