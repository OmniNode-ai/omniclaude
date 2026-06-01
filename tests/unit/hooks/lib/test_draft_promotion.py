# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the small-batch, evidence-backed draft-promotion policy.

Validates the OMN-12571 acceptance criteria:

    - Batch size is configurable (not hardcoded) and evidence-backed.
    - The whole draft backlog is never promoted in a single batch.
    - Only drafts that pass rebase + local validation are eligible.
    - Each promoted PR yields a ledger record carrying the OMN-12569
      provenance fields (head SHA, local verification, branch checks,
      merge-group checks, worktree cleanup status).

Related:
    - OMN-12571: Codify small-batch, evidence-backed draft-promotion rules.
    - OMN-12569: Durable, reconstructable PR ledger (record interface).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from omniclaude.hooks.lib.draft_promotion import (
    DEFAULT_PROMOTION_BATCH_SIZE,
    EnumBranchCheckStatus,
    EnumPromotionDecision,
    EnumWorktreeCleanupStatus,
    ModelDraftCandidate,
    ModelDraftPromotionRecord,
    ModelPromotionBatchResult,
    ModelPromotionPolicy,
    build_promotion_record,
    select_promotion_batch,
)

pytestmark = pytest.mark.unit


# -- Factories ---------------------------------------------------------------


def _candidate(
    number: int,
    *,
    rebased: bool = True,
    validated: bool = True,
    conflict_dirty: bool = False,
    parked: bool = False,
) -> ModelDraftCandidate:
    return ModelDraftCandidate(
        repo="OmniNode-ai/omnibase_infra",
        number=number,
        title=f"draft #{number}",
        head_sha=f"{number:040x}",
        rebased=rebased,
        locally_validated=validated,
        conflict_dirty=conflict_dirty,
        parked=parked,
    )


# =============================================================================
# Configurable batch size (evidence-backed, not hardcoded)
# =============================================================================


class TestConfigurableBatchSize:
    def test_default_batch_size_is_small(self) -> None:
        policy = ModelPromotionPolicy()
        assert policy.batch_size == DEFAULT_PROMOTION_BATCH_SIZE
        assert 1 <= policy.batch_size <= 5

    def test_custom_batch_size_is_honored(self) -> None:
        candidates = [_candidate(n) for n in range(1, 11)]
        policy = ModelPromotionPolicy(
            batch_size=3,
            evidence_ref="OMN-12569 ledger run-abc",
        )

        result = select_promotion_batch(candidates, policy)

        assert len(result.promoted) == 3
        assert result.promoted == [c.number for c in candidates[:3]]

    def test_batch_size_must_be_evidence_backed(self) -> None:
        """A non-default batch size requires an evidence reference."""
        with pytest.raises(ValidationError):
            ModelPromotionPolicy(batch_size=10, evidence_ref="")

    def test_default_batch_size_needs_no_evidence_ref(self) -> None:
        policy = ModelPromotionPolicy()
        assert policy.evidence_ref == ""

    def test_batch_size_rejects_non_positive(self) -> None:
        with pytest.raises(ValidationError):
            ModelPromotionPolicy(batch_size=0, evidence_ref="x")
        with pytest.raises(ValidationError):
            ModelPromotionPolicy(batch_size=-1, evidence_ref="x")

    def test_policy_is_frozen(self) -> None:
        policy = ModelPromotionPolicy()
        with pytest.raises(ValidationError):
            setattr(policy, "batch_size", 99)


# =============================================================================
# Never enqueue the whole draft backlog
# =============================================================================


class TestNeverWholeBacklog:
    def test_batch_never_exceeds_policy_size(self) -> None:
        candidates = [_candidate(n) for n in range(1, 21)]
        policy = ModelPromotionPolicy(batch_size=4, evidence_ref="OMN-12569")

        result = select_promotion_batch(candidates, policy)

        assert len(result.promoted) == 4
        assert len(result.promoted) < len(candidates)

    def test_batch_caps_even_when_size_exceeds_backlog_minus_one(self) -> None:
        """A batch may never equal the whole eligible backlog."""
        candidates = [_candidate(n) for n in range(1, 4)]  # 3 eligible
        policy = ModelPromotionPolicy(batch_size=3, evidence_ref="OMN-12569")

        result = select_promotion_batch(candidates, policy)

        # Even though batch_size==eligible count, the guard refuses to
        # promote the entire backlog in one shot.
        assert len(result.promoted) < len(candidates)
        assert result.whole_backlog_blocked is True

    def test_single_eligible_draft_promotes_without_whole_backlog_block(
        self,
    ) -> None:
        candidates = [_candidate(1)]
        policy = ModelPromotionPolicy()

        result = select_promotion_batch(candidates, policy)

        # A backlog of one is not "the whole backlog" being re-flooded.
        assert result.promoted == [1]
        assert result.whole_backlog_blocked is False

    def test_empty_backlog_promotes_nothing(self) -> None:
        result = select_promotion_batch([], ModelPromotionPolicy())
        assert result.promoted == []
        assert result.deferred == []


