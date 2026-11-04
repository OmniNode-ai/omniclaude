# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21262: onboarding says what happens when none of the chosen models answers.

Operator ask 2026-10-21. Under decision D3 of the delegation requirements
specification, an exhausted ladder ends `returned_to_caller`: the Claude Code
session does the task itself, with zero savings, while the provider still bills
the attempts. A developer choosing their models has to be told that before they
choose, not after a task comes back.

The notice is one fixed pair of sentences, and the same text ships in the
script, in ONBOARDING.md and in the participant email, so a developer who read
either document recognises what the run printed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.skills.test_onboarding_model_probe_omn21465 import HANDLER, SCRIPT, _function

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
ONBOARDING_MD = REPO / "plugins/onex/ONBOARDING.md"

# The operator's wording, 2026-10-21, as one line per sentence. Both sentences
# are asserted whole: a paraphrase of either is a different promise.
NOTICE = (
    "If none of the models you choose can finish a task, free or paid, the task goes "
    "back to Claude Code and Claude does it as usual.",
    "That task shows no savings, and any attempts your models made are still billed "
    "by their provider.",
)

# The first thing the model questions put on the screen, and the prompt that
# takes the answer. The notice has to precede both.
FIRST_MENU_ROW = "1) Gemini"
FIRST_PROMPT = "Choose one or more, e.g. 1,3,4:"


def _flat(text: str) -> str:
    """One space for every run of whitespace, with Markdown blockquote markers
    dropped, so a sentence the screen or the document wrapped still matches as
    the one sentence it is."""
    return re.sub(r"\s+", " ", re.sub(r"(?m)^\s*>\s?", "", text))


def _ask_models(answer: str) -> str:
    """Run ask_models with the script's own helpers and `answer` on stdin."""
    prelude = (
        "set -uo pipefail\n"
        + _function("in_list", SCRIPT)
        + _function("provider_label", SCRIPT)
        + _function("labels", SCRIPT)
        + _function("is_stored", SCRIPT)
        + "LOG=/dev/null\n"
        "say() { printf '%s\\n' \"$*\"; }\n"
        "ALL_MODELS='gemini openrouter openai ollama local openai_compatible'\n"
        "STORED=''; MODELS=''\n"
        "ollama_overrides_ours() { return 1; }\n"
        "quit_setup() { echo QUIT; exit 0; }\n"
    )
    body = _function("parse_model_choice", HANDLER) + _function("ask_models", HANDLER)
    done = subprocess.run(
        ["/bin/bash", "-c", f"{prelude}{body}\nask_models\n"],
        input=answer,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_the_notice_precedes_the_first_model_question() -> None:
    """AC1, the script half: both sentences print, in order, above the menu and
    above the prompt that takes the choice."""
    out = _flat(_ask_models("1\n"))

    for sentence in NOTICE:
        assert sentence in out, f"missing from the run: {sentence}"

    first, second = (out.index(s) for s in NOTICE)
    assert first < second, "the two sentences print out of order"

    assert FIRST_MENU_ROW in out and FIRST_PROMPT in out, out
    assert second < out.index(FIRST_MENU_ROW), (
        "the notice prints after the model menu; a developer reads it too late"
    )
    assert second < out.index(FIRST_PROMPT), (
        "the notice prints after the prompt that takes the choice"
    )

    # The questions still work: the notice is an addition, not a replacement.
    assert "You chose: Gemini" in out


def test_onboarding_md_and_the_participant_email_carry_the_same_text() -> None:
    """AC1, the document half: the same two sentences, verbatim, in the prose a
    participant reads before the run and in the email that sends them to it."""
    text = ONBOARDING_MD.read_text()

    email_heading = "### The participant email (template)"
    assert email_heading in text, (
        "the participant email template is not in ONBOARDING.md"
    )
    prose, email = (_flat(part) for part in text.split(email_heading, 1))

    for sentence in NOTICE:
        assert sentence in prose, f"missing from the ONBOARDING.md prose: {sentence}"
        assert sentence in email, f"missing from the participant email: {sentence}"
