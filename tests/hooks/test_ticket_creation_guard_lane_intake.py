# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Lane intake: label, first-line stamp, lane identity and a closure-funded allowance (OMN-18487).

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
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from omniclaude.handlers.handler_lane_intake import load_policy

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD_PY = _REPO_ROOT / "plugins/onex/hooks/lib/ticket_creation_guard.py"
_POLICY_JSON = _REPO_ROOT / "plugins/onex/hooks/config/ticket_creation_policy.json"
_HANDLER_PY = _REPO_ROOT / "src/omniclaude/handlers/handler_lane_intake.py"

_INTAKE = load_policy(_POLICY_JSON)
_LABEL: str = _INTAKE.label
_STAMP_PREFIX: str = _INTAKE.stamp_prefix
_BUDGET = 3  # A fixture measurement, never an allowance from policy.

_BODY = (
    "Gate: OMN-16729 AC-5\n"
    "\n"
    "The board grows faster than any projection can classify it, so the manual\n"
    "sweep cannot be retired until admission is controlled.\n"
)


def _stamped(lane: str, body: str = _BODY) -> str:
    return f"{_STAMP_PREFIX} {lane}\n\n{body}"


def _create(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "team": "Omninode",
        "title": "Refuse a Linear create with no binding",
        "parentId": "OMN-16729",
        "description": _BODY,
    }
    payload.update(overrides)
    return payload


def _ledger(state: Path) -> Path:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return state / _INTAKE.state_subdir / f"{today}.jsonl"


def _budget(
    tmp_path: Path,
    *,
    created: int = 0,
    closed: int = _BUDGET,
    lane_created: int = 0,
    age: int = 1,
) -> Path:
    end = datetime.now(UTC) - timedelta(seconds=age)
    path = tmp_path / "state" / _INTAKE.budget_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "created_count": created,
                "closed_count": closed,
                "lane_created_count": lane_created,
                "window": {
                    "start": (end - timedelta(days=_INTAKE.window_days)).isoformat(),
                    "end": end.isoformat(),
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _run(
    tool_input: dict[str, object],
    tmp_path: Path,
    *,
    lane: str | None = None,
    agent_id: str | None = None,
    state: bool = True,
    flags: tuple[str, ...] = (),
    extra_env: dict[str, str] | None = None,
    extra_payload: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}
    if state:
        env["ONEX_STATE_DIR"] = str(tmp_path / "state")
    if lane is not None:
        env["ONEX_LANE"] = lane
    env.update(extra_env or {})
    payload: dict[str, object] = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": tool_input,
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    payload.update(extra_payload or {})
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


def test_measured_closure_refuses_at_capacity_with_a_clear_message(
    tmp_path: Path,
) -> None:
    _budget(tmp_path)
    ledger = _ledger(tmp_path / "state")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        "".join('{"lane": "earlier"}\n' for _ in range(_BUDGET)), encoding="utf-8"
    )
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    result = _run(ok, tmp_path, lane="lane-x")
    assert result.returncode == 3
    reason = _reason(result)
    assert "lane_intake_budget" in reason
    assert f"allowance is {_BUDGET} governed closures" in reason
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == _BUDGET


def test_the_budget_admits_up_to_it_and_refuses_the_next(tmp_path: Path) -> None:
    _budget(tmp_path)
    ledger = _ledger(tmp_path / "state")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        "".join('{"lane": "earlier"}\n' for _ in range(_BUDGET - 1)),
        encoding="utf-8",
    )
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    _admitted(_run(ok, tmp_path, lane="lane-x"))
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == _BUDGET
    assert _run(ok, tmp_path, lane="lane-x").returncode == 3


def test_admissions_outside_the_trailing_window_do_not_spend_capacity(
    tmp_path: Path,
) -> None:
    _budget(tmp_path)
    old = tmp_path / "state" / _INTAKE.state_subdir / "2020-01-01.jsonl"
    old.parent.mkdir(parents=True, exist_ok=True)
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
    assert "daily_budget" not in _INTAKE
    assert _INTAKE.window_days == 28
    assert _INTAKE.delta == 0


