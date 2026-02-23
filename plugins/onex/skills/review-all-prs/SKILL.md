---
name: review-all-prs
description: Org-wide PR review — scans all open PRs across omni_home repos, runs local-review on each PR branch in an isolated worktree until N consecutive clean passes, then pushes any fix commits
version: 0.1.0
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
    description: Limit to PRs by these GitHub usernames (comma-separated; default: all)
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

## Algorithm

```
Startup: orphan sweeper (always runs; removes stale worktrees)
  ↓
If --cleanup-orphans: sweeper-only mode, exit after cleanup

Step 1: SCAN — gh pr list per repo (parallel, --max-parallel-repos)
  - Apply --authors filter
  - Skip pr_state_unknown() PRs
  - If --skip-clean: skip is_merge_ready() PRs
  - If --skip-large-repos: skip repos above threshold
  - Check run ledger: skip if head_sha unchanged AND last_result == "clean"
  - Apply --max-total-prs cap

Step 2: CREATE WORKTREES — before dispatch, one per PR
  path = ~/.claude/worktrees/pr-queue/<run_id>/<repo_name>/<pr_number>/
  git -C <local_repo_path> worktree add <path> <headRefName>
  Write: <path>/.onex_worktree.json

Step 3: DISPATCH parallel agents (--max-parallel-prs), one per PR
  Skill(skill="local-review", args="--required-clean-runs <clean_runs>")
  with --max-review-minutes wall-clock timeout

Step 4: CLEANUP — worktree removal always attempted per PR
  git worktree remove --force <path>

Step 5: UPDATE LEDGER + EMIT ModelSkillResult
```

## Worktree Lifecycle

```
Path:    ~/.claude/worktrees/pr-queue/<run_id>/<repo_name>/<pr_number>/
Marker:  <path>/.onex_worktree.json
         {run_id, repo, pr, branch, base_ref, created_at, skill: "review-all-prs"}
Cleanup: git worktree remove --force <path> (always attempted after each PR)
Failure: record cleanup_failed; include path in ModelSkillResult for manual cleanup
Sweeper: on startup (and --cleanup-orphans mode), remove markers older than --orphan-age-hours
```

**CRITICAL**: The marker file `.onex_worktree.json` MUST be written before any agent is
dispatched. This ensures the sweeper can detect and clean up orphaned worktrees even if the
orchestrator crashes mid-run.

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

## Run Ledger

Location: `~/.claude/pr-queue/<date>/review-all-prs_<run_id>.json`

```json
{
  "OmniNode-ai/omniclaude#247": {
    "head_sha": "<sha>",
    "last_result": "clean | fixed_and_pushed | failed | timed_out",
    "reviewed_at": "<ISO timestamp>",
    "local_review_iterations": 2
  }
}
```

Skip logic: if `head_sha` unchanged AND `last_result == "clean"` — skip this PR (already clean
at this commit). Re-review if head_sha changed (new commits pushed) or last result was not clean.

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
| `--authors` | all | Limit to PRs by these GitHub usernames |

## ModelSkillResult

Written to `~/.claude/pr-queue/<date>/review-all-prs_<run_id>.json`:

```json
{
  "skill": "review-all-prs",
  "version": "0.1.0",
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
| `gh pr list` fails for one repo | Log warning, skip repo, continue |
| All repos fail to scan | Emit `status: error`, exit |
| Worktree creation fails | Record `failed`, skip dispatch for that PR, continue |
| local-review times out | Record `timed_out`, cleanup worktree, continue |
| local-review returns error | Record `failed`, cleanup worktree, continue |
| Worktree cleanup fails | Record `cleanup_failed` in result; include path in summary |
| Ledger write fails | Log warning; continue (non-blocking) |
| Report write fails | Log warning; return result (non-blocking) |

## Composability

This skill is designed to be called from `pr-queue-pipeline` as Phase 1 (v1):

```
# From pr-queue-pipeline v1 Phase 1:
Skill(skill="review-all-prs", args={
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

## See Also

- `local-review` skill — sub-skill called per PR (requires `--path` support from OMN-2608)
- `fix-prs` skill — Phase 2 of `pr-queue-pipeline` (conflict + CI + review repair)
- `merge-sweep` skill — Phase 3/4 of `pr-queue-pipeline` (merge execution)
- `pr-queue-pipeline` v1 — uses this skill as Phase 1 (see OMN-2620, planned)
- OMN-2613 — fingerprinted dedup prerequisite (prevents duplicate Linear sub-tickets at scale)
