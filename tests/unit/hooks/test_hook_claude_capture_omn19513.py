# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""All-hooks capture producer (OMN-19513).

The operator ruled "we need all hooks captured". These tests hold the producer
to the seam the contract PR fixed first: the stdin fixtures and the three
lineage scenarios under ``tests/fixtures/hooks/claude_hook_capture``.

Planted secrets are built by concatenation and carry ``FAKE``.
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

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import hook_claude_capture as capture_mod  # noqa: E402
import hook_emit_health as health  # noqa: E402
import hook_emit_journal as journal  # noqa: E402
import hook_turn_id  # noqa: E402

from omniclaude.hooks.model_claude_hook_event import (  # noqa: E402
    ModelClaudeHookEvent,
)

pytestmark = pytest.mark.unit

_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "hooks" / "claude_hook_capture"
_CONTRACT = (
    _REPO_ROOT
    / "src"
    / "omniclaude"
    / "hooks"
    / "contracts"
    / "contract_hook_claude_capture.yaml"
)
_HOOKS_JSON = _REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks.json"
_SCRIPTS = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts"
_CAPTURE_SCRIPT = _SCRIPTS / "claude_hook_capture.sh"
_LINEAGE_KEYS = (
    "session_id",
    "agent_id",
    "agent_type",
    "is_subagent",
    "parent_tool_use_id",
    "workflow_run_id",
    "spawn_depth",
    "tool_use_id",
    "prompt_id",
    "correlation_id",
    "causation_id",
)
ANTHROPIC_FAKE = "sk-" + "ant-" + "FAKE" + "0" * 28


@pytest.fixture(autouse=True)
def _capture_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(capture_mod.OPT_OUT_ENV, raising=False)


@pytest.fixture
def jdir(tmp_path: Path) -> Path:
    directory = tmp_path / "state" / "hook_emit_journal"
    directory.mkdir(parents=True)
    _write_status(directory, ("hook.event", "tool.executed"))
    return directory


def _write_status(journal_dir: Path, types: tuple[str, ...] | None) -> None:
    health.write_status(
        journal_dir.parent / health.STATUS_FILENAME,
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=types,
        ),
    )


def _events(journal_dir: Path) -> list[dict[str, Any]]:
    return [
        dict(entry.record.payload)
        for entry in journal.list_pending(journal_dir)
        if entry.record.event_type == capture_mod.HOOK_EVENT_TYPE
    ]


def _stdin(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (_FIXTURES / "stdin" / f"{name}.json").read_text(encoding="utf-8")
    )
    return loaded


def _contract_hooks() -> list[str]:
    raw = yaml.safe_load(_CONTRACT.read_text(encoding="utf-8"))
    return [row["hook"] for row in raw["coverage"]]


# ---------------------------------------------------------------------------
# every hook type the producer is registered for maps and journals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hook",
    [h for h in _contract_hooks() if h not in capture_mod.NEVER_REGISTERED],
)
def test_every_registered_hook_type_journals_one_contract_event(
    hook: str, jdir: Path
) -> None:
    written = capture_mod.capture(_stdin(hook), journal_dir=jdir)

    assert written == 1
    (payload,) = _events(jdir)
    event = ModelClaudeHookEvent.model_validate(payload)
    assert event.hook_event_name.value == hook
    assert payload["session_id"] == event.lineage.session_id
    assert payload["turn_id"] == event.lineage.turn_id


def test_no_content_reaches_the_metadata_event(jdir: Path) -> None:
    stdin = _stdin("PostToolUse")
    stdin["tool_response"] = {"output": "private output " + ANTHROPIC_FAKE}
    stdin["tool_input"] = {"command": "printf private-input"}

    capture_mod.capture(stdin, journal_dir=jdir)

    raw = json.dumps(_events(jdir))
    assert "FAKE" not in raw
    assert "private output" not in raw
    assert "private-input" not in raw
    (payload,) = _events(jdir)
    # PostToolUse references the result; the input is PreToolUse's reference.
    assert [ref["field"] for ref in payload["content_refs"]] == ["tool_response"]


