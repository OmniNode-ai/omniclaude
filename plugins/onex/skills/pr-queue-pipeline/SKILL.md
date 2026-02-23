---
name: pr-queue-pipeline
description: Daily org-wide PR queue drain — review all PRs, fix broken PRs, then merge all ready PRs with a single Slack gate (v1 adds review-all-prs as Phase 1; use --skip-review for v0 behavior)
version: 0.2.0
category: workflow
tags:
  - pr
  - github
  - pipeline
  - merge
  - repair
  - review
  - org-wide
  - high-risk
author: OmniClaude Team
composable: false
args:
  - name: --repos
    description: Comma-separated repo names to scan (default: all repos in omni_home)
    required: false
  - name: --skip-review
    description: Skip Phase 1 (review-all-prs); restores v0 behavior (default: false)
    required: false
  - name: --skip-fix
    description: Skip Phase 2 (fix-prs); sweep-only mode (default: false)
    required: false
  - name: --dry-run
    description: Phase 0 only — print plan without executing any phase (default: false)
    required: false
  - name: --authors
    description: "Forwarded to all sub-skills. Use 'me' for first production run to limit blast radius"
    required: false
  - name: --max-total-prs
    description: Hard cap on PRs processed across all phases (default: 20)
    required: false
  - name: --max-total-merges
    description: Hard cap on merges across Phase 3 + Phase 4 combined (default: 10)
    required: false
  - name: --max-parallel-prs
    description: Concurrent agents; forwarded to sub-skills (default: 5)
    required: false
  - name: --merge-method
    description: "Merge strategy forwarded to merge-sweep: squash | merge | rebase (default: squash)"
    required: false
  - name: --allow-force-push
    description: Forwarded to fix-prs; permits force-push after rebase (default: false)
    required: false
  - name: --slack-report
    description: Post final report summary to Slack (default: false)
    required: false
  - name: --max-parallel-repos
    description: Repos scanned in parallel during Phase 0 and re-query; forwarded to sub-skills (default: 3)
    required: false
  - name: --clean-runs
    description: Required consecutive clean passes per PR forwarded to review-all-prs (default: 2)
    required: false
  - name: --max-review-minutes
    description: Per-PR wall-clock timeout forwarded to review-all-prs (default: 30)
    required: false
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: complete | partial | nothing_to_do | gate_rejected | error"
---

# PR Queue Pipeline (v1)

## Overview

The daily "drain the queue" command. v1 adds `review-all-prs` as Phase 1, so the pipeline
applies code quality fixes before repairing CI/conflicts and merging. Use `--skip-review` to
restore v0 behavior (Phase 1 skipped).

**Announce at start:** "I'm using the pr-queue-pipeline skill."

**Recommended first run**: `/pr-queue-pipeline --authors me --dry-run` to preview scope.

**First v1 run**: Add `--skip-review` until `review-all-prs` has been validated standalone.

## v1 Phase Sequence

