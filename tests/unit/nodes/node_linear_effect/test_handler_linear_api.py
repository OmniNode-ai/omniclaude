# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The Linear API backend ticks acceptance boxes through the Done-flip guard [OMN-17427]."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

from omniclaude.nodes.node_linear_effect.handlers.handler_lane_repo_evidence import (
    LaneRepoEvidence,
    hook_module,
    run_scm,
)
from omniclaude.nodes.node_linear_effect.handlers.handler_linear_ticketing import (
    HandlerLinearApi,
    tick_labelled_boxes,
)
from omniclaude.nodes.node_linear_effect.models import (
    LinearOperation,
    LinearResultStatus,
    ModelLinearRequest,
)

pytestmark = pytest.mark.unit

_TICKET = "OMN-90001"
_REPO = "OmniNode-ai/omnimarket"
_HEAD = "h" * 40
_DESCRIPTION = f"""Landed in https://github.com/{_REPO}/pull/3300

## Acceptance criteria
- [ ] AC1: the first check passes -- falsifier: uv run pytest a -q
- [ ] AC2: the second check passes -- falsifier: uv run pytest b -q
"""
_ISSUE: dict[str, Any] = {
    "id": "uuid-1",
    "identifier": _TICKET,
    "url": "https://linear.app/x/issue/OMN-90001",
    "description": _DESCRIPTION,
    "state": {"id": "s-review", "name": "In Review", "type": "started"},
    "team": {
        "states": {
            "nodes": [
                {"id": "s-review", "name": "In Review", "type": "started"},
                {"id": "s-done", "name": "Done", "type": "completed"},
            ]
        }
    },
}


class FakeLinear:
    """A transport that answers the issue query and records every mutation."""

    def __init__(self, description: str = _DESCRIPTION) -> None:
        self.issue = {**_ISSUE, "description": description}
        self.mutations: list[dict[str, Any]] = []

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if "issueUpdate" in query:
            self.mutations.append(variables)
            update = variables["input"]
            if "description" in update:
                self.issue["description"] = update["description"]
            if "stateId" in update:
                self.issue["state"] = {"id": update["stateId"], "name": "Done"}
            return {"issueUpdate": {"success": True}}
        if "commentCreate" in query:
            self.mutations.append(variables)
            return {"commentCreate": {"success": True}}
        return {"issue": self.issue}


def _request(**overrides: Any) -> ModelLinearRequest:
    fields: dict[str, Any] = {
        "operation": LinearOperation.TICKET_TICK_ACCEPTANCE,
        "ticket_id": _TICKET,
        **overrides,
    }
    return ModelLinearRequest(**fields)


class _Guard:
    """A guard stand-in that answers in order and keeps the calls it was asked."""

    def __init__(self, *verdicts: tuple[bool, str]) -> None:
        self.answers = list(verdicts)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, call: dict[str, Any]) -> tuple[bool, str]:
        self.calls.append(call)
        return self.answers.pop(0)


def _guard(*verdicts: tuple[bool, str]) -> _Guard:
    return _Guard(*verdicts)


def _run(handler: HandlerLinearApi, request: ModelLinearRequest) -> Any:
    return asyncio.run(handler.handle(request))


def test_tick_changes_only_the_box_token() -> None:
    label = hook_module("no_pr_bound_evidence").canonical_ac_label
    ticked = tick_labelled_boxes(_DESCRIPTION, label)
    assert (
        "- [x] AC1: the first check passes -- falsifier: uv run pytest a -q" in ticked
    )
    assert ticked.replace("[x]", "[ ]") == _DESCRIPTION


def test_tick_leaves_an_unlabelled_box_and_a_held_label_alone() -> None:
    label = hook_module("no_pr_bound_evidence").canonical_ac_label
    text = "- [ ] AC1: a\n- [ ] AC2: b\n- [ ] remember the milk\n"
    ticked = tick_labelled_boxes(text, label, frozenset({"AC2"}))
    assert ticked == "- [x] AC1: a\n- [ ] AC2: b\n- [ ] remember the milk\n"