def test_content_is_scrubbed_before_it_is_hashed(jdir: Path) -> None:
    import hashlib

    clean = "value " + ANTHROPIC_FAKE
    stdin = _stdin("Stop")
    stdin["last_assistant_message"] = clean

    capture_mod.capture(stdin, journal_dir=jdir)

    (payload,) = _events(jdir)
    (ref,) = payload["content_refs"]
    assert ref["sha256"] != hashlib.sha256(clean.encode()).hexdigest()


# ---------------------------------------------------------------------------
# the refusals
# ---------------------------------------------------------------------------


def test_nothing_is_journalled_when_the_drainer_cannot_publish_hook_event(
    jdir: Path,
) -> None:
    _write_status(jdir, ("tool.executed",))
    assert capture_mod.capture(_stdin("Stop"), journal_dir=jdir) == 0
    _write_status(jdir, None)
    assert capture_mod.capture(_stdin("Stop"), journal_dir=jdir) == 0
    assert _events(jdir) == []


def test_nothing_is_journalled_when_the_operator_opts_out(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(capture_mod.OPT_OUT_ENV, "off")
    assert capture_mod.capture(_stdin("Stop"), journal_dir=jdir) == 0
    assert _events(jdir) == []


@pytest.mark.parametrize("hook", sorted(capture_mod.NEVER_REGISTERED))
def test_a_never_registered_hook_is_never_journalled(hook: str, jdir: Path) -> None:
    assert capture_mod.capture(_stdin(hook), journal_dir=jdir) == 0
    assert _events(jdir) == []


def test_input_the_contract_refuses_is_dropped_without_quoting_it(
    jdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stdin = _stdin("PreToolUse")
    del stdin["tool_use_id"]
    stdin["tool_input"] = {"command": "printf " + ANTHROPIC_FAKE}

    assert capture_mod.capture(stdin, journal_dir=jdir) == 0
    assert "FAKE" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# lineage: the three scenarios the contract fixed, replayed with real sidecars
# ---------------------------------------------------------------------------


def _sidecar(
    agent_type: str,
    depth: int,
    *,
    tool_use_id: str | None = None,
    phase: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "agentType": agent_type,
        "description": "deterministic fixture agent",
        "model": "claude-opus-4-1",
        "requestNonInteractive": True,
        "requestShape": "Agent",
        "spawnDepth": depth,
        # A key the harness may add later must not turn the parent unknown.
        "name": "fixture-lane",
    }
    if tool_use_id is not None:
        value["toolUseId"] = tool_use_id
    if phase is not None:
        value["workflowPhase"] = phase
    return value


_SCENARIO_SIDECARS: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {
    "subagent_tree": {
        "a1": ("", _sidecar("general-purpose", 1, tool_use_id="toolu_main_1")),
        "a2": ("", _sidecar("Explore", 2, tool_use_id="toolu_sub_2")),
    },
    "workflow_agent": {
        "workflow-a1": (
            "workflows/workflow-run-1",
            _sidecar("workflow-worker", 1, phase="implementation"),
        ),
    },
    "orphan_agent": {},
}


@pytest.mark.parametrize("scenario", sorted(_SCENARIO_SIDECARS))
def test_scenario_lineage_matches_the_contract_fixtures(
    scenario: str, tmp_path: Path, jdir: Path
) -> None:
    stdin_lines = (
        (_FIXTURES / "scenarios" / f"{scenario}.stdin.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    expected = [
        json.loads(line)
        for line in (_FIXTURES / "scenarios" / f"{scenario}.events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    project = tmp_path / "projects" / "-fixture"
    session_id = json.loads(stdin_lines[0])["session_id"]
    subagents = project / session_id / "subagents"
    for agent_id, (subdir, body) in _SCENARIO_SIDECARS[scenario].items():
        target = subagents / subdir if subdir else subagents
        target.mkdir(parents=True, exist_ok=True)
        (target / f"agent-{agent_id}.meta.json").write_text(json.dumps(body))

    for line in stdin_lines:
        stdin = json.loads(line)
        stdin["transcript_path"] = str(project / f"{session_id}.jsonl")
        assert capture_mod.capture(stdin, journal_dir=jdir) == 1

    got = _events(jdir)
    assert len(got) == len(expected)
    for actual, want in zip(got, expected, strict=True):
        assert actual["hook_event_name"] == want["hook_event_name"]
        for key in _LINEAGE_KEYS:
            assert actual["lineage"][key] == want["lineage"][key], (
                f"{want['hook_event_name']} lineage.{key}"
            )


def test_a_subagent_event_is_told_apart_from_the_main_thread(
    tmp_path: Path, jdir: Path
) -> None:
    main = _stdin("PostToolUse")
    sub = {**main, "agent_id": "a1", "agent_type": "general-purpose"}
    sub["tool_use_id"] = "toolu-sub"

    capture_mod.capture(main, journal_dir=jdir)
    capture_mod.capture(sub, journal_dir=jdir)

    first, second = _events(jdir)
    assert first["session_id"] == second["session_id"]
    assert (first["lineage"]["is_subagent"], second["lineage"]["is_subagent"]) == (
        False,
        True,
    )
    # No readable sidecar: the parent is unknown, never reported as the main
    # thread.
    assert second["lineage"]["parent_tool_use_id"] is None


# ---------------------------------------------------------------------------
# turns: in-turn hooks read the turn the prompt mirror opened, never open one
# ---------------------------------------------------------------------------


def test_an_in_turn_hook_carries_the_open_turn_and_allocates_none(jdir: Path) -> None:
    stdin = _stdin("PostToolUse")
    session = stdin["session_id"]
    turn_dir = hook_turn_id.turn_dir_for(jdir)
    opened = hook_turn_id.resolve_turn_id(
        turn_dir, event_type="prompt.submitted", session_id=session, host_turn_id=None
    )

    capture_mod.capture(stdin, journal_dir=jdir)
    capture_mod.capture(stdin, journal_dir=jdir)

    assert [e["lineage"]["turn_id"] for e in _events(jdir)] == [opened, opened]
    assert hook_turn_id.peek_turn_id(turn_dir, session) == opened


def test_session_lifecycle_hooks_carry_no_turn(jdir: Path) -> None:
    for hook in ("SessionStart", "SessionEnd", "Setup"):
        capture_mod.capture(_stdin(hook), journal_dir=jdir)
    assert [e["lineage"]["turn_id"] for e in _events(jdir)] == [None, None, None]


def test_the_harness_version_comes_from_its_exec_path_or_agent_tag() -> None:
    assert (
        capture_mod.claude_code_version({"CLAUDE_CODE_EXECPATH": "/x/versions/2.1.283"})
        == "2.1.283"
    )
    assert (
        capture_mod.claude_code_version({"AI_AGENT": "claude-code_2-1-282_agent"})
        == "2.1.282"
    )
    assert capture_mod.claude_code_version({}) is None


# ---------------------------------------------------------------------------
# registration: every covered hook, and only through the observer
# ---------------------------------------------------------------------------


def _registered_events(script: str) -> dict[str, list[str | None]]:
    hooks = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    found: dict[str, list[str | None]] = {}
    for event, groups in hooks.items():
        for group in groups:
            for entry in group["hooks"]:
                if entry["command"].endswith(f"/{script}"):
                    found.setdefault(event, []).append(group.get("matcher"))
    return found


def test_hooks_json_registers_the_capture_for_every_covered_hook() -> None:
    registered = _registered_events("claude_hook_capture.sh")
    expected = {
        h
        for h in _contract_hooks()
        if h not in capture_mod.NEVER_REGISTERED and h != "UserPromptSubmit"
    }
    assert set(registered) == expected
    assert all(len(matchers) == 1 for matchers in registered.values())
    # UserPromptSubmit is captured inside its bus mirror, after the turn opens.
    mirror = (_SCRIPTS / "user_prompt_submit_bus_mirror.sh").read_text()
    assert "hook_claude_capture.py" in mirror
    assert "UserPromptSubmit" in _registered_events("user_prompt_submit_bus_mirror.sh")


def test_every_contract_hook_is_either_captured_or_named_never() -> None:
    covered = set(_registered_events("claude_hook_capture.sh")) | {"UserPromptSubmit"}
    assert covered | set(capture_mod.NEVER_REGISTERED) == set(_contract_hooks())
    assert len(_contract_hooks()) == 33


# ---------------------------------------------------------------------------
# the hook script: silent, never blocks, returns before the capture runs
# ---------------------------------------------------------------------------


def _run_script(tmp_path: Path, payload: dict[str, Any]) -> tuple[float, Path]:
    marker = tmp_path / "argv.txt"
    stub = tmp_path / "fake_python.sh"
    stub.write_text(
        f'#!/bin/bash\nsleep 1\nprintf "%s\\n" "$@" > "{marker}"\n'
        "cat >/dev/null\nsleep 4\n"
    )
    stub.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
            "OMNICLAUDE_MODE": "full",
            "ONEX_STATE_DIR": str(tmp_path / "onex_state"),
            "PLUGIN_PYTHON_BIN": str(stub),
        }
    )
    started = time.monotonic()
    result = subprocess.run(
        ["bash", str(_CAPTURE_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
        timeout=30,
        env=env,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 0
    assert result.stdout == ""
    return elapsed, marker


def test_the_capture_script_is_silent_and_returns_before_the_capture(
    tmp_path: Path,
) -> None:
    elapsed, marker = _run_script(
        tmp_path, {"hook_event_name": "SubagentStop", "session_id": "s"}
    )
    assert elapsed < 3.0
    assert not marker.exists()
    deadline = time.monotonic() + 5.0
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.read_text().splitlines()[0].endswith("hook_claude_capture.py")


def test_session_end_returns_at_once_too(tmp_path: Path) -> None:
    # OMN-19537 probe (Claude Code 2.1.283): a headless session cancels a
    # SessionEnd hook still running after about 1.5 s and kills its process
    # group, while a disowned child of a hook that already returned survives.
    # So SessionEnd must return at once like every other hook.
    elapsed, marker = _run_script(
        tmp_path, {"hook_event_name": "SessionEnd", "session_id": "s"}
    )
    assert elapsed < 1.0
    deadline = time.monotonic() + 5.0
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists()


# ---------------------------------------------------------------------------
# the fan-out redaction: the lineage crosses member by member, not as a digest
# ---------------------------------------------------------------------------


def test_the_redaction_mirror_passes_the_lineage_and_hashes_the_undeclared(
    jdir: Path,
) -> None:
    from omniclaude.hooks.capture_redaction import redact_capture
    from omniclaude.hooks.topics import TopicBase

    capture_mod.capture(
        {**_stdin("PostToolUse"), "agent_id": "a1", "agent_type": "Explore"},
        journal_dir=jdir,
    )
    (payload,) = _events(jdir)
    payload["payload"] = {**payload["payload"], "surprise": "undeclared"}

    out = redact_capture(payload, topic=TopicBase.HOOK_EVENT.value)

    assert out["lineage"] == payload["lineage"]
    assert out["lineage"]["agent_id"] == "a1"
    assert out["payload"]["tool_name"] == payload["payload"]["tool_name"]
    assert str(out["payload"]["surprise"]).startswith("sha256:")
    assert out["redaction_state"] == "redacted"
