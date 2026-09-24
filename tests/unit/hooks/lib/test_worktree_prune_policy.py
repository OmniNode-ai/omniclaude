# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the content-keyed worktree prune policy (OMN-16901, OMN-18370).

Operator ruling, 2026-09-14 (``docs/tracking/ROLLING_WORK_LEDGER.md`` line
7870): prune eligibility is keyed to **what the worktree HOLDS**, not to its
ticket's state. These tests hold the line on both halves of the predicate:

* **ELIGIBILITY** establishes that no live lane owns the worktree — an open
  ledger ``CLAIM`` blocks, and a path with no ticket blocks because claims are
  ticket-keyed. The ticket's own lifecycle blocks NOTHING: a clean, zero-ahead
  worktree under an In Progress ticket IS prunable.
* **SAFETY** gates on local git state, and carries the ruling's two limbs —
  (a) zero commits ahead, (b) a MERGED pull request carrying this exact HEAD. A
  dirty tree must NEVER classify safe. An ahead-unmerged branch must NEVER
  classify safe, and a merged PR forgives ahead-ness only at the commit it
  merged.

Both halves are always evaluated and their reasons unioned (AC-3), and a timed
-out probe is its own disposition rather than a safety finding (AC-4).

Everything that is not PRUNE is TRIAGE or TIMED_OUT with named block reasons —
never a silent drop, never a deletion.

All functions under test are pure (no I/O) so a future event hook can call the
same predicate with no scheduler and no filesystem involved.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from omniclaude.hooks.lib.worktree_prune_policy import (
    EnumBranchPrState,
    EnumDebrisRemediation,
    EnumPruneBlockReason,
    EnumPruneDisposition,
    EnumTicketLifecycle,
    ModelPartialMutationDebrisFacts,
    ModelWorktreePruneDecision,
    ModelWorktreePruneFacts,
    classify_partial_mutation_debris,
    classify_worktree_prune,
    is_prune_eligible,
    is_prune_safe,
)

pytestmark = pytest.mark.unit


def _facts(**overrides: object) -> ModelWorktreePruneFacts:
    """Build the ruling's limb (a) baseline: clean tree, nothing ahead, no claim.

    The ticket is deliberately **OPEN** and carries no ledger TERMINAL row. Under
    the superseded ticket-close-keyed rule this baseline was the canonical
    refusal; under the 2026-09-14 ruling it is the canonical removal, because an
    empty worktree holds no work whatever its ticket says.
    """
    base: dict[str, object] = {
        "path": "/wt/omni_worktrees/OMN-1234/omniclaude",
        "ticket": "OMN-1234",
        "repo": "omniclaude",
        "branch": "jonah/omn-1234-thing",
        "ticket_state": EnumTicketLifecycle.OPEN,
        "ledger_has_terminal": False,
        "ledger_open_claim": None,
        "base_ref": "origin/dev",
        "dirty_files": (),
        "commits_ahead": 0,
        "unmerged_ahead_commits": (),
        "tree_diff_vs_base_empty": True,
        "pr_state": EnumBranchPrState.NONE,
        "pr_head_oid": None,
        "head_oid": "a" * 40,
        "attributed_stash_count": 0,
        "unreadable_probes": (),
    }
    base.update(overrides)
    return ModelWorktreePruneFacts(**base)  # type: ignore[arg-type]


def _merged_pr_facts(**overrides: object) -> ModelWorktreePruneFacts:
    """The ruling's limb (b): clean, ahead, and a MERGED PR carrying this HEAD.

    This is the squash-merge shape. `git cherry` still reports the branch's own
    commits as unmerged and the tree-diff against the merge base is NOT empty,
    so the pull request is the only fact that proves the content landed.
    """
    merged_head = "b" * 40
    base: dict[str, object] = {
        "commits_ahead": 4,
        "unmerged_ahead_commits": ("abc1234", "def5678"),
        "tree_diff_vs_base_empty": False,
        "pr_state": EnumBranchPrState.MERGED,
        "pr_head_oid": merged_head,
        "head_oid": merged_head,
    }
    base.update(overrides)
    return _facts(**base)


# =============================================================================
# ELIGIBILITY — no live lane owns it; the ticket's own state decides nothing
# =============================================================================


