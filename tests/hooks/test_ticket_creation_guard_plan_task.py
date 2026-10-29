# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A create that cites an approved plan task spends no lane budget (OMN-17942).

RULING 2026-10-29T10:59:39Z (lane=orchestrator-31d9): tickets from an approved
plan are exempt from the daily lane ticket budget; the budget stays for
lane-invented tickets. The exemption is verified, not asserted: the create names
a plan file and a task id, and the guard admits it only if that file is at
``origin/main`` of the local plan-repository clone and the id opens a
task line in it. These tests run the real guard command against a throwaway
clone, with no network.

Every refusal has a positive control: the same create with a true citation is
admitted, so a refusal is never a guard that refuses everything.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.hooks.test_ticket_creation_guard_lane_intake import (
    _BODY,
    _BUDGET,
    _GUARD_PY,
    _HANDLER_PY,
    _INTAKE,
    _LABEL,
    _POLICY_JSON,
    _STAMP_PREFIX,
    _admitted,
    _create,
    _ledger,
    _reason,
    _run,
)

pytestmark = pytest.mark.unit

_CLONE_ENV: str = _INTAKE["plan_task_exemption"]["clone_env"]
_PLAN = "beta/plans/2026-10-28-example-plan.md"
_PLAN_TEXT = """# Example plan

## Task 1: Wire the first thing

Body of the first task.

**T0.1 Private vocabulary resolution (UPDATE).**
- Acceptance: falsifier named.

### D.5 The new and extended tasks

- **T0.3 K1 handler_di (NEW ticket).** -- falsifier: the fixtures.
- **T4.1a K6 T and N (OMN-21463)** and **T4.1b K6 O, G, F (NEW ticket).**

```
**T9.9 inside a fence is not a task**
```

Depends on: T0.1 (prose naming a task is not a task line).
"""


