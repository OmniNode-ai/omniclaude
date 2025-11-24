#!/usr/bin/env python3
"""
Populate Qdrant with patterns from OmniClaude codebase.

Scans key directories and extracts real patterns from Python files.
"""

import asyncio
import sys
from pathlib import Path


# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agents.lib.patterns.pattern_extractor import PatternExtractor
from agents.lib.patterns.pattern_storage import PatternStorage


def generate_simple_embedding(text: str, dimension: int = 384) -> list[float]:
    """
    Generate a simple hash-based embedding for testing.

    In production, use sentence-transformers or similar.
    """
    import hashlib
    import math

    # Create hash
    hash_obj = hashlib.sha256(text.encode())
    hash_bytes = hash_obj.digest()

    # Convert to floats and normalize
    embedding = []
    for i in range(dimension):
        byte_val = hash_bytes[i % len(hash_bytes)]
        float_val = (byte_val / 127.5) - 1.0
        embedding.append(float_val)

    # Normalize to unit vector
    magnitude = math.sqrt(sum(x * x for x in embedding))
    if magnitude > 0:
        embedding = [x / magnitude for x in embedding]

    return embedding


def find_python_files(directory: Path, max_files: int = 100) -> list[Path]:
    """Find Python files in directory (excluding tests and __pycache__)."""
    python_files = []

    for file in directory.rglob("*.py"):
        # Skip test files, __pycache__, and very large files
        if "__pycache__" in str(file):
            continue
        if file.name.startswith("test_"):
            continue
        if file.stat().st_size > 500_000:  # Skip files > 500KB
            continue

        python_files.append(file)

        if len(python_files) >= max_files:
            break

    return python_files


async def extract_patterns_from_file(
    file_path: Path, extractor: PatternExtractor
) -> tuple[str, list]:
    """Extract patterns from a single Python file."""
    try:
        code = file_path.read_text(encoding="utf-8")

        # Skip empty or very small files
        if len(code) < 100:
            return str(file_path), []

        # Extract patterns
        result = extractor.extract_patterns(
            generated_code=code,
            context={
                "file_path": str(file_path.relative_to(project_root)),
                "directory": file_path.parent.name,
                "framework": "onex",
                "source": "omniclaude_codebase",
            },
        )

        return str(file_path), result.patterns

    except Exception as e:
        print(f"⚠️  Error extracting from {file_path.name}: {e}")
        return str(file_path), []


async def populate_patterns_from_directory(
    directory: Path,
    storage: PatternStorage,
    extractor: PatternExtractor,
    max_files: int = 50,
) -> int:
    """
    Populate patterns from all Python files in a directory.

    Returns:
        Number of patterns stored
    """
    print(f"\n📁 Scanning: {directory.name}/")

    # Find Python files
    python_files = find_python_files(directory, max_files)
    print(f"   Found {len(python_files)} Python files")

    if not python_files:
        return 0

    # Extract patterns from each file
    total_patterns = 0
    stored_patterns = 0

    for file_path in python_files:
        file_name, patterns = await extract_patterns_from_file(file_path, extractor)

        if patterns:
            print(f"   {file_path.name}: {len(patterns)} patterns", end="")

            # Store each pattern
            for pattern in patterns:
                try:
                    # Generate embedding
                    embedding_text = f"{pattern.pattern_name} {pattern.pattern_description} {pattern.pattern_template[:200]}"
                    embedding = generate_simple_embedding(embedding_text)

                    # Store pattern
                    await storage.store_pattern(pattern, embedding)
                    stored_patterns += 1

                except Exception as e:
                    print(f" [ERROR: {e}]", end="")

            print(" ✅")
            total_patterns += len(patterns)

    print(f"   Stored {stored_patterns}/{total_patterns} patterns")
    return stored_patterns


async def main():
    """Populate patterns from OmniClaude codebase."""
    print("\n" + "=" * 70)
    print("POPULATE PATTERNS FROM OMNICLAUDE CODEBASE")
    print("=" * 70)

    # Initialize
    extractor = PatternExtractor(min_confidence=0.5)
    storage = PatternStorage()

    print(f"\n📦 Storage: {storage.qdrant_url}")
    print(f"📊 Collection: {storage.collection_name}")

    # Check if Qdrant is available
    if storage.use_in_memory:
        print("⚠️  WARNING: Using in-memory storage (Qdrant unavailable)")
        print("   Patterns will not persist after this script exits!")
    else:
        print("✅ Connected to Qdrant")

    # Target directories
    directories = [
        project_root / "agents" / "lib" / "patterns",
        project_root / "agents" / "parallel_execution",
        project_root / "agents" / "lib",
        project_root / "agents" / "services",
    ]

    # Populate from each directory
    total_stored = 0

    for directory in directories:
        if not directory.exists():
            print(f"\n⚠️  Directory not found: {directory}")
            continue

        stored = await populate_patterns_from_directory(
            directory, storage, extractor, max_files=30
        )
        total_stored += stored

    # Final stats
    print("\n" + "=" * 70)
    print("POPULATION COMPLETE")
    print("=" * 70)

    stats = await storage.get_storage_stats()
    print(f"\n📈 Final Statistics:")
    for key, value in stats.items():
        print(f"   {key}: {value}")

    # Verify Qdrant
    if not storage.use_in_memory:
        import requests

        try:
            response = requests.get(
                "http://localhost:6333/collections/code_generation_patterns", timeout=5
            )
            data = response.json()
            points = data["result"]["points_count"]

            print(f"\n✅ Qdrant Verification:")
            print(f"   Collection: code_generation_patterns")
            print(f"   Points: {points}")
            print(f"   Status: {data['result']['status']}")

            if points > 0:
                print(f"\n🎉 SUCCESS! Populated {points} patterns to Qdrant")
            else:
                print(
                    f"\n⚠️  WARNING: Collection is empty despite storing {total_stored} patterns"
                )

        except Exception as e:
            print(f"\n❌ Failed to verify Qdrant: {e}")
    else:
        print(f"\n⚠️  Patterns stored in memory only (Qdrant unavailable)")


if __name__ == "__main__":
    asyncio.run(main())
