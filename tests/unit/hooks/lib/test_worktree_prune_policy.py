# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the ticket-close-keyed worktree prune policy (OMN-16901).

The policy is a **two-part predicate**, and these tests hold the line on both
halves independently:

* **ELIGIBILITY** fires on TICKET CLOSING, never on a PR merging. A ticket that
  is still open or In Progress is NEVER prune-eligible, however spotless its
  worktree looks.
* **SAFETY** gates an already-eligible worktree on local git state. A dirty tree
  must NEVER classify safe. An ahead-unmerged branch must NEVER classify safe.
  A squash-merged branch whose tree-diff against ``dev`` is empty MUST classify
  safe — that is exactly the shape a squash leaves behind.

Everything that is not PRUNE is TRIAGE with named block reasons — never a
silent drop, never a deletion.

All functions under test are pure (no I/O) so a future event hook can call the
same predicate with no scheduler and no filesystem involved.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from omniclaude.hooks.lib.worktree_prune_policy import (
    EnumPruneBlockReason,
    EnumPruneDisposition,
    EnumTicketLifecycle,
    ModelWorktreePruneDecision,
    ModelWorktreePruneFacts,
    classify_worktree_prune,
    is_prune_eligible,
    is_prune_safe,
)

pytestmark = pytest.mark.unit


def _facts(**overrides: object) -> ModelWorktreePruneFacts:
    """Build a fully prunable baseline: closed ticket, clean tree, nothing ahead."""
    base: dict[str, object] = {
        "path": "/wt/omni_worktrees/OMN-1234/omniclaude",
        "ticket": "OMN-1234",
        "repo": "omniclaude",
        "branch": "jonah/omn-1234-thing",
        "ticket_state": EnumTicketLifecycle.DONE,
        "ledger_has_terminal": True,
        "ledger_open_claim": None,
        "base_ref": "origin/dev",
        "dirty_files": (),
        "commits_ahead": 0,
        "unmerged_ahead_commits": (),
        "tree_diff_vs_base_empty": True,
        "attributed_stash_count": 0,
        "unreadable_probes": (),
    }
    base.update(overrides)
    return ModelWorktreePruneFacts(**base)  # type: ignore[arg-type]


# =============================================================================
# ELIGIBILITY — keyed to ticket closing, not to a PR merging
# =============================================================================


class TestEligibility:
    def test_done_ticket_is_eligible(self) -> None:
        eligible, reasons, evidence = is_prune_eligible(
            _facts(ticket_state=EnumTicketLifecycle.DONE)
        )
        assert eligible is True
        assert reasons == ()
        assert "done" in evidence.lower()

    def test_canceled_ticket_is_eligible(self) -> None:
        eligible, reasons, _ = is_prune_eligible(
            _facts(ticket_state=EnumTicketLifecycle.CANCELED)
        )
        assert eligible is True
        assert reasons == ()

    @pytest.mark.parametrize("state", [EnumTicketLifecycle.OPEN])
    def test_open_ticket_is_never_eligible_however_clean_the_tree(
        self, state: EnumTicketLifecycle
    ) -> None:
        """The absolute line: an open ticket is not prunable, spotless or not."""
        facts = _facts(
            ticket_state=state,
            ledger_has_terminal=True,  # even a TERMINAL row must not override
            dirty_files=(),
            commits_ahead=0,
        )
        eligible, reasons, _ = is_prune_eligible(facts)
        assert eligible is False
        assert EnumPruneBlockReason.TICKET_NOT_CLOSED in reasons

    def test_unknown_ticket_state_falls_back_to_ledger_terminal(self) -> None:
        eligible, reasons, evidence = is_prune_eligible(
            _facts(
                ticket_state=EnumTicketLifecycle.UNKNOWN,
                ledger_has_terminal=True,
                ledger_open_claim=None,
            )
        )
        assert eligible is True
        assert reasons == ()
        assert "terminal" in evidence.lower()

    def test_unknown_ticket_state_without_terminal_fails_closed(self) -> None:
        eligible, reasons, _ = is_prune_eligible(
            _facts(
                ticket_state=EnumTicketLifecycle.UNKNOWN,
                ledger_has_terminal=False,
            )
        )
        assert eligible is False
        assert EnumPruneBlockReason.TICKET_UNRESOLVED in reasons

    def test_newer_open_claim_blocks_even_a_done_ticket(self) -> None:
        """A live lane re-claimed the ticket — never delete out from under it."""
        eligible, reasons, _ = is_prune_eligible(
            _facts(
                ticket_state=EnumTicketLifecycle.DONE,
                ledger_has_terminal=True,
                ledger_open_claim="2026-08-28T20:35:00Z | omn-1234-repair",
            )
        )
        assert eligible is False
        assert EnumPruneBlockReason.OPEN_CLAIM in reasons

    def test_worktree_with_no_ticket_is_never_eligible(self) -> None:
        eligible, reasons, _ = is_prune_eligible(
            _facts(path="/wt/omni_worktrees/sweep/omniclaude", ticket=None)
        )
        assert eligible is False
        assert EnumPruneBlockReason.NO_TICKET in reasons

    def test_no_ticket_does_not_also_report_unresolved(self) -> None:
        """NO_TICKET is the whole finding; TICKET_UNRESOLVED on top is noise."""
        _, reasons, _ = is_prune_eligible(
            _facts(
                path="/wt/omni_worktrees/sweep/omniclaude",
                ticket=None,
                ticket_state=EnumTicketLifecycle.UNKNOWN,
                ledger_has_terminal=False,
            )
        )
        assert reasons == (EnumPruneBlockReason.NO_TICKET,)


