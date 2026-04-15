# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Enforcement test for OMN-8824: zero mcp__linear-server__ calls in any skill file."""

import re
from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent.parent / "plugins" / "onex" / "skills"
PATTERN = re.compile(r"mcp__linear[-_]server__")


def test_no_hardcoded_mcp_linear_in_skill_prompts() -> None:
    """Assert zero mcp__linear[-_]server__ references remain in any skill file.

    DoD gate for OMN-8824. Fails before migration, passes after all 42 files are ported.
    """
    offenders = [
        str(f.relative_to(SKILLS_DIR.parent.parent.parent))
        for f in SKILLS_DIR.rglob("*")
        if f.is_file() and PATTERN.search(f.read_text())
    ]
    assert not offenders, (
        f"mcp__linear-server__ found in {len(offenders)} file(s):\n"
        + "\n".join(f"  {o}" for o in sorted(offenders))
    )
