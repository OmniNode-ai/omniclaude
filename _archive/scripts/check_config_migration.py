#!/usr/bin/env python3
"""
Check Configuration Migration Progress

Tracks progress of migrating from os.getenv() to config.settings framework.
Run this weekly to monitor migration status.

Usage:
    python3 scripts/check_config_migration.py
    python3 scripts/check_config_migration.py --verbose
    python3 scripts/check_config_migration.py --priority P0
"""

import re
import sys
from collections import defaultdict
from pathlib import Path


def get_priority(filepath: str) -> str:
    """Determine priority level based on file path."""
    if "agents/services/" in filepath:
        return "P0"
    elif "agents/lib/" in filepath or "services/routing_adapter/" in filepath:
        return "P1"
    elif "test" in filepath.lower() or "agents/tests/" in filepath:
        return "P2"
    else:
        return "P3"


def check_file_patterns(filepath: Path) -> tuple[bool, bool, bool, int, int]:
    """
    Check what configuration patterns a file uses.

    Returns:
        (has_settings, has_getenv, has_environ, getenv_count, environ_count)
    """
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()

        has_settings = "from config import settings" in content
        has_getenv = bool(re.search(r"os\.getenv", content))
        has_environ = bool(re.search(r"os\.environ\[", content))
        getenv_count = len(re.findall(r"os\.getenv", content))
        environ_count = len(re.findall(r"os\.environ\[", content))

        return has_settings, has_getenv, has_environ, getenv_count, environ_count
    except Exception:
        return False, False, False, 0, 0