def test_dry_run_asks_the_guard_and_writes_nothing() -> None:
    linear = FakeLinear()
    guard = _guard((True, "ok"))
    result = _run(HandlerLinearApi(transport=linear, guard_decision=guard), _request())
    assert result.status is LinearResultStatus.SUCCESS
    assert result.ticked_labels == ("AC1", "AC2")
    assert linear.mutations == []
    sent = guard.calls[0]["tool_input"]
    assert sent["id"] == _TICKET and "[x] AC1" in sent["description"]
    assert "state" not in sent


def test_apply_writes_the_ticked_description_only_when_the_guard_admits() -> None:
    linear = FakeLinear()
    handler = HandlerLinearApi(transport=linear, guard_decision=_guard((True, "ok")))
    result = _run(handler, _request(apply=True))
    assert result.status is LinearResultStatus.SUCCESS
    assert [list(m["input"]) for m in linear.mutations] == [["description"]]
    assert linear.issue["description"].count("[x]") == 2


def test_guard_refusal_writes_nothing_and_names_the_uncovered_criterion() -> None:
    linear = FakeLinear()
    reason = "ac_tick_without_receipt: AC2: no dod_evidence item in the contracts of x binds it"
    handler = HandlerLinearApi(transport=linear, guard_decision=_guard((False, reason)))
    result = _run(handler, _request(apply=True, set_done=True))
    assert result.status is LinearResultStatus.FAILED
    assert result.uncovered_labels == ("AC2",)
    assert linear.mutations == []


def test_done_is_a_second_edit_after_the_tick() -> None:
    linear = FakeLinear()
    guard = _guard((True, "ok"), (True, "durable_evidence"))
    handler = HandlerLinearApi(transport=linear, guard_decision=guard)
    result = _run(handler, _request(apply=True, set_done=True))
    assert result.ticket_state == "Done"
    assert [list(m["input"]) for m in linear.mutations] == [
        ["description"],
        ["stateId"],
    ]
    assert guard.calls[1]["tool_input"] == {"id": _TICKET, "state": "Done"}


def test_a_done_refusal_keeps_the_tick_and_reports_why() -> None:
    linear = FakeLinear()
    guard = _guard((True, "ok"), (False, "pr_not_merged: #1 closed"))
    handler = HandlerLinearApi(transport=linear, guard_decision=guard)
    result = _run(handler, _request(apply=True, set_done=True))
    assert result.status is LinearResultStatus.SUCCESS
    assert result.ticket_state == "In Review"
    assert "pr_not_merged" in (result.output or "")
    assert [list(m["input"]) for m in linear.mutations] == [["description"]]


def test_leave_open_ticks_the_rest_and_withholds_done() -> None:
    linear = FakeLinear()
    guard = _guard((True, "ok"))
    handler = HandlerLinearApi(transport=linear, guard_decision=guard)
    result = _run(handler, _request(apply=True, set_done=True, leave_open=("AC2",)))
    assert result.ticked_labels == ("AC1",)
    assert "AC2 left open" in (result.output or "")
    assert "- [ ] AC2" in linear.issue["description"]
    assert len(guard.calls) == 1


def test_create_is_refused_and_a_comment_needs_its_actor_line() -> None:
    handler = HandlerLinearApi(transport=FakeLinear(), guard_decision=_guard())
    created = _run(handler, ModelLinearRequest(operation=LinearOperation.TICKET_CREATE))
    assert created.status is LinearResultStatus.FAILED
    bare = ModelLinearRequest(
        operation=LinearOperation.TICKET_ADD_COMMENT,
        ticket_id=_TICKET,
        comment_body="done",
    )
    assert _run(handler, bare).status is LinearResultStatus.FAILED
    signed = ModelLinearRequest(
        operation=LinearOperation.TICKET_ADD_COMMENT,
        ticket_id=_TICKET,
        comment_body="actor: closer-sprint-six (sonnet)\nthe cut is recorded",
    )
    assert _run(handler, signed).status is LinearResultStatus.SUCCESS


