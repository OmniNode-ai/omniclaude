# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-23769: the Mac ticket gate refuses a raw create and a hand edit of a standard ticket.

The guard runs the way the hook runs it: ``ticket_creation_guard.py`` with the
PreToolUse payload on stdin. ``create_route`` is gated by the overlay switch;
``contract_block_edit`` (a standard ticket's contract block or title) is not.
Each refusal has a positive control beside it.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[4]
_GUARD_PY = _REPO_ROOT / "plugins/onex/hooks/lib/ticket_creation_guard.py"
_SWITCH_ENV = "ONEX_TICKET_CREATE_ROUTE_SWITCH"

_BLOCK = "```yaml onex-ticket-contract\nticket: OMN-1\ncriteria: [AC1]\n```\n"
_BODY = f"Gate: OMN-16729 AC-5\n\nWhy this ticket exists.\n\n{_BLOCK}"
_CREATE: dict[str, Any] = {
    "team": "Omninode",
    "title": "Refuse a Linear create with no binding",
    "parentId": "OMN-16729",
    "description": "Gate: OMN-16729 AC-5\n\n- [ ] AC1: it refuses -- falsifier: uv run pytest -k x\n",
}


def _payload(tool_input: dict[str, Any]) -> str:
    return json.dumps(
        {"tool_name": "mcp__linear-server__save_issue", "tool_input": tool_input}
    )


def _run_create(
    tool_input: dict[str, Any],
    tmp_path: Path,
    *,
    switch: str | None,
    flags: tuple[str, ...] = (),
    env: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """The create, run as the hook runs it, with the overlay switch set in the environment."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    run_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}
    run_env.update(env or {})
    if switch is not None:
        run_env[_SWITCH_ENV] = switch
    proc = subprocess.run(
        [sys.executable, str(_GUARD_PY), *flags],
        input=_payload(tool_input),
        capture_output=True,
        text=True,
        env=run_env,
        check=False,
    )
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else {})


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ticket_creation_guard_route", _GUARD_PY
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ticket_creation_guard_route"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def guard() -> ModuleType:
    return _load_guard()


def _run_update(
    guard: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tool_input: dict[str, Any],
    *,
    current_body: str,
    current_title: str,
    switch: str | None,
    flags: list[str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """An update through the guard's own ``main``, the tracker reads replaced by the ticket's current text."""

    monkeypatch.setattr(guard, "_fetch_issue_body", lambda _ref, _key: current_body)
    monkeypatch.setattr(
        guard, "_title_network_lookup", lambda _key: lambda _ref: current_title
    )
    monkeypatch.setenv("LINEAR_API_KEY", "test-key")
    monkeypatch.setenv("ONEX_LEDGER_PATH", "/nonexistent/ledger.md")
    if switch is None:
        monkeypatch.delenv(_SWITCH_ENV, raising=False)
    else:
        monkeypatch.setenv(_SWITCH_ENV, switch)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(_payload(tool_input)))
    monkeypatch.setattr(sys, "stdout", out)
    rc = guard.main(flags or [])
    return rc, (json.loads(out.getvalue()) if out.getvalue().strip() else {})


def test_create_route_refused_names_the_ticket_node_with_the_switch_at_refuse(
    tmp_path: Path,
) -> None:
    rc, out = _run_create(_CREATE, tmp_path, switch="refuse")
    assert rc == 3
    assert out["reason_code"] == "issue-create-raw-route-refused"
    assert "onex ticket create --draft" in out["reason"]
    assert "[create_route]" in out["reason"]


def test_create_route_refused_is_admitted_with_the_switch_at_allow_or_unset(
    tmp_path: Path,
) -> None:
    assert _run_create(_CREATE, tmp_path, switch="allow")[0] == 0
    assert _run_create(_CREATE, tmp_path, switch=None)[0] == 0


def test_create_route_refused_not_for_the_node(tmp_path: Path) -> None:
    """The node passes --node and its lane identity, label and stamp; the switch at refuse does not stop it."""
    node_create = dict(_CREATE, labels=["lane-created"])
    node_create["description"] = (
        "created-by-lane: node-lane\n\n" + _CREATE["description"]
    )
    rc, out = _run_create(
        node_create,
        tmp_path,
        switch="refuse",
        flags=("--node",),
        env={"ONEX_LANE": "node-lane"},
    )
    assert rc == 0, out
    rc, _ = _run_create(
        _CREATE, tmp_path, switch="refuse", env={"ONEX_LANE": "node-lane"}
    )
    assert rc == 3


def test_create_route_refused_reads_the_overlay_file(tmp_path: Path) -> None:
    home = tmp_path / "home" / ".omnibase"
    home.mkdir(parents=True)
    (home / "ticket_create_route_switch").write_text("refuse\n", encoding="utf-8")
    rc, out = _run_create(_CREATE, tmp_path, switch=None)
    assert rc == 3
    assert "onex ticket create --draft" in out["reason"]


def test_create_route_refused_unknown_switch_is_refused_not_read_as_allow(
    tmp_path: Path,
) -> None:
    rc, out = _run_create(_CREATE, tmp_path, switch="maybe")
    assert rc == 3
    assert "[unevaluable] route_switch" in out["reason"]


@pytest.mark.parametrize("switch", ["allow", "refuse", None])
def test_contract_block_edit_refused_whatever_the_switch(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch, switch: str | None
) -> None:
    edited = _BODY.replace("criteria: [AC1]", "criteria: [AC1, AC9]")
    rc, out = _run_update(
        guard,
        monkeypatch,
        {"id": "OMN-1", "description": edited},
        current_body=_BODY,
        current_title="Standard ticket",
        switch=switch,
    )
    assert rc == 3
    assert out["reason_code"] == "issue-update-contract-block-edit"
    assert "[contract_block_edit]" in out["reason"]
    assert "onex ticket sync" in out["reason"]


def test_contract_block_edit_refused_for_a_patch(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch = [
        {"op": "replace", "old_string": "criteria: [AC1]", "new_string": "criteria: []"}
    ]
    rc, out = _run_update(
        guard,
        monkeypatch,
        {"id": "OMN-1", "patch": patch},
        current_body=_BODY,
        current_title="Standard ticket",
        switch=None,
    )
    assert rc == 3
    assert "onex ticket sync" in out["reason"]


def test_contract_block_edit_refused_for_a_title_of_a_standard_ticket(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    rc, out = _run_update(
        guard,
        monkeypatch,
        {"id": "OMN-1", "title": "A different title"},
        current_body=_BODY,
        current_title="Standard ticket",
        switch="allow",
    )
    assert rc == 3
    assert "[contract_block_edit] title" in out["reason"]
    assert "onex ticket sync" in out["reason"]


def test_contract_block_edit_refused_not_for_edits_that_leave_block_and_title_alone(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticked = _BODY.replace(
        "Why this ticket exists.", "Why this ticket exists.\n\nA note below the block."
    )
    for tool_input in (
        {"id": "OMN-1", "description": ticked},
        {"id": "OMN-1", "title": "Standard ticket"},
        {"id": "OMN-1", "state": "In Progress"},
    ):
        rc, out = _run_update(
            guard,
            monkeypatch,
            tool_input,
            current_body=_BODY,
            current_title="Standard ticket",
            switch="refuse",
        )
        assert rc == 0, out


def test_contract_block_edit_refused_not_for_the_title_of_a_ticket_with_no_block(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    rc, out = _run_update(
        guard,
        monkeypatch,
        {"id": "OMN-2", "title": "Renamed"},
        current_body="Gate: OMN-16729 AC-5\n\nNo contract block here.\n",
        current_title="Plain ticket",
        switch="refuse",
    )
    assert rc == 0, out


def test_contract_block_edit_refused_not_for_the_node(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    edited = _BODY.replace("criteria: [AC1]", "criteria: [AC1, AC9]")
    rc, out = _run_update(
        guard,
        monkeypatch,
        {"id": "OMN-1", "description": edited, "title": "Renamed by the node"},
        current_body=_BODY,
        current_title="Standard ticket",
        switch="refuse",
        flags=["--node"],
    )
    assert rc == 0, out


def test_session_the_hook_script_refuses_a_raw_create_and_the_node_create_succeeds(
    tmp_path: Path,
) -> None:
    """AC4's two decisions through the registered hook script with the switch at refuse, then the node's own call."""
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "CLAUDE_PLUGIN_ROOT": str(_GUARD_PY.parents[2]),
        "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
        "OMNICLAUDE_MODE": "full",
        _SWITCH_ENV: "refuse",
    }
    hook = subprocess.run(
        [
            "bash",
            str(_GUARD_PY.parents[1] / "scripts/pre_tool_use_ticket_creation_gate.sh"),
        ],
        input=_payload(_CREATE),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert hook.returncode == 2, hook.stdout + hook.stderr
    decision = json.loads(hook.stdout)
    assert decision["decision"] == "block"
    assert "onex ticket create --draft" in decision["reason"]
    node_create = dict(_CREATE, labels=["lane-created"])
    node_create["description"] = (
        "created-by-lane: node-lane\n\n" + _CREATE["description"]
    )
    node = subprocess.run(
        [sys.executable, str(_GUARD_PY), "--node"],
        input=_payload(node_create),
        capture_output=True,
        text=True,
        env=dict(env, ONEX_LANE="node-lane"),
        check=False,
    )
    assert node.returncode == 0, node.stdout + node.stderr