# =============================================================================
# Rebase + local validation gating
# =============================================================================


class TestRebaseAndValidationGating:
    def test_unrebased_draft_is_deferred(self) -> None:
        candidates = [_candidate(1, rebased=False), _candidate(2)]
        result = select_promotion_batch(candidates, ModelPromotionPolicy())

        assert 1 not in result.promoted
        assert 1 in result.deferred

    def test_unvalidated_draft_is_deferred(self) -> None:
        candidates = [_candidate(1, validated=False), _candidate(2)]
        result = select_promotion_batch(candidates, ModelPromotionPolicy())

        assert 1 not in result.promoted
        assert 1 in result.deferred

    def test_conflict_dirty_draft_is_deferred(self) -> None:
        candidates = [_candidate(1791, conflict_dirty=True), _candidate(2)]
        result = select_promotion_batch(candidates, ModelPromotionPolicy())

        assert 1791 not in result.promoted
        assert 1791 in result.deferred

    def test_parked_draft_is_deferred(self) -> None:
        candidates = [_candidate(1822, parked=True), _candidate(2)]
        result = select_promotion_batch(candidates, ModelPromotionPolicy())

        assert 1822 not in result.promoted
        assert 1822 in result.deferred

    def test_only_eligible_drafts_count_toward_batch(self) -> None:
        candidates = [
            _candidate(1, rebased=False),
            _candidate(2, validated=False),
            _candidate(3),
            _candidate(4),
            _candidate(5),
        ]
        policy = ModelPromotionPolicy(batch_size=2, evidence_ref="OMN-12569")

        result = select_promotion_batch(candidates, policy)

        # Only 3,4,5 eligible; batch_size 2 < 3 eligible → no whole-backlog block.
        assert result.promoted == [3, 4]
        assert set(result.deferred) >= {1, 2}


# =============================================================================
# Ledger record (OMN-12569 provenance interface)
# =============================================================================


class TestLedgerRecord:
    def test_record_carries_all_provenance_fields(self) -> None:
        record = build_promotion_record(
            _candidate(1824),
            decision=EnumPromotionDecision.PROMOTED,
            local_verification="uv run pytest tests/ -q :: 412 passed",
            branch_checks=EnumBranchCheckStatus.GREEN,
            merge_group_checks=EnumBranchCheckStatus.PENDING,
            worktree_cleanup=EnumWorktreeCleanupStatus.CLEAN,
            ledger_run_id="run-abc",
        )

        assert record.pr_number == 1824
        assert record.head_sha == f"{1824:040x}"
        assert record.local_verification.startswith("uv run pytest")
        assert record.branch_checks is EnumBranchCheckStatus.GREEN
        assert record.merge_group_checks is EnumBranchCheckStatus.PENDING
        assert record.worktree_cleanup is EnumWorktreeCleanupStatus.CLEAN
        assert record.ledger_run_id == "run-abc"
        assert record.decision is EnumPromotionDecision.PROMOTED

    def test_record_is_frozen(self) -> None:
        record = build_promotion_record(
            _candidate(1),
            decision=EnumPromotionDecision.PROMOTED,
            local_verification="ok",
            branch_checks=EnumBranchCheckStatus.GREEN,
            merge_group_checks=EnumBranchCheckStatus.GREEN,
            worktree_cleanup=EnumWorktreeCleanupStatus.CLEAN,
            ledger_run_id="run-1",
        )
        with pytest.raises(ValidationError):
            setattr(record, "pr_number", 2)

    def test_record_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ModelDraftPromotionRecord(
                pr_number=1,
                repo="OmniNode-ai/omnibase_infra",
                head_sha="0" * 40,
                decision=EnumPromotionDecision.PROMOTED,
                local_verification="ok",
                branch_checks=EnumBranchCheckStatus.GREEN,
                merge_group_checks=EnumBranchCheckStatus.GREEN,
                worktree_cleanup=EnumWorktreeCleanupStatus.CLEAN,
                ledger_run_id="run-1",
                bogus="x",
            )

    def test_batch_result_records_are_built_for_promoted_and_deferred(self) -> None:
        candidates = [
            _candidate(10),
            _candidate(11),
            _candidate(12),
            _candidate(1791, conflict_dirty=True),
        ]
        policy = ModelPromotionPolicy(batch_size=2, evidence_ref="OMN-12569")

        result = select_promotion_batch(candidates, policy)

        assert isinstance(result, ModelPromotionBatchResult)
        # 3 eligible (10,11,12), batch_size 2 < 3 → no whole-backlog trim.
        assert result.promoted == [10, 11]
        assert result.whole_backlog_blocked is False
        assert 1791 in result.deferred
        assert 12 in result.deferred
