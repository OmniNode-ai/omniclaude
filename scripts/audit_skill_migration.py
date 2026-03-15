#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Audit skill migration completeness.

Compares plugins/onex/skills/ directories against
src/omniclaude/nodes/node_skill_*/ directories and reports any gaps.

Usage:
    uv run python scripts/audit_skill_migration.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "plugins" / "onex" / "skills"
NODES_DIR = REPO_ROOT / "src" / "omniclaude" / "nodes"

# Directories in skills/ that are not actual skills (internal/shared)
EXCLUDED_PREFIXES = ("_", "__")


def normalize_skill_to_node_name(skill_name: str) -> str:
    """Convert a skill directory name to its expected node directory name.

    Example: 'epic-team' -> 'node_skill_epic_team_orchestrator'
    """
    return f"node_skill_{skill_name.replace('-', '_')}_orchestrator"


def get_skill_names() -> set[str]:
    """Get all skill directory names, excluding internal directories."""
    return {
        d.name
        for d in SKILLS_DIR.iterdir()
        if d.is_dir() and not any(d.name.startswith(p) for p in EXCLUDED_PREFIXES)
    }


def get_node_skill_names() -> set[str]:
    """Get all node skill directory names."""
    return {d.name for d in NODES_DIR.iterdir() if d.name.startswith("node_skill_")}


def main() -> int:
    skills = get_skill_names()
    nodes = get_node_skill_names()

    # Map each skill to its expected node name
    skill_to_node = {s: normalize_skill_to_node_name(s) for s in skills}

    # Find skills without nodes
    missing = {s: n for s, n in skill_to_node.items() if n not in nodes}

    # Find nodes without skills (orphaned nodes)
    expected_nodes = set(skill_to_node.values())
    orphaned = nodes - expected_nodes

    print(f"Skills directory: {SKILLS_DIR}")
    print(f"Nodes directory:  {NODES_DIR}")
    print(f"Total skills:     {len(skills)}")
    print(f"Total nodes:      {len(nodes)}")
    print()

    if missing:
        print(f"Skills WITHOUT nodes ({len(missing)}):")
        for s in sorted(missing):
            print(f"  - {s}  (expected: {missing[s]})")
    else:
        print("All skills have corresponding nodes.")

    if orphaned:
        print(f"\nOrphaned nodes (no matching skill) ({len(orphaned)}):")
        for n in sorted(orphaned):
            print(f"  - {n}")

    print()
    if missing:
        print(f"RESULT: {len(missing)} skill(s) missing nodes. Run:")
        print("  uv run python scripts/generate_skill_node.py --all")
        return 1
    else:
        print(
            "RESULT: 100% coverage. All skills have corresponding node orchestrators."
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
