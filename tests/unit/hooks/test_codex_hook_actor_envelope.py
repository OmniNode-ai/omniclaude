# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Codex sessions emit the shared hook envelope with ``actor=codex`` (OMN-18704).

Codex CLI 0.154.0 ships a native, Claude-Code-shaped hooks surface. This suite
proves that the *same* bus-mirror entrypoints the Claude side registers can be
registered by Codex, read Codex's hook JSON off stdin, and append to the *same*
journal with the actor stamped on the envelope.

What each test pins
-------------------
* AC3 -- the shipped Codex ``hooks.json`` registers ``SessionStart``,
  ``SessionEnd``, ``UserPromptSubmit`` and ``PostToolUse`` against the shared
  emit entrypoints, and every one of them declares its actor. Parsed, not
  eyeballed.
* AC4 (unit half) -- a Codex-shaped payload through each entrypoint lands a
  journal record carrying ``actor="codex"`` and the Codex ``session_id`` as the
  correlation id. The live half is a real Codex session; see the PR body.
* AC5 -- the Claude-side and Codex-side records agree, field by field, on every
  shared field name and JSON type, measured against the shipped envelope
  contract rather than against a hand-written list.
* Regression -- a Claude-shaped payload with no actor declaration still yields
  ``actor="claude"`` and leaves every pre-existing field byte-identical.

Why the actor is declared by the registration and never sniffed
---------------------------------------------------------------
Measured on this Mac 2026-09-18: a Codex hook process inherits the environment
of whatever launched Codex. A Codex session started from a Claude Code session
runs its hooks with ``CLAUDECODE=1`` and ``CLAUDE_CODE_SESSION_ID`` set, and
with **no** ``CODEX_*`` variable of its own. Environment sniffing would report
the wrong actor. The stdin shapes also overlap -- Codex's ``SessionEnd`` input
carries neither ``model`` nor ``turn_id``, so there is nothing there to key on
either. The registration is the only sound signal, so it is the only one used:
``--actor <value>`` on the command line, ``ONEX_HOOK_ACTOR`` in the
environment, else the Claude default.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_SCRIPTS = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts"
_CODEX_HOOKS_JSON = _REPO_ROOT / "plugins" / "onex" / "hooks" / "codex" / "hooks.json"
_ENVELOPE_CONTRACT = (
    _REPO_ROOT / "plugins" / "onex" / "hooks" / "contracts" / "hook_actor_envelope.yaml"
)

_CODEX_SESSION_ID = "01a0b512-087d-7bb3-91b1-904552969c5f"
_CODEX_TURN_ID = "01a0b512-0898-7df0-9d16-5fe4e9fd1f0f"
_CLAUDE_SESSION_ID = "9787a4a3-ec49-4819-8bdc-5044efb94550"

# Verbatim shapes, captured from a real Codex 0.154.0 session on this Mac
# (2026-09-18) by a probe hook that wrote its stdin to disk. Do not "tidy"
# these: their value is that they are what the host actually sends.
_CODEX_SESSION_START = {
    "cwd": str(_REPO_ROOT),
    "hook_event_name": "SessionStart",
    "model": "gpt-6-astra",
    "permission_mode": "bypassPermissions",
    "session_id": _CODEX_SESSION_ID,
    "source": "startup",
    "transcript_path": "/tmp/codex/rollout.jsonl",
}
_CODEX_USER_PROMPT_SUBMIT = {
    "cwd": str(_REPO_ROOT),
    "hook_event_name": "UserPromptSubmit",
    "model": "gpt-6-astra",
    "permission_mode": "bypassPermissions",
    "prompt": "Run the shell command: echo omn18704-probe. Then stop.",
    "session_id": _CODEX_SESSION_ID,
    "transcript_path": "/tmp/codex/rollout.jsonl",
    "turn_id": _CODEX_TURN_ID,
}
_CODEX_POST_TOOL_USE = {
    "cwd": str(_REPO_ROOT),
    "hook_event_name": "PostToolUse",
    "model": "gpt-6-astra",
    "permission_mode": "bypassPermissions",
    "session_id": _CODEX_SESSION_ID,
    "tool_input": {"command": "echo omn18704-probe"},
    "tool_name": "Bash",
    # Codex sends a bare string here, where Claude Code sends an object.
    "tool_response": "omn18704-probe\n",
    "tool_use_id": "exec-8f337d3e-05a8-4c10-8fad-de3c313d6c51",
    "transcript_path": "/tmp/codex/rollout.jsonl",
    "turn_id": _CODEX_TURN_ID,
}
_CODEX_SESSION_END = {
    "cwd": str(_REPO_ROOT),
    "hook_event_name": "SessionEnd",
    "reason": "other",
    "session_id": _CODEX_SESSION_ID,
    "transcript_path": "/tmp/codex/rollout.jsonl",
}

