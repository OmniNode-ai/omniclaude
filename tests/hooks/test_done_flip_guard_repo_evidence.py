# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Repo evidence decides before OCC, with all readers injected [OMN-20071]."""

from __future__ import annotations

import base64
import importlib.util
import sys
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
import yaml

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
repo_evidence: Any = importlib.import_module("no_pr_bound_evidence")

_TICKET = "OMN-90001"
_REPO = "OmniNode-ai/omnimarket"
_NUMBER = 3300
_SOURCE = f"{_REPO}#{_NUMBER}"
_MERGE = "m" * 40
_HEAD = "h" * 40
_PR_URL = f"https://github.com/{_REPO}/pull/{_NUMBER}"
_DESCRIPTION = f"""Implemented in {_PR_URL}

## Acceptance criteria
- AC1 -- the first check passes
- AC2 -- the second check passes
"""


def _never(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("this reader or OCC probe must not be consulted")


def _merged(ref: Any) -> Any:
    assert ref.repo == _REPO and ref.number == _NUMBER
    return ldv.PRStatus(
        ref=ref,
        state="MERGED",
        merge_state="CLEAN",
        merge_commit_sha=_MERGE,
        head_sha=_HEAD,
    )


def _contract(*labels: str) -> str:
    return yaml.safe_dump(
        {
            "ticket_id": _TICKET,
            "dod_evidence": [
                {"id": f"dod-{label.lower()}", "binds_ac": [label]} for label in labels
            ],
        }
    )


def _run(**overrides: Any) -> dict[str, Any]:
    return {
        "id": 7100,
        "name": repo_evidence.REPO_EVIDENCE_CHECK_NAME,
        "app": {"slug": "github-actions"},
        "status": "completed",
        "conclusion": "success",
        "completed_at": "2026-10-02T12:00:00Z",
        **overrides,
    }


def _probe(
    contract: str | None = None,
    *,
    runs: Any = None,
    read_contract: Any = None,
    read_check_runs: Any = None,
) -> Any:
    if contract is None:
        contract = _contract("AC1", "AC2")

    def contract_reader(repo: str, ref: str, ticket_id: str) -> Any:
        assert repo == _REPO and ref in (_MERGE, _HEAD) and ticket_id == _TICKET
        return repo_evidence.ContractRead(
            repo_evidence.ContractReadStatus.FOUND, text=contract
        )

    def check_reader(repo: str, sha: str) -> Any:
        assert repo == _REPO and sha == _HEAD
        return [_run()] if runs is None else runs

    evaluate = partial(
        repo_evidence.evaluate_repo_evidence,
        read_contract=read_contract or contract_reader,
        read_check_runs=read_check_runs or check_reader,
    )

    def probe(ticket_id: str, descriptions: list[str], statuses: list[Any]) -> Any:
        return evaluate(ticket_id, descriptions, statuses)

    return probe


def _done(probe: Any, *, description: str = _DESCRIPTION, **kwargs: Any) -> Any:
    return guard.decide(
        {
            "tool_name": "mcp__linear-server__update_issue",
            "tool_input": {"id": _TICKET, "state": "Done"},
        },
        linear_fetcher=lambda _tid: {"description": description, "labels": []},
        pr_fetcher=kwargs.pop("pr_fetcher", _merged),
        occ_probe=kwargs.pop("occ_probe", _never),
        repo_evidence_probe=probe,
        **kwargs,
    )


def _occ(passed: bool) -> Any:
    return lambda _tid, _desc: nbe.BoundEvidenceVerdict(passed, "OCC probe detail")


def test_partial_repo_binding_refuses_without_consulting_occ() -> None:
    decision = _done(_probe(_contract("AC1")))
    assert not decision.allowed
    assert "no_bound_dod_receipt" in decision.reason
    assert "AC2" in decision.reason
    assert "repo-evidence" in decision.reason
    assert _SOURCE in decision.reason and _HEAD in decision.reason


def test_every_criterion_bound_and_success_allows_without_occ() -> None:
    decision = _done(_probe())
    assert decision.allowed, decision.reason
    assert decision.reason == "durable_evidence:repo_bound_checks:all_prs_merged"


@pytest.mark.parametrize("passed", [True, False])
def test_absent_repo_contract_leaves_occ_decision_unchanged(passed: bool) -> None:
    probe = _probe(
        read_contract=lambda *_args: repo_evidence.ContractRead(
            repo_evidence.ContractReadStatus.ABSENT
        ),
        read_check_runs=_never,
    )
    decision = _done(probe, occ_probe=_occ(passed))
    assert decision.allowed is passed
    if passed:
        assert decision.reason == "durable_evidence:occ_bound_receipts:all_prs_merged"
    else:
        expected = guard._bound_receipt_refusal(
            _TICKET,
            "OCC probe detail",
            why="a Done transition needs a passing definition-of-done check for "
            "every acceptance criterion",
        )
        assert decision.reason == expected.reason


def test_red_repo_check_refuses_without_occ() -> None:
    decision = _done(_probe(runs=[_run(conclusion="failure")]))
    assert not decision.allowed
    assert "7100" in decision.reason
    assert "status=completed" in decision.reason
    assert "conclusion=failure" in decision.reason


@pytest.mark.parametrize("passed", [True, False])
def test_contract_without_check_run_falls_back_to_occ(passed: bool) -> None:
    probe = _probe(runs=[])
    verdict = probe(_TICKET, [_DESCRIPTION], [_merged(ldv.PRRef(_NUMBER, _REPO))])
    assert verdict.outcome is repo_evidence.RepoEvidenceOutcome.NOT_ENGAGED
    assert not verdict.engaged
    decision = _done(probe, occ_probe=_occ(passed))
    assert decision.allowed is passed
    if not passed:
        assert "OCC probe detail" in decision.reason
        assert f"{_SOURCE} carries contracts/{_TICKET}.yaml but no " in decision.reason
        assert f"run on head {_HEAD[:12]}" in decision.reason


def test_check_from_other_app_does_not_engage() -> None:
    probe = _probe(runs=[_run(app={"slug": "some-other-app"})])
    decision = _done(probe, occ_probe=_occ(True))
    assert decision.allowed
    assert decision.reason == "durable_evidence:occ_bound_receipts:all_prs_merged"


def test_commit_status_shape_does_not_engage() -> None:
    probe = _probe(runs=[{"context": "repo-evidence / dod-verify", "state": "success"}])
    decision = _done(probe, occ_probe=_occ(True))
    assert decision.allowed
    assert "occ_bound_receipts" in decision.reason


def test_head_contract_differing_from_merged_contract_refuses() -> None:
    def reader(_repo: str, ref: str, _tid: str) -> Any:
        return repo_evidence.ContractRead(
            repo_evidence.ContractReadStatus.FOUND,
            text=_contract("AC1", "AC2") if ref == _MERGE else _contract("AC1"),
        )

    decision = _done(_probe(read_contract=reader))
    assert not decision.allowed
    assert "contract changed between the verified head and the merge commit" in (
        decision.reason
    )
    assert _HEAD in decision.reason and _MERGE in decision.reason


def test_contract_read_error_refuses_without_occ() -> None:
    decision = _done(
        _probe(
            read_contract=lambda *_args: repo_evidence.ContractRead(
                repo_evidence.ContractReadStatus.ERROR, error="permission denied"
            ),
            read_check_runs=_never,
        )
    )
    assert not decision.allowed
    assert "permission denied" in decision.reason
    assert _SOURCE in decision.reason and _MERGE in decision.reason


def test_unreadable_check_runs_refuse_without_occ() -> None:
    decision = _done(_probe(read_check_runs=lambda *_args: None))
    assert not decision.allowed
    assert "check runs unreadable" in decision.reason
    assert _SOURCE in decision.reason and _HEAD in decision.reason


def test_unlabelled_criterion_refuses_without_occ() -> None:
    description = _DESCRIPTION.replace("AC2 -- ", "")
    decision = _done(_probe(), description=description)
    assert not decision.allowed
    assert "carry no label" in decision.reason
    assert "the second check passes" in decision.reason


def test_tick_is_admitted_when_repo_binds_every_criterion() -> None:
    before = _DESCRIPTION.replace("- AC", "- [ ] AC")
    after = before.replace("- [ ] AC1", "- [x] AC1")
    decision = guard.decide(
        {
            "tool_name": "mcp__linear-server__update_issue",
            "tool_input": {"id": _TICKET, "description": after},
        },
        linear_fetcher=lambda _tid: {
            "description": before,
            "attachment_urls": [_PR_URL],
        },
        pr_fetcher=_merged,
        repo_evidence_probe=_probe(),
        occ_probe=_never,
    )
    assert decision.allowed, decision.reason
    assert decision.reason == "not_done_state"


def test_tick_is_refused_when_repo_leaves_a_criterion_unbound() -> None:
    before = _DESCRIPTION.replace("- AC", "- [ ] AC")
    decision = guard.decide(
        {
            "tool_name": "mcp__linear-server__update_issue",
            "tool_input": {
                "id": _TICKET,
                "description": before.replace("- [ ] AC1", "- [x] AC1"),
            },
        },
        linear_fetcher=lambda _tid: {"description": before},
        pr_fetcher=_merged,
        repo_evidence_probe=_probe(_contract("AC1")),
        occ_probe=_never,
    )
    assert not decision.allowed
    assert decision.reason.startswith("ac_tick_without_receipt")
    assert "AC2" in decision.reason and "repo-evidence" in decision.reason


def test_empty_head_skips_default_probe_readers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = _merged(ldv.PRRef(_NUMBER, _REPO))
    status.head_sha = ""
    verdict = repo_evidence.evaluate_repo_evidence(
        _TICKET, [_DESCRIPTION], [status], read_contract=_never, read_check_runs=_never
    )
    assert verdict.outcome is repo_evidence.RepoEvidenceOutcome.NOT_ENGAGED
    monkeypatch.setattr(repo_evidence, "_gh_api_json", _never)
    decision = _done(None, pr_fetcher=lambda _ref: status, occ_probe=_occ(True))
    assert decision.allowed
    assert "occ_bound_receipts" in decision.reason


def test_gh_read_contract_maps_404_to_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repo_evidence, "_gh_api_json", lambda *_args: (None, "gh: Not Found (HTTP 404)")
    )
    read = repo_evidence.gh_read_contract(_REPO, _MERGE, _TICKET)
    assert read.status is repo_evidence.ContractReadStatus.ABSENT


