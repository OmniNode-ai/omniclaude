---
name: review-all-prs
description: Org-wide PR review — scans all open PRs across omni_home repos, runs local-review on each PR branch in an isolated worktree until N consecutive clean passes, then pushes any fix commits
version: 0.2.0
category: workflow
tags:
  - pr
  - github
  - review
  - local-review
  - org-wide
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: Comma-separated repo names to scan (default: all repos in omni_home)
    required: false
  - name: --clean-runs
    description: Required consecutive clean passes per PR (default: 2)
    required: false
  - name: --skip-clean
    description: Skip PRs that are already merge-ready (default: false)
    required: false
  - name: --max-total-prs
    description: Hard cap on PRs reviewed across all repos (default: 20)
    required: false
  - name: --max-parallel-prs
    description: Concurrent review agents (default: 5)
    required: false
  - name: --max-review-minutes
    description: Wall-clock timeout per PR; agent is aborted if exceeded (default: 30)
    required: false
  - name: --skip-large-repos
    description: Skip repos with more files than --large-repo-file-threshold (default: false)
    required: false
  - name: --large-repo-file-threshold
    description: File count threshold for --skip-large-repos (default: 5000)
    required: false
  - name: --cleanup-orphans
    description: Sweeper mode — remove orphaned worktrees older than --orphan-age-hours, then exit
    required: false
  - name: --orphan-age-hours
    description: Marker age threshold for orphan detection (default: 4)
    required: false
  - name: --max-parallel-repos
    description: Repos scanned in parallel during scan phase (default: 3)
    required: false
  - name: --authors
    description: Limit to PRs by these GitHub usernames (comma-separated; default: me)
    required: false
  - name: --all-authors
    description: Review PRs from ALL authors (org-wide blast radius). Requires --gate-attestation and --omn-2613-merged (or --accept-duplicate-ticket-risk).
    required: false
  - name: --gate-attestation
    description: "Gate attestation token required with --all-authors. Format: <slack_ts>:<run_id>"
    required: false
  - name: --omn-2613-merged
    description: Confirms OMN-2613 (fingerprinted dedup) is merged, preventing duplicate Linear sub-tickets at org scale. Required with --all-authors unless --accept-duplicate-ticket-risk is set.
    required: false
  - name: --accept-duplicate-ticket-risk
    description: Explicit acknowledgement that OMN-2613 is NOT merged and duplicate Linear sub-tickets may be created. Required with --all-authors when --omn-2613-merged is absent.
    required: false
  - name: --run-id
    description: "Pipeline run ID for claim registry ownership. Generated if not provided."
    required: false
  - name: --dry-run
    description: Zero filesystem writes — no claim files, no worktree creation, no PR mutations (default: false)
    required: false
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: all_clean | partial | nothing_to_review | error"
---

# review-all-prs

## Overview

Scans all open PRs across `omni_home` repos and runs `local-review` on each PR's branch in an
isolated git worktree. Each PR is reviewed until `--clean-runs` consecutive clean passes are
reached or the agent times out. Any fix commits are pushed back to the PR branch.

**Announce at start:** "I'm using the review-all-prs skill."

**Note**: This skill is planned as Phase 1 of `pr-queue-pipeline` v1 (OMN-2620). It ships
after OMN-2613 (local-review fingerprinted dedup) to prevent duplicate Linear sub-tickets at
org scale.

**Recommended first run**: `/review-all-prs --authors me --max-total-prs 3` to validate the
worktree lifecycle before running org-wide.

## Scope Guard

The default author scope is `--authors me` (the invoking user only). This is a safety default
that prevents org-wide blast radius on first run.

### --all-authors guard

`--all-authors` enables org-wide review (all PR authors). It is gated behind two hard errors:

**Hard error 1** — `--gate-attestation` is required:
```
hard_error: "--all-authors requires --gate-attestation=<slack_ts>:<run_id>.
  Obtain a gate token from the Slack review-all-prs gate before running org-wide."
```

**Hard error 2** — one of the following flags must also be present:
- `--omn-2613-merged` — confirms OMN-2613 (fingerprinted dedup) is merged, preventing
  duplicate Linear sub-tickets at org scale.
- `--accept-duplicate-ticket-risk` — explicit acknowledgement that OMN-2613 is NOT merged
  and duplicate Linear sub-tickets may be created during this run.

