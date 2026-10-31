# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""/onex:delegate sends the Claude Code session's model as the savings baseline (OMN-20557).

A delegation's savings are stated against the developer's own session model when
it is known. Claude Code names that model to the session, and no environment
variable carries it, so the skill passes it on the one command it runs:
``onex delegate ... --session-model <id>``. The CLI writes it to the request
metadata and the receipt then names ``baseline_source: session_model``.

What these tests pin:

* the one fenced command in prompt.md and the command SKILL.md documents pass
  ``--session-model``;
* the prompt says where the id comes from and never to guess one;
* an ``onex`` too old to know the flag still delegates: the prompt names its
  exact refusal and says to run the same command once without the flag.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SKILL_DIR = Path(__file__).parent.parent / "skills" / "delegate"
PROMPT_MD = SKILL_DIR / "prompt.md"
SKILL_MD = SKILL_DIR / "SKILL.md"


def _fenced_delegate_commands(text: str) -> list[str]:
    commands: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and re.match(r'\s*onex delegate\s+"', line):
            commands.append(line.strip())
    return commands


def test_the_prompt_command_passes_the_session_model() -> None:
    (command,) = _fenced_delegate_commands(PROMPT_MD.read_text())
    assert "--session-model <session-model-id>" in command
    assert "--json" in command


def test_skill_md_documents_the_same_command() -> None:
    text = SKILL_MD.read_text()
    assert 'onex delegate "<prompt>" --json --session-model <session-model-id>' in text


def test_the_prompt_says_where_the_id_comes_from_and_never_to_guess() -> None:
    text = PROMPT_MD.read_text()
    section = text[text.index("- `--session-model`") :].split("\n- `", 1)[0]
    assert "exact model ID" in section
    assert "never guess" in section.lower()


def test_an_older_onex_still_delegates_without_the_flag() -> None:
    text = PROMPT_MD.read_text()
    assert "No such option: --session-model" in text
    assert "once more without `--session-model`" in text
