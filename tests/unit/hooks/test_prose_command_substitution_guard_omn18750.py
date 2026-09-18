# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
r"""Prose-sink backtick command-substitution admission gate (OMN-18750).

Why these tests exist
---------------------
On 2026-09-18 two lanes wrote a checkpoint note that quoted a command in
markdown-style backticks inside a double-quoted ``echo``. Inside double
quotes a backtick pair is command substitution, so the shell EXECUTED the
quoted text. Both notes read ``\`uv run onex\``` and both tool calls came
back carrying::

    error: Failed to spawn: `onex`
      Caused by: No such file or directory (os error 2)

The substitution's empty stdout was written into the note (the note lost the
words it was quoting) and the spawn error surfaced on the tool result, where
it read like a broken hook rather than a quoting mistake.

The damage was small only because the quoted text named a command that does
not exist. The identical construction quoting a destructive command runs it.

The command in ``INCIDENT_COMMAND`` below is the 18:21:31Z occurrence, copied
verbatim out of the session transcript with only the write target repointed.
It is the falsifier for AC1: if the guard admits it, the guard does not work.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GUARD_PY = (
    REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "prose_command_substitution_guard.py"
)

# The 2026-09-18T18:21:31Z occurrence, verbatim except for the write target.
# The two bare backticks around the quoted command are the defect: inside the
# double-quoted echo they are command substitution, not markdown.
INCIDENT_COMMAND = (
    'TS=$(date -u +%Y-%m-%dT%H:%M:%SZ) && echo "- $TS omn18086-closer-1915 DONE: '
    "OMN-18086 -> Done 18:20:13Z. Lane note: omnibase_infra/.venv lacks omnimarket "
    "= gate venv by design (OMN-17819); `uv run onex` misread again -- rule 11 now "
    'says wrapper." >> notes/checkpoint.md'
)

# The same note written correctly: the backticks are escaped, so the shell
# passes them through as literal markdown.
ESCAPED_COMMAND = INCIDENT_COMMAND.replace("`uv run onex`", "\\`uv run onex\\`")

# The same note written with single quotes around the prose.
SINGLE_QUOTED_COMMAND = (
    "echo '- lane note: `uv run onex` misread again' >> notes/checkpoint.md"
)


def _decide(command: str, cwd: str | None = None) -> tuple[int, dict]:
    """Run the decision core over one Bash command, returning (exit code, payload)."""
    payload = {
        "session_id": "omn18750-test",
        "cwd": cwd or str(REPO_ROOT),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": "test"},
    }
    proc = subprocess.run(
        [sys.executable, str(GUARD_PY)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        parsed = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        parsed = {"_raw_stdout": proc.stdout, "_raw_stderr": proc.stderr}
    return proc.returncode, parsed


@pytest.mark.unit
def test_guard_module_exists() -> None:
    """The decision core is present. A missing core is an unenforced gate."""
    assert GUARD_PY.is_file(), f"decision core absent at {GUARD_PY}"


@pytest.mark.unit
def test_ac1_refuses_the_verbatim_incident_command() -> None:
    """AC1 falsifier: the real 18:21:31Z command must be refused."""
    rc, decision = _decide(INCIDENT_COMMAND)
    assert rc == 2, f"incident command was admitted (rc={rc}): {decision}"
    assert decision.get("decision") == "block"
    reason = decision.get("reason", "")
    # The refusal has to name the text that would be executed, or a lane
    # cannot tell which backticks in a long note are the problem.
    assert "uv run onex" in reason, (
        f"refusal does not name the substituted text: {reason}"
    )
    # And it has to state both corrections.
    assert "$(" in reason, (
        f"refusal does not offer the explicit-substitution form: {reason}"
    )
    assert "escap" in reason.lower() or "single" in reason.lower(), (
        f"refusal does not offer the escaping correction: {reason}"
    )


@pytest.mark.unit
def test_ac2_admits_the_escaped_form() -> None:
    """AC2: the same note with escaped backticks is a correct command."""
    rc, decision = _decide(ESCAPED_COMMAND)
    assert rc == 0, f"escaped form was refused (rc={rc}): {decision}"
    assert decision.get("decision") == "allow"


@pytest.mark.unit
def test_ac2_admits_single_quoted_prose() -> None:
    """AC2: single quotes suppress substitution, so the prose is literal."""
    rc, decision = _decide(SINGLE_QUOTED_COMMAND)
    assert rc == 0, f"single-quoted prose was refused (rc={rc}): {decision}"


@pytest.mark.unit
def test_ac2_admits_explicit_substitution_into_a_prose_sink() -> None:
    """AC2: an intended substitution uses the explicit form and is untouched."""
    rc, decision = _decide(
        'echo "- $(date -u +%Y-%m-%dT%H:%M:%SZ) lane note" >> docs/tracking/ROLLING_WORK_LEDGER.md'
    )
    assert rc == 0, f"explicit substitution was refused (rc={rc}): {decision}"


@pytest.mark.unit
def test_ac2_admits_backtick_substitution_outside_a_prose_sink() -> None:
    """AC2: legacy backtick substitution in a non-prose command is out of scope.

    This guard is about prose being executed, not about backtick style. A
    command that computes a value and does not write prose anywhere is not
    this hazard and is deliberately not refused here.
    """
    rc, decision = _decide('REV=`git rev-parse HEAD` && echo "$REV"')
    assert rc == 0, f"non-prose backtick substitution was refused (rc={rc}): {decision}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        # ledger append through the mutex wrapper -- the documented row path
        'python3 scripts/ledger_lock.py docs/tracking/ROLLING_WORK_LEDGER.md --append "ts | NOTE | `gh pr merge --squash` was armed"',
        # a pull-request body
        'gh pr create --title "fix(OMN-1): x" --body "we replaced `rm -rf build` with a scoped clean"',
        # a commit message
        'git commit -m "docs: explain why `uv run onex` is not the entrypoint"',
        # tee into a markdown surface
        'echo "note: `uv sync` was run" | tee -a beta/tracking/today.md',
    ],
)
def test_ac1_refuses_every_prose_sink_shape(command: str) -> None:
    """AC1: the hazard is the same wherever prose is the destination."""
    rc, decision = _decide(command)
    assert rc == 2, (
        f"prose sink admitted a substitution (rc={rc}): {command} -> {decision}"
    )


@pytest.mark.unit
def test_non_bash_tool_is_not_evaluated() -> None:
    """A guard that inspects other tools' payloads would refuse prose in them."""
    payload = {
        "cwd": str(REPO_ROOT),
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"old_string": "`a`", "new_string": "`b`"},
    }
    proc = subprocess.run(
        [sys.executable, str(GUARD_PY)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout


@pytest.mark.unit
def test_unreadable_payload_naming_a_backtick_is_refused() -> None:
    """Fail closed: an unparseable payload that carries a backtick is refused.

    A payload the guard cannot read is a payload whose substitutions it cannot
    enumerate. Admitting it would make malformed input the bypass.
    """
    proc = subprocess.run(
        [sys.executable, str(GUARD_PY)],
        input="{not json at all `uv run onex`",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 2, proc.stdout


@pytest.mark.unit
def test_guard_is_registered_as_a_pretooluse_bash_hook() -> None:
    """Rule 5: detection that is not wired is advisory and gets ignored."""
    hooks_json = json.loads(
        (REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks.json").read_text()
    )
    commands = [
        hook.get("command", "")
        for matcher in hooks_json["hooks"].get("PreToolUse", [])
        for hook in matcher.get("hooks", [])
    ]
    assert any(
        "pre_tool_use_prose_command_substitution_guard.sh" in c for c in commands
    ), "the guard is not registered as a PreToolUse hook"


WRAPPER_SH = (
    REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_prose_command_substitution_guard.sh"
)


def _run_wrapper(command: str) -> subprocess.CompletedProcess[str]:
    payload = {
        "cwd": str(REPO_ROOT),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": "test"},
    }
    env = {
        **os.environ,
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT / "plugins" / "onex"),
    }
    return subprocess.run(
        ["bash", str(WRAPPER_SH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )


@pytest.mark.unit
def test_wrapper_actually_refuses_and_is_not_silently_disabled() -> None:
    """The wrapper, not just the core, has to refuse.

    This test exists because the first draft of the wrapper did not source
    error-guard.sh. Without it ``onex_hook_gate`` is not in scope, the
    ``if ! onex_hook_gate ...`` line takes the DISABLED branch on a
    command-not-found, and the guard exits 0 on every call while logging that
    it was deliberately disabled. That is precisely the shape this ticket
    exists to stop shipping, and only an end-to-end run of the wrapper catches
    it -- the decision core was correct the whole time.
    """
    result = _run_wrapper(INCIDENT_COMMAND)
    assert result.returncode == 2, (
        "the wrapper admitted the incident command; a guard that no-ops is "
        f"worse than no guard. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "uv run onex" in result.stdout


@pytest.mark.unit
def test_wrapper_admits_the_escaped_form() -> None:
    """The correct form must not cost a lane a refusal."""
    result = _run_wrapper(ESCAPED_COMMAND)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
