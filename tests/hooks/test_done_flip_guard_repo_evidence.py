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
        read_verdict=lambda _tid: repo_evidence.VerdictRead(
            repo_evidence.VerdictReadStatus.ABSENT
        ),
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