@pytest.mark.parametrize(
    "key",
    [
        "label",
        "stamp_prefix",
        "budget_path",
        "window_days",
        "max_age_seconds",
        "delta",
        "ratio_threshold",
        "state_subdir",
    ],
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


# ---------------------------------------------------------------------------
# A workflow subagent: harness sidecar plus its own open CLAIM (OMN-17942)
# ---------------------------------------------------------------------------

_SESSION = "0f0e0d0c-session"
_AGENT = "a5ub4gent0000001"


def _workflow_subagent(
    tmp_path: Path,
    *,
    sidecar_lane: str | None = "lane-w",
    ledger_rows: tuple[str, ...] = (),
) -> tuple[dict[str, str], dict[str, object]]:
    """The hook env and payload extras of a Mac workflow subagent.

    The harness writes ``agent-<id>.meta.json`` under the PARENT session's
    ``subagents/workflows/<run>/`` with the dispatch label (lane name, then the
    ROUTE line) as its ``description``; the payload carries ``agent_id`` and the
    parent transcript path. No ``ONEX_LANE`` is set: a subagent cannot set it.
    """
    project = tmp_path / "projects" / "-proj"
    transcript = project / f"{_SESSION}.jsonl"
    project.mkdir(parents=True, exist_ok=True)
    transcript.write_text("", encoding="utf-8")
    if sidecar_lane is not None:
        run = project / _SESSION / "subagents" / "workflows" / "wf_0001"
        run.mkdir(parents=True, exist_ok=True)
        (run / f"agent-{_AGENT}.meta.json").write_text(
            json.dumps(
                {
                    "agentType": "workflow-subagent",
                    "description": f"{sidecar_lane} ROUTE: band=B4 model=opus",
                }
            ),
            encoding="utf-8",
        )
    ledger = tmp_path / "ROLLING_WORK_LEDGER.md"
    ledger.write_text("".join(f"{row}\n" for row in ledger_rows), encoding="utf-8")
    env = {"ONEX_LEDGER_PATH": str(ledger)}
    payload = {"session_id": _SESSION, "transcript_path": str(transcript)}
    return env, payload


def _claim(lane: str, at: str = "2026-10-21T21:00:00Z") -> str:
    return f"{at} | CLAIM | lane={lane} | ticket=OMN-17942 | the lane's work"


def _terminal(lane: str, at: str = "2026-10-21T21:30:00Z") -> str:
    return f"{at} | TERMINAL | lane={lane} | ticket=OMN-17942 | outcome=done | done"


def test_a_workflow_subagent_with_an_open_claim_mints(tmp_path: Path) -> None:
    env, extra = _workflow_subagent(tmp_path, ledger_rows=(_claim("lane-w"),))
    ok = _create(description=_stamped("lane-w"), labels=[_LABEL])
    _admitted(_run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=extra))
    rows = _ledger(tmp_path / "state").read_text(encoding="utf-8").splitlines()
    assert [json.loads(r)["lane"] for r in rows] == ["lane-w"]
    assert json.loads(rows[0])["lane_source"] == "sidecar+claim"


def test_the_claimed_subagent_still_needs_its_stamp(tmp_path: Path) -> None:
    """The resolved lane is the one the stamp must name -- not any lane."""
    env, extra = _workflow_subagent(tmp_path, ledger_rows=(_claim("lane-w"),))
    wrong = _create(description=_stamped("lane-other"), labels=[_LABEL])
    result = _run(wrong, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=extra)
    assert result.returncode == 3
    reason = _reason(result)
    assert "lane_stamp_missing" in reason and f"{_STAMP_PREFIX} lane-w" in reason
    assert "lane_identity_missing" not in reason


def test_a_workflow_subagent_without_a_claim_is_refused(tmp_path: Path) -> None:
    env, extra = _workflow_subagent(tmp_path, ledger_rows=(_claim("lane-other"),))
    ok = _create(description=_stamped("lane-w"), labels=[_LABEL])
    result = _run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=extra)
    assert result.returncode == 3
    reason = _reason(result)
    assert "lane_identity_missing" in reason
    assert "no open CLAIM for lane 'lane-w'" in reason, "names the missing CLAIM"
    assert not _ledger(tmp_path / "state").exists(), "a refusal spends no budget"


def test_a_claim_closed_by_its_terminal_no_longer_names_the_lane(
    tmp_path: Path,
) -> None:
    env, extra = _workflow_subagent(
        tmp_path, ledger_rows=(_claim("lane-w"), _terminal("lane-w"))
    )
    ok = _create(description=_stamped("lane-w"), labels=[_LABEL])
    result = _run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=extra)
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)