def _git(clone: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(clone), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        # A full replacement env: a GIT_DIR inherited from a git hook would
        # retarget the real worktree instead of the throwaway clone.
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(clone),
        },
    )


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    """A clone whose ``origin/main`` holds the plan; an unmerged plan sits on a branch."""
    clone = tmp_path / "kb"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "main")
    (clone / _PLAN).parent.mkdir(parents=True)
    (clone / _PLAN).write_text(_PLAN_TEXT, encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "plan")
    _git(clone, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(clone, "checkout", "-q", "-b", "draft")
    draft = clone / "beta/plans/2026-10-29-unmerged-plan.md"
    draft.write_text("**T7.7 Only on a branch.**\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "draft plan")
    return clone


def _cited(task: str, path: str = _PLAN, lane: str = "lane-x") -> dict[str, object]:
    return _create(
        description=f"{_STAMP_PREFIX} {lane}\nPlan task: {path} {task}\n\n{_BODY}",
        labels=[_LABEL],
    )


def _env(kb: Path) -> dict[str, str]:
    return {_CLONE_ENV: str(kb)}


def _seed_spent(tmp_path: Path, count: int) -> Path:
    ledger = _ledger(tmp_path / "state")
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "".join('{"lane": "earlier"}\n' for _ in range(count)), encoding="utf-8"
    )
    return ledger


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize(
    "task", ["T0.1", "T0.3", "T4.1a", "T4.1b", "Task 1"], ids=lambda t: t
)
def test_a_plan_backed_create_is_admitted(task: str, tmp_path: Path, kb: Path) -> None:
    _admitted(_run(_cited(task), tmp_path, lane="lane-x", extra_env=_env(kb)))


def test_a_plan_backed_create_is_admitted_past_the_exhausted_budget(
    tmp_path: Path, kb: Path
) -> None:
    ledger = _seed_spent(tmp_path, _BUDGET)
    _admitted(_run(_cited("T0.3"), tmp_path, lane="lane-x", extra_env=_env(kb)))
    assert _lines(ledger) == _BUDGET, "the count is unchanged by a plan-backed create"


def test_a_plan_backed_create_leaves_the_count_unchanged_and_is_audited(
    tmp_path: Path, kb: Path
) -> None:
    ledger = _seed_spent(tmp_path, 3)
    _admitted(_run(_cited("T0.1"), tmp_path, lane="lane-x", extra_env=_env(kb)))
    assert _lines(ledger) == 3
    audit = ledger.with_name(f"{ledger.stem}.plan{ledger.suffix}")
    entry = json.loads(audit.read_text(encoding="utf-8"))
    assert (entry["plan_path"], entry["plan_task"], entry["lane"]) == (
        _PLAN,
        "T0.1",
        "lane-x",
    )


def test_a_lane_create_with_no_citation_still_spends_the_budget(
    tmp_path: Path, kb: Path
) -> None:
    ledger = _seed_spent(tmp_path, _BUDGET - 1)
    plain = _create(description=f"{_STAMP_PREFIX} lane-x\n\n{_BODY}", labels=[_LABEL])
    _admitted(_run(plain, tmp_path, lane="lane-x", extra_env=_env(kb)))
    assert _lines(ledger) == _BUDGET, "a lane-invented create spends one"
    refused = _run(plain, tmp_path, lane="lane-x", extra_env=_env(kb))
    assert refused.returncode == 3
    assert "lane_intake_budget" in _reason(refused)
    assert _lines(ledger) == _BUDGET


@pytest.mark.parametrize(
    ("task", "path", "missing"),
    [
        ("T9.9", _PLAN, "has no task 'T9.9'"),
        ("T0.9", _PLAN, "has no task 'T0.9'"),
        ("Depends", _PLAN, "has no task 'Depends'"),
        ("T7.7", "beta/plans/2026-10-29-unmerged-plan.md", "is not at origin/main"),
        ("T0.1", "beta/plans/2026-10-28-no-such-plan.md", "is not at origin/main"),
        ("T0.1", "../etc/plans/passwd.md", "is not the path of a plan file"),
        ("T0.1", "beta/requirements/the-prd.md", "is not the path of a plan file"),
    ],
)
def test_a_fake_citation_is_refused_naming_what_is_missing(
    task: str, path: str, missing: str, tmp_path: Path, kb: Path
) -> None:
    ledger = _seed_spent(tmp_path, 2)
    result = _run(_cited(task, path), tmp_path, lane="lane-x", extra_env=_env(kb))
    assert result.returncode == 3, result.stdout + result.stderr
    reason = _reason(result)
    assert "plan_citation_unverified" in reason
    assert missing in reason
    assert "lane_intake_budget" not in reason
    assert _lines(ledger) == 2, "a refusal spends no budget"


def test_a_citation_is_refused_when_no_clone_resolves(tmp_path: Path) -> None:
    result = _run(
        _cited("T0.1"),
        tmp_path,
        lane="lane-x",
        extra_env={_CLONE_ENV: str(tmp_path / "nowhere")},
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "no plan-repository clone resolves" in _reason(result)


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("Plan task: " + _PLAN + " T0.1", "exactly one plan task"),
        ("Plan task: " + _PLAN, "no task id"),
    ],
)
def test_a_malformed_citation_is_refused(
    extra: str, message: str, tmp_path: Path, kb: Path
) -> None:
    description = f"{_STAMP_PREFIX} lane-x\nPlan task: {_PLAN} T0.3\n{extra}\n\n{_BODY}"
    if message == "no task id":
        description = f"{_STAMP_PREFIX} lane-x\n{extra}\n\n{_BODY}"
    result = _run(
        _create(description=description, labels=[_LABEL]),
        tmp_path,
        lane="lane-x",
        extra_env=_env(kb),
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert message in _reason(result)


def test_a_citation_does_not_excuse_the_label_or_the_stamp(
    tmp_path: Path, kb: Path
) -> None:
    unlabelled = _cited("T0.1")
    unlabelled["labels"] = []
    result = _run(unlabelled, tmp_path, lane="lane-x", extra_env=_env(kb))
    assert result.returncode == 3
    assert "lane_label_missing" in _reason(result)
    wrong_stamp = _cited("T0.1", lane="lane-y")
    result = _run(wrong_stamp, tmp_path, lane="lane-x", extra_env=_env(kb))
    assert result.returncode == 3
    assert "lane_stamp_missing" in _reason(result)


def test_a_persons_session_citing_a_plan_is_not_checked(
    tmp_path: Path,
) -> None:
    """Control: the budget binds lanes only, so a person's create is not read."""
    _admitted(_run(_cited("T9.9"), tmp_path))


def test_a_citation_with_no_state_dir_is_admitted_without_an_audit_line(
    tmp_path: Path, kb: Path
) -> None:
    _admitted(
        _run(_cited("T0.1"), tmp_path, lane="lane-x", state=False, extra_env=_env(kb))
    )


def test_the_shipped_exemption_carries_its_reason_and_the_rulings_stamp() -> None:
    exemption = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))["lane_intake"][
        "plan_task_exemption"
    ]
    assert exemption["ruling_stamp"] == "2026-10-29T10:59:39Z"
    assert exemption["reason"].strip()
    assert "2026-10-29T10:59:39Z" in exemption["ruling"]
    assert not {"any", "exempt", "wildcard"} & set(exemption), "no escape entry"


@pytest.mark.parametrize(
    "key",
    [
        "reason",
        "ruling_stamp",
        "ref",
        "clone_env",
        "citation_line_pattern",
        "path_pattern",
        "task_line_patterns",
    ],
)
def test_a_policy_missing_an_exemption_key_refuses_rather_than_defaulting(
    key: str, tmp_path: Path
) -> None:
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    assert key in raw["lane_intake"]["plan_task_exemption"], "positive control"
    del raw["lane_intake"]["plan_task_exemption"][key]
    broken = tmp_path / "policy.json"
    broken.write_text(json.dumps(raw), encoding="utf-8")
    ok = _create(description=f"{_STAMP_PREFIX} lane-x\n\n{_BODY}", labels=[_LABEL])
    result = _run(ok, tmp_path, lane="lane-x", flags=("--policy", str(broken)))
    assert result.returncode == 1, result.stdout + result.stderr


def test_the_guard_and_handlers_spell_none_of_the_exemption_vocabulary() -> None:
    """The citation line, the ref and the clone variable are policy, not literals."""
    exemption = _INTAKE["plan_task_exemption"]
    handlers = _HANDLER_PY.with_name("handler_plan_task_citation.py")
    for source in (_GUARD_PY, _HANDLER_PY, handlers):
        text = source.read_text(encoding="utf-8")
        for literal in ("Plan task:", exemption["clone_env"]):
            assert literal not in text, f"{literal!r} is spelled in {source.name}"