# --- the real guard, with lane readers over a fake scm and a real git clone ---


def _git(clone: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(clone), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    )
    return done.stdout.strip()


def _contract(*labels: str) -> str:
    return yaml.safe_dump(
        {
            "ticket_id": _TICKET,
            "dod_evidence": [
                {"id": f"dod-{label.lower()}", "binds_ac": [label]} for label in labels
            ],
        }
    )


def _clone(
    tmp_path: Path, contract: str, *, earlier: str | None = None
) -> tuple[Path, str]:
    clone = tmp_path / "omnimarket"
    clone.mkdir()
    _git(clone, "init", "-q")
    path = clone / "contracts" / f"{_TICKET}.yaml"
    path.parent.mkdir()
    if earlier is not None:
        path.write_text(earlier)
        _git(clone, "add", ".")
        _git(clone, "commit", "-q", "-m", "earlier contract")
    else:
        (clone / "README").write_text("base")
        _git(clone, "add", ".")
        _git(clone, "commit", "-q", "-m", "base")
    path.write_text(contract)
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "merge")
    return clone, _git(clone, "rev-parse", "HEAD")


def _scm(merge: str, *, started_at: str, conclusion: str = "success") -> Any:
    def run(verb: str, args: list[str]) -> dict[str, Any] | None:
        if verb == "pr-merged":
            return {
                "state": "MERGED",
                "merged": True,
                "head_sha": _HEAD,
                "merged_at": "2026-10-15T00:00:00Z",
            }
        if verb == "pr-merge-commit":
            return {"merge_commit_sha": merge}
        if verb == "commit-check-runs":
            return {
                "check_runs": [
                    {
                        "id": 9,
                        "name": "repo-evidence / dod-verify",
                        "app_slug": "github-actions",
                        "status": "completed",
                        "conclusion": conclusion,
                        "started_at": started_at,
                    }
                ]
            }
        return None

    return run


class _Handler(HandlerLinearApi):
    def _fetch_for_guard(
        self, live_description: str | None, ticket_id: str
    ) -> dict[str, Any]:
        return {
            "description": live_description or self.stored,
            "labels": [],
            "attachment_urls": [],
        }

    stored = _DESCRIPTION


def _lane_handler(
    tmp_path: Path, contract: str, **scm: Any
) -> tuple[_Handler, FakeLinear]:
    clone, merge = _clone(tmp_path, contract)
    evidence = LaneRepoEvidence(
        scm=_scm(merge, started_at=scm.get("started_at", "2999-01-01T00:00:00Z")),
        clone_root=tmp_path,
    )
    linear = FakeLinear()
    return _Handler(transport=linear, evidence=evidence), linear


def test_real_guard_admits_the_tick_when_every_criterion_is_bound(
    tmp_path: Path,
) -> None:
    handler, linear = _lane_handler(tmp_path, _contract("AC1", "AC2"))
    result = _run(handler, _request(apply=True))
    assert result.status is LinearResultStatus.SUCCESS, result.error
    assert linear.issue["description"].count("[x]") == 2


def test_real_guard_refuses_a_partial_binding_and_names_the_gap(tmp_path: Path) -> None:
    handler, linear = _lane_handler(tmp_path, _contract("AC1"))
    result = _run(handler, _request(apply=True))
    assert result.status is LinearResultStatus.FAILED
    assert result.uncovered_labels == ("AC2",)
    assert linear.mutations == []


def test_real_guard_refuses_when_another_commit_changed_the_contract_after_the_check(
    tmp_path: Path,
) -> None:
    clone, merge = _clone(tmp_path, _contract("AC1", "AC2"), earlier=_contract("AC1"))
    evidence = LaneRepoEvidence(
        scm=_scm(merge, started_at="2000-01-01T00:00:00Z"), clone_root=tmp_path
    )
    linear = FakeLinear()
    result = _run(_Handler(transport=linear, evidence=evidence), _request(apply=True))
    assert result.status is LinearResultStatus.FAILED
    assert "changed after the check started" in (result.error or "")
    assert linear.mutations == []


