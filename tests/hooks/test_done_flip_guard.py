# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit and regression tests for the repo-evidence Done-flip guard.

Done and acceptance-box ticks require repo contracts and passing checks.
GitHub, repo evidence and live Linear reads are injected to keep tests hermetic.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

# The guard lib lives under plugins/onex/hooks/lib and imports its sibling
# ``linear_done_verify`` by bare name (the shell wrapper runs it with that dir on
# sys.path[0]). Load it the same way so the sibling import resolves.
_LIB_DIR = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"


def _load_guard() -> Any:
    import sys

    sys.path.insert(0, str(_LIB_DIR))
    spec = importlib.util.spec_from_file_location(
        "done_flip_guard", _LIB_DIR / "done_flip_guard.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve the module by name.
    sys.modules["done_flip_guard"] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()
import no_pr_bound_evidence as nbe  # noqa: E402  (sibling import needs sys.path)


@pytest.fixture(autouse=True)
def _hermetic_linear(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reaches Linear: the default fetcher reads an empty key as 'no live data'."""
    monkeypatch.setenv("LINEAR_API_KEY", "")


# --------------------------------------------------------------------------- #
# Stub factories
# --------------------------------------------------------------------------- #


def _pr_status(state: str, merge_state: str = "CLEAN", error: str | None = None):
    from linear_done_verify import PRRef, PRStatus

    return PRStatus(
        ref=PRRef(number=1, repo="OmniNode-ai/omniclaude"),
        state=state,
        merge_state=merge_state,
        error=error,
    )


def _merged_fetcher(_ref: Any):
    return _pr_status("MERGED")


def _open_fetcher(_ref: Any):
    return _pr_status("OPEN")


def _closed_fetcher(_ref: Any):
    """A CLOSED-without-merge PR (the scratch live-mint readback shape)."""
    return _pr_status("CLOSED")


def _never_called_fetcher(_ref: Any):
    raise AssertionError(
        "no scratch / narrative PR ref must be fetched on the deploy-readback path"
    )


def _no_repo_probe(_ticket_id: str, _descriptions: list[str], _prs: list[Any]) -> Any:
    return nbe.RepoEvidenceVerdict(
        nbe.RepoEvidenceOutcome.NOT_ENGAGED, "no merged product PR carries the contract"
    )


def _repo_pass_probe(_ticket_id: str, _descriptions: list[str], _prs: list[Any]) -> Any:
    return nbe.RepoEvidenceVerdict(
        nbe.RepoEvidenceOutcome.PASSED, "repo-bound: AC1<-dod-001"
    )


def _never_called_probe(*_args: Any) -> Any:
    raise AssertionError("repo evidence must not be evaluated on this path")


def _no_linear(_ticket_id: str) -> dict[str, Any] | None:
    return {}  # LINEAR_API_KEY-absent shape: no live data


# --------------------------------------------------------------------------- #
# Pass-through / carve-out cases
# --------------------------------------------------------------------------- #


def test_non_linear_tool_allows() -> None:
    d = guard.decide({"tool_name": "Read", "tool_input": {}})
    assert d.allowed


def test_non_done_state_allows() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-1", "state": "In Progress"},
    }
    d = guard.decide(call, repo_evidence_probe=_never_called_probe)
    assert d.allowed
    assert d.reason == "not_done_state"


def test_cancel_state_allows() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-1", "state": "Canceled"},
    }
    d = guard.decide(call, repo_evidence_probe=_never_called_probe)
    assert d.allowed
    assert d.reason == "carve_out:cancel_state"


def test_exempt_label_alone_no_longer_closes_omn_20368() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-1",
            "state": "Done",
            "description": "decision only",
            "labels": ["close-if-done"],
        },
    }
    d = guard.decide(call, repo_evidence_probe=_no_repo_probe)
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason
    d = guard.decide(call, repo_evidence_probe=_repo_pass_probe)
    assert d.allowed, d.reason
    assert d.reason == "durable_evidence:repo_bound_checks"


# --------------------------------------------------------------------------- #
# REGRESSION: the OMN-14582 shape — close-if-done label MUST NOT waive an open
# cited/linked product PR (OMN-14641). This is the integrity bug being fixed.
# --------------------------------------------------------------------------- #


def test_close_if_done_label_does_not_bypass_open_cited_pr() -> None:
    """A close-if-done ticket that cites an OPEN product PR in its body → BLOCK.

    Before OMN-14641 the label short-circuited to ALLOW before any PR check.
    """
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-14582",
            "state": "Done",
            "description": (
                "Phase 1 only. PR: https://github.com/OmniNode-ai/omnimarket/pull/1754"
            ),
            "labels": ["close-if-done"],
        },
    }
    d = guard.decide(
        call,
        repo_evidence_probe=_never_called_probe,
        pr_fetcher=_open_fetcher,
    )
    assert not d.allowed
    assert "pr_not_merged" in d.reason


def test_close_if_done_label_does_not_bypass_open_linked_attachment_pr() -> None:
    """The exact OMN-14582 shape: status-only Done flip, PR linked via a Linear
    attachment (not cited in the body), close-if-done label present, PR OPEN.

    The guard folds the attachment URL into the merge check and BLOCKS — the
    Repo evidence is never reached because the linked product PR is unmerged.
    """
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": "OMN-14582", "state": "Done"},
    }
    d = guard.decide(
        call,
        repo_evidence_probe=_never_called_probe,
        pr_fetcher=_open_fetcher,
        linear_fetcher=lambda _t: {
            "description": "",
            "labels": ["close-if-done"],
            "attachment_urls": ["https://github.com/OmniNode-ai/omnimarket/pull/1754"],
        },
    )
    assert not d.allowed
    assert "pr_not_merged" in d.reason


def test_close_if_done_label_allows_merged_linked_attachment_pr() -> None:
    """Symmetric: when the linked PR is MERGED, the Done flip is ALLOWED."""
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": "OMN-14582", "state": "Done"},
    }
    d = guard.decide(
        call,
        repo_evidence_probe=_repo_pass_probe,
        pr_fetcher=_merged_fetcher,
        linear_fetcher=lambda _t: {
            "description": "",
            "labels": ["close-if-done"],
            "attachment_urls": ["https://github.com/OmniNode-ai/omnimarket/pull/1754"],
        },
    )
    assert d.allowed
    assert d.reason == "durable_evidence:repo_bound_checks:all_prs_merged"


# --------------------------------------------------------------------------- #
# REGRESSION: the wf_1628d9a5 incident shape must be BLOCKED
# --------------------------------------------------------------------------- #


def test_incident_backlog_to_done_no_evidence_is_blocked() -> None:
    """wf_1628d9a5: Done flip, no PR cited, no durable receipt → BLOCK.

    This is the exact escape both legacy guards missed: linear_done_verify
    ALLOWS 'no_pr_references' and dod_completion fails OPEN when its evidence
    root is unset. The merged guard blocks.
    """
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-13797",
            "state": "Done",
            "description": "",  # no PR citation, no exemption
        },
    }
    d = guard.decide(
        call,
        repo_evidence_probe=_no_repo_probe,
        pr_fetcher=_open_fetcher,  # must not matter — no PR is cited
        linear_fetcher=_no_linear,
    )
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason


def test_incident_status_only_update_no_evidence_is_blocked() -> None:
    """Status-only update (description omitted) with no durable evidence → BLOCK."""
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": "OMN-13800", "state": "Done"},
    }
    # Live Linear read returns an issue with no PR reference and no exempt label.
    d = guard.decide(
        call,
        repo_evidence_probe=_no_repo_probe,
        linear_fetcher=lambda _t: {"description": "just closing this", "labels": []},
    )
    assert not d.allowed


def test_cited_pr_open_is_blocked() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-3",
            "state": "Done",
            "description": "Fixes https://github.com/OmniNode-ai/omniclaude/pull/1",
        },
    }
    d = guard.decide(
        call, repo_evidence_probe=_never_called_probe, pr_fetcher=_open_fetcher
    )
    assert not d.allowed
    assert "pr_not_merged" in d.reason


def test_no_ticket_id_done_flip_is_blocked() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"state": "Done", "description": ""},
    }
    d = guard.decide(call, repo_evidence_probe=_never_called_probe)
    assert not d.allowed
    assert "no_ticket_id" in d.reason


def test_no_merged_pr_default_repo_verdict_fails_closed() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-5", "state": "Done", "description": ""},
    }
    d = guard.decide(call, linear_fetcher=_no_linear, pr_fetcher=_never_called_fetcher)
    assert not d.allowed
    assert d.reason.startswith("no_bound_dod_receipt for OMN-5")
    assert "no merged product PR" in d.reason


# --------------------------------------------------------------------------- #
# REGRESSION: legitimate Done-flips backed by durable evidence are ALLOWED
# --------------------------------------------------------------------------- #


def test_legit_merged_pr_citation_is_allowed() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-6",
            "state": "Done",
            "description": (
                "Implemented in https://github.com/OmniNode-ai/omniclaude/pull/1"
            ),
        },
    }
    d = guard.decide(
        call, repo_evidence_probe=_repo_pass_probe, pr_fetcher=_merged_fetcher
    )
    assert d.allowed
    assert d.reason == "durable_evidence:repo_bound_checks:all_prs_merged"


def test_passed_repo_verdict_is_allowed() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-7", "state": "Done", "description": ""},
    }
    d = guard.decide(
        call, repo_evidence_probe=_repo_pass_probe, linear_fetcher=_no_linear
    )
    assert d.allowed
    assert d.reason == "durable_evidence:repo_bound_checks"


# --------------------------------------------------------------------------- #
# OMN-15030 / OMN-13991: unchecked acceptance-criteria checkbox gate.
#
# Reproduces the OMN-13991 false-Done SHAPE — a genuinely merged, genuinely
# cited, genuinely implementing PR whose own body admits the ticket's DoD was
# not fully delivered ("Staged: shadow -> measured -> enforcing" only reached
# "measured"). The guard's merged-PR-citation path (path A) ALLOWS this by
# design — "merged" is the only thing it checks. The checkbox gate is the
# first mechanism that can BLOCK on the ticket's own stated, still-unmet
# acceptance criteria regardless of what evidence is otherwise cited.
# --------------------------------------------------------------------------- #

# OMN-13991's real DoD, rewritten with GFM checkboxes as
# feedback_specify_acceptance_tests_in_the_ticket prescribes for new tickets.
_OMN_13991_SHAPED_DESCRIPTION = """\
## DoD

- [x] `DurableEvidenceGate.enforce_default` runs on the live Linear-Done \
transition (not test-only).
- [ ] Staged: shadow -> measured -> enforcing, with evidence the enforcing \
flip does not block legitimate Done transitions.

Implemented in https://github.com/OmniNode-ai/omnimarket/pull/1838
"""


def test_find_unchecked_acceptance_boxes_matches_bullets_and_numbered_items() -> None:
    boxes = guard.find_unchecked_acceptance_boxes(
        "- [ ] bullet item\n"
        "* [ ] star item\n"
        "1. [ ] numbered item\n"
        "2) [ ] paren-numbered item\n"
        "- [x] checked item (not returned)\n"
        "- [X] checked uppercase (not returned)\n"
        "plain text mentioning [ ] mid-sentence (not a list item)\n"
    )
    assert boxes == [
        "- [ ] bullet item",
        "* [ ] star item",
        "1. [ ] numbered item",
        "2) [ ] paren-numbered item",
    ]


def test_find_unchecked_acceptance_boxes_empty_for_no_boxes() -> None:
    assert guard.find_unchecked_acceptance_boxes("no boxes here at all") == []
    assert guard.find_unchecked_acceptance_boxes("") == []


def test_red_merged_pr_with_unchecked_acceptance_box_is_accepted_by_the_old_path() -> (
    None
):
    """RED: replaying ONLY the pre-existing merged-PR check (path A) on the
    OMN-13991 SHAPE allows the flip — proving the gap this ticket closes.
    """
    from linear_done_verify import verify

    result = verify(
        _OMN_13991_SHAPED_DESCRIPTION, [], default_repo=None, fetcher=_merged_fetcher
    )
    assert result.allowed
    assert result.reason == "all_prs_merged"


def test_green_merged_pr_with_unchecked_acceptance_box_is_blocked() -> None:
    """GREEN: the real ``decide()`` entrypoint — which now runs the checkbox
    gate BEFORE the merged-PR path — blocks the same OMN-13991-shaped call.
    """
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-13991",
            "state": "Done",
            "description": _OMN_13991_SHAPED_DESCRIPTION,
        },
    }
    d = guard.decide(
        call,
        repo_evidence_probe=_never_called_probe,
        pr_fetcher=_never_called_fetcher,
    )
    assert not d.allowed
    assert "unchecked_acceptance_criteria" in d.reason
    assert "Staged: shadow -> measured -> enforcing" in d.reason


def test_all_boxes_checked_is_not_blocked_by_the_checkbox_gate() -> None:
    """A ticket whose author checked every box is unaffected — the gate is
    additive, not a new universal requirement to add checkboxes at all.
    """
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-13991",
            "state": "Done",
            "description": (
                "## DoD\n\n- [x] first item done\n- [x] second item done\n\n"
                "Implemented in "
                "https://github.com/OmniNode-ai/omnimarket/pull/1838"
            ),
        },
    }
    d = guard.decide(
        call, repo_evidence_probe=_repo_pass_probe, pr_fetcher=_merged_fetcher
    )
    assert d.allowed
    assert d.reason == "durable_evidence:repo_bound_checks:all_prs_merged"


def test_unchecked_box_blocks_before_repo_evidence() -> None:
    """Unchecked boxes refuse before repo evidence is evaluated."""
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-8",
            "state": "Done",
            "description": "## DoD\n\n- [ ] unmet acceptance criterion\n",
        },
    }
    d = guard.decide(
        call, repo_evidence_probe=_never_called_probe, linear_fetcher=_no_linear
    )
    assert not d.allowed
    assert "unchecked_acceptance_criteria" in d.reason


def test_unchecked_box_blocks_even_with_exempt_label() -> None:
    """The checkbox gate runs before the close-if-done exemption carve-out."""
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-9",
            "state": "Done",
            "description": "## DoD\n\n- [ ] unmet acceptance criterion\n",
            "labels": ["close-if-done"],
        },
    }
    d = guard.decide(call, repo_evidence_probe=_never_called_probe)
    assert not d.allowed
    assert "unchecked_acceptance_criteria" in d.reason


def test_status_only_update_checks_live_fetched_description_for_boxes() -> None:
    """Status-only updates (no description in the call) must still be checked
    against the LIVE Linear description, matching the existing live-fetch
    behavior for PR citations / exemption labels.
    """

    def _live_with_unchecked_box(_ticket_id: str) -> dict[str, Any]:
        return {"description": "- [ ] still open item", "labels": []}

    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-10", "state": "Done"},
    }
    d = guard.decide(
        call,
        repo_evidence_probe=_never_called_probe,
        linear_fetcher=_live_with_unchecked_box,
    )
    assert not d.allowed
    assert "unchecked_acceptance_criteria" in d.reason


# --------------------------------------------------------------------------- #
# OMN-14792: deploy-readback marker path — runtime-deploy tickets proven by a
# live readback (no merged implementing PR) must be ALLOWED, while the marker
# must NOT become a blanket bypass for an unmerged implementing PR.
# --------------------------------------------------------------------------- #

# The OMN-14437 shape: a runtime-deploy ticket whose completion evidence is a
# live readback. Its only PR references are (a) an intentionally-closed scratch
# live-mint readback PR and (b) bare merge-chain-narrative numbers with no repo.
# Neither is a DoD-implementing citation; both previously false-blocked the flip.
_OMN_14437_DESCRIPTION = """\
## Effects runtime image rebuilt to dev-tip (runtime-deploy)

deploy-readback-proven: DEV effects image rebuilt to dev-tip; clean 30/0 live \
OCC mint read back off the deployed bytes; introspection probe exit 0

Scratch live-mint readback PR (intentional throwaway, do-not-merge):
https://github.com/OmniNode-ai/omnimarket/pull/1817

Historical merge-chain narrative (context only — landed long ago): the OCC
autobind emitter fixes shipped across #1724 / #3990 / #3995.
"""


def test_deploy_readback_ticket_with_scratch_and_narrative_is_allowed() -> None:
    """OMN-14437 shape → ALLOWED via the deploy-readback marker.

    The scratch closed PR and bare narrative numbers must NOT be fetched or
    treated as blocking DoD evidence — ``_never_called_fetcher`` proves none of
    them reach the PR-status probe.
    """
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-14437",
            "state": "Done",
            "description": _OMN_14437_DESCRIPTION,
        },
    }
    d = guard.decide(
        call,
        repo_evidence_probe=_repo_pass_probe,
        pr_fetcher=_never_called_fetcher,
        linear_fetcher=_no_linear,
    )
    assert d.allowed
    assert d.reason == "durable_evidence:repo_bound_checks"


def test_deploy_readback_status_only_update_is_allowed() -> None:
    """Status-only Done flip: the marker is read from the live description."""
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": "OMN-14437", "state": "Done"},
    }
    d = guard.decide(
        call,
        repo_evidence_probe=_repo_pass_probe,
        pr_fetcher=_never_called_fetcher,
        linear_fetcher=lambda _t: {
            "description": _OMN_14437_DESCRIPTION,
            "labels": [],
        },
    )
    assert d.allowed
    assert d.reason == "durable_evidence:repo_bound_checks"


def test_deploy_readback_marker_does_not_bypass_open_implementing_pr() -> None:
    """The marker is NOT a blanket bypass: a ticket carrying it that also cites
    an OPEN *implementing* product PR (no scratch annotation) is still BLOCKED.

    This is the OMN-14641 integrity rule applied to the deploy-readback path.
    """
    desc = (
        "deploy-readback-proven: rebuilt dev effects to dev-tip; probe exit 0\n\n"
        "Implemented in https://github.com/OmniNode-ai/omnimarket/pull/2000\n"
    )
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-14999", "state": "Done", "description": desc},
    }
    d = guard.decide(
        call, repo_evidence_probe=_never_called_probe, pr_fetcher=_open_fetcher
    )
    assert not d.allowed
    assert "pr_not_merged" in d.reason


def test_deploy_readback_marker_allows_when_implementing_pr_merged() -> None:
    """Symmetric: a marker ticket whose implementing PR is MERGED is ALLOWED."""
    desc = (
        "deploy-readback-proven: rebuilt dev effects to dev-tip; probe exit 0\n\n"
        "Implemented in https://github.com/OmniNode-ai/omnimarket/pull/2000\n"
    )
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-14998", "state": "Done", "description": desc},
    }
    d = guard.decide(
        call, repo_evidence_probe=_repo_pass_probe, pr_fetcher=_merged_fetcher
    )
    assert d.allowed
    assert d.reason == "durable_evidence:repo_bound_checks"


def test_empty_deploy_readback_marker_is_not_accepted() -> None:
    """A content-free ``deploy-readback-proven:`` (no probe/receipt evidence) is
    NOT a bypass token — it falls through to the normal fail-closed path."""
    desc = "deploy-readback-proven:\n\nno actual readback evidence provided"
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-15000", "state": "Done", "description": desc},
    }
    d = guard.decide(
        call,
        repo_evidence_probe=_no_repo_probe,
        pr_fetcher=_open_fetcher,
        linear_fetcher=_no_linear,
    )
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason


def test_code_ticket_open_implementing_pr_blocked_without_marker() -> None:
    """Acceptance pair: a code ticket citing an OPEN implementing PR and NO
    deploy-readback marker is still BLOCKED (the marker path is never entered)."""
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-14997",
            "state": "Done",
            "description": (
                "Implemented in https://github.com/OmniNode-ai/omnimarket/pull/2001"
            ),
        },
    }
    d = guard.decide(
        call, repo_evidence_probe=_never_called_probe, pr_fetcher=_open_fetcher
    )
    assert not d.allowed
    assert "pr_not_merged" in d.reason


# --------------------------------------------------------------------------- #
# main() end-to-end exit codes via stdin
# --------------------------------------------------------------------------- #


def test_main_blocks_incident(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    # No live Linear data or merged PR: fail closed without network I/O.
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    payload = (
        '{"tool_name": "mcp__linear-server__save_issue", '
        '"tool_input": {"id": "OMN-13797", "state": "Done", "description": ""}}'
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert guard.main() == 2


def test_main_allows_non_done(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    payload = (
        '{"tool_name": "mcp__linear-server__save_issue", '
        '"tool_input": {"id": "OMN-1", "state": "In Progress"}}'
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert guard.main() == 0


def test_errored_pr_probe_still_blocks_omn_18747() -> None:
    """An unresolvable bare PR reference refuses before repo evidence is read."""
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": "OMN-90002", "state": "Done"},
    }

    def _errors_on_unresolvable(ref: Any) -> Any:
        from linear_done_verify import PRStatus

        if ref.repo is None:
            return PRStatus(
                ref=ref,
                state="UNKNOWN",
                merge_state="UNKNOWN",
                error=f"PR #{ref.number} has no associated repo; cannot verify.",
            )
        return PRStatus(ref=ref, state="MERGED", merge_state="CLEAN")

    d = guard.decide(
        call,
        repo_evidence_probe=_never_called_probe,
        pr_fetcher=_errors_on_unresolvable,
        linear_fetcher=lambda _t: {
            # #4242 is anchored by nothing — no qualified citation of that
            # number, and "a"/"the" are not repository names.
            "description": "Implementing work landed in a PR #4242.",
            "labels": [],
            "attachment_urls": [
                "https://github.com/OmniNode-ai/omnimarket/pull/9001",
            ],
        },
    )
    assert not d.allowed
    assert "pr_not_merged" in d.reason
    assert "4242" in d.reason


def test_anchored_bare_ref_is_verified_rather_than_refused_omn_18747() -> None:
    """OMN-18747 companion: the same ticket shape, with the repository named.

    This is the OMN-18086 refusal, reduced. The bare reference is anchored by
    an explicit ``OmniNode-ai/omnimarket#9001`` citation elsewhere in the body,
    so it resolves and is verified as merged instead of refused unverifiable.
    """
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": "OMN-90003", "state": "Done"},
    }

    def _errors_on_unresolvable(ref: Any) -> Any:
        from linear_done_verify import PRStatus

        if ref.repo is None:
            return PRStatus(
                ref=ref,
                state="UNKNOWN",
                merge_state="UNKNOWN",
                error=f"PR #{ref.number} has no associated repo; cannot verify.",
            )
        return PRStatus(ref=ref, state="MERGED", merge_state="CLEAN")

    d = guard.decide(
        call,
        repo_evidence_probe=_repo_pass_probe,
        pr_fetcher=_errors_on_unresolvable,
        linear_fetcher=lambda _t: {
            "description": (
                "AC1: implemented in omnimarket PR #9001.\n\n"
                "Carrier: OmniNode-ai/omnimarket#9001 — merged."
            ),
            "labels": [],
            "attachment_urls": [],
        },
    )
    assert d.allowed, d.reason
    assert d.reason == "durable_evidence:repo_bound_checks:all_prs_merged"


@pytest.mark.parametrize("state", ["OPEN", "CLOSED", "UNKNOWN"])
def test_blocking_attachment_refuses_before_repo_evidence(state: str) -> None:
    from linear_done_verify import PRStatus

    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-15422", "state": "Done"},
    }
    decision = guard.decide(
        call,
        linear_fetcher=lambda _t: {
            "description": "AC1: replacement shipped",
            "attachment_urls": ["https://github.com/OmniNode-ai/omniclaude/pull/2596"],
        },
        pr_fetcher=lambda ref: PRStatus(
            ref=ref,
            state=state,
            merge_state="UNKNOWN",
            error="PR read failed" if state == "UNKNOWN" else None,
        ),
        repo_evidence_probe=_never_called_probe,
    )
    assert not decision.allowed
    assert decision.reason.startswith("pr_not_merged\n")
    assert "2596" in decision.reason