```
Phase 0: SCAN + CLASSIFY + BUILD PLAN
  - Consolidated scan of all repos in scope
  - Build: merge_ready[], needs_fix[]
  - Apply blast radius caps
  - Print plan. If --dry-run: stop here.

Phase 1: REVIEW (sequential — review-all-prs completes before Phase 2 begins)
  - Invoke: review-all-prs (runs local-review on all open PRs, pushes fix commits)
  - If --skip-review: Phase 1 skipped entirely
  - Re-scan after Phase 1 to re-classify PRs that got new commits

Phase 2: FIX (sequential — fix-prs completes before Phase 3 begins)
  - Invoke: fix-prs
  - If --skip-fix: Phase 2 skipped
  - Wait for completion before proceeding

Phase 3: GATE + MERGE (first pass)
  - Re-query merge_ready PRs (Phases 1+2 may have unblocked new ones)
  - Post single HIGH_RISK Slack gate
  - On approval: invoke merge-sweep --no-gate --gate-token <gate_token>

Phase 4: MERGE (second pass, conditional)
  - Condition: Phase 2 prs_fixed > 0 AND those PRs are now merge_ready
  - Invoke: merge-sweep --no-gate --gate-token <gate_token> (reuses Phase 3 token)

Phase 5: REPORT
  - Write org queue report to ~/.claude/pr-queue/<date>/report_<run_id>.md
  - Print report path; post to Slack if --slack-report
```

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--repos` | all | Comma-separated repo names to scan |
| `--skip-review` | false | Skip Phase 1 (review-all-prs); restores v0 behavior |
| `--skip-fix` | false | Skip Phase 2 (sweep-only mode) |
| `--dry-run` | false | Phase 0 only — print plan, no execution |
| `--authors` | all | Forwarded to all sub-skills. Recommended: `me` for first production run |
| `--max-total-prs` | 20 | Hard cap on PRs processed across all phases |
| `--max-total-merges` | 10 | Hard cap on merges across Phase 3 + Phase 4 |
| `--max-parallel-prs` | 5 | Concurrent agents (forwarded to sub-skills) |
| `--merge-method` | `squash` | `squash` \| `merge` \| `rebase` (forwarded to merge-sweep) |
| `--allow-force-push` | false | Forwarded to fix-prs |
| `--slack-report` | false | Post report summary to Slack after completion |
| `--max-parallel-repos` | 3 | Repos scanned in parallel (forwarded to sub-skills) |
| `--clean-runs` | 2 | Required consecutive clean passes; forwarded to review-all-prs |
| `--max-review-minutes` | 30 | Per-PR timeout; forwarded to review-all-prs |

**First production run recommendation**: use `--authors me --skip-review` to limit blast
radius and skip the review phase until it has been validated standalone.

## Gate Token Contract

```
Pipeline generates at start: run_id = "<YYYYMMDD-HHMMSS>-<random6>"

Phase 3 Slack gate returns: gate_message_ts (Slack thread timestamp)
gate_token = "<gate_message_ts>:<run_id>"

merge-sweep called with: --no-gate --gate-token <gate_token>
merge-sweep errors if --no-gate is passed without --gate-token (enforced by merge-sweep)
All merge results include gate_token for audit trail
```

## Slack Gate Message Format (v1)

```
PR Queue Pipeline — run <run_id>
Scope: <repos> | Authors: <authors or "all">

READY TO MERGE (N PRs):
  • OmniNode-ai/omniclaude#247 — feat: auto-detect (5 ✓, approved) SHA: cbca770e
  • OmniNode-ai/omnibase_core#88 — fix: validator (3 ✓, no review required) SHA: ff3ab12c

REVIEWED THIS RUN (Phase 1 applied local-review fixes):
  • OmniNode-ai/omnidash#19 — 2 iterations, 1 fix committed

REPAIRED THIS RUN (Phase 4 sweep picks these up if CI settles):
  • OmniNode-ai/omniintelligence#34 — fixed merge conflict + CI

Commands:
  approve all                    — merge all N ready PRs
  approve except omniclaude#247  — merge all except listed
  skip omniclaude#247            — exclude specific PR, merge rest
  reject                         — cancel merge phase

