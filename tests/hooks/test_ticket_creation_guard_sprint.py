# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Sprint-project admission for lane creates (OMN-25623).

RULING 2026-11-18T12:17:41Z amends the 2026-09-30 default: a lane mint lands
in the sprint project holding today's date, with its milestone and a due date
inside the sprint window. These tests run the guard the way the hook runs it
-- ``python ticket_creation_guard.py`` with the PreToolUse payload on stdin --
because the sprint rules live in a handler the guard loads by path, and only
the real command exercises that load. The tracker seam is pinned per test
(hermetic HOME, no key in the environment, ``--sprint-project`` overrides), so
nothing here reads the network.

Every refusal case has a positive control beside it: the same create, fixed,
is admitted, so a refusal is never a guard that refuses everything.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD_PY = _REPO_ROOT / "plugins/onex/hooks/lib/ticket_creation_guard.py"
_POLICY_JSON = _REPO_ROOT / "plugins/onex/hooks/config/ticket_creation_policy.json"
_HANDLER_PY = (
    _REPO_ROOT
    / "src/omniclaude/nodes/node_linear_effect/handlers/handler_lane_sprint.py"
)

_INTAKE: dict[str, Any] = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))[
    "lane_intake"
]
_LABEL: str = _INTAKE["label"]
_STAMP_PREFIX: str = _INTAKE["stamp_prefix"]

_LANE = "runx17-1611"
_TODAY = dt.datetime.now(dt.UTC).date()
_WINDOW = (_TODAY - dt.timedelta(days=2), _TODAY + dt.timedelta(days=4))
_SPRINT_NAME = f"Sprint {_WINDOW[0]} to {_WINDOW[1]}"
_SPRINT_ID = "9f0d3f21-0000-4000-8000-00000025623"
_BODY = (
    "Gate: OMN-16729 AC-5\n"
    "\n"
    "The board grows faster than any projection can classify it, so the manual\n"
    "sweep cannot be retired until admission is controlled.\n"
)


def _stamped(body: str = _BODY) -> str:
    return f"{_STAMP_PREFIX} {_LANE}\n\n{body}"


def _create(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "team": "Omninode",
        "title": "Carry one sprint ticket to done",
        "parentId": "OMN-16729",
        "description": _stamped(),
        "labels": [_LABEL],
        "project": _SPRINT_NAME,
        "milestone": "Post-Beta Hardening milestone",
        "dueDate": str(_TODAY + dt.timedelta(days=1)),
    }
    payload.update(overrides)
    return payload