def test_real_guard_refuses_a_red_check_run(tmp_path: Path) -> None:
    clone, merge = _clone(tmp_path, _contract("AC1", "AC2"))
    evidence = LaneRepoEvidence(
        scm=_scm(merge, started_at="2999-01-01T00:00:00Z", conclusion="failure"),
        clone_root=tmp_path,
    )
    linear = FakeLinear()
    result = _run(_Handler(transport=linear, evidence=evidence), _request(apply=True))
    assert result.status is LinearResultStatus.FAILED
    assert "conclusion=failure" in (result.error or "")
    assert linear.mutations == []


def test_contract_absent_in_a_held_commit_reads_absent(tmp_path: Path) -> None:
    clone, merge = _clone(tmp_path, _contract("AC1"))
    evidence = LaneRepoEvidence(scm=_scm(merge, started_at="x"), clone_root=tmp_path)
    read = evidence.read_contract(_REPO, merge, "OMN-12345")
    assert read.status.value == "absent"


def test_default_reader_finds_the_internal_sibling_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "registry"
    registry.mkdir()
    clone, merge = _clone(tmp_path, _contract("AC1"))
    clone = clone.rename(tmp_path / "sibling-clone")
    repo = "OmniNode-ai/sibling-clone"
    _git(clone, "config", "onex.repo", repo)
    monkeypatch.setenv("OMNI_HOME", str(registry))
    monkeypatch.setenv("OMNIBASE_INTERNAL_HOME", str(clone))
    monkeypatch.delenv("ONEX_REGISTRY_ROOTS", raising=False)
    read = LaneRepoEvidence().read_contract(repo, merge, _TICKET)
    assert read.status.value == "found", read.error
    assert yaml.safe_load(read.text)["ticket_id"] == _TICKET


def test_default_reader_uses_registered_root_and_repository_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "registry"
    registry.mkdir()
    extra = tmp_path / "registered"
    extra.mkdir()
    clone, merge = _clone(extra, _contract("AC1"))
    clone = clone.rename(extra / "renamed-canonical-clone")
    _git(clone, "config", "onex.repo", _REPO)
    roots = registry / "scripts/git-hooks/registry-roots"
    roots.parent.mkdir(parents=True)
    roots.write_text(f"root={extra}\n")
    monkeypatch.setenv("OMNI_HOME", str(registry))
    monkeypatch.delenv("ONEX_REGISTRY_ROOTS", raising=False)
    monkeypatch.delenv("OMNIBASE_INTERNAL_HOME", raising=False)
    read = LaneRepoEvidence().read_contract(_REPO, merge, _TICKET)
    assert read.status.value == "found", read.error


def test_explicit_clone_root_does_not_read_another_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "registry"
    registry.mkdir()
    clone, merge = _clone(registry, _contract("AC1"))
    _git(clone, "config", "onex.repo", _REPO)
    monkeypatch.setenv("OMNI_HOME", str(registry))
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    read = LaneRepoEvidence(clone_root=explicit).read_contract(_REPO, merge, _TICKET)
    assert read.status.value == "error"


def test_default_reader_refuses_a_same_named_clone_of_another_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone, merge = _clone(tmp_path, _contract("AC1"))
    _git(clone, "config", "onex.repo", "other-owner/omnimarket")
    monkeypatch.setenv("OMNI_HOME", str(tmp_path))
    monkeypatch.delenv("ONEX_REGISTRY_ROOTS", raising=False)
    monkeypatch.delenv("OMNIBASE_INTERNAL_HOME", raising=False)
    read = LaneRepoEvidence().read_contract(_REPO, merge, _TICKET)
    assert read.status.value == "error"