def test_gh_read_contract_decodes_base64_and_encodes_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract("AC1", "AC2")

    def api(path: str, timeout: float) -> Any:
        assert path == (
            f"repos/{_REPO}/contents/contracts/{_TICKET}.yaml?ref=head%2Fbranch"
        )
        assert timeout == 15
        encoded = base64.b64encode(contract.encode()).decode()
        return {"encoding": "base64", "content": encoded + "\n"}, None

    monkeypatch.setattr(repo_evidence, "_gh_api_json", api)
    read = repo_evidence.gh_read_contract(_REPO, "head/branch", _TICKET)
    assert read.status is repo_evidence.ContractReadStatus.FOUND
    assert read.text == contract


def test_gh_read_check_runs_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = [_run()]

    def api(path: str, timeout: float) -> Any:
        name = quote(repo_evidence.REPO_EVIDENCE_CHECK_NAME, safe="")
        assert path == (
            f"repos/{_REPO}/commits/{_HEAD}/check-runs?filter=latest&per_page=100"
            f"&check_name={name}"
        )
        assert timeout == 15
        return {"check_runs": runs}, None

    monkeypatch.setattr(repo_evidence, "_gh_api_json", api)
    assert repo_evidence.gh_read_check_runs(_REPO, _HEAD) == runs


