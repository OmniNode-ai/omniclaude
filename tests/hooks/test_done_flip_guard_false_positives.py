# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for repo evidence and product PR resolution.

No-PR tickets and description readbacks cannot substitute for product contracts
and verified checks. PR supersession, commit anchoring and REST reads retain
their existing product PR semantics. All readers are injected.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_LIB_DIR = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"


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
import linear_done_verify as ldv  # noqa: E402  (sibling import needs sys.path)
import no_pr_bound_evidence as nbe  # noqa: E402  (sibling import needs sys.path)


@pytest.fixture(autouse=True)
def _hermetic_linear(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reaches Linear: the default fetcher reads an empty key as 'no live data'."""
    monkeypatch.setenv("LINEAR_API_KEY", "")


def _call(ticket_id: str, description: str) -> dict[str, Any]:
    return {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": ticket_id, "state": "Done", "description": description},
    }


def _no_repo_probe(*_args: Any) -> Any:
    return nbe.RepoEvidenceVerdict(
        nbe.RepoEvidenceOutcome.NOT_ENGAGED, "no product contract"
    )


def _pass_probe(*_args: Any) -> Any:
    return nbe.RepoEvidenceVerdict(
        nbe.RepoEvidenceOutcome.PASSED, "repo-bound: AC1<-dod-001"
    )


def _never_called_fetcher(ref: Any) -> Any:
    raise AssertionError(f"PR {ref.repo}#{ref.number} must not be fetched here")


def _table_fetcher(table: dict[tuple[str, int], dict[str, Any]]) -> Any:
    """A fetcher answering from ``{(repo, number): PRStatus kwargs}``."""

    def fetch(ref: Any) -> Any:
        if ref.repo is None:
            # No repository: the real fetcher refuses without any network call.
            return ldv.fetch_pr_status(ref)
        key = (ref.repo, ref.number)
        if key not in table:
            return ldv.PRStatus(
                ref=ref,
                state="UNKNOWN",
                merge_state="UNKNOWN",
                error=f"unexpected fetch of {ref.repo}#{ref.number}",
            )
        return ldv.PRStatus(ref=ref, **table[key])

    return fetch


# =========================================================================== #
# (a) no-PR housekeeping ticket with a live-state readback — OMN-13907
# =========================================================================== #

_OMN_13907_BODY = """\
## Needs human/agent triage (NOT safe to prune)

Abandoned mega-dirty (no PR ever opened): `OMN-8781/omniclaude`,
`pr-1369-fix/onex_change_control`.

## DoD

* Each flagged worktree has an explicit disposition recorded here.
* `git worktree list` across repos shows no remaining dirty non-active worktrees.
"""

_NO_PR_BODY = """\
Housekeeping: dispose of the flagged worktrees.

## DoD

* DoD1: each flagged worktree has an explicit disposition recorded here.
* DoD2: `git worktree list` across repos shows no remaining dirty non-active worktrees.
"""

_CONTRACT: dict[str, Any] = {
    "schema_version": "1.0.0",
    "ticket_id": "OMN-13907",
    "dod_evidence": [
        {
            "id": "dod-dispositions",
            "binds_ac": ["DoD1"],
            "checks": [{"check_type": "command", "check_value": "true"}],
        },
        {
            "id": "dod-worktrees-clean",
            "binds_ac": ["DoD2"],
            "checks": [{"check_type": "command", "check_value": "true"}],
        },
    ],
}


def _contract_probe(contract: dict[str, Any] | None) -> Any:
    import yaml

    def probe(tid: str, descriptions: list[str], prs: list[Any]) -> Any:
        return nbe.evaluate_repo_evidence(
            tid,
            descriptions,
            prs,
            read_contract=lambda *_args: nbe.ContractRead(
                nbe.ContractReadStatus.FOUND
                if contract is not None
                else nbe.ContractReadStatus.ABSENT,
                text=yaml.safe_dump(contract),
            ),
            read_check_runs=lambda *_args: [
                {
                    "id": 1,
                    "name": nbe.REPO_EVIDENCE_CHECK_NAME,
                    "app": {"slug": "github-actions"},
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        )

    return probe


_PRODUCT_PR = "https://github.com/OmniNode-ai/omniclaude/pull/77"


def _evidence_fetcher(ref: Any) -> Any:
    return ldv.PRStatus(
        ref=ref,
        state="MERGED",
        merge_state="CLEAN",
        head_sha="h" * 40,
        merge_commit_sha="m" * 40,
    )


def test_a_bare_live_state_line_no_longer_closes() -> None:
    """The first cut's positive is now a negative: the line is not evidence."""
    marker = (
        "live-state-proven: 2026-09-25 `ls $OMNI_HOME/omni_worktrees/OMN-8781` -> "
        "No such file or directory\n"
    )
    d = guard.decide(
        _call("OMN-13907", _OMN_13907_BODY + "\n" + marker),
        repo_evidence_probe=_contract_probe(None),
        pr_fetcher=_never_called_fetcher,
    )
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason
    assert not hasattr(ldv, "parse_live_state_marker")


def test_a_no_pr_ticket_is_refused_even_when_a_contract_is_available() -> None:
    d = guard.decide(
        _call("OMN-13907", _NO_PR_BODY),
        repo_evidence_probe=_contract_probe(_CONTRACT),
        pr_fetcher=_never_called_fetcher,
    )
    assert not d.allowed
    assert d.reason.startswith("no_bound_dod_receipt for OMN-13907")
    assert "no merged product PR" in d.reason


def test_a_repo_verdict_names_which_item_binds_each_criterion() -> None:
    v = _contract_probe(_CONTRACT)(
        "OMN-13907",
        [_NO_PR_BODY],
        [_evidence_fetcher(ldv.PRRef(77, "OmniNode-ai/omniclaude"))],
    )
    assert v.outcome is nbe.RepoEvidenceOutcome.PASSED, v.detail
    assert "DOD1<-dod-dispositions" in v.detail
    assert "DOD2<-dod-worktrees-clean" in v.detail


def test_a_control_unbound_criterion_is_refused() -> None:
    """A partially bound contract: DoD2 is claimed by no item. Refused."""
    contract = {
        **_CONTRACT,
        "dod_evidence": [_CONTRACT["dod_evidence"][0]],
    }
    d = guard.decide(
        _call("OMN-13907", _NO_PR_BODY + "\n" + _PRODUCT_PR),
        repo_evidence_probe=_contract_probe(contract),
        pr_fetcher=_evidence_fetcher,
    )
    assert not d.allowed
    assert "DOD2: no dod_evidence item" in d.reason


def test_a_control_retired_binding_does_not_count() -> None:
    """A well-formed supersedes_ac_binding withdraws the claim it names."""
    contract = {
        **_CONTRACT,
        "dod_evidence": [
            *_CONTRACT["dod_evidence"],
            {
                "id": "dod-retire",
                "checks": [{"check_type": "command", "check_value": "true"}],
                "supersedes_ac_binding": [
                    {
                        "item": "dod-worktrees-clean",
                        "label": "DoD2",
                        "reason": "the check read the wrong root",
                    }
                ],
            },
        ],
    }
    d = guard.decide(
        _call("OMN-13907", _NO_PR_BODY + "\n" + _PRODUCT_PR),
        repo_evidence_probe=_contract_probe(contract),
        pr_fetcher=_evidence_fetcher,
    )
    assert not d.allowed
    assert "DOD2: no dod_evidence item" in d.reason


def test_a_control_unlabelled_criteria_are_unbindable() -> None:
    """OMN-13907 as written today: DoD bullets with no labels. Refused."""
    d = guard.decide(
        _call("OMN-13907", _OMN_13907_BODY + "\n" + _PRODUCT_PR),
        repo_evidence_probe=_contract_probe(_CONTRACT),
        pr_fetcher=_evidence_fetcher,
    )
    assert not d.allowed
    assert "carry no label" in d.reason


def test_a_control_no_contract_fails_closed() -> None:
    d = guard.decide(
        _call("OMN-13907", _NO_PR_BODY + "\n" + _PRODUCT_PR),
        repo_evidence_probe=_contract_probe(None),
        pr_fetcher=_evidence_fetcher,
    )
    assert not d.allowed
    assert "no merged product PR carries contracts/OMN-13907.yaml" in d.reason


def test_a_control_repo_evidence_does_not_waive_an_open_cited_pr() -> None:
    desc = (
        _NO_PR_BODY
        + "\nFollow-up recovery in https://github.com/OmniNode-ai/omniclaude/pull/77\n"
    )
    fetcher = _table_fetcher(
        {("OmniNode-ai/omniclaude", 77): {"state": "OPEN", "merge_state": "BLOCKED"}}
    )
    d = guard.decide(
        _call("OMN-13907", desc),
        repo_evidence_probe=_contract_probe(_CONTRACT),
        pr_fetcher=fetcher,
    )
    assert not d.allowed
    assert "pr_not_merged" in d.reason


# =========================================================================== #
# (b) closed-as-superseded PR whose work landed in a named merged PR — OMN-14642
# =========================================================================== #

_OMN_14642_ATTACHED = """\
Dashboard reads must route through the projection-api proxy.

https://github.com/OmniNode-ai/omnidash/pull/261
https://github.com/OmniNode-ai/omninode_infra/pull/618
https://github.com/OmniNode-ai/omninode_infra/pull/614
"""

_SUPERSEDED_NOTE = (
    "Superseded by #618, which recut the same OMN-14642 change on a "
    "ticket-bearing branch, and merged at 9f19412a."
)


def _omn_14642_table(
    *,
    note: str | None = _SUPERSEDED_NOTE,
    successor_state: str = "MERGED",
    successor_title: str = "chore(OMN-14642): pin deployed omnidash staging image",
) -> dict[tuple[str, int], dict[str, Any]]:
    return {
        ("OmniNode-ai/omnidash", 261): {"state": "MERGED", "merge_state": "UNKNOWN"},
        ("OmniNode-ai/omninode_infra", 618): {
            "state": successor_state,
            "merge_state": "UNKNOWN",
            "title": successor_title,
        },
        ("OmniNode-ai/omninode_infra", 614): {
            "state": "CLOSED",
            "merge_state": "UNKNOWN",
            "title": "chore(OMN-14642): pin deployed omnidash staging image",
            "closing_notes": (note,) if note else (),
        },
    }


def test_b_closed_pr_superseded_by_named_merged_successor_is_allowed() -> None:
    d = guard.decide(
        _call("OMN-14642", _OMN_14642_ATTACHED),
        repo_evidence_probe=_pass_probe,
        pr_fetcher=_table_fetcher(_omn_14642_table()),
    )
    assert d.allowed, d.reason
    assert d.reason == "durable_evidence:repo_bound_checks:all_prs_merged"


def test_b_verify_records_the_proven_successor() -> None:
    result = ldv.verify(
        _OMN_14642_ATTACHED,
        [],
        fetcher=_table_fetcher(_omn_14642_table()),
        ticket_id="OMN-14642",
    )
    assert result.allowed, result.reason
    closed = [s for s in result.pr_statuses if s.ref.number == 614]
    assert closed[0].superseded_by == "OmniNode-ai/omninode_infra#618"


def test_b_control_closed_pr_with_no_note_is_still_abandoned() -> None:
    d = guard.decide(
        _call("OMN-14642", _OMN_14642_ATTACHED),
        repo_evidence_probe=_no_repo_probe,
        pr_fetcher=_table_fetcher(_omn_14642_table(note=None)),
    )
    assert not d.allowed
    assert "omninode_infra#614" in d.reason


def test_b_control_named_successor_not_merged_still_blocks() -> None:
    table = _omn_14642_table(successor_state="CLOSED")
    desc = (
        "https://github.com/OmniNode-ai/omnidash/pull/261\n"
        "https://github.com/OmniNode-ai/omninode_infra/pull/614\n"
    )
    d = guard.decide(
        _call("OMN-14642", desc),
        repo_evidence_probe=_no_repo_probe,
        pr_fetcher=_table_fetcher(table),
    )
    assert not d.allowed
    assert "omninode_infra#614" in d.reason


def test_b_control_successor_for_another_ticket_does_not_count() -> None:
    table = _omn_14642_table(successor_title="fix(OMN-99999): unrelated change")
    desc = (
        "https://github.com/OmniNode-ai/omnidash/pull/261\n"
        "https://github.com/OmniNode-ai/omninode_infra/pull/614\n"
    )
    d = guard.decide(
        _call("OMN-14642", desc),
        repo_evidence_probe=_no_repo_probe,
        pr_fetcher=_table_fetcher(table),
    )
    assert not d.allowed
    assert "omninode_infra#614" in d.reason


def test_b_control_note_naming_no_successor_does_not_count() -> None:
    table = _omn_14642_table(note="Superseded by later work, closing.")
    desc = "https://github.com/OmniNode-ai/omninode_infra/pull/614\n"
    d = guard.decide(
        _call("OMN-14642", desc),
        repo_evidence_probe=_no_repo_probe,
        pr_fetcher=_table_fetcher(table),
    )
    assert not d.allowed


def test_b_control_note_without_ticket_id_in_verify_does_not_count() -> None:
    """A caller that cannot say which ticket it is closing gets no note-based
    supersession: the successor binding needs the ticket id to check."""
    result = ldv.verify(
        "https://github.com/OmniNode-ai/omninode_infra/pull/614\n",
        [],
        fetcher=_table_fetcher(_omn_14642_table()),
    )
    assert not result.allowed


# =========================================================================== #
# (c) unanchored bare "PR #N" in incident narrative — OMN-14642
# =========================================================================== #

_NARRATIVE = (
    "* Activating commit: `8a4fe66b` (PR #257, author a teammate, 2026-07-15) "
    "wired the secret ref, which deepened the direct-DB read.\n"
)
_CITED = (
    "https://github.com/OmniNode-ai/omnidash/pull/261\n"
    "https://github.com/OmniNode-ai/omninode_infra/pull/618\n"
)


def _c_table(
    omnidash_257: dict[str, Any] | None = None,
    infra_257: dict[str, Any] | None = None,
) -> dict[tuple[str, int], dict[str, Any]]:
    merged = {"state": "MERGED", "merge_state": "UNKNOWN"}
    return {
        ("OmniNode-ai/omnidash", 261): merged,
        ("OmniNode-ai/omninode_infra", 618): merged,
        ("OmniNode-ai/omnidash", 257): omnidash_257
        or {
            "state": "MERGED",
            "merge_state": "UNKNOWN",
            "merge_commit_sha": "8a4fe66b0720939dbd7d87619203c66337b82f86",
        },
        ("OmniNode-ai/omninode_infra", 257): infra_257
        or {
            "state": "MERGED",
            "merge_state": "UNKNOWN",
            "merge_commit_sha": "134b90d764aa83550349ae86f6c50ddc2fe49b55",
        },
    }


def test_c_commit_anchored_narrative_ref_resolves_to_its_merged_pr() -> None:
    d = guard.decide(
        _call("OMN-14642", _NARRATIVE + _CITED),
        repo_evidence_probe=_pass_probe,
        pr_fetcher=_table_fetcher(_c_table()),
    )
    assert d.allowed, d.reason
    result = ldv.verify(_NARRATIVE + _CITED, [], fetcher=_table_fetcher(_c_table()))
    resolved = [s for s in result.pr_statuses if s.ref.number == 257]
    assert [s.ref.repo for s in resolved] == ["OmniNode-ai/omnidash"]


def test_c_line_commit_anchor_is_parsed_only_for_unanchored_refs() -> None:
    refs = ldv.parse_pr_refs(_NARRATIVE + _CITED)
    bare = [r for r in refs if r.number == 257]
    assert bare[0].repo is None
    assert bare[0].commit_anchor == "8a4fe66b"
    anchored = ldv.parse_pr_refs("omnidash PR #257 at `8a4fe66b`")
    assert anchored[0].repo == "OmniNode-ai/omnidash"
    assert anchored[0].commit_anchor == ""


def test_c_control_sha_matching_no_candidate_still_blocks() -> None:
    table = _c_table(
        omnidash_257={
            "state": "MERGED",
            "merge_state": "UNKNOWN",
            "merge_commit_sha": "ffffffff0720939dbd7d87619203c66337b82f86",
        }
    )
    d = guard.decide(
        _call("OMN-14642", _NARRATIVE + _CITED),
        repo_evidence_probe=_no_repo_probe,
        pr_fetcher=_table_fetcher(table),
    )
    assert not d.allowed
    assert "no associated repo" in d.reason


def test_c_control_unmerged_candidate_does_not_resolve() -> None:
    """An OPEN PR has no merge commit, so the anchor cannot land on it."""
    table = _c_table(
        omnidash_257={
            "state": "OPEN",
            "merge_state": "CLEAN",
            "merge_commit_sha": "8a4fe66b0720939dbd7d87619203c66337b82f86",
        }
    )
    d = guard.decide(
        _call("OMN-14642", _NARRATIVE + _CITED),
        repo_evidence_probe=_no_repo_probe,
        pr_fetcher=_table_fetcher(table),
    )
    assert not d.allowed


def test_c_control_only_an_unanchored_ref_still_blocks() -> None:
    """No other citation, so no candidate repository: still refused."""
    d = guard.decide(
        _call("OMN-14642", _NARRATIVE),
        repo_evidence_probe=_no_repo_probe,
        pr_fetcher=ldv.fetch_pr_status,
    )
    assert not d.allowed
    assert "no associated repo" in d.reason


def test_c_control_unanchored_ref_without_sha_still_blocks() -> None:
    d = guard.decide(
        _call("OMN-14642", "Implementing work landed in a PR #257.\n" + _CITED),
        repo_evidence_probe=_no_repo_probe,
        pr_fetcher=_table_fetcher(_c_table()),
    )
    assert not d.allowed
    assert "no associated repo" in d.reason


def test_c_control_ambiguously_anchored_ref_still_blocks() -> None:
    """A number the ticket anchors to two repos is a citation, not narrative."""
    desc = (
        "Carriers: OmniNode-ai/omnimarket#2504 and OmniNode-ai/omnibase_infra#2504.\n"
        "The behaviour change landed in PR #2504 at `8a4fe66b`.\n"
    )
    merged = {"state": "MERGED", "merge_state": "UNKNOWN"}
    d = guard.decide(
        _call("OMN-18086", desc),
        repo_evidence_probe=_no_repo_probe,
        pr_fetcher=_table_fetcher(
            {
                ("OmniNode-ai/omnimarket", 2504): merged,
                ("OmniNode-ai/omnibase_infra", 2504): merged,
            }
        ),
    )
    assert not d.allowed
    assert "more than one repo" in d.reason


# =========================================================================== #
# (d) PR state read by REST, not GraphQL — OMN-14652
# =========================================================================== #


class _FakeRun:
    """Stands in for ``subprocess.run``; answers ``gh api`` REST paths."""

    def __init__(self, responses: dict[str, tuple[int, Any]]) -> None:
        self.responses = responses
        self.argvs: list[list[str]] = []

    def __call__(self, argv: list[str], **_kwargs: Any) -> Any:
        self.argvs.append(list(argv))
        path = next((a for a in argv if a.startswith("repos/")), "")
        code, payload = self.responses.get(path.split("?")[0], (1, "not found"))
        out = json.dumps(payload) if code == 0 else ""
        err = "" if code == 0 else str(payload)
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr=err)


