# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for env_parity ticket creation defaults (OMN-9069)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_SKILL_DIR = (
    Path(__file__).resolve().parents[3] / "plugins" / "onex" / "skills" / "env_parity"
)
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_PROMPT_MD = _SKILL_DIR / "prompt.md"


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), "SKILL.md must start with YAML frontmatter"
    _, frontmatter, body = text.split("---", 2)
    parsed = yaml.safe_load(frontmatter)
    assert isinstance(parsed, dict), "Frontmatter must parse as a mapping"
    return parsed, body


@pytest.mark.unit
def test_env_parity_exposes_create_tickets_and_no_create_tickets_args() -> None:
    frontmatter, _ = _parse_frontmatter(_SKILL_MD)
    args = {arg["name"]: arg for arg in frontmatter["args"]}

    assert "--create-tickets" in args
    assert "--no-create-tickets" in args
    assert "Default: true" in args["--create-tickets"]["description"]
    assert "--no-create-tickets" in args["--create-tickets"]["description"]


@pytest.mark.unit
def test_env_parity_docs_make_ticket_creation_default_and_opt_out() -> None:
    _, body = _parse_frontmatter(_SKILL_MD)

    assert "Linear ticket creation is enabled by default" in body
    assert "Pass `--no-create-tickets`" in body
    assert "requires the explicit `--create-tickets` flag" not in body
    assert "It is NOT the default" not in body


@pytest.mark.unit
def test_env_parity_prompt_parses_create_tickets_default_true() -> None:
    prompt = _PROMPT_MD.read_text(encoding="utf-8")

    assert "| `--create-tickets` | true |" in prompt
    assert "| `--no-create-tickets` | unset |" in prompt
    assert "Set `CREATE_TICKETS=true` unless `--no-create-tickets` is present" in prompt
    assert "${CREATE_TICKETS:+--create-tickets}" in prompt
    assert "${NO_CREATE_TICKETS:+--no-create-tickets}" in prompt
