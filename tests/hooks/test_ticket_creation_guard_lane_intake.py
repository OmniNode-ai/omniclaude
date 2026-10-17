# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Lane intake: label, first-line stamp, lane identity and a daily budget (OMN-17942).

Every Linear item a lane opens is written through the operator's one existing
Linear key, so its author field reads as the operator's own. These tests run
the guard the way the hook runs it -- ``python ticket_creation_guard.py`` with
the PreToolUse payload on stdin -- because rules 11-14 live in a handler the
guard loads by path, and only the real command exercises that load.

Every refusal case has a positive control beside it: the same create, fixed,
is admitted, so a refusal is never a guard that refuses everything.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD_PY = _REPO_ROOT / "plugins/onex/hooks/lib/ticket_creation_guard.py"
_POLICY_JSON = _REPO_ROOT / "plugins/onex/hooks/config/ticket_creation_policy.json"
_HANDLER_PY = _REPO_ROOT / "src/omniclaude/handlers/handler_lane_intake.py"

_INTAKE: dict[str, Any] = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))[
    "lane_intake"
]
_LABEL: str = _INTAKE["label"]
_STAMP_PREFIX: str = _INTAKE["stamp_prefix"]
_BUDGET: int = _INTAKE["daily_budget"]

_BODY = (
    "Gate: OMN-16729 AC-5\n"
    "\n"
    "The board grows faster than any projection can classify it, so the manual\n"
    "sweep cannot be retired until admission is controlled.\n"
)


def _stamped(lane: str, body: str = _BODY) -> str:
    return f"{_STAMP_PREFIX} {lane}\n\n{body}"


def _create(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "team": "Omninode",
        "title": "Refuse a Linear create with no binding",
        "parentId": "OMN-16729",
        "description": _BODY,
    }
    payload.update(overrides)
    return payload


def _ledger(state: Path) -> Path:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return state / _INTAKE["state_subdir"] / f"{today}.jsonl"


def _run(
    tool_input: dict[str, Any],
    tmp_path: Path,
    *,
    lane: str | None = None,
    agent_id: str | None = None,
    state: bool = True,
    flags: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}
    if state:
        env["ONEX_STATE_DIR"] = str(tmp_path / "state")
    if lane is not None:
        env["ONEX_LANE"] = lane
    payload: dict[str, Any] = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": tool_input,
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return subprocess.run(
        [sys.executable, str(_GUARD_PY), *flags],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def _reason(result: subprocess.CompletedProcess[str]) -> str:
    return str(json.loads(result.stdout)["reason"])


def _admitted(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_persons_session_is_unchanged_by_the_lane_rules(tmp_path: Path) -> None:
    """Control: no lane marker, no label, no stamp -- admitted, nothing recorded."""
    _admitted(_run(_create(), tmp_path))
    assert not _ledger(tmp_path / "state").exists()


def test_a_lane_create_without_label_or_stamp_is_refused(tmp_path: Path) -> None:
    result = _run(_create(), tmp_path, lane="lane-x")
    assert result.returncode == 3, result.stdout + result.stderr
    reason = _reason(result)
    assert "lane_label_missing" in reason
    assert "lane_stamp_missing" in reason
    assert f"{_STAMP_PREFIX} lane-x" in reason, "the fix names the exact stamp"
    assert not _ledger(tmp_path / "state").exists(), "a refusal spends no budget"


def test_a_labelled_and_stamped_lane_create_is_admitted_and_counted(
    tmp_path: Path,
) -> None:
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    _admitted(_run(ok, tmp_path, lane="lane-x"))
    rows = _ledger(tmp_path / "state").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["lane"] == "lane-x"


def test_the_label_alone_is_not_enough(tmp_path: Path) -> None:
    result = _run(_create(labels=[_LABEL]), tmp_path, lane="lane-x")
    assert result.returncode == 3
    reason = _reason(result)
    assert "lane_stamp_missing" in reason
    assert "lane_label_missing" not in reason


def test_the_stamp_alone_is_not_enough(tmp_path: Path) -> None:
    result = _run(_create(description=_stamped("lane-x")), tmp_path, lane="lane-x")
    assert result.returncode == 3
    reason = _reason(result)
    assert "lane_label_missing" in reason
    assert "lane_stamp_missing" not in reason


def test_a_stamp_naming_another_lane_is_refused(tmp_path: Path) -> None:
    wrong = _create(description=_stamped("lane-y"), labels=[_LABEL])
    result = _run(wrong, tmp_path, lane="lane-x")
    assert result.returncode == 3
    assert "lane_stamp_missing" in _reason(result)


def test_the_stamp_must_be_the_first_line(tmp_path: Path) -> None:
    late = _create(
        description=f"Context first.\n{_STAMP_PREFIX} lane-x\n\n{_BODY}",
        labels=[_LABEL],
    )
    result = _run(late, tmp_path, lane="lane-x")
    assert result.returncode == 3
    assert "lane_stamp_missing" in _reason(result)


def test_the_label_is_matched_by_name_not_substring(tmp_path: Path) -> None:
    near = _create(description=_stamped("lane-x"), labels=[f"not-{_LABEL}"])
    result = _run(near, tmp_path, lane="lane-x")
    assert result.returncode == 3
    assert "lane_label_missing" in _reason(result)


def test_a_subagent_with_no_lane_identity_is_refused(tmp_path: Path) -> None:
    """A lane context (``agent_id``) that declares no lane has no stamp to write."""
    result = _run(_create(labels=[_LABEL]), tmp_path, agent_id="a1b2c3")
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)


def test_a_subagent_that_declares_its_lane_is_admitted(tmp_path: Path) -> None:
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    _admitted(_run(ok, tmp_path, lane="lane-x", agent_id="a1b2c3"))


def test_the_daily_budget_refuses_past_it_with_a_clear_message(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "state")
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "".join('{"lane": "earlier"}\n' for _ in range(_BUDGET)), encoding="utf-8"
    )
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    result = _run(ok, tmp_path, lane="lane-x")
    assert result.returncode == 3
    reason = _reason(result)
    assert "lane_intake_budget" in reason
    assert f"daily budget is {_BUDGET}" in reason
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == _BUDGET


