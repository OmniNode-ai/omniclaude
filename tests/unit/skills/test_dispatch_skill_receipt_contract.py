# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-13097 Phase 4a — single-command dispatch-skill receipt contract.

All 24 dispatch-only shims migrate to the proven delegate (Phase 2b) shape:
a dispatch skill IS one CLI call (``uv run onex skill <name>`` /
``uv run onex delegate``) printing exactly one ``ModelSkillResult[T]``. This
suite replaces the per-skill ``onex run-node`` shim-contract tests
(test_compliance_sweep_shim, test_platform_readiness_shim, test_merge_sweep_shim,
test_s21_shims, the hostile_reviewer prose-contract tests) whose assertions
encoded the now-deleted procedure-body pattern.

The invariants here are the same ones the Phase 4b validator
(``validate_skill_dispatch_receipt_mode``, OMN-13097 4b) enforces as a gate:

  1. SKILL.md frontmatter parses and declares ``skill_kind: dispatch``.
  2. prompt.md has NO YAML frontmatter (procedure-body deletion).
  3. The skill markdown invokes the single receipt-mode command form
     (``onex skill <name>`` or ``onex delegate``) and NO bare
     ``onex (run|node|run-node)`` dispatch.
  4. No ``cat .../workflow_result.json`` and no "surface the JSON verbatim".
  5. The skill directory contains NO executable logic (``*.py``, ``*.sh``,
     ``_lib/``) — markdown (and metadata yaml) only.
  6. No LLM SDK imports leak into the markdown.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "onex" / "skills"

# The 24 dispatch-only shims migrated by OMN-13097 Phase 4a. delegate ships its
# own `onex delegate` subcommand (Phase 2b); the other 23 route through
# `onex skill <name>` (omnibase_infra skill_mapping.yaml).
DELEGATE = "delegate"
ONEX_SKILL_SHIMS = (
    "aislop_sweep",
    "data_flow_sweep",
    "auto_merge",
    "build_loop",
    "coderabbit_triage",
    "compliance_sweep",
    "coverage_sweep",
    "create_ticket",
    "database_sweep",
    "design_to_plan",
    "doc_freshness_sweep",
    "dod_verify",
    "duplication_sweep",
    "hostile_reviewer",
    "linear_housekeeping",
    "merge_sweep",
    "plan_to_tickets",
    "platform_readiness",
    "pr_polish",
    "pr_review",
    "pr_review_bot",
    "session",
    "shim_audit",
)
ALL_DISPATCH_SHIMS = (*ONEX_SKILL_SHIMS, DELEGATE)

_BARE_DISPATCH = re.compile(r"\bonex\s+(?:run-node|run|node)\b")
# A real `cat ... workflow_result.json` COMMAND inside a fenced bash block — not
# the negative prose ("do NOT cat workflow_result.json") that the shim body
# carries to instruct Claude. Bare prose mentions are allowed; commands are not.
_BASH_BLOCK = re.compile(r"```bash\n(.*?)```", re.DOTALL)
_LEGACY_CAT = re.compile(r"\bcat\b[^\n]*workflow_result\.json", re.IGNORECASE)
_VERBATIM = re.compile(r"surface\s+the\s+json\s+verbatim", re.IGNORECASE)
_LLM_SDK = re.compile(
    r"\b(?:import\s+anthropic|from\s+anthropic|import\s+openai|from\s+openai)\b"
)


def _skill_dir(name: str) -> Path:
    return SKILLS_DIR / name


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    return None, text