# =============================================================================
# SAFETY — applied only after eligibility; the safety line is absolute
# =============================================================================


class TestSafety:
    def test_clean_and_not_ahead_is_safe(self) -> None:
        safe, reasons, evidence = is_prune_safe(_facts())
        assert safe is True
        assert reasons == ()
        assert evidence

    def test_dirty_tree_is_never_safe(self) -> None:
        safe, reasons, _ = is_prune_safe(_facts(dirty_files=("src/a.py", "docs/b.md")))
        assert safe is False
        assert EnumPruneBlockReason.DIRTY_TREE in reasons

    def test_dirty_tree_is_never_safe_even_when_fully_merged(self) -> None:
        """Merged-ness must not launder uncommitted work."""
        safe, reasons, _ = is_prune_safe(
            _facts(
                dirty_files=("src/a.py",),
                commits_ahead=0,
                tree_diff_vs_base_empty=True,
            )
        )
        assert safe is False
        assert EnumPruneBlockReason.DIRTY_TREE in reasons

    def test_ahead_unmerged_branch_is_never_safe(self) -> None:
        safe, reasons, _ = is_prune_safe(
            _facts(
                commits_ahead=3,
                unmerged_ahead_commits=("abc1234", "def5678", "0123456"),
                tree_diff_vs_base_empty=False,
            )
        )
        assert safe is False
        assert EnumPruneBlockReason.AHEAD_UNMERGED in reasons

    def test_squash_merged_branch_with_empty_tree_diff_is_safe(self) -> None:
        """A squash orphans the branch: commits still ahead, content already in dev."""
        safe, reasons, evidence = is_prune_safe(
            _facts(
                commits_ahead=4,
                unmerged_ahead_commits=("abc1234", "def5678"),
                tree_diff_vs_base_empty=True,
            )
        )
        assert safe is True
        assert reasons == ()
        assert "origin/dev" in evidence

    def test_ahead_commits_all_cherry_equivalent_in_base_are_safe(self) -> None:
        safe, reasons, _ = is_prune_safe(
            _facts(
                commits_ahead=2,
                unmerged_ahead_commits=(),
                tree_diff_vs_base_empty=False,
            )
        )
        assert safe is True
        assert reasons == ()

    def test_unpushed_stash_is_never_safe(self) -> None:
        safe, reasons, _ = is_prune_safe(_facts(attributed_stash_count=1))
        assert safe is False
        assert EnumPruneBlockReason.UNPUSHED_STASH in reasons

    def test_detached_head_is_never_safe(self) -> None:
        safe, reasons, _ = is_prune_safe(_facts(branch=None))
        assert safe is False
        assert EnumPruneBlockReason.DETACHED_HEAD in reasons

    def test_unresolvable_base_ref_fails_closed(self) -> None:
        safe, reasons, _ = is_prune_safe(_facts(base_ref=None))
        assert safe is False
        assert EnumPruneBlockReason.BASE_REF_UNRESOLVED in reasons

    def test_an_unreadable_git_probe_is_never_safe(self) -> None:
        """A probe that failed is an UNKNOWN fact, never a clean one.

        `git status --porcelain` returning non-zero (timeout, OSError, a broken
        gitdir pointer) yields empty stdout. Read as a fact that would mean
        "clean tree"; read honestly it means "we do not know". An empty result is
        not evidence of absence, and here the difference is deleting live work.
        """
        safe, reasons, evidence = is_prune_safe(
            _facts(unreadable_probes=("git status --porcelain",))
        )
        assert safe is False
        assert EnumPruneBlockReason.FACTS_UNREADABLE in reasons
        assert evidence == ""

    def test_unreadable_probe_blocks_even_when_every_other_fact_looks_clean(
        self,
    ) -> None:
        safe, reasons, _ = is_prune_safe(
            _facts(
                dirty_files=(),
                commits_ahead=0,
                attributed_stash_count=0,
                unreadable_probes=("git rev-list --count origin/dev..HEAD",),
            )
        )
        assert safe is False
        assert EnumPruneBlockReason.FACTS_UNREADABLE in reasons

    def test_every_block_reason_is_reported_not_just_the_first(self) -> None:
        safe, reasons, _ = is_prune_safe(
            _facts(
                dirty_files=("src/a.py",),
                commits_ahead=2,
                unmerged_ahead_commits=("abc1234",),
                tree_diff_vs_base_empty=False,
                attributed_stash_count=2,
            )
        )
        assert safe is False
        assert EnumPruneBlockReason.DIRTY_TREE in reasons
        assert EnumPruneBlockReason.AHEAD_UNMERGED in reasons
        assert EnumPruneBlockReason.UNPUSHED_STASH in reasons


