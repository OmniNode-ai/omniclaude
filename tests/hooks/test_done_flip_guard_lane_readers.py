# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The Done-flip hook reads no GitHub through gh, and admits docs-only tickets [OMN-20368].

Three defects found by the 2026-10-22 sprint triage dry runs:

* the hook's own GitHub reads (PR state of an older merged PR, the product
  contract, the ``repo-evidence / dod-verify`` check run) went through ``gh
  api``, which a lane's gh shim refuses, so merged and verified tickets were
  refused. The hook now hands ``decide`` the ``LaneReaders``: the PR watcher
  and canonical clone first, then the sanctioned read node over the bus;
* the tick rule and the Done rule read the same product-repository verdict
  (one ``_bar``), so a contract that lives in the product repository admits a
  tick (covered by test_done_flip_guard_repo_evidence.py; pinned here for the
  lane readers);
* a documentation ticket had no path: a merged docs-only PR that names the
  ticket, with no contract, is now its evidence (RULING 2026-10-14T03:57:46Z
  item 4), and nothing else is.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit

_LIB_DIR = Path(__file__).parents[2] / "plugins" / "onex" / "hooks" / "lib"


def _load_guard() -> Any:
    sys.path.insert(0, str(_LIB_DIR))
    spec = importlib.util.spec_from_file_location(
        "done_flip_guard", _LIB_DIR / "done_flip_guard.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["done_flip_guard"] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()
ldv: Any = importlib.import_module("linear_done_verify")
nbe: Any = importlib.import_module("no_pr_bound_evidence")
handler: Any = importlib.import_module(
    "omniclaude.nodes.node_linear_effect.handlers.handler_lane_repo_evidence"
)
readers_mod: Any = importlib.import_module(
    "omniclaude.nodes.node_linear_effect.handlers.handler_hook_evidence_readers"
)

_TICKET = "OMN-90002"
_CODE_REPO = "OmniNode-ai/omnimarket"
_DOCS_REPO = "OmniNode-ai/knowledge_base_internal"
_NUMBER = 4222
_MERGE = "m" * 40
_HEAD = "h" * 40
_DESCRIPTION = f"""Implemented in https://github.com/{_CODE_REPO}/pull/{_NUMBER}

## Acceptance criteria
- [x] AC1 -- the first check passes
- [x] AC2 -- the second check passes
"""
_DOCS_DESCRIPTION = f"""Written in https://github.com/{_DOCS_REPO}/pull/1415

## Acceptance criteria
- [x] AC1 -- the dictionary lists every figure
"""


@pytest.fixture(autouse=True)
def _no_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any gh read in these tests is the defect itself."""

    def _refused(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the hook must not read GitHub through gh")

    monkeypatch.setattr(ldv, "_gh_api_json", _refused)
    monkeypatch.setattr(nbe, "_gh_api_json", _refused)
    monkeypatch.setenv("LINEAR_API_KEY", "")


def _status(ref: Any, state: str = "MERGED", **fields: Any) -> Any:
    return ldv.PRStatus(ref=ref, state=state, merge_state="UNKNOWN", **fields)


def _contract(*labels: str) -> str:
    return yaml.safe_dump(
        {
            "ticket_id": _TICKET,
            "dod_evidence": [
                {"id": f"dod-{label.lower()}", "binds_ac": [label]} for label in labels
            ],
        }
    )


class _FakeEvidence:
    """``LaneRepoEvidence`` as the read node and clone would answer."""

    def __init__(self, *, contract: str | None, runs: Any = None) -> None:
        self.contract = contract
        self.runs = runs
        self.pr_reads: list[str] = []
        self.pr_answer: Any = None

    def fetch_pr_status(self, ref: Any) -> Any:
        self.pr_reads.append(f"{ref.repo}#{ref.number}")
        if self.pr_answer is not None:
            return self.pr_answer(ref)
        return _status(ref, head_sha=_HEAD, merge_commit_sha=_MERGE)

    def read_contract(self, repo: str, ref: str, ticket_id: str) -> Any:
        if self.contract is None:
            return nbe.ContractRead(nbe.ContractReadStatus.ABSENT)
        return nbe.ContractRead(nbe.ContractReadStatus.FOUND, text=self.contract)

    def read_check_runs(self, repo: str, sha: str) -> Any:
        if self.runs is not None:
            return self.runs
        return [
            {
                "id": 1,
                "name": nbe.REPO_EVIDENCE_CHECK_NAME,
                "app": {"slug": nbe.REPO_EVIDENCE_APP_SLUG},
                "status": "completed",
                "conclusion": "success",
            }
        ]


def _readers(
    evidence: _FakeEvidence,
    *,
    local: Any = None,
    merge_commit: tuple[str, list[str]] | None = None,
) -> Any:
    """``HookEvidenceReaders`` over a fake evidence handler and local PR read."""
    return readers_mod.HookEvidenceReaders(
        cast("Any", evidence),
        local_pr_status=local or (lambda ref: _status(ref, merge_commit_sha=_MERGE)),
        read_merge_commit=lambda _repo, _sha: merge_commit,
    )


def _call(description: str, *, state: str = "Done") -> dict[str, Any]:
    return {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": _TICKET, "state": state, "description": description},
    }


def _decide(readers: Any, call: dict[str, Any], live: str) -> Any:
    return guard.decide(
        call,
        repo_evidence_probe=readers.repo_evidence,
        pr_fetcher=readers.pr_status,
        linear_fetcher=lambda _tid: {"description": live, "labels": []},
    )


# --------------------------------------------------------------------------- #
# (a) no gh read: the hook entrypoint hands decide the handler's readers
# --------------------------------------------------------------------------- #


def test_main_hands_decide_the_handler_readers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def _capture(call: dict[str, Any], **readers: Any) -> Any:
        seen.update(readers)
        return guard.Decision(True, "captured")

    monkeypatch.setattr(guard, "decide", _capture)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_call(_DESCRIPTION))))
    assert guard.main() == 0
    assert set(seen) == {"repo_evidence_probe", "pr_fetcher"}

    calls: list[tuple[str, tuple[Any, ...]]] = []

    class _Recorder:
        def __getattr__(self, name: str) -> Any:
            return lambda *args: calls.append((name, args)) or name

    monkeypatch.setattr(handler, "hook_evidence_readers", _Recorder)
    assert seen["pr_fetcher"]("ref") == "pr_status"
    assert seen["repo_evidence_probe"]("t", [], []) == "repo_evidence"
    assert calls == [("pr_status", ("ref",)), ("repo_evidence", ("t", [], []))]


def test_a_hook_venv_older_than_the_plugin_keeps_the_old_readers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A branch-installed plugin over a venv without the handler refuses nothing new."""
    monkeypatch.delattr(handler, "hook_evidence_readers")
    monkeypatch.setattr(guard, "fetch_pr_status", lambda ref: ("old-pr-read", ref))
    monkeypatch.setattr(guard, "evaluate_repo_evidence", lambda *a: ("old-bar", a))
    readers = guard._lane_readers()
    assert readers["pr_fetcher"]("ref") == ("old-pr-read", "ref")
    assert readers["repo_evidence_probe"]("t", [], []) == ("old-bar", ("t", [], []))


def test_main_does_not_import_the_handler_for_a_call_needing_no_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> Any:
        raise AssertionError("no evidence is needed for an In Progress move")

    monkeypatch.setattr(handler, "hook_evidence_readers", _boom)
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": _TICKET, "state": "In Progress"},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(call)))
    assert guard.main() == 0


def test_clone_only_merged_pr_gets_its_head_from_the_read_node() -> None:
    """The defect: a merged PR the watcher dropped had no head, so no check run."""
    evidence = _FakeEvidence(contract=_contract("AC1", "AC2"))
    status = _readers(evidence).pr_status(ldv.PRRef(_NUMBER, _CODE_REPO))
    assert status.state == "MERGED"
    assert status.head_sha == _HEAD and status.merge_commit_sha == _MERGE
    assert evidence.pr_reads == [f"{_CODE_REPO}#{_NUMBER}"]


def test_open_pr_from_the_watcher_does_not_reach_the_bus() -> None:
    evidence = _FakeEvidence(contract=None)
    readers = _readers(evidence, local=lambda ref: _status(ref, state="OPEN"))
    assert readers.pr_status(ldv.PRRef(_NUMBER, _CODE_REPO)).state == "OPEN"
    assert evidence.pr_reads == []


def test_unreadable_pr_state_still_refuses() -> None:
    evidence = _FakeEvidence(contract=_contract("AC1", "AC2"))
    evidence.pr_answer = lambda ref: _status(
        ref, state="UNKNOWN", error="onex scm pr-merged gave no result"
    )
    readers = _readers(
        evidence, local=lambda ref: _status(ref, state="UNKNOWN", error="no clone")
    )
    decision = _decide(readers, _call(_DESCRIPTION), _DESCRIPTION)
    assert not decision.allowed
    assert "pr_not_merged" in decision.reason


def test_done_with_a_product_contract_is_admitted_with_no_gh_read() -> None:
    readers = _readers(_FakeEvidence(contract=_contract("AC1", "AC2")))
    decision = _decide(readers, _call(_DESCRIPTION), _DESCRIPTION)
    assert decision.allowed, decision.reason
    assert decision.reason.startswith("durable_evidence:repo_bound_checks")


def test_tick_reads_the_product_contract_through_the_handler_readers() -> None:
    """(b) the tick rule takes the same product-repository verdict as Done."""
    readers = _readers(_FakeEvidence(contract=_contract("AC1", "AC2")))
    unticked = _DESCRIPTION.replace("[x]", "[ ]")
    tick = _call(_DESCRIPTION, state="In Progress")
    assert _decide(readers, tick, unticked).allowed


def test_tick_with_a_criterion_the_product_contract_leaves_unbound_refuses() -> None:
    readers = _readers(_FakeEvidence(contract=_contract("AC1")))
    unticked = _DESCRIPTION.replace("[x]", "[ ]")
    decision = _decide(readers, _call(_DESCRIPTION, state="In Progress"), unticked)
    assert not decision.allowed
    assert "ac_tick_without_receipt" in decision.reason and "AC2" in decision.reason


def test_contract_without_a_check_run_is_not_rescued_by_the_docs_path() -> None:
    readers = _readers(
        _FakeEvidence(contract=_contract("AC1", "AC2"), runs=[]),
        merge_commit=(f"docs({_TICKET}): notes (#{_NUMBER})", ["docs/a.md"]),
    )
    decision = _decide(readers, _call(_DESCRIPTION), _DESCRIPTION)
    assert not decision.allowed
    assert "so its contract decides" in decision.reason


def test_refused_contract_verdict_is_final() -> None:
    readers = _readers(
        _FakeEvidence(contract=_contract("AC1")),
        merge_commit=(f"docs({_TICKET}): notes (#{_NUMBER})", ["docs/a.md"]),
    )
    verdict = readers.repo_evidence(_TICKET, [_DESCRIPTION], [_merged_code()])
    assert verdict.outcome is nbe.RepoEvidenceOutcome.REFUSED


def _merged_code() -> Any:
    return _status(
        ldv.PRRef(_NUMBER, _CODE_REPO), head_sha=_HEAD, merge_commit_sha=_MERGE
    )


# --------------------------------------------------------------------------- #
# (c) the docs-only path
# --------------------------------------------------------------------------- #


def _docs_readers(merge_commit: tuple[str, list[str]] | None) -> Any:
    return _readers(_FakeEvidence(contract=None), merge_commit=merge_commit)


@pytest.mark.parametrize(
    "paths", [["docs/metric_dictionary.md"], ["beta/a.md", "README.rst", "x/y.txt"]]
)
def test_docs_only_ticket_closes_on_its_merged_docs_pr(paths: list[str]) -> None:
    readers = _docs_readers((f"docs({_TICKET}): metric dictionary (#1415)", paths))
    decision = _decide(readers, _call(_DOCS_DESCRIPTION), _DOCS_DESCRIPTION)
    assert decision.allowed, decision.reason
    verdict = readers.repo_evidence(_TICKET, [_DOCS_DESCRIPTION], [_merged_docs()])
    assert verdict.outcome is nbe.RepoEvidenceOutcome.PASSED
    assert verdict.detail.startswith(
        "docs-only: OmniNode-ai/knowledge_base_internal#1415"
    )


def _merged_docs() -> Any:
    return _status(ldv.PRRef(1415, _DOCS_REPO), merge_commit_sha=_MERGE)


def test_docs_only_ticket_may_tick_its_boxes() -> None:
    readers = _docs_readers((f"docs({_TICKET}): metric dictionary (#1415)", ["a.md"]))
    unticked = _DOCS_DESCRIPTION.replace("[x]", "[ ]")
    tick = _call(_DOCS_DESCRIPTION, state="In Progress")
    assert _decide(readers, tick, unticked).allowed


def test_docs_path_refuses_a_merge_that_changed_code() -> None:
    readers = _docs_readers(
        (
            f"docs({_TICKET}): dictionary with a checker (#1415)",
            ["docs/a.md", "scripts/check_bindings.py"],
        )
    )
    decision = _decide(readers, _call(_DOCS_DESCRIPTION), _DOCS_DESCRIPTION)
    assert not decision.allowed
    assert "scripts/check_bindings.py" in decision.reason


def test_docs_path_refuses_a_docs_pr_that_does_not_name_the_ticket() -> None:
    readers = _docs_readers(("docs(OMN-900021): another ticket (#1415)", ["a.md"]))
    decision = _decide(readers, _call(_DOCS_DESCRIPTION), _DOCS_DESCRIPTION)
    assert not decision.allowed
    assert "names OMN-90002" in decision.reason


def test_docs_path_refuses_an_unreadable_merge() -> None:
    decision = _decide(_docs_readers(None), _call(_DOCS_DESCRIPTION), _DOCS_DESCRIPTION)
    assert not decision.allowed
    assert "not readable in a canonical clone" in decision.reason


def test_docs_path_still_needs_every_box_ticked() -> None:
    readers = _docs_readers((f"docs({_TICKET}): dictionary (#1415)", ["a.md"]))
    unticked = _DOCS_DESCRIPTION.replace("[x]", "[ ]")
    decision = _decide(readers, _call(unticked), unticked)
    assert not decision.allowed
    assert "unchecked_acceptance_criteria" in decision.reason


def test_a_docs_pr_with_no_cited_merge_does_not_engage() -> None:
    readers = _docs_readers((f"docs({_TICKET}): dictionary (#1415)", ["a.md"]))
    verdict = readers.docs_evidence(_TICKET, [])
    assert verdict.outcome is nbe.RepoEvidenceOutcome.NOT_ENGAGED


@pytest.mark.parametrize(
    ("path", "doc"),
    [
        ("docs/a.md", True),
        ("A.MD", True),
        ("guide.rst", True),
        ("notes.txt", True),
        ("scripts/check.py", False),
        ("contracts/OMN-1.yaml", False),
        ("Makefile", False),
        ("docs/md", False),
    ],
)
def test_is_doc_path(path: str, doc: bool) -> None:
    assert readers_mod.is_doc_path(path) is doc


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    )
    return done.stdout.strip()


def test_read_merge_commit_reads_subject_and_paths_from_the_clone(
    tmp_path: Path,
) -> None:
    clone = tmp_path / "knowledge_base_internal"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "main")
    _git(clone, "config", "user.email", "t@example.invalid")
    _git(clone, "config", "user.name", "t")
    _git(clone, "config", "commit.gpgsign", "false")
    (clone / "seed.md").write_text("seed\n")
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "seed")
    (clone / "docs").mkdir()
    (clone / "docs" / "dictionary.md").write_text("figures\n")
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", f"docs({_TICKET}): dictionary (#1415)")
    sha = _git(clone, "rev-parse", "HEAD")

    evidence = handler.LaneRepoEvidence(scm=lambda *_a: None, clone_root=tmp_path)
    readers = readers_mod.HookEvidenceReaders(evidence)
    assert readers.read_merge_commit(_DOCS_REPO, sha) == (
        f"docs({_TICKET}): dictionary (#1415)",
        ["docs/dictionary.md"],
    )
    assert readers.read_merge_commit(_DOCS_REPO, "0" * 40) is None
