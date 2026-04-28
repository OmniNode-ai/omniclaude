# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Phase 1 Task 2 (OMN-10191): canonical SKILL.md orchestrator-shim shape.

Asserts the structural invariants every migrated SKILL.md must follow:
  - required section headers
  - `uv run onex run-node` and `gh pr checks` references
  - no inline executable code fences (python/bash/sh/shell)
  - foreground-only Agent() ADR cited by filename
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "_shared"
    / "skill_orchestrator_template.md"
)

_REQUIRED_SECTIONS = (
    "## What this skill does",
    "## Dispatch",
    "uv run onex run-node",
    "## Foreground responsibility",
    "## Worker self-verification",
    "gh pr checks",
    "## Backing node contract",
    "## Failure modes",
)


def test_shim_template_exists_and_declares_required_sections() -> None:
    template = _TEMPLATE_PATH.read_text()
    for required in _REQUIRED_SECTIONS:
        assert required in template, f"template missing required section: {required}"


def test_shim_template_forbids_inline_executable_code() -> None:
    """Template must not contain executable Python/shell code blocks.

    Detects both backtick (```) and tilde (~~~) fences; tolerates leading
    indentation and case-insensitive language IDs so the gate cannot be
    bypassed by `   ```BASH`.
    """
    template = _TEMPLATE_PATH.read_text()
    in_fence = False
    fence_delim = ""
    fence_lang = ""
    for raw_line in template.splitlines():
        line = raw_line.lstrip()
        if line.startswith(("```", "~~~")):
            delim = line[:3]
            if not in_fence:
                in_fence = True
                fence_delim = delim
                fence_lang = line[3:].strip().split(maxsplit=1)[0].lower()
            elif delim == fence_delim:
                in_fence = False
                fence_delim = ""
                fence_lang = ""
            continue
        if in_fence and fence_lang in ("python", "bash", "sh", "shell"):
            raise AssertionError(
                f"template must not contain ```{fence_lang} executable fence"
            )


def test_shim_template_cites_adr() -> None:
    template = _TEMPLATE_PATH.read_text()
    assert "adr-dispatch-architecture-foreground-only-agent-call" in template
