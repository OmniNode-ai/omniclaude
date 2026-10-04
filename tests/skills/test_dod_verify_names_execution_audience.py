# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20368: /onex:dod_verify names the execution audience its backing node requires.

``node_dod_verify`` refuses with ``EXECUTION_AUDIENCE_REQUIRED`` unless the caller passes
``--execution-audience hosted|local_done_gate`` (omnimarket#3042). The skill shim listed
only ``--contract-path`` and ``--dry-run``, so every lane that followed the skill's own
command line was refused, and at least five lanes recorded the refusal as friction between
2026-09-29 and 2026-10-02.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SKILL_DIR = (
    Path(__file__).resolve().parents[2] / "plugins" / "onex" / "skills" / "dod_verify"
)
SKILL_MD = SKILL_DIR / "SKILL.md"
PROMPT_MD = SKILL_DIR / "prompt.md"

COMMAND_RE = re.compile(r"^uv run onex skill dod_verify .*$", re.MULTILINE)


def test_the_documented_command_declares_an_audience() -> None:
    commands = COMMAND_RE.findall(PROMPT_MD.read_text(encoding="utf-8"))
    assert len(commands) == 1, commands
    assert "--execution-audience <hosted|local_done_gate>" in commands[0]


def test_the_skill_front_matter_lists_the_flag_as_required() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    block = front_matter.split("- name: --execution-audience", 1)
    assert len(block) == 2, "front matter does not list --execution-audience"
    assert "required: true" in block[1].split("- name:", 1)[0]


def test_the_prompt_names_the_refusal_and_both_audiences() -> None:
    text = PROMPT_MD.read_text(encoding="utf-8")
    assert "EXECUTION_AUDIENCE_REQUIRED" in text
    assert "`hosted`" in text and "`local_done_gate`" in text
