#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Validate SKILL.md frontmatter for all onex skills.

Validates:
- description, level, debug keys are present
- level is one of: basic, intermediate, advanced
- debug is present and is a boolean (true/false)
- Frontmatter boundary is correct (opening and closing ---)
- name is NOT present (derived from directory name per OMN-5389)

Parses frontmatter correctly: finds the second occurrence of --- (not split('---'))
to avoid mishandling --- inside content.
"""

import sys
from pathlib import Path

VALID_LEVELS = {"basic", "intermediate", "advanced"}

REQUIRED_KEYS = {"description", "level", "debug"}

# name must NOT be in frontmatter — it is derived from the directory name (OMN-5389)
FORBIDDEN_KEYS = {"name"}


def parse_frontmatter(content: str, filepath: Path) -> dict[str, str] | None:
    """Parse YAML frontmatter from content. Returns dict of key:value or None on error."""
    if not content.startswith("---"):
        return None

    # Find the closing --- (must be on its own line after the opening ---)
    lines = content.split("\n")
    if lines[0].strip() != "---":
        return None

    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break

    if close_idx is None:
        return None

    frontmatter_lines = lines[1:close_idx]
    result: dict[str, str] = {}

    for line in frontmatter_lines:
        if ":" not in line:
            continue
        # Handle multi-word values: only split on first colon
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value

    return result


def validate_skill(skill_dir: Path) -> list[str]:
    """Validate a single skill's SKILL.md. Returns list of error messages."""
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.exists():
        errors.append(f"{skill_dir.name}: SKILL.md not found")
        return errors

    content = skill_md.read_text(encoding="utf-8")
    fm = parse_frontmatter(content, skill_md)

    if fm is None:
        errors.append(
            f"{skill_dir.name}: No valid frontmatter (missing opening/closing ---)"
        )
        return errors

    # Check required keys
    for key in REQUIRED_KEYS:
        if key not in fm:
            errors.append(f"{skill_dir.name}: Missing required frontmatter key '{key}'")

    # Check forbidden keys (name is derived from directory, not frontmatter)
    for key in FORBIDDEN_KEYS:
        if key in fm:
            errors.append(
                f"{skill_dir.name}: Forbidden frontmatter key '{key}' — derived from directory name"
            )

    # Validate level
    if "level" in fm:
        level = fm["level"]
        if level not in VALID_LEVELS:
            errors.append(
                f"{skill_dir.name}: Invalid level '{level}' (must be one of: {', '.join(sorted(VALID_LEVELS))})"
            )

    # Validate debug
    if "debug" in fm:
        debug_val = fm["debug"].lower()
        if debug_val not in {"true", "false"}:
            errors.append(
                f"{skill_dir.name}: Invalid debug value '{fm['debug']}' (must be true or false)"
            )

        # debug=true must have level=advanced
        if debug_val == "true" and fm.get("level") != "advanced":
            errors.append(
                f"{skill_dir.name}: debug: true requires level: advanced (got '{fm.get('level', 'missing')}')"
            )

    return errors


def main() -> int:
    skills_root = Path(__file__).parent.parent / "plugins" / "onex" / "skills"

    all_errors: list[str] = []
    validated = 0

    for skill_dir in sorted(skills_root.iterdir()):
        if skill_dir.name.startswith("_"):
            continue
        if not skill_dir.is_dir():
            continue

        errors = validate_skill(skill_dir)
        all_errors.extend(errors)
        validated += 1

    if all_errors:
        print(
            f"FAIL: {len(all_errors)} frontmatter error(s) found across {validated} skills:\n"
        )
        for err in all_errors:
            print(f"  ERROR: {err}")
        return 1
    else:
        print(
            f"OK: All {validated} skills have valid frontmatter (description, level, debug)"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
