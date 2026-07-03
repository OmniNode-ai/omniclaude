# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Small-batch, evidence-backed draft-promotion policy [OMN-12571].

Codifies how draft PRs are promoted into the infra merge queue:

    - Promote drafts in **small batches** only after rebase + local validation.
    - Batch size is **configurable and evidence-backed**, never permanently
      hardcoded -- future queue behavior may justify different limits.
    - The whole draft backlog is **never** enqueued at once.
    - For each promoted PR, build a ledger record carrying the OMN-12569
      provenance fields (head SHA, local verification, branch checks,
      merge-group checks, worktree cleanup status).

Truth semantics (OMN-12569): the produced records are a *derived projection*
fed into the durable PR ledger -- they are not authoritative truth on their
own. The orchestrator owns the ledger; this module supplies record-shaped
promotion provenance for it to persist.

All functions are pure (no I/O) to enable unit testing. The merge-sweep
orchestrator wires these classifiers to live ``gh`` / git state.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Default kept deliberately small. It is *not* a hard cap -- callers may raise
# it via an evidence-backed ``ModelPromotionPolicy``. Codified (not hardcoded
# in branching logic) so the value is greppable and overridable.
DEFAULT_PROMOTION_BATCH_SIZE: int = 3


class EnumBranchCheckStatus(StrEnum):
    """Status of branch or merge-group CI checks for a draft."""

    GREEN = "green"
    PENDING = "pending"
    RED = "red"
    NONE = "none"


class EnumWorktreeCleanupStatus(StrEnum):
    """Worktree cleanup state recorded after a promotion attempt."""

    CLEAN = "clean"
    DIRTY = "dirty"
    NOT_APPLICABLE = "not_applicable"


class EnumPromotionDecision(StrEnum):
    """Final promotion decision for a single draft."""

    PROMOTED = "promoted"
    DEFERRED = "deferred"


class ModelPromotionPolicy(BaseModel):
    """Configurable, evidence-backed promotion policy.

    The default batch size is small and requires no evidence reference. Any
    non-default batch size must cite an evidence reference (e.g. an OMN-12569
    ledger run id or a Linear ticket) so that limit changes are justified
    rather than silently widened.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_size: int = Field(
        default=DEFAULT_PROMOTION_BATCH_SIZE,
        gt=0,
        description="Maximum drafts to promote in a single batch.",
    )
    evidence_ref: str = Field(
        default="",
        description=(
            "Evidence reference (OMN ticket / ledger run id) justifying a "
            "non-default batch size. Required when batch_size differs from "
            "the default."
        ),
    )

    @model_validator(mode="after")
    def _require_evidence_for_non_default(self) -> ModelPromotionPolicy:
        if self.batch_size != DEFAULT_PROMOTION_BATCH_SIZE and not self.evidence_ref:
            raise ValueError(
                "A non-default batch_size must cite evidence_ref "
                "(e.g. an OMN-12569 ledger run id or Linear ticket)."
            )
        return self


class ModelDraftCandidate(BaseModel):
    """A draft PR considered for promotion into the merge queue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(
        ..., description="Full repo name (e.g. OmniNode-ai/omnibase_infra)"
    )
    number: int = Field(..., description="PR number")
    title: str = Field(default="", description="PR title")
    head_sha: str = Field(..., description="Current head commit SHA")
    rebased: bool = Field(
        default=False, description="Whether the draft was rebased onto the base branch"
    )
    locally_validated: bool = Field(
        default=False, description="Whether local validation (full test suite) passed"
    )
    conflict_dirty: bool = Field(
        default=False, description="Whether the draft is conflict-dirty / CONFLICTING"
    )
    parked: bool = Field(
        default=False,
        description="Whether the draft is explicitly parked (e.g. release draft #1822)",
    )

    @property
    def is_eligible(self) -> bool:
        """Eligible only after a clean rebase + local validation, not parked."""
        return (
            self.rebased
            and self.locally_validated
            and not self.conflict_dirty
            and not self.parked
        )


class ModelDraftPromotionRecord(BaseModel):
    """Ledger record for a single promotion decision (OMN-12569 interface).

    This is the record shape the durable PR ledger persists. It is a derived
    projection -- authoritative truth remains GitHub state plus orchestrator
    receipts. Every field is provenance the orchestrator needs to reconstruct
    queue behavior without a hand-maintained ledger.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pr_number: int = Field(..., description="PR number")
    repo: str = Field(..., description="Full repo name")
    head_sha: str = Field(..., description="Head SHA promoted (provenance)")
    decision: EnumPromotionDecision = Field(..., description="Promote or defer")
    local_verification: str = Field(
        default="", description="Local verification evidence (command + outcome)"
    )
    branch_checks: EnumBranchCheckStatus = Field(
        ..., description="Branch CI check status at promotion time"
    )
    merge_group_checks: EnumBranchCheckStatus = Field(
        ..., description="Merge-group CI check status at promotion time"
    )
    worktree_cleanup: EnumWorktreeCleanupStatus = Field(
        ..., description="Worktree cleanup status after the attempt"
    )
    ledger_run_id: str = Field(
        ..., description="OMN-12569 ledger run id this record is attributed to"
    )
    deferral_reason: str = Field(
        default="", description="Why the draft was deferred (empty when promoted)"
    )


class ModelPromotionBatchResult(BaseModel):
    """Result of selecting a promotion batch from a draft backlog."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    promoted: list[int] = Field(
        default_factory=list, description="PR numbers selected for promotion"
    )
    deferred: list[int] = Field(
        default_factory=list, description="PR numbers held back this batch"
    )
    whole_backlog_blocked: bool = Field(
        default=False,
        description=(
            "True when the batch was trimmed to avoid promoting the entire "
            "eligible backlog at once."
        ),
    )
    batch_size: int = Field(..., description="Effective batch size used")
    evidence_ref: str = Field(
        default="", description="Evidence reference for the policy used"
    )