def test_gh_read_check_runs_returns_none_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        repo_evidence, "_gh_api_json", lambda *_args: (None, "permission denied")
    )
    assert repo_evidence.gh_read_check_runs(_REPO, _HEAD) is None


def test_repo_success_never_loads_default_occ_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guard, "load_ticket_occ_evidence", _never)
    monkeypatch.setattr(guard, "resolve_omni_home", _never)
    decision = _done(_probe(), occ_probe=None)
    assert decision.allowed, decision.reason


def test_done_fetches_pr_status_only_once() -> None:
    refs: list[Any] = []

    def fetcher(ref: Any) -> Any:
        refs.append(ref)
        return _merged(ref)

    decision = _done(_probe(), pr_fetcher=fetcher)
    assert decision.allowed
    assert len(refs) == 1


@pytest.mark.parametrize(
    "body", ["[not, a, mapping]", "dod_evidence: [", "ticket_id: OMN-99999"]
)
def test_invalid_repo_contract_refuses(body: str) -> None:
    decision = _done(_probe(body, read_check_runs=_never))
    assert not decision.allowed
    assert _SOURCE in decision.reason and _MERGE in decision.reason


def test_newest_check_run_controls_verdict() -> None:
    decision = _done(
        _probe(
            runs=[
                _run(),
                _run(
                    id=7101,
                    completed_at="2026-10-02T13:00:00Z",
                    conclusion="failure",
                ),
            ]
        )
    )
    assert not decision.allowed
    assert "run 7101" in decision.reason