@pytest.mark.unit
@pytest.mark.parametrize("name", ALL_DISPATCH_SHIMS)
def test_skill_dir_markdown_only(name: str) -> None:
    """A dispatch skill directory holds markdown + metadata yaml only."""
    d = _skill_dir(name)
    assert d.is_dir(), f"{name}: skill directory missing at {d}"
    offenders: list[str] = []
    for p in d.rglob("*"):
        if "__pycache__" in p.parts:
            continue
        if p.is_dir() and p.name == "_lib":
            offenders.append(str(p.relative_to(d)))
        if p.is_file() and p.suffix in {".py", ".sh"}:
            offenders.append(str(p.relative_to(d)))
    assert not offenders, (
        f"{name}: dispatch skill must contain no executable logic, found {offenders}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("name", ALL_DISPATCH_SHIMS)
def test_skill_md_declares_dispatch_kind(name: str) -> None:
    skill_md = _skill_dir(name) / "SKILL.md"
    assert skill_md.is_file(), f"{name}: SKILL.md missing"
    fm_text, _ = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
    assert fm_text is not None, f"{name}: SKILL.md has no YAML frontmatter"
    fm = yaml.safe_load(fm_text)
    assert isinstance(fm, dict), f"{name}: SKILL.md frontmatter is not a mapping"
    assert fm.get("skill_kind") == "dispatch", (
        f"{name}: SKILL.md must declare skill_kind: dispatch, got {fm.get('skill_kind')!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("name", ALL_DISPATCH_SHIMS)
def test_prompt_md_has_no_frontmatter(name: str) -> None:
    """prompt.md is procedure-free: no YAML frontmatter, just command + present."""
    prompt_md = _skill_dir(name) / "prompt.md"
    assert prompt_md.is_file(), f"{name}: prompt.md missing"
    fm_text, _ = _split_frontmatter(prompt_md.read_text(encoding="utf-8"))
    assert fm_text is None, f"{name}: prompt.md must not carry YAML frontmatter"


@pytest.mark.unit
@pytest.mark.parametrize("name", ALL_DISPATCH_SHIMS)
def test_no_bare_dispatch_no_legacy_cat(name: str) -> None:
    """No bare onex run/node/run-node, no cat-of-workflow_result, no verbatim dump."""
    d = _skill_dir(name)
    combined = "\n".join(
        (d / fn).read_text(encoding="utf-8") for fn in ("SKILL.md", "prompt.md")
    )
    # Bare-dispatch and legacy-cat are forbidden as real COMMANDS (fenced bash
    # blocks), not as the negative prose the shim body uses to instruct Claude
    # what NOT to do. Scan only executable bash blocks for those two.
    bash = "\n".join(_BASH_BLOCK.findall(combined))
    assert not _BARE_DISPATCH.search(bash), (
        f"{name}: bare `onex run|node|run-node` dispatch is forbidden — "
        "use `onex skill <name>` / `onex delegate` receipt-mode form"
    )
    assert not _LEGACY_CAT.search(bash), (
        f"{name}: `cat ... workflow_result.json` command is forbidden "
        "(the receipt is the only thing on stdout)"
    )
    assert not _VERBATIM.search(combined), (
        f"{name}: 'surface the JSON verbatim' procedure language is forbidden"
    )
    assert not _LLM_SDK.search(combined), f"{name}: LLM SDK import leaked into markdown"


@pytest.mark.unit
@pytest.mark.parametrize("name", ONEX_SKILL_SHIMS)
def test_onex_skill_single_command(name: str) -> None:
    """Each non-delegate shim invokes exactly its `onex skill <name>` command."""
    d = _skill_dir(name)
    combined = "\n".join(
        (d / fn).read_text(encoding="utf-8") for fn in ("SKILL.md", "prompt.md")
    )
    pattern = re.compile(rf"\bonex\s+skill\s+{re.escape(name)}\b")
    matches = pattern.findall(combined)
    assert matches, f"{name}: missing the `uv run onex skill {name}` command"


@pytest.mark.unit
def test_delegate_uses_onex_delegate_command() -> None:
    d = _skill_dir(DELEGATE)
    combined = "\n".join(
        (d / fn).read_text(encoding="utf-8") for fn in ("SKILL.md", "prompt.md")
    )
    assert "onex delegate" in combined, "delegate: missing `onex delegate` command"
