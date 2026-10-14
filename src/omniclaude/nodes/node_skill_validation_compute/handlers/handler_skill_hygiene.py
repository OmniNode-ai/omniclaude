# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Skill hygiene checks ported from onex_change_control."""

from __future__ import annotations

from pathlib import Path

from omniclaude.nodes.node_skill_validation_compute.enums import (
    EnumSkillViolationSeverity,
)
from omniclaude.nodes.node_skill_validation_compute.models import (
    ModelSkillValidationReport,
    ModelSkillValidationRequest,
    ModelSkillViolation,
)

SEVERITY_ERROR = EnumSkillViolationSeverity.ERROR
SEVERITY_WARNING = EnumSkillViolationSeverity.WARNING

CHECK_UNDERSCORE_NAMES = "underscore-names"
CHECK_NO_DUPLICATE_NAMES = "no-duplicate-names"
CHECK_NO_UNINDEXED_NESTING = "no-unindexed-nesting"
CHECK_SKILL_MD_REQUIRED = "skill-md-required"
CHECK_NAME_MATCHES_DIR = "name-matches-dir"
CHECK_NO_PYTHON_IN_SKILLS = "no-python-in-skills"
CHECK_NO_ORPHAN_TOPICS = "no-orphan-topics"

# Checks that are WARNING in migration mode, ERROR in --strict mode
STRICT_PROMOTED_CHECKS = {CHECK_SKILL_MD_REQUIRED, CHECK_NAME_MATCHES_DIR}


def is_infrastructure_dir(name: str) -> bool:
    """Return True if the directory name indicates an infrastructure dir."""
    return name.startswith("_")


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def parse_skill_md_frontmatter(skill_md_path: Path) -> dict[str, str]:
    """Parse YAML frontmatter from a SKILL.md file."""
    result: dict[str, str] = {}
    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except OSError:
        return result

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return result

    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            # Handle simple values only (not arrays/objects)
            if key and not value.startswith("[") and not value.startswith("{"):
                result[key] = value
            elif key and value.startswith("["):
                # Store array values as-is for completeness
                result[key] = value

    return result


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------


def check_underscore_names(
    skills_root: Path, strict: bool
) -> list[ModelSkillViolation]:
    """Check #1: Skill dir names must use underscores, not dashes."""
    violations: list[ModelSkillViolation] = []

    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir() or is_infrastructure_dir(entry.name):
            continue
        if "-" in entry.name:
            violations.append(
                ModelSkillViolation(
                    path=entry.name,
                    check=CHECK_UNDERSCORE_NAMES,
                    severity=SEVERITY_ERROR,
                    message=f"Skill directory uses dashes: '{entry.name}' — rename to '{entry.name.replace('-', '_')}'",
                )
            )
        # Also check nested child dirs
        for child in sorted(entry.iterdir()):
            if not child.is_dir() or is_infrastructure_dir(child.name):
                continue
            if "-" in child.name:
                violations.append(
                    ModelSkillViolation(
                        path=f"{entry.name}/{child.name}",
                        check=CHECK_UNDERSCORE_NAMES,
                        severity=SEVERITY_ERROR,
                        message=f"Nested skill directory uses dashes: '{child.name}' — rename to '{child.name.replace('-', '_')}'",
                    )
                )

    return violations


def check_no_duplicate_names(
    skills_root: Path, strict: bool
) -> list[ModelSkillViolation]:
    """Check #2: No two dirs normalize to the same name after - → _ ."""
    violations: list[ModelSkillViolation] = []

    names: dict[str, list[str]] = {}
    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir() or is_infrastructure_dir(entry.name):
            continue
        normalized = entry.name.replace("-", "_")
        names.setdefault(normalized, []).append(entry.name)

    for normalized, originals in sorted(names.items()):
        if len(originals) > 1:
            violations.append(
                ModelSkillViolation(
                    path=", ".join(originals),
                    check=CHECK_NO_DUPLICATE_NAMES,
                    severity=SEVERITY_ERROR,
                    message=f"Directories normalize to same name '{normalized}': {originals}",
                )
            )

    return violations


def check_no_unindexed_nesting(
    skills_root: Path, strict: bool
) -> list[ModelSkillViolation]:
    """Check #3: Parent with SKILL.md + child dirs with SKILL.md must have index: true."""
    violations: list[ModelSkillViolation] = []

    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir() or is_infrastructure_dir(entry.name):
            continue

        parent_skill_md = entry / "SKILL.md"
        if not parent_skill_md.exists():
            continue

        # Check if any child dirs have SKILL.md
        has_child_skills = False
        for child in sorted(entry.iterdir()):
            if child.is_dir() and not is_infrastructure_dir(child.name):
                if (child / "SKILL.md").exists():
                    has_child_skills = True
                    break

        if not has_child_skills:
            continue

        # Parent has SKILL.md and children have SKILL.md — check for index: true
        frontmatter = parse_skill_md_frontmatter(parent_skill_md)
        index_val = frontmatter.get("index", "").lower()
        if index_val != "true":
            violations.append(
                ModelSkillViolation(
                    path=entry.name,
                    check=CHECK_NO_UNINDEXED_NESTING,
                    severity=SEVERITY_ERROR,
                    message=f"Parent dir '{entry.name}' has SKILL.md with child skill dirs but missing 'index: true' in frontmatter",
                )
            )

    return violations