# =============================================================================
# Combined decision — eligibility FIRES, safety GATES
# =============================================================================


class TestClassifyWorktreePrune:
    def test_closed_ticket_and_safe_tree_prunes(self) -> None:
        decision = classify_worktree_prune(_facts())
        assert isinstance(decision, ModelWorktreePruneDecision)
        assert decision.disposition is EnumPruneDisposition.PRUNE
        assert decision.block_reasons == ()
        assert decision.eligibility_evidence
        assert decision.safety_evidence

    def test_open_ticket_with_spotless_tree_triages(self) -> None:
        decision = classify_worktree_prune(
            _facts(ticket_state=EnumTicketLifecycle.OPEN, ledger_has_terminal=False)
        )
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert EnumPruneBlockReason.TICKET_NOT_CLOSED in decision.block_reasons

    def test_closed_ticket_with_dirty_tree_triages_and_reports_the_hazard(
        self,
    ) -> None:
        decision = classify_worktree_prune(
            _facts(dirty_files=("src/a.py", "src/b.py", "docs/c.md"))
        )
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert EnumPruneBlockReason.DIRTY_TREE in decision.block_reasons
        # Triage rows carry the adjudication facts a human needs.
        assert decision.dirty_file_count == 3
        assert decision.path == "/wt/omni_worktrees/OMN-1234/omniclaude"
        assert decision.branch == "jonah/omn-1234-thing"

    def test_ineligible_worktree_does_not_report_safety_evidence(self) -> None:
        """Safety is a gate applied AFTER eligibility, never a substitute for it."""
        decision = classify_worktree_prune(
            _facts(ticket_state=EnumTicketLifecycle.OPEN, ledger_has_terminal=False)
        )
        assert decision.safety_evidence == ""

    def test_triage_row_carries_the_matching_ledger_claim(self) -> None:
        claim = "2026-08-28T20:35:00Z | omn-1234-repair"
        decision = classify_worktree_prune(_facts(ledger_open_claim=claim))
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert decision.ledger_open_claim == claim

    def test_unreadable_probe_triages_a_closed_clean_ticket(self) -> None:
        decision = classify_worktree_prune(
            _facts(unreadable_probes=("git status --porcelain",))
        )
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert EnumPruneBlockReason.FACTS_UNREADABLE in decision.block_reasons

    def test_decision_is_frozen(self) -> None:
        decision = classify_worktree_prune(_facts())
        with pytest.raises(ValidationError):
            decision.disposition = EnumPruneDisposition.TRIAGE  # type: ignore[misc]
