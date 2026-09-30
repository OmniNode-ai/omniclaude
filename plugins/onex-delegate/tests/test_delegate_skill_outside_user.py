# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The delegate skill reads correctly for a user outside OmniNode (OMN-19965)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SKILL = Path(__file__).parent.parent / "skills" / "delegate" / "SKILL.md"


def _text() -> str:
    return SKILL.read_text()


def _frontmatter() -> str:
    return _text().split("---", 2)[1]


def test_frontmatter_is_not_local_only_or_advanced() -> None:
    fm = _frontmatter()
    assert "local-llm" not in fm
    assert "Single-command local LLM" not in fm
    assert "level: advanced" not in fm


def test_size_section_has_no_insider_references() -> None:
    text = _text()
    start = text.index("## Prompt Size")
    end = text.index("## Usage")
    section = text[start:end]
    for token in ("OMN-", "GLM rung", "the lab", "Lane rule", "measured 2026"):
        assert token not in section, f"insider reference {token!r} in the size section"


def test_platform_statement_and_intel_check() -> None:
    text = _text()
    assert "## Supported platforms" in text
    assert "uname -sm" in text
    assert "Darwin x86_64" in text
    assert "Docker is not required" in text
