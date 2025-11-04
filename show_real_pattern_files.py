#!/usr/bin/env python3
"""
Show real file paths from actual patterns in Qdrant.
"""

import asyncio
import os
import sys
from pathlib import Path


# Add agents to path
sys.path.insert(0, str(Path(__file__).parent / "agents"))

from lib.manifest_injector import ManifestInjector
from lib.task_classifier import TaskClassifier


async def show_real_file_paths():
    """Show actual file paths from Qdrant patterns"""

    print("=" * 100)
    print("REAL PATTERN FILE PATHS FROM QDRANT")
    print("=" * 100)
    print()

    # Query for orchestrator-related patterns
    user_prompt = (
        "Create an orchestrator node to orchestrate our node generation pipeline"
    )

    classifier = TaskClassifier()
    task_context = classifier.classify(user_prompt)

    print(f"📝 User Prompt: {user_prompt}")
    print()

    # Query patterns
    injector = ManifestInjector()

    import uuid

    correlation_id = str(uuid.uuid4())

    print("🔍 Querying archon_vectors collection...")
    result = await injector._query_patterns_direct_qdrant(
        correlation_id=correlation_id,
        collections=["archon_vectors"],
        limit_per_collection=50,
        task_context=task_context,
        user_prompt=user_prompt,
    )

    patterns = result.get("patterns", [])
    print(f"✅ Retrieved {len(patterns)} patterns")
    print()

    # Extract and display file paths
    print("=" * 100)
    print("FILE PATHS IN PATTERNS")
    print("=" * 100)
    print()

    patterns_with_files = []
    patterns_without_files = []

    for pattern in patterns:
        name = pattern.get("name", "Unknown")
        file_path = pattern.get("file_path", "")

        if file_path:
            patterns_with_files.append((name, file_path))
        else:
            patterns_without_files.append(name)

    print(f"Patterns with file paths: {len(patterns_with_files)}/{len(patterns)}")
    print(f"Patterns without file paths: {len(patterns_without_files)}/{len(patterns)}")
    print()

    if patterns_with_files:
        print("=" * 100)
        print("PATTERNS WITH FILE PATHS")
        print("=" * 100)
        print()

        for i, (name, file_path) in enumerate(patterns_with_files[:20], 1):
            print(f"{i:2}. {name}")
            print(f"    File: {file_path}")

            # Show if file exists
            full_path = Path(file_path)
            if full_path.exists():
                print("    ✅ File exists")
            else:
                # Try relative to different base paths
                for base in [
                    "/Volumes/PRO-G40/Code/omniarchon",
                    "/Volumes/PRO-G40/Code/omniclaude",
                    "/Volumes/PRO-G40/Code/omninode_bridge",
                ]:
                    test_path = Path(base) / file_path
                    if test_path.exists():
                        print(f"    ✅ File exists at: {test_path}")
                        break
                else:
                    print("    ⚠️  File not found locally")
            print()

    if patterns_without_files:
        print("=" * 100)
        print("PATTERNS WITHOUT FILE PATHS (showing first 10)")
        print("=" * 100)
        print()

        for i, name in enumerate(patterns_without_files[:10], 1):
            print(f"{i:2}. {name}")

        if len(patterns_without_files) > 10:
            print(f"    ... and {len(patterns_without_files) - 10} more")

    # Show pattern structure
    if patterns:
        print()
        print("=" * 100)
        print("SAMPLE PATTERN STRUCTURE (First Pattern)")
        print("=" * 100)
        print()

        sample = patterns[0]
        print(f"Pattern: {sample.get('name', 'Unknown')}")
        print()
        print("Available fields:")
        for key, value in sample.items():
            if isinstance(value, (str, int, float)):
                print(f"  • {key}: {value}")
            elif isinstance(value, list):
                print(f"  • {key}: [{len(value)} items]")
            elif isinstance(value, dict):
                print(f"  • {key}: {{{len(value)} keys}}")
        print()

        # Show source_context if available
        source_context = sample.get("source_context", {})
        if source_context:
            print("source_context fields:")
            for key, value in source_context.items():
                print(f"  • {key}: {value}")


if __name__ == "__main__":
    import sys

    # Verify POSTGRES_PASSWORD is set
    if not os.environ.get("POSTGRES_PASSWORD"):
        print("❌ ERROR: POSTGRES_PASSWORD environment variable not set")
        print("   Please run: source .env")
        sys.exit(1)

    asyncio.run(show_real_file_paths())