_CLAUDE_POST_TOOL_USE = {
    "session_id": _CLAUDE_SESSION_ID,
    "cwd": str(_REPO_ROOT),
    "hook_event_name": "PostToolUse",
    "tool_name": "Bash",
    "tool_input": {"command": "git status"},
    "tool_response": {"stdout": "on branch dev\n", "stderr": "", "interrupted": False},
    "duration_ms": 42,
    # Claude Code 2.1.283 sends the tool call's id on every PostToolUse; the
    # tool-executed payload carries it since OMN-19513.
    "tool_use_id": "toolu_01FAKEclaudeEnvelope",
}

_EVENT_SCRIPTS = {
    "SessionStart": "session_start_bus_mirror.sh",
    "SessionEnd": "session_end_bus_mirror.sh",
    "UserPromptSubmit": "user_prompt_submit_bus_mirror.sh",
    "PostToolUse": "post_tool_use_bus_mirror.sh",
}


def _run_hook(
    script_name: str,
    payload: dict[str, Any],
    tmp_path: Path,
    *,
    actor_argv: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Drive one bus-mirror hook against a throwaway journal, return its records.

    The hook backgrounds and disowns the append, so the journal is polled
    rather than read once -- a single read races the fork and reports a false
    empty.
    """
    journal_dir = tmp_path / "journal"
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(_REPO_ROOT)
    env["OMNICLAUDE_MODE"] = "full"
    env["ONEX_STATE_DIR"] = str(tmp_path / "onex_state")
    env["ONEX_HOOK_EMIT_JOURNAL_DIR"] = str(journal_dir)
    env["PLUGIN_PYTHON_BIN"] = sys.executable
    env.pop("ONEX_HOOK_ACTOR", None)
    if extra_env:
        env.update(extra_env)

    argv = ["bash", str(_SCRIPTS / script_name), *(actor_argv or [])]
    result = subprocess.run(
        argv,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, (
        f"{script_name} must exit 0 (fail-open). stderr: {result.stderr}"
    )

    deadline = time.monotonic() + 15.0
    records: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        if journal_dir.is_dir():
            files = sorted(p for p in journal_dir.iterdir() if p.suffix == ".json")
            if files:
                try:
                    records = [json.loads(p.read_text()) for p in files]
                except json.JSONDecodeError:
                    records = []
                if records:
                    break
        time.sleep(0.05)
    assert records, (
        f"{script_name} appended no journal record to {journal_dir}. "
        f"stderr: {result.stderr}"
    )
    return records


# --------------------------------------------------------------------------
# AC3 -- the shipped Codex registration
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_codex_hooks_json_registers_the_four_shared_emit_entrypoints() -> None:
    """AC3: parsed, not eyeballed -- all four matchers, all four scripts."""
    assert _CODEX_HOOKS_JSON.exists(), (
        f"No Codex hooks registration shipped at {_CODEX_HOOKS_JSON}"
    )
    hooks = json.loads(_CODEX_HOOKS_JSON.read_text())["hooks"]

    for event, script in _EVENT_SCRIPTS.items():
        assert event in hooks, f"Codex hooks.json registers no {event} matcher"
        commands = [
            entry["command"]
            for group in hooks[event]
            for entry in group.get("hooks", [])
        ]
        assert any(script in command for command in commands), (
            f"{event} does not invoke the shared entrypoint {script}: {commands}"
        )
        assert all("--actor codex" in command for command in commands), (
            f"{event} does not declare its actor on the command line: {commands}. "
            "The actor is declared by the registration -- it is never sniffed "
            "from the environment, which a Codex hook inherits from its parent."
        )


# --------------------------------------------------------------------------
# AC4 (unit half) -- Codex payloads land with actor=codex
# --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("event", "payload", "expected_event_type"),
    [
        ("SessionStart", _CODEX_SESSION_START, "session.started"),
        ("UserPromptSubmit", _CODEX_USER_PROMPT_SUBMIT, "prompt.submitted"),
        ("PostToolUse", _CODEX_POST_TOOL_USE, "tool.executed"),
        ("SessionEnd", _CODEX_SESSION_END, "session.ended"),
    ],
)
def test_codex_payload_lands_with_actor_codex(
    event: str,
    payload: dict[str, Any],
    expected_event_type: str,
    tmp_path: Path,
) -> None:
    """AC4: the Codex hook JSON produces a shared-journal record, actor=codex."""
    records = _run_hook(
        _EVENT_SCRIPTS[event], payload, tmp_path, actor_argv=["--actor", "codex"]
    )
    record = records[0]
    assert record["event_type"] == expected_event_type
    assert record["correlation_id"] == _CODEX_SESSION_ID, (
        "the Codex session_id must become the correlation id, unchanged"
    )
    assert record["payload"]["actor"] == "codex", (
        f"{event} record carries actor={record['payload'].get('actor')!r}, "
        "not 'codex' -- the ticket's own falsifier"
    )
    assert record["payload"]["session_id"] == _CODEX_SESSION_ID


@pytest.mark.unit
@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("UserPromptSubmit", _CODEX_USER_PROMPT_SUBMIT),
        ("PostToolUse", _CODEX_POST_TOOL_USE),
    ],
)
def test_codex_turn_id_is_carried_onto_the_envelope(
    event: str, payload: dict[str, Any], tmp_path: Path
) -> None:
    """Codex's per-turn identifier is the attribution Claude Code cannot give."""
    records = _run_hook(
        _EVENT_SCRIPTS[event], payload, tmp_path, actor_argv=["--actor", "codex"]
    )
    assert records[0]["payload"]["turn_id"] == _CODEX_TURN_ID


@pytest.mark.unit
def test_codex_post_tool_use_reports_absent_fields_as_null_not_as_zero(
    tmp_path: Path,
) -> None:
    """Codex's PostToolUse input carries no timing and no interrupt flag.

    Emitting ``0``/``false`` for those would be a measurement the host never
    made. They are explicitly null, and the envelope contract records why.
    """
    records = _run_hook(
        "post_tool_use_bus_mirror.sh",
        _CODEX_POST_TOOL_USE,
        tmp_path,
        actor_argv=["--actor", "codex"],
    )
    payload = records[0]["payload"]
    assert payload["duration_ms"] is None, (
        "Codex supplies no duration; a 0 here would read as a measured zero"
    )
    assert payload["interrupted"] is None, (
        "Codex supplies no interrupt flag; a false here would read as measured"
    )
    # The privacy invariant is unchanged for the new actor.
    assert "tool_input" not in payload
    assert "tool_response" not in payload
    assert "omn18704-probe" not in json.dumps(payload)


@pytest.mark.unit
def test_environment_alone_never_sets_the_actor_to_codex(tmp_path: Path) -> None:
    """A Codex hook inherits CLAUDECODE=1 from its parent; sniffing is unsound.

    The converse guard: a Claude-shaped invocation running in an environment
    that happens to carry Codex variables must still report ``claude``, because
    nothing but the registration decides.
    """
    records = _run_hook(
        "post_tool_use_bus_mirror.sh",
        _CLAUDE_POST_TOOL_USE,
        tmp_path,
        extra_env={
            "CODEX_HOME": str(tmp_path / "codex_home"),
            "CODEX_SESSION_ID": _CODEX_SESSION_ID,
        },
    )
    assert records[0]["payload"]["actor"] == "claude"


@pytest.mark.unit
def test_unrecognised_actor_is_never_silently_attributed(tmp_path: Path) -> None:
    """An unknown host resolves to ``unknown``, never to a plausible default.

    Defaulting an unrecognised value to ``claude`` would make a mislabelled
    record indistinguishable from a correct one.
    """
    records = _run_hook(
        "post_tool_use_bus_mirror.sh",
        _CLAUDE_POST_TOOL_USE,
        tmp_path,
        actor_argv=["--actor", "cursor"],
    )
    assert records[0]["payload"]["actor"] == "unknown"


# --------------------------------------------------------------------------
# Regression -- the Claude side is unchanged apart from the added actor
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_claude_shaped_payload_still_yields_actor_claude(tmp_path: Path) -> None:
    """No declaration means the Claude host, and every old field is untouched."""
    records = _run_hook("post_tool_use_bus_mirror.sh", _CLAUDE_POST_TOOL_USE, tmp_path)
    payload = records[0]["payload"]
    assert payload["actor"] == "claude"
    assert payload["duration_ms"] == 42, "the Claude timing must not become null"
    assert payload["interrupted"] is False, "the Claude flag must not become null"
    assert payload["tool_name"] == "Bash"
    assert payload["working_directory"] == _REPO_ROOT.name
    assert payload["hook_source"] == "post_tool_use"
    assert records[0]["correlation_id"] == _CLAUDE_SESSION_ID


# --------------------------------------------------------------------------
# AC5 -- one projection reads both
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_shared_fields_agree_in_name_and_type_across_actors(tmp_path: Path) -> None:
    """AC5: a field-by-field diff of a Claude record against a Codex one.

    Every field present on both sides must carry the same JSON type, except
    where the shipped contract declares the field nullable for that actor and
    states the reason. A field that is null with no declared reason fails here.
    """
    contract = yaml.safe_load(_ENVELOPE_CONTRACT.read_text())
    fields = contract["fields"]

    claude = _run_hook(
        "post_tool_use_bus_mirror.sh", _CLAUDE_POST_TOOL_USE, tmp_path / "claude"
    )[0]["payload"]
    codex = _run_hook(
        "post_tool_use_bus_mirror.sh",
        _CODEX_POST_TOOL_USE,
        tmp_path / "codex",
        actor_argv=["--actor", "codex"],
    )[0]["payload"]

    shared = set(claude) & set(codex)
    assert {"actor", "session_id", "tool_name", "working_directory"} <= shared, (
        f"the envelope lost a field both actors must carry: {sorted(shared)}"
    )

    mismatches: list[str] = []
    for name in sorted(shared):
        claude_value, codex_value = claude[name], codex[name]
        if type(claude_value) is type(codex_value):
            continue
        declared = fields.get(name, {})
        nullable_for = declared.get("null_for_actors", [])
        if codex_value is None and "codex" in nullable_for and declared.get("reason"):
            continue
        if claude_value is None and "claude" in nullable_for and declared.get("reason"):
            continue
        mismatches.append(
            f"{name}: claude={claude_value!r} ({type(claude_value).__name__}) "
            f"vs codex={codex_value!r} ({type(codex_value).__name__}), "
            f"undeclared in {_ENVELOPE_CONTRACT.name}"
        )
    assert not mismatches, "shared fields disagree:\n  " + "\n  ".join(mismatches)


@pytest.mark.unit
def test_every_envelope_contract_field_declares_its_actors_and_reason() -> None:
    """The contract is the reason-of-record; an undocumented null is a defect."""
    contract = yaml.safe_load(_ENVELOPE_CONTRACT.read_text())
    assert contract["actors"] == ["claude", "codex"]
    for name, declared in contract["fields"].items():
        assert declared.get("type"), f"{name} declares no type"
        assert declared.get("produced_by"), f"{name} declares no producing actors"
        if declared.get("null_for_actors"):
            assert declared.get("reason"), (
                f"{name} is nullable for {declared['null_for_actors']} with no "
                "recorded reason -- the whole point of the declaration"
            )
