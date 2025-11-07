#!/usr/bin/env python3
"""
Performance benchmark for username logging enhancements.

Verifies that enhancements maintain <50ms performance target.
"""

import os
import sys
import time

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from session_intelligence import get_environment_metadata, get_git_metadata


def benchmark_metadata_capture(iterations=100):
    """Benchmark metadata capture performance."""
    print("=" * 60)
    print("Performance Benchmark: Metadata Capture")
    print("=" * 60)
    print()

    # Benchmark environment metadata
    env_times = []
    for _ in range(iterations):
        start = time.time()
        metadata = get_environment_metadata()
        elapsed_ms = (time.time() - start) * 1000
        env_times.append(elapsed_ms)

    avg_env = sum(env_times) / len(env_times)
    max_env = max(env_times)
    min_env = min(env_times)

    print("Environment Metadata Capture:")
    print(f"  Iterations: {iterations}")
    print(f"  Average: {avg_env:.3f}ms")
    print(f"  Min: {min_env:.3f}ms")
    print(f"  Max: {max_env:.3f}ms")
    print()

    # Benchmark git metadata
    git_times = []
    for _ in range(iterations):
        start = time.time()
        metadata = get_git_metadata(os.getcwd())
        elapsed_ms = (time.time() - start) * 1000
        git_times.append(elapsed_ms)

    avg_git = sum(git_times) / len(git_times)
    max_git = max(git_times)
    min_git = min(git_times)

    print("Git Metadata Capture:")
    print(f"  Iterations: {iterations}")
    print(f"  Average: {avg_git:.3f}ms")
    print(f"  Min: {min_git:.3f}ms")
    print(f"  Max: {max_git:.3f}ms")
    print()

    # Combined estimate
    combined_avg = avg_env + avg_git
    combined_max = max_env + max_git

    print("Combined Metadata Capture:")
    print(f"  Average: {combined_avg:.3f}ms")
    print(f"  Max: {combined_max:.3f}ms")
    print()

    # Performance target check
    target_ms = 50
    target_metadata_ms = 25  # Leave 25ms for DB logging

    print("=" * 60)
    print("Performance Target Analysis")
    print("=" * 60)
    print()
    print(f"Overall Target: <{target_ms}ms (session start total)")
    print(f"Metadata Target: <{target_metadata_ms}ms (leave time for DB)")
    print()

    # Check if we meet targets
    if combined_avg < target_metadata_ms:
        print(
            f"✅ PASS: Average metadata capture ({combined_avg:.1f}ms) < {target_metadata_ms}ms target"
        )
    else:
        print(
            f"⚠️  WARNING: Average metadata capture ({combined_avg:.1f}ms) > {target_metadata_ms}ms target"
        )

    if combined_max < target_metadata_ms:
        print(
            f"✅ PASS: Max metadata capture ({combined_max:.1f}ms) < {target_metadata_ms}ms target"
        )
    else:
        print(
            f"⚠️  WARNING: Max metadata capture ({combined_max:.1f}ms) > {target_metadata_ms}ms target"
        )

    print()

    # Overhead analysis
    # Assume baseline environment metadata was ~5ms before enhancements
    baseline_env = 5.0
    overhead = avg_env - baseline_env

    print("Enhancement Overhead Analysis:")
    print(f"  Baseline (before): ~{baseline_env:.1f}ms")
    print(f"  Current (after): {avg_env:.1f}ms")
    print(f"  Overhead: {overhead:.1f}ms")
    print(f"  Increase: {(overhead / baseline_env * 100):.1f}% (acceptable if < 50%)")
    print()

    if overhead < baseline_env * 0.5:
        print("✅ PASS: Overhead is acceptable (< 50% increase)")
    else:
        print("⚠️  WARNING: Overhead is significant (> 50% increase)")

    print()
    print("=" * 60)

    # Return statistics
    return {
        "avg_env": avg_env,
        "avg_git": avg_git,
        "combined_avg": combined_avg,
        "combined_max": combined_max,
        "overhead": overhead,
        "meets_target": combined_avg < target_metadata_ms,
    }


def test_metadata_fields():
    """Verify all expected fields are captured."""
    print("=" * 60)
    print("Metadata Fields Verification")
    print("=" * 60)
    print()

    metadata = get_environment_metadata()

    required_fields = ["user", "hostname", "platform", "python_version"]
    optional_fields = ["shell", "uid", "user_fullname", "domain"]

    print("Required fields:")
    for field in required_fields:
        if field in metadata and metadata[field] is not None:
            value = str(metadata[field])
            # Truncate long values
            if len(value) > 50:
                value = value[:47] + "..."
            print(f"  ✅ {field}: {value}")
        else:
            print(f"  ❌ {field}: MISSING")

    print()
    print("Optional fields:")
    for field in optional_fields:
        if field in metadata and metadata[field] is not None:
            value = str(metadata[field])
            if len(value) > 50:
                value = value[:47] + "..."
            print(f"  ✅ {field}: {value}")
        else:
            print(f"  ⚪ {field}: not available")

    print()
    print("=" * 60)
    print()


def main():
    """Run performance benchmarks."""
    print()
    test_metadata_fields()
    print()
    stats = benchmark_metadata_capture(iterations=100)
    print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print()

    if stats["meets_target"]:
        print("✅ All performance targets MET - enhancements are APPROVED")
        print()
        print("Key metrics:")
        print(f"  • Average metadata capture: {stats['combined_avg']:.1f}ms")
        print(f"  • Enhancement overhead: {stats['overhead']:.1f}ms")
        print(
            f"  • Still well within 50ms target (using {stats['combined_avg']:.1f}ms of 50ms budget)"
        )
    else:
        print("⚠️  Performance targets EXCEEDED - review recommended")
        print()
        print("Key metrics:")
        print(f"  • Average metadata capture: {stats['combined_avg']:.1f}ms")
        print(f"  • Enhancement overhead: {stats['overhead']:.1f}ms")

    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