@pytest.mark.parametrize("complete", [True, False])
def test_real_guard_uses_sibling_clone_without_weakening_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, complete: bool
) -> None:
    registry = tmp_path / "registry"
    registry.mkdir()
    clone, merge = _clone(
        tmp_path, _contract(*(("AC1", "AC2") if complete else ("AC1",)))
    )
    clone = clone.rename(tmp_path / "sibling-clone")
    repo = "OmniNode-ai/sibling-clone"
    _git(clone, "config", "onex.repo", repo)
    monkeypatch.setenv("OMNI_HOME", str(registry))
    monkeypatch.delenv("ONEX_REGISTRY_ROOTS", raising=False)
    monkeypatch.setenv("OMNIBASE_INTERNAL_HOME", str(clone))
    description = _DESCRIPTION.replace(_REPO, repo)
    linear = FakeLinear(description)
    handler = _Handler(
        transport=linear,
        evidence=LaneRepoEvidence(scm=_scm(merge, started_at="2999-01-01T00:00:00Z")),
    )
    handler.stored = description
    result = _run(handler, _request(apply=True))
    if complete:
        assert result.status is LinearResultStatus.SUCCESS, result.error
        assert linear.issue["description"].count("[x]") == 2
    else:
        assert result.status is LinearResultStatus.FAILED
        assert result.uncovered_labels == ("AC2",)
        assert linear.mutations == []


def test_unheld_head_proof_uses_the_registered_clone_holding_the_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "registry"
    registry.mkdir()
    stale_root = tmp_path / "stale"
    fresh_root = tmp_path / "fresh"
    stale_root.mkdir()
    fresh_root.mkdir()
    stale, _ = _clone(stale_root, _contract("AC1"))
    fresh, merge = _clone(fresh_root, _contract("AC1", "AC2"))
    stale = stale.rename(registry / "a-stale")
    fresh = fresh.rename(registry / "b-fresh")
    for clone in (stale, fresh):
        _git(clone, "config", "onex.repo", _REPO)
    monkeypatch.setenv("OMNI_HOME", str(registry))
    monkeypatch.delenv("ONEX_REGISTRY_ROOTS", raising=False)
    monkeypatch.delenv("OMNIBASE_INTERNAL_HOME", raising=False)
    evidence = LaneRepoEvidence(scm=_scm(merge, started_at="2999-01-01T00:00:00Z"))
    ref = hook_module("linear_done_verify").PRRef(number=3300, repo=_REPO)
    evidence.fetch_pr_status(ref)
    evidence.read_check_runs(_REPO, _HEAD)
    read = evidence.read_contract(_REPO, _HEAD, _TICKET)
    assert read.status.value == "found", read.error
    assert len(yaml.safe_load(read.text)["dod_evidence"]) == 2


def test_scm_subprocess_reads_its_target_instead_of_the_inherited_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_root = tmp_path / "target"
    foreign_root = tmp_path / "foreign"
    target_root.mkdir()
    foreign_root.mkdir()
    target, expected = _clone(target_root, _contract("AC1", "AC2"))
    foreign, wrong = _clone(foreign_root, _contract("AC1"))
    assert expected != wrong
    command = tmp_path / "onex"
    command.write_text(
        f"#!{sys.executable}\n"
        "import json, subprocess\n"
        f"sha = subprocess.check_output(['git', '-C', {str(target)!r}, "
        "'rev-parse', 'HEAD'], text=True).strip()\n"
        "print(json.dumps({'outcome': 'completed', 'result': {'sha': sha}}))\n"
    )
    command.chmod(0o755)
    monkeypatch.setenv("ONEX_BIN", str(command))
    monkeypatch.setenv("GIT_DIR", str(foreign / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(foreign))
    result = run_scm("pr-merge-commit", [f"{_REPO}#3300"])
    assert result == {"sha": expected}
    assert os.environ["GIT_DIR"] == str(foreign / ".git")
    assert os.environ["GIT_WORK_TREE"] == str(foreign)