If neither flag is present alongside `--all-authors` and `--gate-attestation`:
```
hard_error: "--all-authors requires either:
  --omn-2613-merged  (if OMN-2613 fingerprinted dedup is merged), or
  --accept-duplicate-ticket-risk  (explicit risk acceptance for duplicate tickets).
  See OMN-2613 for context."
```

### Default scope behavior

Without `--all-authors`, the effective author filter is always `me` (the invoking user),
regardless of whether `--authors` is explicitly set. `--authors` may name specific users
but cannot expand to all-authors scope without the full guard flag set.

## Algorithm

```
Startup: orphan sweeper (always runs; removes stale worktrees)
  ↓
If --cleanup-orphans: sweeper-only mode, exit after cleanup

Scope guard check (BEFORE any scan):
  If --all-authors:
    - Require --gate-attestation → hard_error if absent
    - Require --omn-2613-merged OR --accept-duplicate-ticket-risk → hard_error if neither
  Else:
    - Default scope: authors = [me]  (--authors may specify subset; no all-authors expansion)

Step 1: SCAN — gh pr list per repo (parallel, --max-parallel-repos)
  - Apply author scope filter
  - Skip pr_state_unknown() PRs
  - If --skip-clean: skip is_merge_ready() PRs
  - If --skip-large-repos: skip repos above threshold
  - Check dedup ledger: skip if fingerprint already present with result: ticket_created
  - Apply --max-total-prs cap

Step 2: CREATE WORKTREES — before dispatch, one per PR
  path = ~/.claude/worktrees/pr-queue/<run_id>/<repo_name>/<pr_number>/
  acquire_claim(pr_key, run_id, "review") via _lib/pr-safety/helpers.md
  git -C <local_repo_path> worktree add <path> <headRefName>
  Write: <path>/.onex_worktree.json

Step 3: DISPATCH parallel agents (--max-parallel-prs), one per PR
  Skill(skill="onex:local-review", args="--required-clean-runs <clean_runs>")
  with --max-review-minutes wall-clock timeout

Step 4: CLEANUP — worktree removal always attempted per PR
  git worktree remove --force <path>
  release_claim(pr_key, run_id)

Step 5: UPDATE DEDUP LEDGER + EMIT ModelSkillResult
```

## Worktree Lifecycle

```
Path:    ~/.claude/worktrees/pr-queue/<run_id>/<repo_name>/<pr_number>/
Marker:  <path>/.onex_worktree.json
         {run_id, repo, pr, branch, base_ref, created_at, skill: "review-all-prs"}
Claim:   claim_path(pr_key)  (see _lib/pr-safety/helpers.md; acquired BEFORE worktree add)
Cleanup: release_claim(pr_key, run_id) + git worktree remove --force <path>
Failure: record cleanup_failed; include path in ModelSkillResult for manual cleanup
Sweeper: on startup (and --cleanup-orphans mode), remove markers older than --orphan-age-hours
```

**Claim-before-worktree invariant**: `acquire_claim()` from `_lib/pr-safety/helpers.md`
MUST be called before `get_worktree()`. The claim file at `claim_path(pr_key)` must exist
before any worktree directory is created. If `acquire_claim()` returns `"skip"`, do NOT
create the worktree.

**Preflight tripwire**: Before dispatching any agent, the orchestrator verifies that for every
PR in the work queue, a claim file exists at `claim_path(pr_key)`. If a worktree directory is
found at the expected path WITHOUT a corresponding claim file, this is a hard error:
```
hard_error: "worktree exists for <pr_key> but no active claim held.
  This indicates the orchestrator created a worktree without first acquiring a claim.
  Manual cleanup required: git worktree remove --force <path>"
```

**CRITICAL**: The marker file `.onex_worktree.json` MUST be written before any agent is
dispatched. This ensures the sweeper can detect and clean up orphaned worktrees even if the
orchestrator crashes mid-run.

## Dedup Ledger

Location: `~/.claude/pr-queue/<date>/review-all-prs_<run_id>.json`

The dedup ledger prevents re-processing the same thread fingerprint within a single run.
Each PR thread fingerprint is checked against the ledger at scan time. If the fingerprint
is already present with `last_result: "ticket_created"` or `last_result: "clean"` for the
same `head_sha`, the PR is skipped without creating a duplicate ticket.

