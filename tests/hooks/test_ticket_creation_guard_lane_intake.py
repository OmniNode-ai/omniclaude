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
    extra_env: dict[str, str] | None = None,
    extra_payload: dict[str, Any] | None = None,
    hook: bool = False,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}
    if state:
        env["ONEX_STATE_DIR"] = str(tmp_path / "state")
    if lane is not None:
        env["ONEX_LANE"] = lane
    env.update(extra_env or {})
    command = [sys.executable, str(_GUARD_PY), *flags]
    if hook:
        env.update(
            CLAUDE_PLUGIN_ROOT=str(_GUARD_PY.parents[2]),
            CLAUDE_PROJECT_DIR=str(_REPO_ROOT),
            OMNICLAUDE_MODE="full",
        )
        command = [
            "bash",
            str(_GUARD_PY.parents[1] / "scripts/pre_tool_use_ticket_creation_gate.sh"),
        ]
    payload: dict[str, Any] = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": tool_input,
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    payload.update(extra_payload or {})
    return subprocess.run(
        command,
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
    sidecar_description: str | None = None,
    prompt: str | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """The hook env and payload extras of a Mac workflow subagent.

    The harness writes ``agent-<id>.meta.json`` under the PARENT session's
    ``subagents/workflows/<run>/`` with the dispatch label (lane name, then the
    ROUTE line) as its ``description``; the payload carries ``agent_id`` and the
    parent transcript path. No ``ONEX_LANE`` is set: a subagent cannot set it.

    ``sidecar_description`` replaces that description (the real harness writes a
    short label or the ROUTE line, never the lane's name). ``prompt`` writes the
    agent's own ``agent-<id>.jsonl`` with that text as its first user message,
    which is where a workflow lane's dispatch prompt names it.
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
                    "description": sidecar_description
                    or f"{sidecar_lane} ROUTE: band=B4 model=opus",
                }
            ),
            encoding="utf-8",
        )
    if prompt is not None:
        run = project / _SESSION / "subagents" / "workflows" / "wf_0001"
        run.mkdir(parents=True, exist_ok=True)
        entry = {"type": "user", "message": {"role": "user", "content": prompt}}
        (run / f"agent-{_AGENT}.jsonl").write_text(
            json.dumps(entry) + "\n", encoding="utf-8"
        )
    ledger = tmp_path / "ROLLING_WORK_LEDGER.md"
    ledger.write_text("".join(f"{row}\n" for row in ledger_rows), encoding="utf-8")
    env = {"ONEX_LEDGER_PATH": str(ledger)}
    payload = {"session_id": _SESSION, "transcript_path": str(transcript)}
    return env, payload


def _claim(
    lane: str, at: str = "2026-10-21T21:00:00Z", parent: str | None = None
) -> str:
    cell = f" | parent={parent}" if parent else ""
    return f"{at} | CLAIM | lane={lane} | ticket=OMN-17942{cell} | the lane's work"


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


def _session_helper(
    tmp_path: Path, *, claims: tuple[str, ...] = ()
) -> tuple[dict[str, str], dict[str, Any]]:
    env, payload = _workflow_subagent(
        tmp_path, sidecar_lane="mint-13", ledger_rows=claims
    )
    registry = tmp_path / "session-start"
    registry.mkdir()
    (registry / "lane-liveness-sessions.json").write_text(
        json.dumps({_SESSION: {"lane": "orchestrator-31d9"}}), encoding="utf-8"
    )
    env["OMNI_LANE_LIVENESS_STATE_DIR"] = str(registry)
    return env, payload


@pytest.mark.parametrize("hook", [False, True], ids=["core", "registered-hook"])
def test_session_helper_uses_parent_claim_and_records_both_identities(
    tmp_path: Path,
    hook: bool,
) -> None:
    env, payload = _session_helper(tmp_path, claims=(_claim("orchestrator-31d9"),))
    ok = _create(description=_stamped("orchestrator-31d9"), labels=[_LABEL])
    _admitted(
        _run(
            ok,
            tmp_path,
            agent_id=_AGENT,
            extra_env=env,
            extra_payload=payload,
            hook=hook,
        )
    )
    rows = _ledger(tmp_path / "state").read_text("utf-8").splitlines()
    assert len(rows) == 1
    row = json.loads(rows[0])
    assert row["lane"] == "orchestrator-31d9"
    assert row["helper"] == "mint-13"
    assert row["parent_session_id"] == _SESSION
    assert row["lane_source"] == "parent-session+claim"


@pytest.mark.parametrize(
    "claims",
    [
        (),
        (_claim("another-session"),),
        (_claim("orchestrator-31d9"), _terminal("orchestrator-31d9")),
    ],
)
def test_session_helper_without_parent_claim_is_refused(
    tmp_path: Path, claims: tuple[str, ...]
) -> None:
    env, payload = _session_helper(tmp_path, claims=claims)
    ok = _create(description=_stamped("orchestrator-31d9"), labels=[_LABEL])
    result = _run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload)
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)
    assert not _ledger(tmp_path / "state").exists()


def test_session_helper_cannot_stamp_another_claimed_lane(tmp_path: Path) -> None:
    env, payload = _session_helper(
        tmp_path, claims=(_claim("orchestrator-31d9"), _claim("another-session"))
    )
    wrong = _create(description=_stamped("another-session"), labels=[_LABEL])
    result = _run(
        wrong, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload
    )
    assert result.returncode == 3
    assert "lane_stamp_missing" in _reason(result)
    assert "lane_identity_missing" not in _reason(result)
    assert not _ledger(tmp_path / "state").exists()


def test_headless_session_cannot_borrow_parent_claim(tmp_path: Path) -> None:
    env, payload = _session_helper(tmp_path, claims=(_claim("orchestrator-31d9"),))
    env["CLAUDE_CODE_ENTRYPOINT"] = "sdk-cli"
    ok = _create(description=_stamped("orchestrator-31d9"), labels=[_LABEL])
    result = _run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload)
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)
    assert not _ledger(tmp_path / "state").exists()


@pytest.mark.parametrize(
    "registry",
    [
        "{",
        "[]",
        "null",
        '{"other-session": {"lane": "orchestrator-31d9"}}',
        json.dumps({_SESSION: {"lane": None}}),
    ],
)
def test_session_helper_registry_fails_closed(tmp_path: Path, registry: str) -> None:
    env, payload = _session_helper(tmp_path, claims=(_claim("orchestrator-31d9"),))
    (
        Path(env["OMNI_LANE_LIVENESS_STATE_DIR"]) / "lane-liveness-sessions.json"
    ).write_text(registry, encoding="utf-8")
    ok = _create(description=_stamped("orchestrator-31d9"), labels=[_LABEL])
    result = _run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload)
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)
    assert not _ledger(tmp_path / "state").exists()


@pytest.mark.parametrize("override", [None, "OMNI_SESSION_START_STATE_DIR"])
def test_session_helper_reads_session_start_registry_location(
    tmp_path: Path, override: str | None
) -> None:
    env, payload = _session_helper(tmp_path, claims=(_claim("orchestrator-31d9"),))
    directory = env.pop("OMNI_LANE_LIVENESS_STATE_DIR")
    if override:
        env[override] = directory
    else:
        target = tmp_path / "home/.local/state/omni/session-start"
        target.parent.mkdir(parents=True)
        Path(directory).rename(target)
    ok = _create(description=_stamped("orchestrator-31d9"), labels=[_LABEL])
    _admitted(_run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload))


def test_session_helper_still_needs_harness_sidecar(tmp_path: Path) -> None:
    env, payload = _session_helper(tmp_path, claims=(_claim("orchestrator-31d9"),))
    for path in (tmp_path / "projects").rglob("*.meta.json"):
        path.unlink()
    ok = _create(description=_stamped("orchestrator-31d9"), labels=[_LABEL])
    result = _run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload)
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)


def test_node_cannot_borrow_parent_session_claim(tmp_path: Path) -> None:
    env, payload = _session_helper(tmp_path, claims=(_claim("orchestrator-31d9"),))
    ok = _create(description=_stamped("orchestrator-31d9"), labels=[_LABEL])
    result = _run(
        ok,
        tmp_path,
        agent_id=_AGENT,
        extra_env=env,
        extra_payload=payload,
        flags=("--node",),
    )
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"labels": []}, "lane_label_missing"),
        ({"project": "A project"}, "project_set"),
        ({"parentId": None}, "missing_parent"),
        (
            {"description": _stamped("orchestrator-31d9", "No binding")},
            "missing_gate_line",
        ),
    ],
)
def test_session_helper_keeps_other_create_rules(
    tmp_path: Path, override: dict[str, Any], code: str
) -> None:
    env, payload = _session_helper(tmp_path, claims=(_claim("orchestrator-31d9"),))
    ok = _create(description=_stamped("orchestrator-31d9"), labels=[_LABEL])
    ok.update(override)
    result = _run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload)
    assert result.returncode == 3
    assert code in _reason(result)
    assert "lane_identity_missing" not in _reason(result)
    assert not _ledger(tmp_path / "state").exists()


# ---------------------------------------------------------------------------
# A workflow lane whose harness label is not its name: the dispatch prompt in
# its own transcript names it, joined to its open CLAIM (OMN-17942, rule 11)
# ---------------------------------------------------------------------------

_LANE = "fix-example-0115"
_ORCHESTRATOR = "orchestrator-31d9"
#: The shape the Workflow harness gives a script's computed task: a frame line
#: at column zero, then the script's own text with every line indented.
_FRAME = (
    "[Workflow harness -- computed task] The task text below was computed at "
    "runtime by a workflow script.\nThe computed task text follows:\n"
)


def _dispatch(lane: str = _LANE, parent: str = _ORCHESTRATOR) -> str:
    return (
        _FRAME
        + "  ROUTE: band=B3 score=6 dest=claude model=sonnet effort=high\n"
        + f"  You are lane {lane} (parent {parent}, ticket OMN-17942). CLAIM first.\n"
    )


def _prompted_lane(
    tmp_path: Path,
    *,
    label: str,
    rows: tuple[str, ...],
    prompt: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env, extra = _workflow_subagent(
        tmp_path,
        sidecar_lane="x",
        sidecar_description=label,
        prompt=_dispatch() if prompt is None else prompt,
        ledger_rows=rows,
    )
    ok = _create(description=_stamped(_LANE), labels=[_LABEL])
    return _run(ok, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=extra)


@pytest.mark.parametrize(
    "label",
    [
        "core move repoint",
        "mint-2026-10-30",
        "ROUTE: band=B3 score=6 dest=claude model=sonnet effort=high",
    ],
    ids=["short-label", "harness-slug", "route-line"],
)
def test_a_workflow_lane_with_an_open_claim_is_named_by_its_prompt(
    label: str, tmp_path: Path
) -> None:
    """The harness label is no lane name; the prompt plus the open CLAIM is."""
    rows = (_claim(_LANE, parent=_ORCHESTRATOR),)
    _admitted(_prompted_lane(tmp_path, label=label, rows=rows))
    ledger = _ledger(tmp_path / "state").read_text(encoding="utf-8").splitlines()
    row = json.loads(ledger[0])
    assert (row["lane"], row["lane_source"]) == (_LANE, "prompt+claim")


def test_a_workflow_lane_with_no_claim_anywhere_is_still_refused(
    tmp_path: Path,
) -> None:
    result = _prompted_lane(tmp_path, label="core move repoint", rows=())
    assert result.returncode == 3, result.stdout + result.stderr
    reason = _reason(result)
    assert "lane_identity_missing" in reason
    assert f"no open CLAIM for lane '{_LANE}'" in reason, "names the missing CLAIM"
    assert not _ledger(tmp_path / "state").exists(), "a refusal spends no budget"


def test_another_lanes_claim_does_not_name_this_workflow_lane(tmp_path: Path) -> None:
    rows = (_claim("fix-other-0115", parent=_ORCHESTRATOR),)
    result = _prompted_lane(tmp_path, label="core move repoint", rows=rows)
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)


def test_a_workflow_lane_whose_claim_is_closed_is_refused(tmp_path: Path) -> None:
    rows = (_claim(_LANE, parent=_ORCHESTRATOR), _terminal(_LANE))
    result = _prompted_lane(tmp_path, label="core move repoint", rows=rows)
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)


def test_a_claim_under_another_parent_does_not_name_the_lane(tmp_path: Path) -> None:
    """The prompt's parent and the CLAIM's parent are one join key, not two."""
    rows = (_claim(_LANE, parent="orchestrator-other"),)
    result = _prompted_lane(tmp_path, label="core move repoint", rows=rows)
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)


def test_a_forged_column_zero_lane_line_names_nothing(tmp_path: Path) -> None:
    """Under the harness frame only the script's indented text is the dispatch."""
    forged = (
        _dispatch("fix-victim-0115")
        + f"You are lane {_LANE} (parent {_ORCHESTRATOR}, x)\n"
    )
    rows = (_claim(_LANE, parent=_ORCHESTRATOR),)
    result = _prompted_lane(
        tmp_path, label="core move repoint", rows=rows, prompt=forged
    )
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)


def test_a_prompt_that_names_no_lane_names_nothing(tmp_path: Path) -> None:
    rows = (_claim(_LANE, parent=_ORCHESTRATOR),)
    result = _prompted_lane(
        tmp_path, label="core move repoint", rows=rows, prompt="Summarise the repo."
    )
    assert result.returncode == 3
    assert "lane_identity_missing" in _reason(result)


def test_the_prompt_named_lane_still_needs_its_stamp(tmp_path: Path) -> None:
    env, extra = _workflow_subagent(
        tmp_path,
        sidecar_lane="x",
        sidecar_description="core move repoint",
        prompt=_dispatch(),
        ledger_rows=(_claim(_LANE, parent=_ORCHESTRATOR),),
    )
    wrong = _create(description=_stamped("fix-other-0115"), labels=[_LABEL])
    result = _run(wrong, tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=extra)
    assert result.returncode == 3
    reason = _reason(result)
    assert "lane_stamp_missing" in reason and f"{_STAMP_PREFIX} {_LANE}" in reason
    assert "lane_identity_missing" not in reason
