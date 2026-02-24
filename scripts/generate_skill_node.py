#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""generate_skill_node.py — scaffold ONEX node directories for omniclaude skills.

Each omniclaude skill becomes a discoverable ONEX NodeOrchestrator shell with
three generated files:

    src/omniclaude/nodes/node_skill_{snake}_orchestrator/
        __init__.py      — package init, exports node class
        node.py          — thin NodeOrchestrator subclass shell
        contract.yaml    — declarative ONEX contract

Usage
-----
    uv run python scripts/generate_skill_node.py local-review
    uv run python scripts/generate_skill_node.py --all
    uv run python scripts/generate_skill_node.py local-review --dry-run

The script reads SKILL.md frontmatter (name, description) from
``plugins/onex/skills/{skill-name}/SKILL.md`` and populates the template
via plain string replacement (no Jinja2).

Template
--------
Lives at ``docs/templates/skill_node_contract.yaml.template``.
Placeholders: SKILL_NAME_SNAKE, SKILL_NAME, SKILL_DESCRIPTION, CREATED_DATE.

Topic naming
------------
Subscribe:  onex.cmd.omniclaude.{skill-name}.v1
Publish:    onex.evt.omniclaude.{skill-name}-completed.v1
            onex.evt.omniclaude.{skill-name}-failed.v1

No ``-requested`` suffix, no ``{env}.`` prefix.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def snake_to_pascal(snake: str) -> str:
    """Convert a snake_case string to PascalCase.

    Uses per-segment capitalize() so acronyms like ``ci`` become ``Ci``,
    not ``CI``.  This matches the expected class name convention used by the
    ONEX platform for generated skill node classes.

    Args:
        snake: Input snake_case string (e.g. ``"ci_fix_pipeline"``).

    Returns:
        PascalCase string (e.g. ``"CiFixPipeline"``).

    Examples:
        >>> snake_to_pascal("review")
        'Review'
        >>> snake_to_pascal("local_review")
        'LocalReview'
        >>> snake_to_pascal("ci_fix_pipeline")
        'CiFixPipeline'
        >>> snake_to_pascal("pr_release_ready")
        'PrReleaseReady'
    """
    return "".join(part.capitalize() for part in snake.split("_"))


def kebab_to_snake(kebab: str) -> str:
    """Convert a kebab-case string to snake_case.

    Args:
        kebab: Input kebab-case string (e.g. ``"ci-fix-pipeline"``).

    Returns:
        snake_case string (e.g. ``"ci_fix_pipeline"``).
    """
    return kebab.replace("-", "_")


def read_skill_frontmatter(skill_dir: Path) -> tuple[str, str]:
    """Extract ``name`` and ``description`` from a SKILL.md YAML frontmatter block.

    Reads the first ``---`` delimited block at the top of the file.  Returns
    the raw ``name`` and ``description`` values.  If a field is absent, an
    empty string is returned for that field.

    Args:
        skill_dir: Directory containing ``SKILL.md``.

    Returns:
        Tuple of ``(name, description)``.

    Raises:
        FileNotFoundError: If ``SKILL.md`` does not exist in ``skill_dir``.
        ValueError: If the file has no opening ``---`` frontmatter fence.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found at {skill_md}")

    content = skill_md.read_text(encoding="utf-8")
    lines = content.splitlines()

    if not lines or lines[0].strip() != "---":
        raise ValueError(f"No YAML frontmatter found in {skill_md}")

    # Collect lines until the closing ---
    fm_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm_lines.append(line)

    name = ""
    description = ""
    for line in fm_lines:
        if line.startswith("name:"):
            name = line[len("name:") :].strip().strip('"').strip("'")
        elif line.startswith("description:"):
            description = line[len("description:") :].strip().strip('"').strip("'")

    return name, description


def render_template(template_text: str, substitutions: dict[str, str]) -> str:
    """Apply plain string substitutions to a template.

    Applies each ``{placeholder: replacement}`` pair via ``str.replace()``.
    No Jinja2 or other templating engine is used.

    Substitutions are applied longest-placeholder-first to avoid partial matches
    (e.g. ``SKILL_NAME`` being replaced before ``SKILL_NAME_SNAKE``).

    Args:
        template_text: Raw template content.
        substitutions: Mapping from placeholder string to replacement value.

    Returns:
        Rendered string with all substitutions applied.
    """
    result = template_text
    # Sort by placeholder length descending so longer (more specific) placeholders
    # are replaced first.  This prevents SKILL_NAME from matching the prefix of
    # SKILL_NAME_SNAKE before the snake variant has been substituted.
    for placeholder in sorted(substitutions, key=len, reverse=True):
        result = result.replace(placeholder, substitutions[placeholder])
    return result


def generate_init_py(skill_name_snake: str) -> str:
    """Generate the content for the node package ``__init__.py``.

    Args:
        skill_name_snake: snake_case skill name (e.g. ``"local_review"``).

    Returns:
        File content as a string.
    """
    pascal = snake_to_pascal(skill_name_snake)
    class_name = f"NodeSkill{pascal}Orchestrator"
    return f"""\
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
\"\"\"Skill node: {skill_name_snake} orchestrator.\"\"\"

from omniclaude.nodes.node_skill_{skill_name_snake}_orchestrator.node import (
    {class_name},
)

__all__ = ["{class_name}"]
"""


def generate_node_py(skill_name_snake: str, skill_name_kebab: str) -> str:
    """Generate the content for the node class ``node.py``.

    Args:
        skill_name_snake: snake_case skill name.
        skill_name_kebab: kebab-case skill name (used in docstring).

    Returns:
        File content as a string.
    """
    pascal = snake_to_pascal(skill_name_snake)
    class_name = f"NodeSkill{pascal}Orchestrator"
    return f"""\
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
\"\"\"NodeSkill{pascal}Orchestrator — thin orchestrator shell for the {skill_name_kebab} skill.