```json
{
  "OmniNode-ai/omniclaude#247": {
    "head_sha": "<sha>",
    "last_result": "clean | fixed_and_pushed | failed | timed_out | ticket_created",
    "reviewed_at": "<ISO timestamp>",
    "local_review_iterations": 2,
    "thread_fingerprint": "<sha256 of thread content>"
  }
}
```

**Per-run dedup**: The dedup ledger protects against duplicate ticket creation within a
single run. If the fingerprint for a thread appears in the ledger with `last_result:
"ticket_created"`, the thread is skipped on subsequent pages/batches of the same run.

Skip logic:
- `head_sha` unchanged AND `last_result == "clean"` → skip (already clean at this commit)
- `thread_fingerprint` present AND `last_result == "ticket_created"` → skip (ticket already filed this run)

Re-review if `head_sha` changed (new commits pushed) or `last_result` was not clean.

## Dry-Run Contract

When `--dry-run` is passed, review-all-prs produces **zero writes to `~/.claude/`**:

- No claim files created (`acquire_claim()` is skipped in dry-run)
- No worktrees created (`get_worktree()` is not called; no worktree directories written)
- No ledger writes (`atomic_write()` raises `DryRunWriteError`)
- No marker files written (`.onex_worktree.json` not created)
- All output to stdout only

The `--dry-run` flag is propagated to all sub-calls that use `atomic_write()` from
`_lib/pr-safety/helpers.md`. Any attempted filesystem write in dry-run mode raises
`DryRunWriteError` and is caught + logged without aborting the dry-run preview.

## PR Classification

