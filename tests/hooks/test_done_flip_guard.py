# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit + regression tests for the Done-flip durable-evidence guard [OMN-13856].

The non-negotiable regression proofs (design §2 acceptance):

* the ``wf_1628d9a5`` incident shape — a Backlog→Done flip via ``save_issue``
  with no merged PR and no durable receipt — is BLOCKED;
* a legitimate Done-flip backed by durable evidence (a merged PR **or** a PASS
  OCC receipt on ``origin/dev``) is ALLOWED;
* freshness: a receipt that exists on ``origin/dev`` but NOT in the local clone's
  working tree is still ALLOWED (the guard reads the ref, not the stale tree).

Decision-level I/O boundaries (OCC probe, GitHub PR fetch, live Linear read) are
injected as deterministic stubs so those tests are hermetic. The git-backed OCC
probe itself is exercised against a real local temp git repo (no network).
"""

from __future__ import annotations

import importlib.util
import subprocess
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


def _no_receipt_probe(_ticket_id: str) -> bool:
    """No PASS OCC receipt on origin/dev (incident / unresolved)."""
    return False


def _receipt_probe(_ticket_id: str) -> bool:
    """A PASS OCC receipt on origin/dev exists for the ticket."""
    return True


def _never_called_probe(_ticket_id: str) -> bool:
    raise AssertionError("OCC probe must not be invoked on this path")


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
    d = guard.decide(call, occ_probe=_never_called_probe)
    assert d.allowed
    assert d.reason == "not_done_state"


def test_cancel_state_allows() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-1", "state": "Canceled"},
    }
    d = guard.decide(call, occ_probe=_never_called_probe)
    assert d.allowed
    assert d.reason == "carve_out:cancel_state"


def test_exempt_label_allows() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-1",
            "state": "Done",
            "description": "decision only",
            "labels": ["close-if-done"],
        },
    }
    d = guard.decide(call, occ_probe=_never_called_probe)
    assert d.allowed
    assert d.reason == "carve_out:exempt_label"


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
    d = guard.decide(call, occ_probe=_never_called_probe, pr_fetcher=_open_fetcher)
    assert not d.allowed
    assert "pr_not_merged" in d.reason


def test_close_if_done_label_does_not_bypass_open_linked_attachment_pr() -> None:
    """The exact OMN-14582 shape: status-only Done flip, PR linked via a Linear
    attachment (not cited in the body), close-if-done label present, PR OPEN.

    The guard folds the attachment URL into the merge check and BLOCKS — the
    OCC probe is never reached because the linked product PR is unmerged.
    """
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": "OMN-14582", "state": "Done"},
    }
    d = guard.decide(
        call,
        occ_probe=_never_called_probe,
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
        occ_probe=_never_called_probe,
        pr_fetcher=_merged_fetcher,
        linear_fetcher=lambda _t: {
            "description": "",
            "labels": ["close-if-done"],
            "attachment_urls": ["https://github.com/OmniNode-ai/omnimarket/pull/1754"],
        },
    )
    assert d.allowed
    assert d.reason == "durable_evidence:all_prs_merged"


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
        occ_probe=_no_receipt_probe,
        pr_fetcher=_open_fetcher,  # must not matter — no PR is cited
        linear_fetcher=_no_linear,
    )
    assert not d.allowed
    assert "no_durable_evidence" in d.reason


def test_incident_status_only_update_no_evidence_is_blocked() -> None:
    """Status-only update (description omitted) with no durable evidence → BLOCK."""
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": "OMN-13800", "state": "Done"},
    }
    # Live Linear read returns an issue with no PR reference and no exempt label.
    d = guard.decide(
        call,
        occ_probe=_no_receipt_probe,
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
    d = guard.decide(call, occ_probe=_never_called_probe, pr_fetcher=_open_fetcher)
    assert not d.allowed
    assert "pr_not_merged" in d.reason


def test_no_ticket_id_done_flip_is_blocked() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"state": "Done", "description": ""},
    }
    d = guard.decide(call, occ_probe=_never_called_probe)
    assert not d.allowed
    assert "no_ticket_id" in d.reason


def test_omni_home_unset_no_pr_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """OMNI_HOME unresolvable + no merged-PR citation → BLOCK (fail-closed).

    The OCC clone cannot be resolved without OMNI_HOME; the guard must NOT
    fail-open on a fake-Done (design requirement 4). No probe is injected, so the
    production default-probe path is exercised.
    """
    monkeypatch.delenv("OMNI_HOME", raising=False)
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-5", "state": "Done", "description": ""},
    }
    d = guard.decide(call, linear_fetcher=_no_linear)
    assert not d.allowed
    assert "OMNI_HOME" in d.reason


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
    d = guard.decide(call, occ_probe=_never_called_probe, pr_fetcher=_merged_fetcher)
    assert d.allowed
    assert d.reason == "durable_evidence:all_prs_merged"


def test_legit_occ_receipt_is_allowed() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-7", "state": "Done", "description": ""},
    }
    d = guard.decide(call, occ_probe=_receipt_probe, linear_fetcher=_no_linear)
    assert d.allowed
    assert d.reason == "durable_evidence:occ_receipt_on_dev"


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
        occ_probe=_never_called_probe,
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
    d = guard.decide(call, occ_probe=_never_called_probe, pr_fetcher=_merged_fetcher)
    assert d.allowed
    assert d.reason == "durable_evidence:all_prs_merged"


def test_unchecked_box_blocks_even_with_occ_receipt_evidence() -> None:
    """The checkbox gate is not waivable by the OCC-receipt path either — it
    runs before all evidence paths, including the receipt path.
    """
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-8",
            "state": "Done",
            "description": "## DoD\n\n- [ ] unmet acceptance criterion\n",
        },
    }
    d = guard.decide(call, occ_probe=_never_called_probe, linear_fetcher=_no_linear)
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
    d = guard.decide(call, occ_probe=_never_called_probe)
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
        call, occ_probe=_never_called_probe, linear_fetcher=_live_with_unchecked_box
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
        occ_probe=_never_called_probe,
        pr_fetcher=_never_called_fetcher,
        linear_fetcher=_no_linear,
    )
    assert d.allowed
    assert d.reason == "durable_evidence:deploy_readback_proven"


def test_deploy_readback_status_only_update_is_allowed() -> None:
    """Status-only Done flip: the marker is read from the live description."""
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": "OMN-14437", "state": "Done"},
    }
    d = guard.decide(
        call,
        occ_probe=_never_called_probe,
        pr_fetcher=_never_called_fetcher,
        linear_fetcher=lambda _t: {
            "description": _OMN_14437_DESCRIPTION,
            "labels": [],
        },
    )
    assert d.allowed
    assert d.reason == "durable_evidence:deploy_readback_proven"


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
    d = guard.decide(call, occ_probe=_never_called_probe, pr_fetcher=_open_fetcher)
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
    d = guard.decide(call, occ_probe=_never_called_probe, pr_fetcher=_merged_fetcher)
    assert d.allowed
    assert d.reason == "durable_evidence:deploy_readback_proven"


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
        occ_probe=_no_receipt_probe,
        pr_fetcher=_open_fetcher,
        linear_fetcher=_no_linear,
    )
    assert not d.allowed
    assert "no_durable_evidence" in d.reason


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
    d = guard.decide(call, occ_probe=_never_called_probe, pr_fetcher=_open_fetcher)
    assert not d.allowed
    assert "pr_not_merged" in d.reason


# --------------------------------------------------------------------------- #
# Receipt parsing / binding coverage
# --------------------------------------------------------------------------- #

_PASS_RECEIPT = """---
schema_version: "1.0.0"
ticket_id: OMN-9999
evidence_item_id: dod-001
check_type: command
status: PASS
run_timestamp: "2026-07-02T22:00:00Z"
probe_stdout: |
  status: PASS should not be parsed from this block scalar