def main():
    """Run migration audit."""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    priority_filter = None

    for arg in sys.argv[1:]:
        if arg.startswith("--priority="):
            priority_filter = arg.split("=")[1].upper()
        elif arg in ["P0", "P1", "P2", "P3"]:
            priority_filter = arg

    # Find all Python files
    # Use project root dynamically (scripts/ is in project root)
    root = Path(__file__).parent.parent.resolve()
    py_files = list(root.rglob("*.py"))

    # Categorize files
    migrated = []
    mixed = []
    needs_migration = []
    clean = []

    # Track by priority
    priority_stats = defaultdict(
        lambda: {
            "migrated": 0,
            "mixed": 0,
            "needs_migration": 0,
            "getenv_calls": 0,
            "environ_calls": 0,
            "files": [],
        }
    )

    for py_file in py_files:
        filepath = str(py_file.relative_to(root))
        has_settings, has_getenv, has_environ, getenv_count, environ_count = (
            check_file_patterns(py_file)
        )

        has_old = has_getenv or has_environ
        priority = get_priority(filepath)

        # Skip if filtering by priority
        if priority_filter and priority != priority_filter:
            continue

        if has_settings and has_old:
            mixed.append(filepath)
            priority_stats[priority]["mixed"] += 1
            priority_stats[priority]["files"].append(("MIXED", filepath, getenv_count))
        elif has_settings and not has_old:
            migrated.append(filepath)
            priority_stats[priority]["migrated"] += 1
            if verbose:
                priority_stats[priority]["files"].append(("MIGRATED", filepath, 0))
        elif not has_settings and has_old:
            needs_migration.append(filepath)
            priority_stats[priority]["needs_migration"] += 1
            priority_stats[priority]["getenv_calls"] += getenv_count
            priority_stats[priority]["environ_calls"] += environ_count
            priority_stats[priority]["files"].append(
                ("NEEDS_MIGRATION", filepath, getenv_count)
            )
        else:
            clean.append(filepath)

    # Calculate totals
    total_relevant = len(migrated) + len(mixed) + len(needs_migration)
    migrated_percent = (
        (len(migrated) * 100 / total_relevant) if total_relevant > 0 else 0
    )

    total_getenv = sum(p["getenv_calls"] for p in priority_stats.values())
    total_environ = sum(p["environ_calls"] for p in priority_stats.values())

    # Print summary
    print("=" * 80)
    print("CONFIG SETTINGS MIGRATION PROGRESS")
    print("=" * 80)
    print()
    print(f"Total Python files: {len(py_files):,}")
    print(f"Files with config patterns: {total_relevant:,}")
    print()
    print(f"✅ Migrated (settings only): {len(migrated):,} ({migrated_percent:.1f}%)")
    print(f"⚠️  Mixed (both patterns): {len(mixed):,}")
    print(f"❌ Needs Migration: {len(needs_migration):,}")
    print(f"✓  Clean: {len(clean):,}")
    print()
    print(f"Total os.getenv() calls remaining: {total_getenv:,}")
    print(f"Total os.environ[] calls remaining: {total_environ:,}")
    print(f"Total legacy calls: {total_getenv + total_environ:,}")
    print()

    # Print by priority
    print("=" * 80)
    print("BREAKDOWN BY PRIORITY")
    print("=" * 80)
    print()

    priority_order = ["P0", "P1", "P2", "P3"]
    priority_labels = {
        "P0": "🔴 P0 - Critical Services",
        "P1": "🟠 P1 - Core Libraries",
        "P2": "🟡 P2 - Tests",
        "P3": "🟢 P3 - Scripts/Hooks",
    }

    for priority in priority_order:
        if priority not in priority_stats:
            continue

        stats = priority_stats[priority]
        total = stats["migrated"] + stats["mixed"] + stats["needs_migration"]

        if total == 0:
            continue

        percent = (stats["migrated"] * 100 / total) if total > 0 else 0

        print(f"{priority_labels[priority]}")
        print(f"  Progress: {percent:.1f}% ({stats['migrated']}/{total} files)")
        print(f"  ✅ Migrated: {stats['migrated']} files")
        print(f"  ⚠️  Mixed: {stats['mixed']} files")
        print(f"  ❌ Needs Migration: {stats['needs_migration']} files")
        print(
            f"  Legacy Calls: {stats['getenv_calls']} os.getenv() + {stats['environ_calls']} os.environ[]"
        )
        print()

        # Show files if verbose or if filtered by priority
        if verbose or priority_filter:
            if stats["files"]:
                # Sort by getenv count (descending)
                sorted_files = sorted(stats["files"], key=lambda x: x[2], reverse=True)

                # Show top 10 or all if less
                max_show = 10 if not priority_filter else len(sorted_files)
                for status, filepath, count in sorted_files[:max_show]:
                    if status == "NEEDS_MIGRATION":
                        print(f"    ❌ {filepath}: {count} calls")
                    elif status == "MIXED":
                        print(f"    ⚠️  {filepath}: {count} calls (mixed)")
                    elif status == "MIGRATED" and verbose:
                        print(f"    ✅ {filepath}")

                if len(sorted_files) > max_show:
                    print(f"    ... and {len(sorted_files) - max_show} more")
                print()

    # Print critical files
    print("=" * 80)
    print("🎯 IMMEDIATE ACTION REQUIRED (P0)")
    print("=" * 80)
    print()

    critical_files = [
        "agents/services/agent_router_event_service.py",
        "agents/lib/routing_event_client.py",
    ]

    for filepath in critical_files:
        full_path = root / filepath
        if full_path.exists():
            has_settings, has_getenv, has_environ, getenv_count, environ_count = (
                check_file_patterns(full_path)
            )

            if has_settings and not (has_getenv or has_environ):
                status = "✅ MIGRATED"
            elif has_settings and (has_getenv or has_environ):
                status = f"⚠️  MIXED ({getenv_count} os.getenv calls)"
            elif has_getenv or has_environ:
                status = f"❌ NOT MIGRATED ({getenv_count} os.getenv calls)"
            else:
                status = "✓  CLEAN"

            print(f"  {filepath}")
            print(f"    {status}")
        else:
            print(f"  {filepath}")
            print("    ❓ FILE NOT FOUND")
        print()

    # Print next steps
    print("=" * 80)
    print("📋 NEXT STEPS")
    print("=" * 80)
    print()

    p0_needs_migration = (
        priority_stats["P0"]["needs_migration"] + priority_stats["P0"]["mixed"]
    )
    p1_needs_migration = (
        priority_stats["P1"]["needs_migration"] + priority_stats["P1"]["mixed"]
    )

    if p0_needs_migration > 0:
        print(
            f"🔴 IMMEDIATE: Migrate {p0_needs_migration} P0 files (critical services)"
        )
        print("   Command: python3 scripts/check_config_migration.py --priority=P0")
    elif p1_needs_migration > 0:
        print(
            f"🟠 HIGH PRIORITY: Migrate {p1_needs_migration} P1 files (core libraries)"
        )
        print("   Command: python3 scripts/check_config_migration.py --priority=P1")
    else:
        print("✅ All critical and high-priority files migrated!")
        print("   Continue with P2 (tests) and P3 (scripts) as time permits")

    print()
    print("Full audit report: CONFIG_MIGRATION_AUDIT.md")
    print()

    # Exit code
    if p0_needs_migration > 0:
        sys.exit(1)  # Critical files need migration
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