# ---------------------------------------------------------------------------
# Pure selection / record-building functions (no I/O)
# ---------------------------------------------------------------------------


def select_promotion_batch(
    candidates: list[ModelDraftCandidate],
    policy: ModelPromotionPolicy,
) -> ModelPromotionBatchResult:
    """Select a small, eligible batch of drafts to promote.

    Rules (OMN-12571):
        - Only drafts that are rebased + locally validated, not conflict-dirty,
          and not parked are eligible.
        - At most ``policy.batch_size`` drafts are promoted.
        - The whole eligible backlog is never promoted in a single batch: if the
          batch would cover every eligible draft (and there is more than one),
          it is trimmed by one and ``whole_backlog_blocked`` is set.

    Args:
        candidates: Draft PRs in priority order (earliest = highest priority).
        policy: Configurable, evidence-backed promotion policy.

    Returns:
        ModelPromotionBatchResult with promoted/deferred PR numbers.
    """
    eligible = [c for c in candidates if c.is_eligible]
    ineligible = [c for c in candidates if not c.is_eligible]

    effective_size = min(policy.batch_size, len(eligible))

    # Never re-flood the queue with the whole eligible backlog. A backlog of a
    # single draft is not "the whole backlog" being re-flooded, so only trim
    # when more than one eligible draft exists.
    whole_backlog_blocked = False
    if len(eligible) > 1 and effective_size >= len(eligible):
        effective_size = len(eligible) - 1
        whole_backlog_blocked = True

    promoted = [c.number for c in eligible[:effective_size]]
    deferred = [c.number for c in eligible[effective_size:]] + [
        c.number for c in ineligible
    ]

    return ModelPromotionBatchResult(
        promoted=promoted,
        deferred=deferred,
        whole_backlog_blocked=whole_backlog_blocked,
        batch_size=policy.batch_size,
        evidence_ref=policy.evidence_ref,
    )


def deferral_reason_for(candidate: ModelDraftCandidate) -> str:
    """Return a human-readable reason a draft is deferred, or '' if eligible."""
    if candidate.parked:
        return "parked (e.g. release draft pending refreshed evidence)"
    if candidate.conflict_dirty:
        return "conflict-dirty: rebase required before promotion"
    if not candidate.rebased:
        return "not rebased onto base branch"
    if not candidate.locally_validated:
        return "local validation (full test suite) not passed"
    return ""


def build_promotion_record(
    candidate: ModelDraftCandidate,
    *,
    decision: EnumPromotionDecision,
    local_verification: str,
    branch_checks: EnumBranchCheckStatus,
    merge_group_checks: EnumBranchCheckStatus,
    worktree_cleanup: EnumWorktreeCleanupStatus,
    ledger_run_id: str,
) -> ModelDraftPromotionRecord:
    """Build an OMN-12569 ledger record for a single promotion decision.

    Args:
        candidate: The draft the decision applies to.
        decision: PROMOTED or DEFERRED.
        local_verification: Local verification evidence (command + outcome).
        branch_checks: Branch CI status at promotion time.
        merge_group_checks: Merge-group CI status at promotion time.
        worktree_cleanup: Worktree cleanup status after the attempt.
        ledger_run_id: OMN-12569 ledger run id to attribute the record to.

    Returns:
        A frozen ModelDraftPromotionRecord ready to feed the durable ledger.
    """
    return ModelDraftPromotionRecord(
        pr_number=candidate.number,
        repo=candidate.repo,
        head_sha=candidate.head_sha,
        decision=decision,
        local_verification=local_verification,
        branch_checks=branch_checks,
        merge_group_checks=merge_group_checks,
        worktree_cleanup=worktree_cleanup,
        ledger_run_id=ledger_run_id,
        deferral_reason=(
            ""
            if decision is EnumPromotionDecision.PROMOTED
            else deferral_reason_for(candidate)
        ),
    )


__all__ = [
    "DEFAULT_PROMOTION_BATCH_SIZE",
    "EnumBranchCheckStatus",
    "EnumPromotionDecision",
    "EnumWorktreeCleanupStatus",
    "ModelDraftCandidate",
    "ModelDraftPromotionRecord",
    "ModelPromotionBatchResult",
    "ModelPromotionPolicy",
    "build_promotion_record",
    "deferral_reason_for",
    "select_promotion_batch",
]