commit_sha: "abc1234"
"""

_FAIL_RECEIPT = _PASS_RECEIPT.replace("status: PASS", "status: FAIL")

_VACUOUS_RECEIPT = """---
schema_version: "1.0.0"
ticket_id: OMN-9999
status: PASS
run_timestamp: "2026-07-02T22:00:00Z"
"""


def test_parse_receipt_fields_flat_scalars() -> None:
    fields = guard.parse_receipt_fields(_PASS_RECEIPT)
    assert fields["status"] == "PASS"
    assert fields["ticket_id"] == "OMN-9999"
    assert fields["evidence_item_id"] == "dod-001"
    assert fields["check_type"] == "command"
    # Block-scalar body must NOT leak a bogus top-level key.
    assert "should not be parsed" not in " ".join(fields.values())


def test_receipt_is_pass_bound() -> None:
    assert guard._receipt_is_pass_bound(
        guard.parse_receipt_fields(_PASS_RECEIPT), "OMN-9999"
    )
    # Wrong ticket
    assert not guard._receipt_is_pass_bound(
        guard.parse_receipt_fields(_PASS_RECEIPT), "OMN-0000"
    )
    # FAIL status
    assert not guard._receipt_is_pass_bound(
        guard.parse_receipt_fields(_FAIL_RECEIPT), "OMN-9999"
    )
    # PASS but no check binding (vacuous)
    assert not guard._receipt_is_pass_bound(
        guard.parse_receipt_fields(_VACUOUS_RECEIPT), "OMN-9999"
    )


# --------------------------------------------------------------------------- #
# Git-backed OCC probe — freshness against origin/dev (real local temp repo)
# --------------------------------------------------------------------------- #


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    )


def _make_occ_clone_with_dev_receipt(
    tmp_path: Path, ticket_id: str, receipt_text: str
) -> Path:
    """Build a clone whose origin/dev carries a receipt absent from its worktree."""
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", str(origin)], check=True, capture_output=True
    )
    clone = tmp_path / "onex_change_control"
    subprocess.run(
        ["git", "clone", str(origin), str(clone)], check=True, capture_output=True
    )
    _git(clone, "config", "user.email", "t@example.com")
    _git(clone, "config", "user.name", "t")
    _git(clone, "checkout", "-b", "dev")
    rp = clone / "drift" / "dod_receipts" / ticket_id / "dod-001"
    rp.mkdir(parents=True)
    (rp / "command.yaml").write_text(receipt_text, encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "add receipt on dev")
    _git(clone, "push", "origin", "dev")
    # Move the WORKING TREE off dev so the receipt is not present locally on-tree.
    _git(clone, "checkout", "-b", "other")
    _git(clone, "rm", "-r", "drift")
    _git(clone, "commit", "-m", "remove receipt from working tree")
    return clone


def test_occ_probe_reads_origin_dev_not_working_tree(tmp_path: Path) -> None:
    """FRESHNESS: receipt on origin/dev but absent from the working tree → True.

    This is the whole reason the guard reads the ref instead of the tree — a
    just-merged OCC receipt must be visible even when the local clone is behind.
    """
    clone = _make_occ_clone_with_dev_receipt(tmp_path, "OMN-9999", _PASS_RECEIPT)
    # Sanity: the receipt is NOT in the checked-out working tree.
    assert not (clone / "drift" / "dod_receipts" / "OMN-9999").exists()
    # But it IS resolvable on origin/dev.
    assert guard.occ_receipt_pass_on_dev(clone, "OMN-9999", fetch=True) is True


def test_occ_probe_missing_ticket_is_false(tmp_path: Path) -> None:
    clone = _make_occ_clone_with_dev_receipt(tmp_path, "OMN-9999", _PASS_RECEIPT)
    assert guard.occ_receipt_pass_on_dev(clone, "OMN-0000", fetch=True) is False


def test_occ_probe_fail_receipt_is_false(tmp_path: Path) -> None:
    clone = _make_occ_clone_with_dev_receipt(tmp_path, "OMN-9999", _FAIL_RECEIPT)
    assert guard.occ_receipt_pass_on_dev(clone, "OMN-9999", fetch=True) is False


def test_occ_probe_vacuous_receipt_is_false(tmp_path: Path) -> None:
    """A PASS receipt with no check binding is not durable evidence."""
    clone = _make_occ_clone_with_dev_receipt(tmp_path, "OMN-9999", _VACUOUS_RECEIPT)
    assert guard.occ_receipt_pass_on_dev(clone, "OMN-9999", fetch=True) is False


def test_occ_probe_missing_clone_is_false(tmp_path: Path) -> None:
    assert (
        guard.occ_receipt_pass_on_dev(tmp_path / "nope", "OMN-9999", fetch=False)
        is False
    )


def test_occ_probe_end_to_end_allows_via_decide(tmp_path: Path) -> None:
    """decide() ALLOWS when the injected probe resolves a real origin/dev receipt."""
    clone = _make_occ_clone_with_dev_receipt(tmp_path, "OMN-9999", _PASS_RECEIPT)
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-9999", "state": "Done", "description": ""},
    }
    d = guard.decide(
        call,
        occ_probe=lambda tid: guard.occ_receipt_pass_on_dev(clone, tid, fetch=True),
        linear_fetcher=_no_linear,
    )
    assert d.allowed
    assert d.reason == "durable_evidence:occ_receipt_on_dev"


# --------------------------------------------------------------------------- #
# main() end-to-end exit codes via stdin
# --------------------------------------------------------------------------- #


def test_main_blocks_incident(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    # Hermetic: no OMNI_HOME (OCC clone can't resolve) and no LINEAR_API_KEY (the
    # real fetcher returns {} instead of a live network call) => fail-closed.
    monkeypatch.delenv("OMNI_HOME", raising=False)
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