def test_a_claim_without_a_sidecar_names_no_lane(tmp_path: Path) -> None:
    """An open CLAIM alone is not identity: the harness must name the caller."""
    env, extra = _workflow_subagent(
        tmp_path, sidecar_lane=None, ledger_rows=(_claim("lane-w"),)
    )
    ok = _create(description=_stamped("lane-w"), labels=[_LABEL])
    result = _run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=extra)
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)


def test_an_agent_id_that_is_a_path_names_no_lane(tmp_path: Path) -> None:
    env, extra = _workflow_subagent(tmp_path, ledger_rows=(_claim("lane-w"),))
    ok = _create(description=_stamped("lane-w"), labels=[_LABEL])
    result = _run(ok, tmp_path, agent_id="../x", extra_env=env, extra_payload=extra)
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)


@pytest.mark.parametrize("key", ["ONEX_LANE", "ONEX_REMOTE_LANE"])
def test_a_declared_lane_still_wins_over_the_sidecar(key: str, tmp_path: Path) -> None:
    """The remote-lane path is unchanged: its declaration names the lane, with
    no CLAIM read, even when a sidecar and a claim name another lane."""
    env, extra = _workflow_subagent(tmp_path, ledger_rows=(_claim("lane-w"),))
    env[key] = "lane-remote"
    ok = _create(description=_stamped("lane-remote"), labels=[_LABEL])
    _admitted(_run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=extra))
    row = json.loads(_ledger(tmp_path / "state").read_text("utf-8").splitlines()[0])
    assert (row["lane"], row["lane_source"]) == ("lane-remote", "env")


def test_planned_child_admitted_past_old_flat_cap_when_closures_allow(
    tmp_path: Path,
) -> None:
    """Today's old cap refused the 31st planned child despite closure capacity."""
    _budget(tmp_path, created=200, closed=100, lane_created=30)
    before_snapshot = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    _ledger(tmp_path / "state").write_text(
        "".join(
            json.dumps({"at": before_snapshot, "lane": "earlier"}) + "\n"
            for _ in range(30)
        )
    )
    ok = _create(description=_stamped("lane-plan"), labels=[_LABEL])
    _admitted(_run(ok, tmp_path, lane="lane-plan"))


def test_planned_child_refused_below_old_flat_cap_when_closures_spent(
    tmp_path: Path,
) -> None:
    _budget(tmp_path, created=1, closed=1, lane_created=1)
    ok = _create(description=_stamped("lane-plan"), labels=[_LABEL])
    result = _run(ok, tmp_path, lane="lane-plan")
    assert result.returncode == 3
    assert "lane_intake_budget" in _reason(result)


def test_yesterday_spends_the_same_trailing_allowance(tmp_path: Path) -> None:
    _budget(tmp_path, closed=1)
    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    path = _ledger(tmp_path / "state").with_name(f"{yesterday}.jsonl")
    path.write_text('{"lane": "earlier"}\n', encoding="utf-8")
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    result = _run(ok, tmp_path, lane="lane-x")
    assert result.returncode == 3
    assert "lane_intake_budget" in _reason(result)