def test_d_fetch_pr_status_reads_state_by_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRun(
        {
            "repos/OmniNode-ai/omnibase_infra/pulls/2471": (
                0,
                {"state": "closed", "merged": True, "mergeable_state": "unknown"},
            )
        }
    )
    monkeypatch.setattr(ldv.subprocess, "run", fake)
    status = ldv.fetch_pr_status(ldv.PRRef(2471, "OmniNode-ai/omnibase_infra"))
    assert status.error is None, status.error
    assert status.state == "MERGED"
    assert all(argv[:2] == ["gh", "api"] for argv in fake.argvs)
    assert not any("graphql" in a or a == "view" for argv in fake.argvs for a in argv)


def test_d_rest_state_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRun(
        {
            "repos/O/r/pulls/1": (
                0,
                {"state": "open", "merged": False, "mergeable_state": "blocked"},
            ),
            "repos/O/r/pulls/2": (
                0,
                {
                    "state": "closed",
                    "merged": False,
                    "title": "chore(OMN-1): x",
                    "body": "first attempt",
                },
            ),
            "repos/O/r/issues/2/comments": (0, [{"body": "Superseded by #3."}]),
        }
    )
    monkeypatch.setattr(ldv.subprocess, "run", fake)
    open_status = ldv.fetch_pr_status(ldv.PRRef(1, "O/r"))
    assert (open_status.state, open_status.merge_state) == ("OPEN", "BLOCKED")
    closed = ldv.fetch_pr_status(ldv.PRRef(2, "O/r"))
    assert closed.state == "CLOSED"
    assert closed.title == "chore(OMN-1): x"
    assert "Superseded by #3." in closed.closing_notes


def test_d_control_rest_failure_still_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRun(
        {"repos/OmniNode-ai/omnibase_infra/pulls/2471": (1, "API rate limit exceeded")}
    )
    monkeypatch.setattr(ldv.subprocess, "run", fake)
    status = ldv.fetch_pr_status(ldv.PRRef(2471, "OmniNode-ai/omnibase_infra"))
    assert status.error is not None
    assert "rate limit" in status.error
    assert ldv.classify_blocking(status) is True


def test_d_occ_membership_probe_reads_by_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRun(
        {"repos/OmniNode-ai/onex_change_control/pulls/4605": (0, {"number": 4605})}
    )
    monkeypatch.setattr(ldv.subprocess, "run", fake)
    assert ldv.probe_occ_membership(4605) is True
    assert fake.argvs[0][:2] == ["gh", "api"]
