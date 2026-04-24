# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-8750 DoD gate: /onex:session is a dispatch-only shim.

A4 AST-lint rules for the session skill:
  1. Zero LLM SDK imports (anthropic, openai)
  2. Exactly one `onex run` dispatch call across SKILL.md + prompt.md
  3. No subprocess orchestration wrappers (`subprocess.`, `os.system`)
  4. No inline Agent() / Skill() orchestration calls
  5. prompt.md <= 30 lines (dispatch-only body)
  6. No prose fallback path — skill must raise SkillRoutingError on dispatch failure
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILL_DIR = (
    Path(__file__).resolve().parents[2] / "plugins" / "onex" / "skills" / "session"
)
PROMPT_PATH = SKILL_DIR / "prompt.md"
SKILL_PATH = SKILL_DIR / "SKILL.md"

LLM_SDK_PATTERNS = [
    re.compile(r"\bfrom\s+anthropic\s+import\b"),
    re.compile(r"\bimport\s+anthropic\b"),
    re.compile(r"\bfrom\s+openai\s+import\b"),
    re.compile(r"\bimport\s+openai\b"),
    re.compile(r"\bmcp__anthropic\w*"),
    re.compile(r"\bmcp__openai\w*"),
]
ONEX_RUN_PATTERN = re.compile(r"\bonex\s+run\b")
SUBPROCESS_PATTERN = re.compile(r"\b(?:subprocess\.|os\.system\b)")
AGENT_CALL_PATTERN = re.compile(r"\bAgent\s*\(")
SKILL_CALL_PATTERN = re.compile(r"\bSkill\s*\(\s*skill\s*=")
PROSE_FALLBACK_MARKERS = [
    re.compile(r"\bprose\s+fallback\s+when\b", re.IGNORECASE),
    re.compile(r"\bfall\s+back\s+to\s+prose\b", re.IGNORECASE),
    re.compile(r"\bClaude\s+IS\s+the\s+orchestrator\b", re.IGNORECASE),
]


def _combined_text() -> str:
    parts = []
    for p in (SKILL_PATH, PROMPT_PATH):
        assert p.exists(), f"Missing required shim file: {p}"
        parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_prompt_file_exists() -> None:
    assert PROMPT_PATH.exists(), f"session skill missing prompt.md at {PROMPT_PATH}"


def test_skill_file_exists() -> None:
    assert SKILL_PATH.exists(), f"session skill missing SKILL.md at {SKILL_PATH}"


def test_no_llm_sdk_imports() -> None:
    text = _combined_text()
    hits = [pat.pattern for pat in LLM_SDK_PATTERNS if pat.search(text)]
    assert not hits, f"LLM SDK import(s) detected in session shim: {hits}"


def test_exactly_one_onex_run_dispatch() -> None:
    text = _combined_text()
    matches = ONEX_RUN_PATTERN.findall(text)
    assert len(matches) == 1, (
        f"session shim must dispatch via exactly one `onex run` call, "
        f"found {len(matches)}"
    )


def test_no_subprocess_orchestration() -> None:
    text = _combined_text()
    hits = SUBPROCESS_PATTERN.findall(text)
    assert not hits, f"session shim must not use subprocess/os.system: {hits}"


def test_no_inline_agent_or_skill_calls() -> None:
    text = _combined_text()
    agent_hits = AGENT_CALL_PATTERN.findall(text)
    skill_hits = SKILL_CALL_PATTERN.findall(text)
    assert not agent_hits, f"inline Agent() dispatch forbidden in shim: {agent_hits}"
    assert not skill_hits, f"inline Skill() dispatch forbidden in shim: {skill_hits}"


def test_prompt_body_under_thirty_lines() -> None:
    lines = PROMPT_PATH.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 30, f"prompt.md exceeds 30-line DoD budget: {len(lines)} lines"


def test_no_prose_fallback_path() -> None:
    text = _combined_text()
    hits = [pat.pattern for pat in PROSE_FALLBACK_MARKERS if pat.search(text)]
    assert not hits, f"prose fallback markers found in session shim: {hits}"


def test_references_skill_routing_error() -> None:
    """Dispatch failure must surface SkillRoutingError, not prose."""
    text = _combined_text()
    assert "SkillRoutingError" in text, (
        "session shim must reference SkillRoutingError as the dispatch-failure envelope"
    )


def test_references_backing_node() -> None:
    """Shim must name the backing omnimarket node for routing traceability."""
    text = _combined_text()
    assert "node_session_orchestrator" in text, (
        "session shim must reference backing node `node_session_orchestrator`"
    )


@pytest.mark.parametrize("path", [PROMPT_PATH, SKILL_PATH])
def test_no_phase_bodies_in_shim(path: Path) -> None:
    """Phase 1/2/3 bodies must live in the handler, not the shim."""
    text = path.read_text(encoding="utf-8")
    forbidden = [
        re.compile(r"###\s+Step\s+3b:\s+Run\s+8\s+health\s+dimensions", re.IGNORECASE),
        re.compile(r"RSD\s+Scoring\s+\(Phase\s+2\)", re.IGNORECASE),
        re.compile(r"##\s+Step\s+5:\s+Phase\s+3\s+—\s+Dispatch", re.IGNORECASE),
    ]
    hits = [p.pattern for p in forbidden if p.search(text)]
    assert not hits, f"phase body leaked into shim {path.name}: {hits}"