Capability: skill.{skill_name_snake}
All dispatch logic lives in the shared handle_skill_requested handler.
\"\"\"

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class {class_name}(NodeOrchestrator):
    \"\"\"Orchestrator node for the {skill_name_kebab} skill.

    Capability: skill.{skill_name_snake}

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    \"\"\"

    def __init__(self, container: ModelONEXContainer) -> None:
        \"\"\"Initialize the {class_name}.

        Args:
            container: ONEX container for dependency injection.
        \"\"\"
        super().__init__(container)


__all__ = ["{class_name}"]
"""


# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------


def generate_node_for_skill(
    skill_name_kebab: str,
    *,
    repo_root: Path,
    dry_run: bool = False,
) -> bool:
    """Generate node directory files for a single skill.

    Creates three files under
    ``src/omniclaude/nodes/node_skill_{snake}_orchestrator/``:
        - ``__init__.py``
        - ``node.py``
        - ``contract.yaml``

    Skips if the node directory already exists.

    Args:
        skill_name_kebab: The kebab-case skill name (e.g. ``"local-review"``).
        repo_root: Absolute path to the repository root.
        dry_run: If ``True``, print what would be created without writing files.

    Returns:
        ``True`` if generation happened (or would happen in dry-run),
        ``False`` if the node already exists and was skipped.
    """
    skill_name_snake = kebab_to_snake(skill_name_kebab)
    node_dir_name = f"node_skill_{skill_name_snake}_orchestrator"
    node_dir = repo_root / "src" / "omniclaude" / "nodes" / node_dir_name

    if node_dir.exists():
        print(f"[SKIP] {node_dir_name} already exists — skipping {skill_name_kebab!r}")
        return False

    skills_dir = repo_root / "plugins" / "onex" / "skills"
    skill_dir = skills_dir / skill_name_kebab

    if not skill_dir.exists():
        print(
            f"[ERROR] Skill directory not found: {skill_dir}",
            file=sys.stderr,
        )
        return False

    try:
        _name, description = read_skill_frontmatter(skill_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(
            f"[ERROR] Could not read SKILL.md for {skill_name_kebab!r}: {exc}",
            file=sys.stderr,
        )
        return False

    # Use frontmatter name if present, otherwise fall back to kebab name.
    if not _name:
        _name = skill_name_kebab

    template_path = (
        repo_root / "docs" / "templates" / "skill_node_contract.yaml.template"
    )
    if not template_path.exists():
        print(f"[ERROR] Template not found: {template_path}", file=sys.stderr)
        return False

    template_text = template_path.read_text(encoding="utf-8")
    today = datetime.now(tz=UTC).date().isoformat()
    contract_content = render_template(
        template_text,
        {
            "SKILL_NAME_SNAKE": skill_name_snake,
            "SKILL_NAME": _name,
            "SKILL_DESCRIPTION": description or f"Executes the {_name} skill.",
            "CREATED_DATE": today,
        },
    )

    init_content = generate_init_py(skill_name_snake)
    node_content = generate_node_py(skill_name_snake, skill_name_kebab)

    files_to_create = [
        (node_dir / "__init__.py", init_content),
        (node_dir / "node.py", node_content),
        (node_dir / "contract.yaml", contract_content),
    ]

    if dry_run:
        for path, _ in files_to_create:
            print(f"[DRY RUN] Would create: {path}")
        return True

    node_dir.mkdir(parents=True, exist_ok=True)
    for path, content in files_to_create:
        path.write_text(content, encoding="utf-8")
        print(f"[CREATE] {path}")

    return True


def discover_all_skills(repo_root: Path) -> list[str]:
    """Return a sorted list of all kebab-case skill names found in the skills directory.

    Skips directories starting with ``_`` (lib/shared helpers).

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        Sorted list of skill name strings in kebab-case.
    """
    skills_dir = repo_root / "plugins" / "onex" / "skills"
    if not skills_dir.exists():
        return []
    return sorted(
        d.name
        for d in skills_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="generate_skill_node.py",
        description="Scaffold ONEX node directories for omniclaude skills.",
    )
    parser.add_argument(
        "skill",
        nargs="?",
        help="Skill name in kebab-case (e.g. local-review). Omit when using --all.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_skills",
        help="Generate nodes for all skills that are missing one.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Preview what would be created without writing files.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help=(
            "Path to the repository root. "
            "Defaults to the parent of the scripts/ directory."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the generation script.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # Resolve repo root: default to the parent of this script's directory.
    if args.repo_root is not None:
        repo_root = args.repo_root.resolve()
    else:
        repo_root = Path(__file__).parent.parent.resolve()

    if not args.all_skills and not args.skill:
        parser.error("Provide a skill name or --all.")

    if args.all_skills and args.skill:
        parser.error("Cannot specify both a skill name and --all.")

    if args.all_skills:
        skills = discover_all_skills(repo_root)
        if not skills:
            print(
                "[ERROR] No skills discovered. Check plugins/onex/skills/ directory.",
                file=sys.stderr,
            )
            return 1
        generated = 0
        skipped = 0
        for skill_name in skills:
            result = generate_node_for_skill(
                skill_name, repo_root=repo_root, dry_run=args.dry_run
            )
            if result:
                generated += 1
            else:
                skipped += 1
        print(f"\nDone. Generated: {generated}, Skipped (already exist): {skipped}")
    else:
        result = generate_node_for_skill(
            args.skill, repo_root=repo_root, dry_run=args.dry_run
        )
        if not result and not args.dry_run:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