def test_the_budget_admits_up_to_it_and_refuses_the_next(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "state")
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "".join('{"lane": "earlier"}\n' for _ in range(_BUDGET - 1)),
        encoding="utf-8",
    )
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    _admitted(_run(ok, tmp_path, lane="lane-x"))
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == _BUDGET
    assert _run(ok, tmp_path, lane="lane-x").returncode == 3


def test_yesterdays_admissions_do_not_spend_todays_budget(tmp_path: Path) -> None:
    old = tmp_path / "state" / _INTAKE["state_subdir"] / "2020-01-01.jsonl"
    old.parent.mkdir(parents=True)
    old.write_text("".join('{"lane": "old"}\n' for _ in range(_BUDGET)), "utf-8")
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    _admitted(_run(ok, tmp_path, lane="lane-x"))


def test_an_unmeasurable_budget_refuses_rather_than_waving_through(
    tmp_path: Path,
) -> None:
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    result = _run(ok, tmp_path, lane="lane-x", state=False)
    assert result.returncode == 3
    assert "ONEX_STATE_DIR" in _reason(result)


def test_an_update_from_a_lane_is_not_an_intake(tmp_path: Path) -> None:
    """Control: only a CREATE is an intake; a state flip passes untouched."""
    update = {"id": "OMN-17942", "state": "In Review"}
    _admitted(_run(update, tmp_path, lane="lane-x"))
    assert not _ledger(tmp_path / "state").exists()


def test_node_mode_forces_a_lane_context_whatever_the_environment(
    tmp_path: Path,
) -> None:
    ok = _create(description=_stamped("node-x"), labels=[_LABEL])
    refused = _run(ok, tmp_path, flags=("--node",))
    assert refused.returncode == 3, "no lane identity declared: refused"
    assert "lane_identity_missing" in _reason(refused)
    _admitted(_run(ok, tmp_path, lane="node-x", flags=("--node",)))


def test_a_dry_run_spends_no_budget(tmp_path: Path) -> None:
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    _admitted(_run(ok, tmp_path, lane="lane-x", flags=("--no-record",)))
    assert not _ledger(tmp_path / "state").exists()


def test_lane_intake_mode_judges_only_the_intake_rules(tmp_path: Path) -> None:
    """A node's create has no Gate line; ``--lane-intake`` must not ask for one."""
    bare = {
        "title": "[onex-repair] baseline failure",
        "description": f"{_STAMP_PREFIX} node-x\n\nno gate line here",
        "labels": [_LABEL],
    }
    _admitted(_run(bare, tmp_path, lane="node-x", flags=("--lane-intake",)))
    assert len(_ledger(tmp_path / "state").read_text("utf-8").splitlines()) == 1


def test_lane_intake_mode_refuses_an_unmarked_create(tmp_path: Path) -> None:
    bare = {"title": "t", "description": "no stamp", "labels": []}
    result = _run(bare, tmp_path, lane="node-x", flags=("--lane-intake",))
    assert result.returncode == 3
    reason = _reason(result)
    assert "lane_label_missing" in reason and "lane_stamp_missing" in reason


def test_lane_intake_mode_fails_closed_on_a_payload_it_cannot_judge(
    tmp_path: Path,
) -> None:
    result = _run({"id": "OMN-1"}, tmp_path, lane="node-x", flags=("--lane-intake",))
    assert result.returncode == 1


def test_the_shipped_policy_carries_the_lane_intake_vocabulary() -> None:
    assert _LABEL == "lane-created"
    assert _STAMP_PREFIX == "created-by-lane:"
    assert isinstance(_BUDGET, int) and _BUDGET >= 1


@pytest.mark.parametrize(
    "key", ["label", "stamp_prefix", "daily_budget", "state_subdir"]
)
def test_a_policy_missing_a_lane_intake_key_refuses_rather_than_defaulting(
    key: str, tmp_path: Path
) -> None:
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    assert key in raw["lane_intake"], "positive control: the shipped key exists"
    del raw["lane_intake"][key]
    broken = tmp_path / "policy.json"
    broken.write_text(json.dumps(raw), encoding="utf-8")
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [sys.executable, str(_GUARD_PY), "--policy", str(broken)],
        input=json.dumps(
            {"tool_name": "mcp__linear-server__save_issue", "tool_input": ok}
        ),
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "ONEX_STATE_DIR": str(tmp_path / "state"),
            "ONEX_LANE": "lane-x",
        },
        timeout=60,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr


def test_the_guard_and_handler_spell_none_of_the_lane_intake_vocabulary() -> None:
    """The label, stamp prefix and budget are policy, not Python literals."""
    for source in (_GUARD_PY, _HANDLER_PY):
        text = source.read_text(encoding="utf-8")
        for literal in (_LABEL, _STAMP_PREFIX):
            assert literal not in text, f"{literal!r} is spelled in {source.name}"