def test_rerun_in_progress_is_not_outranked_by_an_older_success() -> None:
    decision = _done(
        _probe(
            runs=[
                _run(),
                _run(id=7102, status="in_progress", conclusion=None, completed_at=None),
            ]
        )
    )
    assert not decision.allowed
    assert "run 7102" in decision.reason


@pytest.mark.parametrize("state", ["open", "closed", "merged"])
@pytest.mark.parametrize("head", [{"sha": _HEAD}, None, "malformed"])
def test_rest_pr_head_is_populated_for_every_state(
    monkeypatch: pytest.MonkeyPatch, state: str, head: Any
) -> None:
    data = {"state": state, "merged": state == "merged", "head": head}
    monkeypatch.setattr(ldv, "_gh_api_json", lambda *_args: (data, None))
    status = ldv.fetch_pr_status(ldv.PRRef(_NUMBER, _REPO))
    assert status.head_sha == (_HEAD if isinstance(head, dict) else "")


# A ticket landed by several PRs in one repository: each later PR re-verifies the
# whole contract on its own head, so the newest merged one decides (OMN-20071).
_OLD_NUMBER = 3284
_OLD_HEAD = "o" * 40
_OLD_MERGE = "p" * 40
_OLD_MERGED_AT = "2026-10-03T04:51:58Z"
_NEW_MERGED_AT = "2026-10-08T01:36:06Z"
_TWO_PR_DESCRIPTION = f"""Implemented in https://github.com/{_REPO}/pull/{_OLD_NUMBER} and {_PR_URL}

## Acceptance criteria
- AC1 -- the first check passes
- AC2 -- the second check passes
"""


def _two_prs(*, old_merged_at: str = _OLD_MERGED_AT) -> Any:
    def fetch(ref: Any) -> Any:
        assert ref.repo == _REPO and ref.number in (_OLD_NUMBER, _NUMBER)
        old = ref.number == _OLD_NUMBER
        return ldv.PRStatus(
            ref=ref,
            state="MERGED",
            merge_state="CLEAN",
            merge_commit_sha=_OLD_MERGE if old else _MERGE,
            head_sha=_OLD_HEAD if old else _HEAD,
            merged_at=old_merged_at if old else _NEW_MERGED_AT,
        )

    return fetch


def _two_pr_probe(
    *, old_runs: Any, new_runs: Any, old_contract: str = "", new_contract: str = ""
) -> Any:
    contracts = {
        _OLD_MERGE: old_contract or _contract("AC1", "AC2"),
        _OLD_HEAD: old_contract or _contract("AC1", "AC2"),
        _MERGE: new_contract or _contract("AC1", "AC2"),
        _HEAD: new_contract or _contract("AC1", "AC2"),
    }

    def contract_reader(repo: str, ref: str, ticket_id: str) -> Any:
        assert repo == _REPO and ticket_id == _TICKET
        return repo_evidence.ContractRead(
            repo_evidence.ContractReadStatus.FOUND, text=contracts[ref]
        )

    def check_reader(repo: str, sha: str) -> Any:
        assert repo == _REPO
        return {_OLD_HEAD: old_runs, _HEAD: new_runs}[sha]

    return _probe(read_contract=contract_reader, read_check_runs=check_reader)