class TestEligibility:
    @pytest.mark.parametrize(
        "state",
        [
            EnumTicketLifecycle.OPEN,
            EnumTicketLifecycle.DONE,
            EnumTicketLifecycle.CANCELED,
            EnumTicketLifecycle.UNKNOWN,
        ],
    )
    def test_ticket_state_never_blocks_eligibility(
        self, state: EnumTicketLifecycle
    ) -> None:
        """The 2026-09-14 ruling: eligibility is keyed to what the worktree holds.

        Every lifecycle value, including an In Progress ticket with no ledger
        TERMINAL row, must fire eligibility. Under the superseded rule the OPEN
        and UNKNOWN cases returned TICKET_NOT_CLOSED / TICKET_UNRESOLVED.
        """
        eligible, reasons, evidence = is_prune_eligible(
            _facts(ticket_state=state, ledger_has_terminal=False)
        )
        assert eligible is True
        assert reasons == ()
        assert "no open ledger CLAIM" in evidence

    def test_evidence_names_the_ticket_state_as_reported_not_decisive(self) -> None:
        _, _, evidence = is_prune_eligible(
            _facts(ticket_state=EnumTicketLifecycle.OPEN)
        )
        assert "not decisive" in evidence

    def test_open_claim_blocks_however_empty_the_worktree(self) -> None:
        """A live lane owns this worktree — the one trigger-half refusal left."""
        eligible, reasons, _ = is_prune_eligible(
            _facts(
                ticket_state=EnumTicketLifecycle.DONE,
                ledger_has_terminal=True,
                ledger_open_claim="2026-09-14T20:35:00Z | omn-1234-repair",
            )
        )
        assert eligible is False
        assert reasons == (EnumPruneBlockReason.OPEN_CLAIM,)

    def test_worktree_with_no_ticket_is_never_eligible(self) -> None:
        """Ledger claims are ticket-keyed, so absence of one cannot be shown."""
        eligible, reasons, _ = is_prune_eligible(
            _facts(path="/wt/omni_worktrees/sweep/omniclaude", ticket=None)
        )
        assert eligible is False
        assert reasons == (EnumPruneBlockReason.NO_TICKET,)

    def test_retired_ticket_state_block_reasons_no_longer_exist(self) -> None:
        """The ruling removed them; a shim that still emits them would be drift."""
        names = {reason.value for reason in EnumPruneBlockReason}
        assert "ticket_not_closed" not in names
        assert "ticket_unresolved" not in names


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

    def test_merged_pull_request_forgives_ahead_ness_at_the_merged_head(self) -> None:
        """Limb (b) of the ruling. The squash shape no other fact can recognise."""
        safe, reasons, evidence = is_prune_safe(_merged_pr_facts())
        assert safe is True
        assert reasons == ()
        assert "limb (b)" in evidence

    def test_merged_pull_request_does_not_forgive_a_commit_made_after_the_merge(
        self,
    ) -> None:
        """A local commit past the merged head is unmerged work, and protected.

        The ruling protects "any unmerged commit"; a merged PR proves only the
        commit it merged. HEAD having moved past it is exactly the case where
        the two sentences of the ruling would otherwise collide.
        """
        safe, reasons, _ = is_prune_safe(
            _merged_pr_facts(head_oid="c" * 40, pr_head_oid="b" * 40)
        )
        assert safe is False
        assert EnumPruneBlockReason.AHEAD_UNMERGED in reasons

    def test_unknown_pr_state_falls_back_to_limb_a_rather_than_forgiving(self) -> None:
        """`gh` unavailable must make limb (b) unavailable, never permissive."""
        safe, reasons, _ = is_prune_safe(
            _merged_pr_facts(pr_state=EnumBranchPrState.UNKNOWN, pr_head_oid=None)
        )
        assert safe is False
        assert EnumPruneBlockReason.AHEAD_UNMERGED in reasons

    def test_a_branch_pushed_to_origin_at_this_head_is_safe(self) -> None:
        """Limb (c). The ruling names pushing as the way to clear an unmerged commit."""
        safe, reasons, evidence = is_prune_safe(
            _facts(
                commits_ahead=4,
                unmerged_ahead_commits=("abc1234",),
                tree_diff_vs_base_empty=False,
                head_oid="d" * 40,
                origin_head_oid="d" * 40,
            )
        )
        assert safe is True
        assert reasons == ()
        assert "limb (c)" in evidence

    def test_origin_holding_an_older_commit_does_not_forgive_the_newer_one(
        self,
    ) -> None:
        """A commit made after the push is still only local, and still protected."""
        safe, reasons, _ = is_prune_safe(
            _facts(
                commits_ahead=5,
                unmerged_ahead_commits=("abc1234",),
                tree_diff_vs_base_empty=False,
                head_oid="e" * 40,
                origin_head_oid="d" * 40,
            )
        )
        assert safe is False
        assert EnumPruneBlockReason.AHEAD_UNMERGED in reasons

    def test_an_unpushed_branch_has_no_limb_c(self) -> None:
        safe, reasons, _ = is_prune_safe(
            _facts(
                commits_ahead=1,
                unmerged_ahead_commits=("abc1234",),
                tree_diff_vs_base_empty=False,
                origin_head_oid=None,
            )
        )
        assert safe is False
        assert EnumPruneBlockReason.AHEAD_UNMERGED in reasons

    def test_dirty_tree_is_never_safe_even_with_a_merged_pull_request(self) -> None:
        safe, reasons, _ = is_prune_safe(_merged_pr_facts(dirty_files=("src/a.py",)))
        assert safe is False
        assert EnumPruneBlockReason.DIRTY_TREE in reasons

    def test_a_timed_out_probe_is_not_a_safety_finding(self) -> None:
        """AC-4: a timeout is a host reading, held apart from FACTS_UNREADABLE."""
        safe, reasons, _ = is_prune_safe(
            _facts(
                timed_out_probes=("git status --porcelain",),
                load_average=127.4,
            )
        )
        assert safe is False
        assert EnumPruneBlockReason.PROBE_TIMEOUT in reasons
        assert EnumPruneBlockReason.FACTS_UNREADABLE not in reasons

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
    def test_empty_worktree_under_an_in_progress_ticket_prunes(self) -> None:
        """Limb (a), and the 186 rows the superseded rule refused on 2026-09-14."""
        decision = classify_worktree_prune(_facts())
        assert isinstance(decision, ModelWorktreePruneDecision)
        assert decision.disposition is EnumPruneDisposition.PRUNE
        assert decision.block_reasons == ()
        assert decision.eligibility_evidence
        assert decision.safety_evidence
        assert decision.branch_content_preserved is True

    def test_merged_pr_worktree_under_a_backlog_ticket_prunes(self) -> None:
        """Limb (b) end to end."""
        decision = classify_worktree_prune(
            _merged_pr_facts(ticket_state=EnumTicketLifecycle.OPEN)
        )
        assert decision.disposition is EnumPruneDisposition.PRUNE
        assert decision.pr_state is EnumBranchPrState.MERGED
        assert decision.branch_content_preserved is True

    def test_open_claim_triages_and_never_authorises_a_branch_delete(self) -> None:
        decision = classify_worktree_prune(
            _facts(ledger_open_claim="2026-09-14T20:35:00Z | omn-1234-repair")
        )
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert EnumPruneBlockReason.OPEN_CLAIM in decision.block_reasons
        assert decision.branch_content_preserved is False

    def test_both_halves_are_evaluated_so_every_reason_is_counted(self) -> None:
        """AC-3. The superseded revision returned before the safety half ran, so a
        row that was both claimed and dirty and detached reported only the claim —
        which is how the 2026-09-14 report said detached_head 40 against an actual
        130 and dirty_tree 26 against an actual 158."""
        decision = classify_worktree_prune(
            _facts(
                ledger_open_claim="2026-09-14T20:35:00Z | a live lane",
                branch=None,
                dirty_files=("src/a.py",),
            )
        )
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert EnumPruneBlockReason.OPEN_CLAIM in decision.block_reasons
        assert EnumPruneBlockReason.DETACHED_HEAD in decision.block_reasons
        assert EnumPruneBlockReason.DIRTY_TREE in decision.block_reasons

    def test_a_timed_out_row_is_timed_out_not_triage(self) -> None:
        """AC-4 falsifier: a timeout carries the load reading and is not 'unsafe'."""
        decision = classify_worktree_prune(
            _facts(
                timed_out_probes=("git status --porcelain",),
                load_average=127.4,
            )
        )
        assert decision.disposition is EnumPruneDisposition.TIMED_OUT
        assert decision.load_average == 127.4
        assert decision.timed_out_probes == ("git status --porcelain",)
        assert EnumPruneBlockReason.PROBE_TIMEOUT in decision.block_reasons
        assert EnumPruneBlockReason.FACTS_UNREADABLE not in decision.block_reasons

    def test_an_unmerged_branch_never_authorises_a_branch_delete(self) -> None:
        """AC-2 at the predicate: the branch delete is gated on the same proof."""
        decision = classify_worktree_prune(
            _facts(
                commits_ahead=2,
                unmerged_ahead_commits=("abc1234",),
                tree_diff_vs_base_empty=False,
            )
        )
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert EnumPruneBlockReason.AHEAD_UNMERGED in decision.block_reasons
        assert decision.branch_content_preserved is False

    def test_dirty_tree_triages_and_reports_the_hazard(
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

    def test_a_claimed_worktree_does_not_report_eligibility_evidence(self) -> None:
        """Evidence is only ever printed for the half that actually passed."""
        decision = classify_worktree_prune(
            _facts(ledger_open_claim="2026-09-14T20:35:00Z | a live lane")
        )
        assert decision.eligibility_evidence == ""
        # ...while the safety half still ran, so its reasons are countable.
        assert decision.safety_evidence

    def test_an_unsafe_worktree_does_not_report_safety_evidence(self) -> None:
        decision = classify_worktree_prune(_facts(dirty_files=("src/a.py",)))
        assert decision.safety_evidence == ""

    def test_triage_row_carries_the_matching_ledger_claim(self) -> None:
        claim = "2026-08-28T20:35:00Z | omn-1234-repair"
        decision = classify_worktree_prune(_facts(ledger_open_claim=claim))
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert decision.ledger_open_claim == claim

    def test_unreadable_probe_triages_an_otherwise_clean_worktree(self) -> None:
        decision = classify_worktree_prune(
            _facts(unreadable_probes=("git status --porcelain",))
        )
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert EnumPruneBlockReason.FACTS_UNREADABLE in decision.block_reasons

    def test_decision_is_frozen(self) -> None:
        decision = classify_worktree_prune(_facts())
        with pytest.raises(ValidationError):
            decision.disposition = EnumPruneDisposition.TRIAGE  # type: ignore[misc]


# =============================================================================
# Partial-mutation debris predicate [OMN-16951]
#
# A `.git`-gone leftover directory is a DISTINCT shape from the eligibility/
# safety predicate above: `git worktree remove` can never succeed on it, so it
# gets its own block reason and its own (much narrower) auto-remove predicate.
# The provably-reachable-content-AND-prunable case must be the ONLY
# auto-removable one — every other combination is TRIAGE, never a deletion.
# =============================================================================


def _debris_facts(**overrides: object) -> ModelPartialMutationDebrisFacts:
    """Build the one auto-removable baseline: prunable clone record, all
    remaining file content already reachable as a blob in the owning clone."""
    base: dict[str, object] = {
        "path": "/wt/omni_worktrees/OMN-9999/omnibase_infra",
        "ticket": "OMN-9999",
        "repo": "omnibase_infra",
        "owning_clone": "/wt/omnibase_infra",
        "worktree_list_state": "prunable gitdir file points to non-existent location",
        "file_count": 3,
        "unreachable_files": (),
    }
    base.update(overrides)
    return ModelPartialMutationDebrisFacts(**base)


class TestClassifyPartialMutationDebris:
    def test_always_carries_the_partial_mutation_debris_reason(self) -> None:
        """Every decision from this classifier names the one reason it exists for."""
        decision = classify_partial_mutation_debris(_debris_facts())
        assert decision.block_reasons == (EnumPruneBlockReason.PARTIAL_MUTATION_DEBRIS,)

    def test_prunable_and_fully_reachable_is_auto_removable(self) -> None:
        decision = classify_partial_mutation_debris(_debris_facts())
        assert decision.remediation is EnumDebrisRemediation.AUTO_REMOVABLE
        assert "prunable" in decision.evidence
        assert "3" in decision.evidence

    def test_prunable_but_one_unreachable_file_is_triage_not_auto_removable(
        self,
    ) -> None:
        """The conjunction is never weakened to 'most files reachable'."""
        decision = classify_partial_mutation_debris(
            _debris_facts(unreachable_files=("src/omnibase_infra/local_edit.py",))
        )
        assert decision.remediation is EnumDebrisRemediation.TRIAGE
        assert "local_edit.py" in decision.evidence

    def test_fully_reachable_but_not_prunable_is_triage(self) -> None:
        """Git itself must already agree the worktree is administratively gone."""
        decision = classify_partial_mutation_debris(
            _debris_facts(worktree_list_state="")
        )
        assert decision.remediation is EnumDebrisRemediation.TRIAGE
        assert "not 'prunable'" in decision.evidence

    def test_locked_worktree_list_state_is_not_prunable(self) -> None:
        decision = classify_partial_mutation_debris(
            _debris_facts(worktree_list_state="locked")
        )
        assert decision.remediation is EnumDebrisRemediation.TRIAGE

    def test_no_owning_clone_found_is_triage(self) -> None:
        """No known clone's `git worktree list` references this path at all."""
        decision = classify_partial_mutation_debris(
            _debris_facts(owning_clone=None, worktree_list_state=None)
        )
        assert decision.remediation is EnumDebrisRemediation.TRIAGE
        assert "no owning clone" in decision.evidence

    def test_multiple_unreachable_files_are_all_named_up_to_a_cap(self) -> None:
        decision = classify_partial_mutation_debris(
            _debris_facts(
                unreachable_files=tuple(f"src/f{i}.py" for i in range(7)),
                file_count=7,
            )
        )
        assert decision.remediation is EnumDebrisRemediation.TRIAGE
        assert "7 file(s)" in decision.evidence

    def test_decision_is_frozen(self) -> None:
        decision = classify_partial_mutation_debris(_debris_facts())
        with pytest.raises(ValidationError):
            decision.remediation = EnumDebrisRemediation.TRIAGE  # type: ignore[misc]


# =============================================================================
# The open-pull-request fence for unattended removal [OMN-19399]
# =============================================================================


class TestUnmergedPrFence:
    """An unattended removal may not take a worktree whose branch is in review.

    The standing consent for the morning prune (OPERATOR-CONSENT row stamped
    2026-09-24T13:50:25Z) puts "any worktree whose branch has an OPEN pull
    request" OUT OF SCOPE. Limb (c) alone would remove such a worktree once its
    HEAD is on origin, which is exactly the state of a lane waiting on review.
    The fence is opt-in (`hold_open_pr`), so the interactive predicate the
    2026-09-14 ruling defines is unchanged, and it fails CLOSED: an open-PR
    listing that did not resolve (`open_pr=None`) holds the row too.
    """

    def _pushed_at_head(self, **overrides: object) -> ModelWorktreePruneFacts:
        head = "c" * 40
        base: dict[str, object] = {
            "commits_ahead": 2,
            "unmerged_ahead_commits": ("abc1234",),
            "tree_diff_vs_base_empty": False,
            "pr_state": EnumBranchPrState.NOT_MERGED,
            "head_oid": head,
            "origin_head_oid": head,
        }
        base.update(overrides)
        return _facts(**base)

    def test_unfenced_pushed_at_head_row_with_open_pr_is_still_prunable(
        self,
    ) -> None:
        """Positive control: without the fence the row IS removed today."""
        decision = classify_worktree_prune(self._pushed_at_head(open_pr=True))
        assert decision.disposition is EnumPruneDisposition.PRUNE

    def test_fence_holds_a_row_whose_branch_has_an_open_pr(self) -> None:
        decision = classify_worktree_prune(
            self._pushed_at_head(open_pr=True), hold_open_pr=True
        )
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert EnumPruneBlockReason.OPEN_PR_FENCE in decision.block_reasons
        assert decision.branch_content_preserved is False

    def test_fence_holds_when_the_open_pr_listing_did_not_resolve(self) -> None:
        decision = classify_worktree_prune(_facts(open_pr=None), hold_open_pr=True)
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert EnumPruneBlockReason.OPEN_PR_FENCE in decision.block_reasons

    def test_fence_releases_a_row_proven_to_have_no_open_pr(self) -> None:
        decision = classify_worktree_prune(
            self._pushed_at_head(pr_state=EnumBranchPrState.NONE, open_pr=False),
            hold_open_pr=True,
        )
        assert decision.disposition is EnumPruneDisposition.PRUNE
        assert decision.block_reasons == ()

    def test_fence_is_a_safety_reason_reported_with_the_others(self) -> None:
        safe, reasons, evidence = is_prune_safe(
            _facts(open_pr=True, dirty_files=("a.py",)), hold_open_pr=True
        )
        assert safe is False
        assert evidence == ""
        assert EnumPruneBlockReason.DIRTY_TREE in reasons
        assert EnumPruneBlockReason.OPEN_PR_FENCE in reasons