def _run(
    tool_input: dict[str, Any],
    tmp_path: Path,
    *,
    lane: bool = True,
    flags: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """The guard as the hook runs it, on a machine with no tracker answer."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}
    if lane:
        env["ONEX_LANE"] = _LANE
    payload = {"tool_name": "mcp__linear-server__save_issue", "tool_input": tool_input}
    return subprocess.run(
        [sys.executable, str(_GUARD_PY), *flags],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def _codes(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def _sprint_override() -> str:
    return json.dumps(
        {
            "id": _SPRINT_ID,
            "name": _SPRINT_NAME,
            "startDate": str(_WINDOW[0]),
            "targetDate": str(_WINDOW[1]),
        }
    )


# -- AC1: no project is refused sprint_missing; today's sprint is admitted ----


def test_a_lane_create_with_no_project_is_refused_sprint_missing(
    tmp_path: Path,
) -> None:
    result = _run(_create(project=None, milestone=None, dueDate=None), tmp_path)
    assert result.returncode == 3, _codes(result)
    assert "sprint_missing" in _codes(result)


def test_the_same_create_with_the_sprint_project_is_admitted(
    tmp_path: Path,
) -> None:
    result = _run(_create(), tmp_path)
    assert result.returncode == 0, _codes(result)


def test_the_projectid_spelling_carries_the_sprint_too(tmp_path: Path) -> None:
    result = _run(
        _create(project=None, projectId=_SPRINT_NAME),
        tmp_path,
        flags=("--sprint-project", _sprint_override()),
    )
    assert result.returncode == 0, _codes(result)


def test_the_tracker_resolved_sprint_admits_its_own_id(tmp_path: Path) -> None:
    result = _run(
        _create(project=_SPRINT_ID),
        tmp_path,
        flags=("--sprint-project", _sprint_override()),
    )
    assert result.returncode == 0, _codes(result)


def test_the_tracker_resolved_sprint_refuses_another_project(
    tmp_path: Path,
) -> None:
    result = _run(
        _create(project="7ab68a44-653e-40e1-a770-b5e6a964b159"),
        tmp_path,
        flags=("--sprint-project", _sprint_override()),
    )
    assert result.returncode == 3, _codes(result)
    assert "sprint_project_not_today" in _codes(result)


def test_a_self_describing_project_outside_today_is_refused(
    tmp_path: Path,
) -> None:
    stale = (
        f"Sprint {_TODAY - dt.timedelta(days=40)} to {_TODAY - dt.timedelta(days=26)}"
    )
    result = _run(_create(project=stale), tmp_path)
    assert result.returncode == 3, _codes(result)
    assert "sprint_project_not_today" in _codes(result)


def test_an_id_shaped_project_with_no_tracker_answer_fails_closed(
    tmp_path: Path,
) -> None:
    """A lane cannot dodge the sprint rule where the tracker will not answer."""
    result = _run(_create(project="7ab68a44-653e-40e1-a770-b5e6a964b159"), tmp_path)
    assert result.returncode == 3, _codes(result)
    assert "sprint_unverified" in _codes(result)


# -- AC2: milestone and due date ride with the sprint project ----------------


def test_ticket_creation_guard_sprint_fields_milestone_missing(
    tmp_path: Path,
) -> None:
    result = _run(_create(milestone=None), tmp_path)
    assert result.returncode == 3, _codes(result)
    assert "sprint_milestone_missing" in _codes(result)


def test_ticket_creation_guard_sprint_fields_due_date_missing(
    tmp_path: Path,
) -> None:
    result = _run(_create(dueDate=None), tmp_path)
    assert result.returncode == 3, _codes(result)
    assert "sprint_due_date_missing" in _codes(result)


def test_ticket_creation_guard_sprint_fields_due_date_outside(
    tmp_path: Path,
) -> None:
    result = _run(_create(dueDate=str(_TODAY + dt.timedelta(days=30))), tmp_path)
    assert result.returncode == 3, _codes(result)
    assert "sprint_due_date_outside" in _codes(result)


def test_ticket_creation_guard_sprint_fields_all_present_admit(
    tmp_path: Path,
) -> None:
    result = _run(
        _create(dueDate=str(_TODAY + dt.timedelta(days=2))),
        tmp_path,
        flags=("--sprint-project", _sprint_override()),
    )
    assert result.returncode == 0, _codes(result)


# -- a person's create keeps the 2026-09-30 default --------------------------


def test_a_persons_create_with_a_project_is_still_refused_project_set(
    tmp_path: Path,
) -> None:
    result = _run(_create(), tmp_path, lane=False)
    assert result.returncode == 3, _codes(result)
    assert "project_set" in _codes(result)
    assert "2026-09-30T14:30:05Z" in _codes(result)


def test_a_persons_create_with_no_project_is_still_admitted(
    tmp_path: Path,
) -> None:
    result = _run(
        _create(project=None, milestone=None, dueDate=None), tmp_path, lane=False
    )
    assert result.returncode == 0, _codes(result)


# -- the resolver itself ------------------------------------------------------


def _load_handler() -> ModuleType:
    spec = importlib.util.spec_from_file_location("handler_lane_sprint", _HANDLER_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sprint_from_projects_picks_the_window_holding_today() -> None:
    handler = _load_handler()
    nodes = [
        {"id": "old", "name": "Sprint 2026-11-02 to 2026-11-08"},
        {
            "id": _SPRINT_ID,
            "name": _SPRINT_NAME,
            "startDate": str(_WINDOW[0]),
            "targetDate": str(_WINDOW[1]),
        },
    ]
    resolved = handler.sprint_from_projects(nodes, _TODAY)
    assert resolved is not None and resolved.id == _SPRINT_ID


def test_sprint_from_projects_names_carry_the_window_without_dates() -> None:
    handler = _load_handler()
    resolved = handler.sprint_from_projects([{"id": "n", "name": _SPRINT_NAME}], _TODAY)
    assert resolved is not None and resolved.start == _WINDOW[0]


def test_sprint_from_projects_with_no_window_holding_today_is_none() -> None:
    handler = _load_handler()
    assert (
        handler.sprint_from_projects(
            [{"id": "old", "name": "Sprint 2026-11-02 to 2026-11-08"}], _TODAY
        )
        is None
    )