def _collect_skill_dirs(skills_root: Path) -> list[tuple[Path, str]]:
    """Collect all non-infrastructure dirs that should be skill dirs."""
    result: list[tuple[Path, str]] = []
    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir() or is_infrastructure_dir(entry.name):
            continue

        # Check if this is an index parent (has child skill dirs)
        has_child_skills = False
        for child in sorted(entry.iterdir()):
            if child.is_dir() and not is_infrastructure_dir(child.name):
                if (child / "SKILL.md").exists():
                    has_child_skills = True
                    # Add child as a skill dir
                    result.append((child, f"{entry.name}/{child.name}"))

        if not has_child_skills:
            # Leaf skill dir
            result.append((entry, entry.name))
        # else: index parent — not itself a skill to validate for SKILL.md requirement

    return result


def check_skill_md_required(
    skills_root: Path, strict: bool
) -> list[ModelSkillViolation]:
    """Check #4: Every non-index skill dir must have SKILL.md."""
    violations: list[ModelSkillViolation] = []
    severity = SEVERITY_ERROR if strict else SEVERITY_WARNING

    for dir_path, display_name in _collect_skill_dirs(skills_root):
        if not (dir_path / "SKILL.md").exists():
            violations.append(
                ModelSkillViolation(
                    path=display_name,
                    check=CHECK_SKILL_MD_REQUIRED,
                    severity=severity,
                    message=f"Skill directory '{display_name}' is missing SKILL.md",
                )
            )

    return violations


def check_name_matches_dir(
    skills_root: Path, strict: bool
) -> list[ModelSkillViolation]:
    """Check #5: SKILL.md name: frontmatter must match directory name."""
    violations: list[ModelSkillViolation] = []
    severity = SEVERITY_ERROR if strict else SEVERITY_WARNING

    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir() or is_infrastructure_dir(entry.name):
            continue

        skill_md = entry / "SKILL.md"
        if skill_md.exists():
            frontmatter = parse_skill_md_frontmatter(skill_md)
            name = frontmatter.get("name", "")
            if name and name != entry.name:
                violations.append(
                    ModelSkillViolation(
                        path=entry.name,
                        check=CHECK_NAME_MATCHES_DIR,
                        severity=severity,
                        message=f"SKILL.md name: '{name}' does not match directory name '{entry.name}'",
                    )
                )

        # Check nested children too
        for child in sorted(entry.iterdir()):
            if not child.is_dir() or is_infrastructure_dir(child.name):
                continue
            child_skill_md = child / "SKILL.md"
            if child_skill_md.exists():
                frontmatter = parse_skill_md_frontmatter(child_skill_md)
                name = frontmatter.get("name", "")
                if name and name != child.name:
                    violations.append(
                        ModelSkillViolation(
                            path=f"{entry.name}/{child.name}",
                            check=CHECK_NAME_MATCHES_DIR,
                            severity=severity,
                            message=f"SKILL.md name: '{name}' does not match directory name '{child.name}'",
                        )
                    )

    return violations


def check_no_python_in_skills(
    skills_root: Path, strict: bool
) -> list[ModelSkillViolation]:
    """Check #6: No .py files in skill dirs. Python belongs in _-prefixed dirs only."""
    violations: list[ModelSkillViolation] = []

    for py_file in sorted(skills_root.rglob("*.py")):
        # Get the relative path parts from skills_root
        rel = py_file.relative_to(skills_root)
        parts = rel.parts

        # Skip if any ancestor dir is infrastructure-prefixed
        in_infra = False
        for part in parts[:-1]:  # check dir components, not the file itself
            if is_infrastructure_dir(part):
                in_infra = True
                break

        if in_infra:
            continue

        # Skip top-level __init__.py (the skills package itself)
        if len(parts) == 1 and parts[0] == "__init__.py":
            continue

        violations.append(
            ModelSkillViolation(
                path=str(rel),
                check=CHECK_NO_PYTHON_IN_SKILLS,
                severity=SEVERITY_ERROR,
                message=f"Python file in skill directory: {rel} — move to a _-prefixed infrastructure dir (e.g. _lib/)",
            )
        )

    return violations


def check_no_orphan_topics(
    skills_root: Path, strict: bool
) -> list[ModelSkillViolation]:
    """Check #7: topics.yaml without SKILL.md in same dir is suspicious."""
    violations: list[ModelSkillViolation] = []

    for topics_file in sorted(skills_root.rglob("topics.yaml")):
        parent = topics_file.parent
        rel = topics_file.relative_to(skills_root)

        # Skip infrastructure dirs
        parts = rel.parts
        in_infra = False
        for part in parts[:-1]:
            if is_infrastructure_dir(part):
                in_infra = True
                break
        if in_infra:
            continue

        if not (parent / "SKILL.md").exists():
            violations.append(
                ModelSkillViolation(
                    path=str(rel),
                    check=CHECK_NO_ORPHAN_TOPICS,
                    severity=SEVERITY_WARNING,
                    message=f"topics.yaml found without SKILL.md in same directory: {parent.name}/",
                )
            )

    return violations


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_underscore_names,
    check_no_duplicate_names,
    check_no_unindexed_nesting,
    check_skill_md_required,
    check_name_matches_dir,
    check_no_python_in_skills,
    check_no_orphan_topics,
]


class HandlerSkillHygiene:
    """Run all seven hygiene checks in source order."""

    def handle(
        self, request: ModelSkillValidationRequest
    ) -> ModelSkillValidationReport:
        violations: list[ModelSkillViolation] = []
        for check_fn in ALL_CHECKS:
            violations.extend(check_fn(request.skills_root, request.strict))
        return ModelSkillValidationReport(violations=tuple(violations))
