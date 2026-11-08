# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The delegate skill does the task itself when no model answers (OMN-23166).

When every model the developer chose fails, the orchestrator ends the run with
``terminal_failure_cause: returned_to_caller`` (OMN-21264): no answer, zero savings, and
the message "do the task in this session". The skill used to tell the session to stop on
every failure, so a handed-back task was dropped. Both skill files must name
``returned_to_caller`` and tell the session to do the task, while every other failure keeps
its stop-after-the-error-line rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SKILL_DIR = Path(__file__).parent.parent / "skills" / "delegate"
FILES = {"SKILL.md": SKILL_DIR / "SKILL.md", "prompt.md": SKILL_DIR / "prompt.md"}


@pytest.mark.parametrize("name", sorted(FILES))
def test_file_names_returned_to_caller_and_the_instruction_to_do_the_task(
    name: str,
) -> None:
    text = FILES[name].read_text()
    assert "returned_to_caller" in text
    lowered = text.lower()
    assert "do the task yourself" in lowered or "does the task itself" in lowered


def test_prompt_prints_the_reason_then_does_the_task() -> None:
    text = FILES["prompt.md"].read_text()
    section = text[text.index("## When no model answers") :]
    assert "terminal_failure_reason" in section
    assert "Run: <correlation_id>" in section
    assert section.index("Print one line naming the reason") < section.index(
        "Do the task yourself"
    )


def test_other_failures_still_stop_without_an_inline_fallback() -> None:
    text = FILES["prompt.md"].read_text()
    assert "inline LLM call" in text
    assert "Any other non-`completed` status keeps the" in text
