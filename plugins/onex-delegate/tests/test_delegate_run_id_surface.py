# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The delegate skill shows the answer, then one line naming the run (OMN-17427).

M4 board criterion C30 grades the published plugin by driving ``/onex:delegate`` through
Claude Code and parsing the Bash tool result of the ``onex delegate`` invocation for the
typed result object (``{"skill_name": "node_delegate_skill_orchestrator", ...}``) and its
``correlation_id``. The ``--result-only`` form (OMN-21088) prints the answer alone, so the
tool result carried no run id and C30 went red. The skill therefore runs ``--json``, shows
``result.response`` first, and ends with one ``Run: <correlation_id>`` line.

The probe lives in another repository, so its two parsing rules are spelled here, in
this repo, and checked against a captured ``--json`` stdout: the marker that opens the
typed object and the UUID shape of ``correlation_id``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TESTS_DIR = Path(__file__).parent
SKILL_DIR = TESTS_DIR.parent / "skills" / "delegate"
PROMPT_MD = SKILL_DIR / "prompt.md"
SKILL_MD = SKILL_DIR / "SKILL.md"
JSON_STDOUT = TESTS_DIR / "fixtures" / "delegate_json_stdout.json"

_SHELL_OPERATORS = ("|", ">", "<<", "&&", "||", ";", "$(", "`")

# The board probe's parse of a delegation tool result (the M4 board C30
# delegate probe, parse_delegation_run).
_PROBE_MARKER = re.compile(
    r'\{\s*"skill_name"\s*:\s*"node_delegate_skill_orchestrator"'
)
_PROBE_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_RUN_LINE = re.compile(r"^Run: (?P<id>\S+)$")


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


def _probe_correlation_id(tool_result: str) -> str | None:
    """What the board probe reads from the delegation's Bash tool result."""
    decoder = json.JSONDecoder()
    found: str | None = None
    for match in _PROBE_MARKER.finditer(tool_result):
        try:
            payload, _end = decoder.raw_decode(tool_result[match.start() :])
        except ValueError:
            continue
        correlation_id = payload.get("correlation_id")
        if isinstance(correlation_id, str) and _PROBE_UUID.fullmatch(correlation_id):
            found = correlation_id
    return found


def _present_section(text: str) -> str:
    return text[text.index("## Present the result") :]


def test_prompt_runs_one_plain_json_command() -> None:
    commands = _fenced_delegate_commands(PROMPT_MD.read_text())
    assert len(commands) == 1, (
        f"prompt.md must carry exactly one `onex delegate` command, got {commands}"
    )
    command = commands[0]
    assert "--json" in command, (
        "the tool result must carry the typed result and its run id"
    )
    assert "--result-only" not in command, "--result-only prints no run id (C30 red)"
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


def test_captured_json_stdout_carries_a_parseable_run_id() -> None:
    """Positive control: the `--json` stdout the skill now reads is what the probe parses."""
    stdout = JSON_STDOUT.read_text()
    run_id = _probe_correlation_id(stdout)
    assert run_id is not None
    payload = json.loads(stdout)
    assert run_id == payload["correlation_id"] == payload["result"]["correlation_id"]
    assert payload["result"]["response"], "the answer is in the same object"


def test_result_only_stdout_has_no_parseable_run_id() -> None:
    """Negative control: the answer alone, as `--result-only` prints it, parses to nothing."""
    answer = json.loads(JSON_STDOUT.read_text())["result"]["response"]
    assert _probe_correlation_id(answer) is None


def test_prompt_names_the_fields_the_output_is_built_from() -> None:
    section = _present_section(PROMPT_MD.read_text())
    assert "result.response" in section, "the answer comes from result.response"
    assert "correlation_id" in section, "the run line comes from correlation_id"


def test_prompt_shows_the_answer_first_then_one_run_line() -> None:
    section = _present_section(PROMPT_MD.read_text())
    answer_at = section.index("result.response")
    run_at = section.index("Run: <correlation_id>")
    assert answer_at < run_at, "the answer must come before the run line"
    assert "one line" in section.lower()


def test_run_line_form_is_the_probe_run_id() -> None:
    """The line the skill prints, filled from the captured result, is `Run: <uuid>`."""
    payload = json.loads(JSON_STDOUT.read_text())
    answer = payload["result"]["response"]
    output = f"{answer}\n\nRun: {payload['correlation_id']}"
    *_answer, run_line = output.splitlines()
    match = _RUN_LINE.match(run_line)
    assert match is not None
    assert _PROBE_UUID.fullmatch(match["id"])
    assert output.startswith(answer), "the answer is first"


def test_prompt_never_asks_to_dump_the_receipt_json() -> None:
    """The context shows the answer and the run line, not the typed object."""
    section = _present_section(PROMPT_MD.read_text()).lower()
    assert "do not show" in section or "never show" in section or "not show" in section
    for stale in ("cost_savings_usd", "ModelSkillResult"):
        assert stale not in PROMPT_MD.read_text()


def test_prompt_reports_the_failure_without_an_inline_fallback() -> None:
    text = PROMPT_MD.read_text()
    assert "non-zero" in text.lower()
    assert "result.error_message" in text
    assert "inline LLM call" in text, "must keep the no-inline-fallback rule"


def test_skill_description_and_prerequisites_name_json_and_run_line() -> None:
    text = SKILL_MD.read_text()
    frontmatter = text.split("---", 2)[1]
    assert "--json" in frontmatter
    assert "--result-only" not in frontmatter
    assert "Run: <correlation_id>" in text
