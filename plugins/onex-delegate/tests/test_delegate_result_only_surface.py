# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The delegate skill runs `onex delegate ... --result-only` and shows only that (OMN-21088).

The customer's agent context must receive the final answer on success and one error
line on failure: no receipt JSON, no metrics, no diagnostics. The skill therefore runs
ONE plain `onex delegate "<prompt>" --result-only ...` invocation. The permission rule
is `Bash(onex delegate:*)`, so a redirect, pipe or `&&` would fall outside it and ask
on every call.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SKILL_DIR = Path(__file__).parent.parent / "skills" / "delegate"
PROMPT_MD = SKILL_DIR / "prompt.md"
SKILL_MD = SKILL_DIR / "SKILL.md"

_SHELL_OPERATORS = ("|", ">", "<<", "&&", "||", ";", "$(", "`")


def _fenced_delegate_commands(text: str) -> list[str]:
    """Every line inside a fenced block that invokes `onex delegate "<prompt>"`."""
    commands: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and re.match(r'\s*onex delegate\s+"', line):
            commands.append(line.strip())
    return commands


def test_prompt_runs_one_plain_result_only_command() -> None:
    commands = _fenced_delegate_commands(PROMPT_MD.read_text())
    assert len(commands) == 1, (
        f"prompt.md must carry exactly one `onex delegate` command, got {commands}"
    )
    command = commands[0]
    assert "--result-only" in command
    assert "--json" not in command
    assert "--human" not in command


def test_prompt_command_stays_inside_the_allow_rule() -> None:
    """`Bash(onex delegate:*)` matches a plain invocation, not a redirect or a pipe."""
    command = _fenced_delegate_commands(PROMPT_MD.read_text())[0]
    # Drop the quoted prompt and the <type>/<n> placeholders: the user's text and
    # values replace them, they are not shell syntax.
    skeleton = re.sub(r"<[a-z-]+>", "X", re.sub(r'"[^"]*"', '""', command))
    assert skeleton.startswith("onex delegate ")
    for operator in _SHELL_OPERATORS:
        assert operator not in skeleton, (
            f"{operator!r} in {command!r} falls outside Bash(onex delegate:*)"
        )
    assert "2>" not in command


def test_prompt_never_asks_for_json_parsing() -> None:
    text = PROMPT_MD.read_text()
    for stale in (
        "Parse the single JSON object",
        "result.response",
        "cost_savings_usd",
        "ModelSkillResult",
    ):
        assert stale not in text, f"prompt.md still presents the JSON result: {stale!r}"


def test_prompt_shows_stdout_as_the_answer() -> None:
    text = PROMPT_MD.read_text()
    assert "stdout" in text
    assert "answer" in text.lower()


def test_prompt_reports_the_one_error_line_on_failure() -> None:
    text = PROMPT_MD.read_text()
    assert "Error: <terminal cause>: <error_message> (receipt: <path>)" in text
    assert "non-zero" in text.lower()
    assert "inline LLM call" in text, "must keep the no-inline-fallback rule"


def test_prompt_reads_receipt_only_on_demand() -> None:
    text = PROMPT_MD.read_text()
    assert "receipt.json" in text
    section = text[text.index("receipt.json") - 400 : text.index("receipt.json") + 400]
    assert "only" in section.lower()
    for need in ("cost", "model", "attempts"):
        assert need in section.lower(), f"receipt guidance must name {need!r}"


def test_skill_description_and_prerequisites_name_result_only() -> None:
    text = SKILL_MD.read_text()
    frontmatter = text.split("---", 2)[1]
    assert "--result-only" in frontmatter
    assert "--json" not in frontmatter
    assert "ModelSkillResult" not in frontmatter
    assert "`--result-only` flag" in text