This is HIGH_RISK — silence will NOT auto-advance.
```

## ModelSkillResult

Written to `~/.claude/pr-queue/<date>/pipeline_<run_id>.json`:

```json
{
  "skill": "pr-queue-pipeline",
  "version": "0.2.0",
  "status": "complete | partial | nothing_to_do | gate_rejected | error",
  "run_id": "<run_id>",
  "gate_token": "<slack_ts>:<run_id>",
  "phases": {
    "scan": {"repos_scanned": 5, "merge_ready": 3, "needs_fix": 4},
    "review_all_prs": {
      "status": "all_clean | partial | nothing_to_review | skipped",
      "prs_reviewed": 8,
      "prs_fixed_and_pushed": 2
    },
    "fix_prs": {"status": "partial", "prs_fixed": 3, "prs_failed": 1, "skipped": false},
    "merge_sweep_phase3": {"status": "merged", "merged": 3},
    "merge_sweep_phase4": {"status": "merged", "merged": 2}
  },
  "total_prs_merged": 5,
  "total_prs_reviewed": 8,
  "total_prs_fixed": 3,
  "total_prs_still_blocked": 2,
  "total_prs_needs_human": 1,
  "total_prs_blocked_external": 1,
  "report_path": "~/.claude/pr-queue/2026-02-23/report_<run_id>.md"
}
```

Status values:
- `complete` — all work done, merges occurred
- `partial` — some phases completed, some had failures
- `nothing_to_do` — no merge-ready or fixable PRs found
- `gate_rejected` — human rejected the Slack gate
- `error` — unrecoverable error

## Phase Sequencing Invariant

**CRITICAL**: Phases run strictly sequentially. No phase starts until the previous completes.

```
Phase 1 (review-all-prs) → MUST COMPLETE (includes Phase 0 re-scan) → Phase 2 (fix-prs)
Phase 2 (fix-prs) → MUST COMPLETE → Phase 3 (gate+merge)
Phase 3 (merge) → MUST COMPLETE → Phase 4 (conditional merge)
Phase 4 (merge) → MUST COMPLETE → Phase 5 (report)
```

Note: "Phase 0 re-scan" is the final step of Phase 1 (not a separate phase). After
`review-all-prs` completes, the orchestrator re-runs the scan before handing off to Phase 2.

## Failure Handling

| Error | Behavior |
|-------|----------|
| Phase 0 scan fails | Return `status: error` |
| Phase 1 review-all-prs returns `error` | Log warning, continue to Phase 2 with pre-Phase-1 state |
| Phase 2 fix-prs returns `error` | Log warning, continue to Phase 3 with pre-Phase-2 merge_ready list |
| Phase 3 gate rejected | Return `status: gate_rejected`; write partial report |
| Phase 3 merge-sweep fails | Return `status: error` |
| Phase 4 condition not met | Skip Phase 4 silently |
| Phase 4 merge-sweep fails | Return `status: partial` (Phase 3 succeeded) |
| Report write fails | Log warning; return result (report is non-blocking) |

## Sub-skills Used

- `review-all-prs` (Phase 1) — runs local-review on all open PRs, pushes fix commits
- `fix-prs` (Phase 2) — autonomously repairs broken PRs (conflicts + CI + reviews)
- `merge-sweep` (Phase 3 + Phase 4) — merges approved PRs with gate bypass
- `slack-gate` (Phase 3, via merge-sweep) — HIGH_RISK gate for merge approval

## Org Queue Report Format

Written to `~/.claude/pr-queue/<date>/report_<run_id>.md`:

```markdown
# PR Queue Pipeline Report — <run_id>
Date: <date> | v1 | Scope: <repos> | Authors: <authors>

## Merged (<N> PRs)
- OmniNode-ai/omniclaude#247 — feat: auto-detect | squash | SHA: cbca770e

## Reviewed This Run (<N> PRs — Phase 1)
- OmniNode-ai/omnidash#19 — 2 iterations, fixed_and_pushed

## Fixed This Run (<N> PRs — Phase 2)
- OmniNode-ai/omniintelligence#34 — fixed merge conflict

## Still Blocked (<N> PRs)
- OmniNode-ai/omniarchon#12 — reason: conflict_unresolved

## Needs Human Review (<N> PRs)
- OmniNode-ai/omnidash#19 — retry_count: 3, no progress

## Blocked External (<N> PRs)
- OmniNode-ai/omnibase_core#55 — blocked_check: deploy-staging
```

## See Also

- `review-all-prs` skill — Phase 1 sub-skill (local-review on all open PRs)
- `fix-prs` skill — Phase 2 sub-skill (conflict + CI + review repair)
- `merge-sweep` skill — Phase 3/4 sub-skill (merge execution with gate bypass)
- `pr-queue-pipeline` v0 (OMN-2618) — predecessor; use `--skip-review` for v0 behavior
