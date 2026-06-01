# Small-Batch, Evidence-Backed Draft Promotion

**Created:** 2026-06-01
**Ticket:** OMN-12571 (parent OMN-12504 — merge queue recovery)
**Source plan:** `omni_home/docs/plans/2026-06-01-infra-ci-durability-plan.md` (Task 5.1)
**Source design:** `omni_home/docs/tracking/2026-06-01-infra-durable-issues.md` (Issue #8)
**Runbook context:** `omni_home/docs/runbooks/codex-nightly-controller.md` (§8 Merge Queue Driver)
**Ledger interface:** OMN-12569 — durable, reconstructable PR ledger (Task 4.1)
**OCC evidence:** `onex_change_control` PR #2044 (contract + receipts), merged as commit `35bd864ae5c55b37c558e1eb3151d8bd6c81f29b`

---

## Why This Exists

After the infra merge-queue recovery, the remaining `omnibase_infra` PRs are
**drafts**. Several are conflict-dirty or carry stale failed/cancelled CI
contexts from the pre-fix CI shape. Re-flooding the merge queue with the whole
draft backlog at once recreates the cascade the recovery just cleared: known-red
or conflict-dirty PRs sit ahead of clean ones, merge-group runs thrash, and the
queue stalls.

This procedure codifies the inverse: promote drafts in **small, verified
batches**, with a batch size that is **configurable and evidence-backed** rather
than permanently hardcoded.

The mechanical guard lives in
[`src/omniclaude/hooks/lib/draft_promotion.py`](../../src/omniclaude/hooks/lib/draft_promotion.py)
and is covered by
[`tests/unit/hooks/lib/test_draft_promotion.py`](../../tests/unit/hooks/lib/test_draft_promotion.py).

---

## The Rules (non-negotiable)

1. **Rebase + local validation first.** A draft is eligible only after it is
   rebased onto the base branch *and* local validation (full test suite, no
   `-k` filter) passes. Conflict-dirty and parked drafts are never eligible.
2. **Small batches only.** Promote at most `batch_size` eligible drafts per
   pass. The default is `DEFAULT_PROMOTION_BATCH_SIZE = 3`.
3. **Batch size is configurable and evidence-backed.** Raising the batch size
   above the default requires an `evidence_ref` (an OMN-12569 ledger run id or a
   Linear ticket) on `ModelPromotionPolicy`. A non-default batch size with no
   evidence reference is rejected by validation. The limit is *not* hardcoded in
   branching logic — future queue behavior may justify a different value.
4. **Never enqueue the whole draft backlog at once.** Even when the configured
   batch size meets or exceeds the eligible backlog, the selector trims the
   batch so the entire eligible backlog is never promoted in a single pass
   (`whole_backlog_blocked` is set). A backlog of exactly one draft is not
   treated as "the whole backlog."
5. **Every promotion produces a ledger record.** For each promoted PR, build a
   `ModelDraftPromotionRecord` carrying the OMN-12569 provenance fields:
   - head SHA,
   - local verification evidence (command + outcome),
   - branch-check status,
   - merge-group-check status,
   - worktree cleanup status,
   - the ledger run id it is attributed to.

   These records are a **derived projection** fed into the durable PR ledger
   (OMN-12569). They are not authoritative truth on their own — authoritative
   truth remains GitHub state plus durable orchestrator receipts.

---

## Procedure

1. **Inventory the draft backlog** for the target repo (`omnibase_infra`) via
   `gh pr list --state open --draft`.
2. **Build candidates.** For each draft, populate a `ModelDraftCandidate`:
   `rebased`, `locally_validated`, `conflict_dirty`, `parked`.
   - Rebase the draft onto `main` and run the full local suite to set
     `rebased` / `locally_validated`.
   - Mark known conflict-dirty drafts (see below) `conflict_dirty=True` until
     they are rebased clean.
   - Mark the parked release draft `parked=True`.
3. **Select the batch.** Call `select_promotion_batch(candidates, policy)`.
   - Default policy: `ModelPromotionPolicy()` (batch size 3).
   - To use a different batch size, cite evidence:
     `ModelPromotionPolicy(batch_size=N, evidence_ref="OMN-12569 ledger run-...")`.
4. **Promote the selected PRs** by marking each ready and arming auto-merge per
   the queue policy in `codex-nightly-controller.md` §8 (bare `--auto` on the
   squash-only infra queue; never `--merge` / `--rebase`).
5. **Record provenance.** For each promoted and each deferred PR, call
   `build_promotion_record(...)` and persist the record into the OMN-12569
   ledger run. Do **not** duplicate the ledger here — this module supplies the
   record shape; the orchestrator owns the durable ledger.
6. **Repeat** in subsequent passes for the deferred remainder, never widening to
   the whole backlog.

---

## Current Draft State (2026-06-01)

These are tracked so a promotion pass does not blindly promote them. State must
be re-verified live before any pass — this is a snapshot, not authoritative
truth.

### Conflict-dirty drafts (rebase required before promotion)

`#1791`, `#1792`, `#1797`, `#1809`, `#1815`, `#1818`, `#1819`, `#1821`

These carry merge conflicts and/or stale failed/cancelled CI contexts from the
pre-fix CI shape. They are **deferred** (`conflict_dirty=True`) until rebased
onto `main` and re-validated locally. Promote each only after the rebase is
clean and the full local suite passes.

### Parked release draft

`#1822` — release draft. **Parked** (`parked=True`) until the release evidence
is refreshed. Do not promote it as part of an ordinary batch.

---

## Acceptance Mapping

| Acceptance criterion | Where it is enforced |
|----------------------|----------------------|
| Documented promotion procedure | This document |
| Configurable, evidence-backed batch size | `ModelPromotionPolicy` validator (`test_batch_size_must_be_evidence_backed`) |
| Never enqueue the whole backlog | `select_promotion_batch` whole-backlog guard (`TestNeverWholeBacklog`) |
| Rebase + local validation gate | `ModelDraftCandidate.is_eligible` (`TestRebaseAndValidationGating`) |
| Per-PR ledger record with provenance | `build_promotion_record` / `ModelDraftPromotionRecord` (`TestLedgerRecord`) |
| Trial batch promotes ≤N with full records | `select_promotion_batch` + `build_promotion_record` (covered end-to-end in tests) |
