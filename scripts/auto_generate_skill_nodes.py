#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pre-commit hook: auto-generate ONEX orchestrator nodes for new skills.

Detects skill directories that have a SKILL.md but no corresponding
orchestrator node under ``src/omniclaude/nodes/`` and runs
``generate_skill_node.py`` to scaffold them automatically.

This prevents the recurring friction of skills being committed without
their ONEX orchestrator node (F57 — fourth occurrence as of OMN-6815).

Usage (pre-commit hook):
    python scripts/auto_generate_skill_nodes.py

Exit codes:
    0 — No missing nodes, or all missing nodes were generated successfully.
    1 — Generation failed for one or more skills.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / "plugins" / "onex" / "skills"
_NODES_DIR = _REPO_ROOT / "src" / "omniclaude" / "nodes"


def _kebab_to_snake(kebab: str) -> str:
    return kebab.replace("-", "_")


def find_skills_missing_nodes() -> list[str]:
    """Return kebab-case names of skills that have SKILL.md but no orchestrator node."""
    if not _SKILLS_DIR.exists():
        return []

    missing: list[str] = []
    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
            continue
        if not (skill_dir / "SKILL.md").exists():
            continue

        snake = _kebab_to_snake(skill_dir.name)
        node_dir = _NODES_DIR / f"node_skill_{snake}_orchestrator"
        if not node_dir.exists():
            missing.append(skill_dir.name)

    return missing


def main() -> int:
    missing = find_skills_missing_nodes()
    if not missing:
        return 0

    print(
        f"[auto-generate-skill-nodes] {len(missing)} skill(s) missing orchestrator nodes:"
    )
    for name in missing:
        print(f"  - {name}")

    # Run generate_skill_node.py for each missing skill
    failed: list[str] = []
    generated: list[str] = []
    for skill_name in missing:
        result = subprocess.run(
            [
                sys.executable,
                str(_REPO_ROOT / "scripts" / "generate_skill_node.py"),
                skill_name,
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"  [ERROR] Failed to generate node for {skill_name!r}:")
            print(f"    {result.stderr.strip()}")
            failed.append(skill_name)
        else:
            generated.append(skill_name)
            # Print generation output
            for line in result.stdout.strip().splitlines():
                print(f"  {line}")

    if generated:
        # Stage the generated files so they're included in the commit
        for skill_name in generated:
            snake = _kebab_to_snake(skill_name)
            node_dir = _NODES_DIR / f"node_skill_{snake}_orchestrator"
            subprocess.run(
                ["git", "add", str(node_dir)],
                cwd=str(_REPO_ROOT),
                capture_output=True,
                check=False,
            )
        print(
            f"\n[auto-generate-skill-nodes] Generated and staged {len(generated)} node(s)."
        )

    if failed:
        print(
            f"\n[auto-generate-skill-nodes] FAILED to generate {len(failed)} node(s).",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