@pytest.fixture(scope="module")
def over_threshold_budget(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _budget(tmp_path_factory.mktemp("over-threshold"), created=200, closed=100)


def _unbound() -> dict[str, object]:
    return _create(description=_stamped("lane-x", "No gate declared."), labels=[_LABEL])


def test_over_threshold_unbound_create_refused(
    over_threshold_budget: Path, tmp_path: Path
) -> None:
    result = _run(
        _unbound(),
        over_threshold_budget.parents[3],
        lane="lane-x",
        flags=("--lane-intake",),
    )
    assert result.returncode == 3
    assert "inflow_ratio" in _reason(result)


def test_over_threshold_bound_create_admitted(
    over_threshold_budget: Path, tmp_path: Path
) -> None:
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    _admitted(
        _run(
            ok,
            over_threshold_budget.parents[3],
            lane="lane-x",
            flags=("--lane-intake",),
        )
    )


def test_under_threshold_unbound_create_admitted(tmp_path: Path) -> None:
    _budget(tmp_path, created=10, closed=100)
    _admitted(_run(_unbound(), tmp_path, lane="lane-x", flags=("--lane-intake",)))


@pytest.mark.parametrize("condition", ["missing", "unreadable", "stale"])
def test_missing_unreadable_stale_budget_admits_and_records_reason(
    condition: str, tmp_path: Path
) -> None:
    if condition == "unreadable":
        path = _budget(tmp_path)
        path.unlink()
        path.mkdir()  # An OS read failure even when tests run as root.
    elif condition == "stale":
        _budget(tmp_path, age=_INTAKE.max_age_seconds + 1)
    result = _run(_unbound(), tmp_path, lane="lane-x", flags=("--lane-intake",))
    _admitted(result)
    decision = json.loads(result.stdout)
    assert decision["decision"] == "allow"
    assert condition in decision["reason"]
    row = json.loads(_ledger(tmp_path / "state").read_text().splitlines()[0])
    assert row["budget_reason"] == decision["reason"]


def test_budget_exception_does_not_weaken_existing_binding_check(
    tmp_path: Path,
) -> None:
    result = _run(_unbound(), tmp_path, lane="lane-x")
    assert result.returncode == 3
    assert "missing_gate_line" in _reason(result)


def test_new_closures_move_allowance_without_a_policy_edit(tmp_path: Path) -> None:
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    _budget(tmp_path, created=1, closed=1, lane_created=1)
    assert _run(ok, tmp_path, lane="lane-x").returncode == 3
    _budget(tmp_path, created=1, closed=2, lane_created=1)
    _admitted(_run(ok, tmp_path, lane="lane-x"))
    assert _run(ok, tmp_path, lane="lane-x").returncode == 3


def test_concurrent_creates_cannot_spend_the_last_closure_twice(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    _budget(tmp_path, closed=1)
    (tmp_path / "home").mkdir()
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _run(ok, tmp_path, lane="lane-x"), range(4)))
    assert sum(result.returncode == 0 for result in results) == 1
    assert len(_ledger(tmp_path / "state").read_text().splitlines()) == 1
    assert all(result.returncode in (0, 1, 3) for result in results)


def test_snapshot_covered_admissions_are_not_counted_twice(tmp_path: Path) -> None:
    _budget(tmp_path, created=10, closed=11, lane_created=10)
    before_snapshot = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    _ledger(tmp_path / "state").write_text(
        "".join(
            json.dumps({"at": before_snapshot, "lane": "earlier"}) + "\n"
            for _ in range(10)
        )
    )
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    _admitted(_run(ok, tmp_path, lane="lane-x"))
    assert _run(ok, tmp_path, lane="lane-x").returncode == 3


def test_malformed_journal_cannot_erase_consumed_allowance(tmp_path: Path) -> None:
    _budget(tmp_path, closed=100)
    _ledger(tmp_path / "state").write_text("not-json\n")
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    result = _run(ok, tmp_path, lane="lane-x")
    assert result.returncode == 3
    assert "trailing intake journal could not be read" in _reason(result)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("window_days", 0),
        ("window_days", True),
        ("delta", -1),
        ("max_age_seconds", 0),
        ("ratio_threshold", 0),
        ("ratio_threshold", True),
        ("budget_path", "../escape.json"),
        ("state_subdir", "/tmp/escape"),
    ],
)
def test_malformed_policy_refuses_instead_of_defaulting(
    key: str, value: object, tmp_path: Path
) -> None:
    raw = json.loads(_POLICY_JSON.read_text())
    raw["lane_intake"][key] = value
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw))
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    assert (
        _run(ok, tmp_path, lane="lane-x", flags=("--policy", str(path))).returncode == 1
    )


def test_declared_delta_is_added_to_measured_closures(tmp_path: Path) -> None:
    _budget(tmp_path, closed=0)
    raw = json.loads(_POLICY_JSON.read_text())
    raw["lane_intake"]["delta"] = 2
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(raw))
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    for _ in range(2):
        _admitted(_run(ok, tmp_path, lane="lane-x", flags=("--policy", str(policy))))
    result = _run(ok, tmp_path, lane="lane-x", flags=("--policy", str(policy)))
    assert result.returncode == 3
    assert "0 governed closures + declared delta 2" in _reason(result)


def test_zero_closures_and_zero_delta_fund_no_admissions(tmp_path: Path) -> None:
    _budget(tmp_path, closed=0)
    ok = _create(description=_stamped("lane-x"), labels=[_LABEL])
    result = _run(ok, tmp_path, lane="lane-x")
    assert result.returncode == 3
    assert "lane_intake_budget" in _reason(result)