def _two_pr_done(probe: Any, **kwargs: Any) -> Any:
    return _done(
        probe,
        description=_TWO_PR_DESCRIPTION,
        pr_fetcher=kwargs.pop("pr_fetcher", _two_prs()),
        **kwargs,
    )


def test_red_run_on_a_superseded_merged_pr_does_not_refuse() -> None:
    probe = _two_pr_probe(
        old_runs=[_run(id=7000, conclusion="failure")], new_runs=[_run()]
    )
    decision = _two_pr_done(probe)
    assert decision.allowed, decision.reason
    assert decision.reason == "durable_evidence:repo_bound_checks:all_prs_merged"


def test_red_run_on_the_newest_merged_pr_refuses_after_an_older_success() -> None:
    probe = _two_pr_probe(
        old_runs=[_run(id=7000)], new_runs=[_run(id=7101, conclusion="failure")]
    )
    decision = _two_pr_done(probe)
    assert not decision.allowed
    assert "run 7101" in decision.reason and _HEAD in decision.reason


def test_newest_contract_leaving_a_criterion_unbound_refuses() -> None:
    probe = _two_pr_probe(
        old_runs=[_run(id=7000)],
        new_runs=[_run()],
        new_contract=_contract("AC1"),
    )
    decision = _two_pr_done(probe)
    assert not decision.allowed
    assert "AC2" in decision.reason


def test_newest_pr_without_a_run_falls_back_to_occ_not_to_an_older_success() -> None:
    probe = _two_pr_probe(old_runs=[_run(id=7000)], new_runs=[])
    decision = _two_pr_done(probe, occ_probe=_occ(False))
    assert not decision.allowed
    assert "OCC probe detail" in decision.reason


def test_merged_pr_without_a_merge_time_is_never_treated_as_superseded() -> None:
    probe = _two_pr_probe(
        old_runs=[_run(id=7000, conclusion="failure")], new_runs=[_run()]
    )
    decision = _two_pr_done(probe, pr_fetcher=_two_prs(old_merged_at=""))
    assert not decision.allowed
    assert "run 7000" in decision.reason and _OLD_HEAD in decision.reason


@pytest.mark.parametrize(
    ("merged", "merged_at", "expected"),
    [(True, _NEW_MERGED_AT, _NEW_MERGED_AT), (False, None, "")],
)
def test_rest_pr_merge_time_is_populated(
    monkeypatch: pytest.MonkeyPatch, merged: bool, merged_at: Any, expected: str
) -> None:
    data = {
        "state": "closed",
        "merged": merged,
        "merged_at": merged_at,
        "head": {"sha": _HEAD},
    }
    monkeypatch.setattr(ldv, "_gh_api_json", lambda *_args: (data, None))
    status = ldv.fetch_pr_status(ldv.PRRef(_NUMBER, _REPO))
    assert status.merged_at == expected


def test_done_gate_adds_no_module_outside_its_baselined_files() -> None:
    """The gate's sibling-import closure is its three baselined modules (AC6)."""
    import ast

    repo_root = _LIB_DIR.parents[3]
    baseline = {
        line.strip()
        for line in (repo_root / ".onex_ratchets" / "canonical_file_shape_baseline.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.startswith("#")
    }
    closure: set[str] = set()
    pending = ["done_flip_guard"]
    while pending:
        name = pending.pop()
        if name in closure:
            continue
        closure.add(name)
        tree = ast.parse((_LIB_DIR / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            pending.extend(m for m in modules if (_LIB_DIR / f"{m}.py").is_file())
    assert closure == {"done_flip_guard", "linear_done_verify", "no_pr_bound_evidence"}
    for name in closure:
        assert f"plugins/onex/hooks/lib/{name}.py" in baseline
