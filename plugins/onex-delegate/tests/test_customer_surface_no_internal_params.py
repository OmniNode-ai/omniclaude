# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The customer plugin must not tell a customer to use internal-only parameters (OMN-19367).

Why this file exists
--------------------
The customer-facing `onex` plugin shipped a delegate SKILL.md that told the reader to
install `omnimarket` from a git direct reference on the unreleased `dev` branch and to
export the OmniNode workspace-root variables. Neither exists on a customer machine, and
both contradicted the public quickstart, which installs all three packages from PyPI and
says there is no workspace variable to set. No check read the customer surface for that
class, so it shipped unseen.

This module reads every file the customer marketplace ships (the `plugins/onex-delegate`
tree plus both `marketplace.json` copies) and fails on any internal-only parameter.

The needles are assembled from fragments so that this file, which lives inside the tree it
scans, does not match itself.

Run by the `onex-delegate-customer-surface` pre-commit hook and by the Plugin Compat Gate
workflow, which runs `pytest plugins/onex-delegate/tests/`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PLUGIN_DIR = Path(__file__).parent.parent
REPO_ROOT = PLUGIN_DIR.parent.parent

_WORKSPACE_ROOT = "internal workspace-root variable; a customer machine has none"

#: Internal-only parameters, each with the reason a customer surface must not name it.
_INTERNAL_ONLY: dict[str, str] = {
    "_".join(("OMNI", "HOME")): _WORKSPACE_ROOT,
    "_".join(("OMNIBASE", "PATH")): _WORKSPACE_ROOT,
    "_".join(("ONEX", "REGISTRY", "ROOT")): "internal registry-clone variable",
    "_".join(("ONEX", "WORKTREES", "ROOT")): "internal worktree-root variable",
    "+".join(("git", "https://github.com/OmniNode-ai/")): (
        "installs unreleased source from git; the public quickstart installs PyPI releases"
    ),
}

_TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".py", ".txt", ".toml", ".sh"}


def _customer_files() -> list[Path]:
    files = [
        p
        for p in sorted(PLUGIN_DIR.rglob("*"))
        if p.is_file() and p.suffix in _TEXT_SUFFIXES and "__pycache__" not in p.parts
    ]
    files.append(REPO_ROOT / ".claude-plugin" / "marketplace.json")
    files.append(REPO_ROOT / "plugins" / ".claude-plugin" / "marketplace.json")
    return files


def _offenders(text: str, label: str) -> list[str]:
    found: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for needle, why in _INTERNAL_ONLY.items():
            if needle in line:
                found.append(f"{label}:{lineno}: names {needle!r} ({why})")
    return found


def test_scan_covers_the_shipped_skills_and_both_marketplaces() -> None:
    """A scan that silently reads nothing would pass for the wrong reason."""
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in _customer_files()}
    for required in (
        "plugins/onex-delegate/skills/delegate/SKILL.md",
        "plugins/onex-delegate/skills/delegate/prompt.md",
        "plugins/onex-delegate/skills/cloud_delegate/SKILL.md",
        "plugins/onex-delegate/plugin-compat.yaml",
        "plugins/onex-delegate/.claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        "plugins/.claude-plugin/marketplace.json",
    ):
        assert required in rels, f"customer-surface scan does not read {required}"


@pytest.mark.parametrize("needle", sorted(_INTERNAL_ONLY))
def test_matcher_flags_every_needle(needle: str) -> None:
    """Positive control: each needle, on a synthetic line, is reported."""
    assert _offenders(f"export {needle}=/somewhere", "synthetic"), needle


def test_customer_surface_names_no_internal_only_parameter() -> None:
    offenders: list[str] = []
    for path in _customer_files():
        offenders.extend(
            _offenders(path.read_text(), path.relative_to(REPO_ROOT).as_posix())
        )
    assert not offenders, (
        "the customer plugin surface names internal-only parameters. A customer "
        "follows the public quickstart (PyPI packages, no workspace variables); "
        "rewrite these lines to match it:\n" + "\n".join(offenders)
    )
