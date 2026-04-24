# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-8756: /onex:redeploy must be a dispatch-only thin shim.

Locks in the A4 amendment invariants from OMN-8737:
  - zero LLM SDK imports
  - exactly one ``onex run-node`` dispatch call
  - no subprocess orchestration wrappers
  - no hidden conditional fallback prose paths (no prompt.md)
  - prose_fallback_lines <= 50 (deterministic classification)
"""

import re
from pathlib import Path

import pytest

SKILL_DIR = (
    Path(__file__).resolve().parents[2] / "plugins" / "onex" / "skills" / "redeploy"
)
SKILL_MD = SKILL_DIR / "SKILL.md"
PROMPT_MD = SKILL_DIR / "prompt.md"

LLM_SDK_FORBIDDEN = [
    r"from anthropic import",
    r"import anthropic",
    r"from openai import",
    r"import openai",
    r"anthropic\.Anthropic",
    r"openai\.OpenAI",
    r"mcp__anthropic",
    r"mcp__openai",
]

ORCHESTRATION_FORBIDDEN = [
    r"\bsubprocess\b",
    r"\bos\.system\b",
    r"\bkcat\b",
    r"\bdocker exec\b",
]


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_skill_md_exists() -> None:
    assert SKILL_MD.exists(), "redeploy SKILL.md must exist"


def test_no_prompt_md() -> None:
    """The thin shim has no separate prompt.md — SKILL.md is the only surface."""
    assert not PROMPT_MD.exists(), (
        "redeploy/prompt.md must not exist — it housed the inline orchestration "
        "prose stripped by OMN-8756. All phase logic lives in node_redeploy."
    )


def test_no_llm_sdk_imports() -> None:
    text = _skill_text()
    for pat in LLM_SDK_FORBIDDEN:
        assert not re.search(pat, text), (
            f"LLM SDK reference {pat!r} must not appear in redeploy/SKILL.md"
        )


def test_exactly_one_onex_run_dispatch() -> None:
    text = _skill_text()
    matches = re.findall(r"onex run-node\b", text)
    assert len(matches) == 1, (
        f"redeploy/SKILL.md must contain exactly one `onex run-node` dispatch "
        f"(found {len(matches)})"
    )


def test_dispatches_to_node_redeploy() -> None:
    """The single dispatch must target node_redeploy, not some other node."""
    text = _skill_text()
    dispatch_matches = re.findall(r"onex run-node\s+(\S+)", text)
    assert dispatch_matches == ["node_redeploy"], (
        f"SKILL.md must dispatch to `node_redeploy` exactly once; "
        f"found dispatch targets: {dispatch_matches}"
    )


def test_no_subprocess_orchestration_wrappers() -> None:
    text = _skill_text()
    for pat in ORCHESTRATION_FORBIDDEN:
        assert not re.search(pat, text), (
            f"orchestration token {pat!r} must not appear in redeploy/SKILL.md "
            f"— those side effects live in node_redeploy handlers"
        )


def test_prose_fallback_within_deterministic_budget() -> None:
    """Mirror scripts/audit_skill_shims.py prose counting: <= 50 lines = deterministic."""
    text = _skill_text()
    lines = text.split("\n")
    in_frontmatter = False
    in_code_fence = False
    prose_count = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if stripped:
            prose_count += 1
    assert prose_count <= 50, (
        f"redeploy/SKILL.md has {prose_count} prose lines — must be <= 50 for "
        f"deterministic classification (A4 amendment, OMN-8737)"
    )


@pytest.mark.parametrize(
    "arg",
    ["--scope", "--git-ref", "--versions", "--skip-sync", "--verify-only", "--dry-run"],
)
def test_documents_expected_args(arg: str) -> None:
    """Contract-documented inputs must be listed in SKILL.md args."""
    text = _skill_text()
    assert arg in text, f"SKILL.md must document `{arg}` arg"