```python
def is_merge_ready(pr):
    return (
        pr["mergeable"] == "MERGEABLE"
        and is_green(pr)
        and pr.get("reviewDecision") in ("APPROVED", None)
    )

def pr_state_unknown(pr):
    return pr["mergeable"] == "UNKNOWN"

def is_green(pr):
    required = [c for c in pr["statusCheckRollup"] if c.get("isRequired", False)]
    if not required:
        return True
    return all(c.get("conclusion") == "SUCCESS" for c in required)
```

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--repos` | all | Comma-separated repo names to scan |
| `--clean-runs` | 2 | Required consecutive clean passes per PR |
| `--skip-clean` | false | Skip already merge-ready PRs |
| `--max-total-prs` | 20 | Hard cap on PRs reviewed across all repos |
| `--max-parallel-prs` | 5 | Concurrent review agents |
| `--max-review-minutes` | 30 | Wall-clock timeout per PR |
| `--skip-large-repos` | false | Skip repos above file count threshold |
| `--large-repo-file-threshold` | 5000 | File count threshold for large repo detection |
| `--cleanup-orphans` | false | Sweeper-only mode: remove orphaned worktrees, then exit |
| `--orphan-age-hours` | 4 | Marker age threshold for orphan detection (hours) |
| `--max-parallel-repos` | 3 | Repos scanned in parallel during scan phase |
| `--authors` | me | Limit to PRs by these GitHub usernames (default: invoking user) |
| `--all-authors` | false | Review PRs from ALL authors (requires gate flags) |
| `--gate-attestation` | — | Gate token required with --all-authors (`<slack_ts>:<run_id>`) |
| `--omn-2613-merged` | false | Confirms OMN-2613 dedup is merged (required with --all-authors) |
| `--accept-duplicate-ticket-risk` | false | Explicit risk acceptance for duplicate tickets |
| `--run-id` | generated | Pipeline run ID for claim registry ownership. Generated if not provided. |
| `--dry-run` | false | Zero filesystem writes — no claim files, no worktree creation, no PR mutations |

## ModelSkillResult

Written to `~/.claude/pr-queue/<date>/review-all-prs_<run_id>.json`:

```json
{
  "skill": "review-all-prs",
  "version": "0.2.0",
  "status": "all_clean | partial | nothing_to_review | error",
  "run_id": "<run_id>",
  "prs_reviewed": 12,
  "prs_clean": 9,
  "prs_fixed_and_pushed": 2,
  "prs_failed": 1,
  "prs_timed_out": 0,
  "prs_skipped_ledger": 3,
  "cleanup_failures": [
    {"repo": "OmniNode-ai/omniclaude", "pr": 247, "path": "~/.claude/worktrees/pr-queue/..."}
  ],
  "details": [
    {
      "repo": "OmniNode-ai/omniclaude",
      "pr": 247,
      "result": "clean | fixed_and_pushed | failed | timed_out | skipped_ledger",
      "local_review_iterations": 2,
      "head_sha_before": "<sha>",
      "head_sha_after": "<sha or null>",
      "worktree_cleaned": true
    }
  ]
}
```

Status values:
- `all_clean` — every reviewed PR is `clean` or `fixed_and_pushed` (all succeeded)
- `partial` — some PRs succeeded (clean or fixed_and_pushed), some failed or timed out
- `nothing_to_review` — no PRs matched the scan criteria (or all skipped by ledger)
- `error` — scan failed entirely (no repos scanned successfully)

## Failure Handling

| Situation | Action |
|-----------|--------|
| `--all-authors` without `--gate-attestation` | `hard_error` immediately, exit |
| `--all-authors` + `--gate-attestation` without OMN-2613 flag | `hard_error` immediately, exit |
| `gh pr list` fails for one repo | Log warning, skip repo, continue |
| All repos fail to scan | Emit `status: error`, exit |
| Worktree exists without claim (preflight tripwire) | `hard_error`, exit |
| `acquire_claim()` returns `"skip"` | Record `result: skipped_claim`, skip dispatch |
| Worktree creation fails | Record `failed`, skip dispatch for that PR, continue |
| local-review times out | Record `timed_out`, cleanup worktree, release claim, continue |
| local-review returns error | Record `failed`, cleanup worktree, release claim, continue |
| Worktree cleanup fails | Record `cleanup_failed` in result; log path for manual cleanup |
| Ledger write fails | Log warning; continue (non-blocking) |
| Report write fails | Log warning; return result (non-blocking) |

## Composability

This skill is designed to be called from `pr-queue-pipeline` as Phase 1 (v1):

```
# From pr-queue-pipeline v1 Phase 1:
Skill(skill="onex:review-all-prs", args={
  repos: <scope>,
  max_total_prs: <cap>,
  max_parallel_prs: <cap>,
  clean_runs: 2,
  skip_clean: true,   # pipeline already scans merge-ready separately
  authors: <authors>
})
```

After `review-all-prs` completes, the pipeline re-runs Phase 0 scan to pick up any PRs that
became merge-ready as a result of the review phase.

## Integration Test

Integration tests are in `tests/integration/skills/review_all_prs/test_review_all_prs_integration.py`.
All tests are static analysis / structural tests that run without external credentials, live
GitHub access, or live PRs. Safe for CI.

### Test Cases

| # | Test | Expected Result |
|---|------|-----------------|
| 1 | `--all-authors` without `--gate-attestation` | `hard_error: "missing --gate-attestation"` documented in SKILL.md |
| 2 | `--all-authors` + `--gate-attestation` without OMN-2613 flag | `hard_error: "missing --omn-2613-merged or --accept-duplicate-ticket-risk"` documented |
| 3 | Worktree creation claims PR first | `claim_path(pr_key)` exists before `get_worktree()` is called (documented in SKILL.md) |
| 4 | Claim released after worktree deleted | `release_claim()` called in cleanup; `claim_path(pr_key)` absent after cleanup |
| 5 | Dedup ledger prevents re-processing same fingerprint | `thread_fingerprint` + `last_result: ticket_created` → skip documented |
| 6 | Preflight tripwire: worktree without claim → hard error | `hard_error` documented if worktree exists without claim |
| 7 | Dry-run produces zero `~/.claude/` writes | `--dry-run` propagates `DryRunWriteError`; no filesystem writes documented |

## See Also

- `local-review` skill — sub-skill called per PR (requires `--path` support from OMN-2608)
- `fix-prs` skill — Phase 2 of `pr-queue-pipeline` (conflict + CI + review repair)
- `merge-sweep` skill — Phase 3/4 of `pr-queue-pipeline` (merge execution)
- `pr-queue-pipeline` v1 — uses this skill as Phase 1 (see OMN-2620, planned)
- OMN-2613 — fingerprinted dedup prerequisite (prevents duplicate Linear sub-tickets at scale)
- `_lib/pr-safety/helpers.md` — claim lifecycle, `acquire_claim()`, `release_claim()`, `atomic_write()`
