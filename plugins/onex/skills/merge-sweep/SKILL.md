---
name: merge-sweep
description: Org-wide PR sweep — enables GitHub auto-merge on ready PRs and runs pr-polish on PRs with blocking issues (CI failures, conflicts, changes requested)
version: 3.0.0
category: workflow
tags:
  - pr
  - github
  - merge
  - autonomous
  - pipeline
  - org-wide
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: Comma-separated repo names to scan (default: all repos in omni_home)
    required: false
  - name: --dry-run
    description: Print candidates without enabling auto-merge or running pr-polish; zero filesystem writes including claim files
    required: false
  - name: --merge-method
    description: "Merge strategy: squash | merge | rebase (default: squash)"
    required: false
  - name: --require-approval
    description: Require GitHub review approval (default: true)
    required: false
  - name: --require-up-to-date
    description: "Branch update policy: always | never | repo (default: repo — respect branch protection)"
    required: false
  - name: --max-total-merges
    description: Hard cap on auto-merge candidates per run (default: 10)
    required: false
  - name: --max-parallel-prs
    description: Concurrent auto-merge enable operations (default: 5)
    required: false
  - name: --max-parallel-repos
    description: Repos scanned in parallel (default: 3)
    required: false
  - name: --max-parallel-polish
    description: Concurrent pr-polish agents (default: 2; pr-polish is resource-intensive)
    required: false
  - name: --skip-polish
    description: Skip Track B entirely; only process merge-ready PRs
    required: false
  - name: --polish-clean-runs
    description: "Consecutive clean local-review passes required during pr-polish (default: 2)"
    required: false
  - name: --authors
    description: Limit to PRs by these GitHub usernames (comma-separated; default: all)
    required: false
  - name: --since
    description: "Filter PRs updated after this date (ISO 8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ). Avoids sweeping ancient PRs."
    required: false
  - name: --label
    description: "Filter PRs that have this GitHub label. Use comma-separated for multiple (any match). Default: all labels"
    required: false
  - name: --run-id
    description: "Pipeline run ID for claim registry ownership. Generated if not provided."
    required: false
inputs:
  - name: repos
    description: "list[str] — repo names to scan; empty list means all"
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: queued | nothing_to_merge | partial | error"
---

# Merge Sweep

## Overview

Composable skill that scans all repos in `omni_home` for open PRs and handles them in two tracks:

**Track A — GitHub Auto-Merge**: PRs that are already merge-ready get `gh pr merge --auto` enabled
immediately. GitHub merges them automatically when all required checks pass — no polling, no
waiting, no human gate required.

**Track B — Polish**: PRs with fixable blocking issues get dispatched to `pr-polish` in a
temporary worktree. pr-polish resolves conflicts, fixes CI failures, addresses review comments,
and runs a local-review loop. If a PR becomes merge-ready after polishing, auto-merge is
enabled on it too.

Designed as the daily close-out command — one sweep drains both the merge queue and the fix queue.

**Announce at start:** "I'm using the merge-sweep skill."

## Quick Start

```
/merge-sweep                                       # Scan all repos, enable auto-merge + polish
/merge-sweep --dry-run                             # Print candidates only (no mutations)
/merge-sweep --repos omniclaude,omnibase_core      # Limit to specific repos
/merge-sweep --skip-polish                         # Only enable auto-merge on ready PRs
/merge-sweep --authors jonahgabriel                # Only PRs by this author
/merge-sweep --max-total-merges 5                  # Cap auto-merge queue at 5
/merge-sweep --merge-method merge                  # Use merge commit (not squash)
/merge-sweep --since 2026-02-01                    # Only PRs updated after Feb 1, 2026
/merge-sweep --since 2026-02-23T00:00:00Z          # Only PRs updated after midnight UTC
/merge-sweep --label ready-for-merge               # Only PRs with this label
/merge-sweep --label ready-for-merge,approved      # PRs with either label
/merge-sweep --since 2026-02-20 --label ready-for-merge  # Combine filters
/merge-sweep --max-parallel-polish 1               # Throttle pr-polish (lower resource use)
```

## PR Classification Predicates

```python
def is_merge_ready(pr, require_approval=True) -> bool:
    """Track A: PR is safe to auto-merge immediately."""
    if pr["isDraft"]:
        return False
    if pr["mergeable"] != "MERGEABLE":
        return False
    if not is_green(pr):
        return False
    if require_approval:
        # APPROVED = explicit approval; None = no review required by branch policy
        return pr.get("reviewDecision") in ("APPROVED", None)
    return True

def needs_polish(pr, require_approval=True) -> bool:
    """Track B: PR has fixable blocking issues."""
    if pr["isDraft"]:
        return False  # draft PRs are intentionally incomplete
    if pr["mergeable"] == "UNKNOWN":
        return False  # can't determine state — skip
    if is_merge_ready(pr, require_approval=require_approval):
        return False  # already ready — goes to Track A
    # Fixable: conflicts (resolvable), CI failing (fixable), changes requested (addressable)
    if pr["mergeable"] == "CONFLICTING":
        return True
    if not is_green(pr):
        return True
    if require_approval and pr.get("reviewDecision") == "CHANGES_REQUESTED":
        return True
    return False  # other cases (e.g., REVIEW_REQUIRED — needs human, not automation)

def is_green(pr) -> bool:
    required_checks = [c for c in pr["statusCheckRollup"] if c.get("isRequired")]
    if not required_checks:
        return True  # no required checks = green
    return all(c.get("conclusion") == "SUCCESS" for c in required_checks)
```

`mergeable == "UNKNOWN"` — skip with warning (GitHub still computing merge state).
`REVIEW_REQUIRED` — skip (needs human approval; not fixable by automation).
Draft PRs — skip silently.

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--repos` | all | Comma-separated repo names to scan |
| `--dry-run` | false | Print candidates without enabling auto-merge or polishing; zero filesystem writes |
| `--run-id` | generated | Identifier for this run; correlates logs and claim registry ownership |
| `--merge-method` | `squash` | `squash` \| `merge` \| `rebase` |
| `--require-approval` | true | Require at least one GitHub APPROVED review |
| `--require-up-to-date` | `repo` | `always` \| `never` \| `repo` (respect branch protection) |
| `--max-total-merges` | 10 | Hard cap on Track A candidates per run |
| `--max-parallel-prs` | 5 | Concurrent auto-merge enable operations |
| `--max-parallel-repos` | 3 | Repos scanned in parallel |
| `--max-parallel-polish` | 2 | Concurrent pr-polish agents (resource-intensive) |
| `--skip-polish` | false | Skip Track B entirely |
| `--polish-clean-runs` | 2 | Clean local-review passes required during pr-polish |
| `--authors` | all | Limit to PRs by these GitHub usernames (comma-separated) |
| `--since` | — | Filter PRs updated after this date (ISO 8601). Skips ancient PRs. |
| `--label` | all | Filter PRs with this label. Comma-separated = any match. |

## Execution Algorithm

```
1. VALIDATE: parse and validate --since date if provided

2. SCAN (parallel, up to --max-parallel-repos):
   For each repo:
     gh pr list --repo <repo> --state open --json \
       number,title,mergeable,statusCheckRollup,reviewDecision, \
       headRefName,baseRefName,baseRepository,headRepository,headRefOid,
       author,labels,updatedAt,isDraft

3. CLASSIFY (apply all filters including --authors, --since, --label):
   - is_merge_ready() + passes filters → candidates[] (Track A)
   - needs_polish() + passes filters → polish_queue[] (Track B)
   - mergeable == UNKNOWN → skipped_unknown[] (warn)
   - draft / REVIEW_REQUIRED / else → ignore silently
   Check claim registry; exclude PRs with active claims from other runs.
   Apply --max-total-merges cap to candidates[].

4. If candidates[] and polish_queue[] are both empty:
   → emit ModelSkillResult(status=nothing_to_merge), exit

5. If --dry-run:
   → print both queues (Track A and Track B tables), exit

6. PHASE A — Enable GitHub auto-merge (parallel, up to --max-parallel-prs):
   For each candidate in candidates[]:
     acquire claim
     gh pr merge <N> --repo <repo> --<merge_method> --auto
     release claim

7. PHASE B — pr-polish queue (parallel, up to --max-parallel-polish):
   Skip if --skip-polish or polish_queue is empty.
   For each PR in polish_queue[]:
     acquire claim
     dispatch polymorphic-agent:
       - create worktree at ${OMNI_WORKTREES}/merge-sweep-<run_id>/<repo>-pr-<N>/
       - Skill(skill="onex:pr-polish", args="<N> --required-clean-runs <polish_clean_runs>")
       - re-check mergeable state after polish
       - if now merge-ready: gh pr merge <N> --repo <repo> --<merge_method> --auto
       - remove worktree
     release claim

8. COLLECT results

9. SUMMARY: Post LOW_RISK informational notification to Slack (best-effort, no polling)

10. EMIT ModelSkillResult
```

## --since Date Filter

The `--since` flag filters PRs to only those updated after the given date:

```python
def parse_since(since_str: str) -> datetime:
    """Parse ISO 8601 date or datetime string."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(since_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse --since date: {since_str!r}. Use YYYY-MM-DD or ISO 8601.")
```

**Purpose**: Avoids sweeping ancient PRs with stale CI or forgotten review state.

## --label Filter

```python
def passes_label_filter(pr: dict, filter_labels: list[str]) -> bool:
    if not filter_labels:
        return True
    pr_labels = {label["name"] for label in pr.get("labels", [])}
    return bool(pr_labels & set(filter_labels))
```

## Sweep Summary (Slack Notification)

After both phases complete, post a LOW_RISK informational message to Slack.
No polling — notification only. Best-effort: if posting fails, log warning and continue.

```
[merge-sweep] run <run_id> complete

Track A (auto-merge enabled):  N queued | K failed
Track B (pr-polish):           M fixed → M queued | P partial | Q blocked

Auto-merge enabled:
  • OmniNode-ai/omniclaude#247 — feat: auto-detect
  • OmniNode-ai/omnibase_core#88 — fix: validator (after polish)

Blocked (manual intervention needed):
  • OmniNode-ai/omnidash#19 — conflict resolution failed

Status: queued | partial | error
Run: <run_id>
```

## ModelSkillResult

Written to `~/.claude/skill-results/<run_id>/merge-sweep.json`:

```json
{
  "skill": "merge-sweep",
  "status": "queued | nothing_to_merge | partial | error",
  "run_id": "20260223-143012-a3f",
  "filters": {
    "since": "2026-02-20",
    "labels": ["ready-for-merge"],
    "authors": ["jonahgabriel"],
    "repos": ["OmniNode-ai/omniclaude"]
  },
  "candidates_found": 3,
  "polish_queue_found": 2,
  "auto_merge_set": 4,
  "polished": 1,
  "polish_partial": 0,
  "polish_blocked": 1,
  "skipped": 1,
  "failed": 0,
  "details": [
    {
      "repo": "OmniNode-ai/omniclaude",
      "pr": 247,
      "head_sha": "cbca770e",
      "track": "A",
      "result": "auto_merge_set",
      "merge_method": "squash",
      "skip_reason": null
    },
    {
      "repo": "OmniNode-ai/omnidash",
      "pr": 19,
      "head_sha": "d3f9a22b",
      "track": "B",
      "result": "polished_and_queued",
      "merge_method": "squash",
      "skip_reason": null
    }
  ]
}
```

Status values:
- `queued` — all candidates had auto-merge enabled (Track A and/or Track B)
- `nothing_to_merge` — no actionable PRs found (after all filters)
- `partial` — some queued, some failed or blocked
- `error` — no PRs successfully queued

Track B `result` values: `polished_and_queued` | `polished_partial` | `blocked` | `failed` | `skipped`

## Failure Handling

| Error | Behavior |
|-------|----------|
| PR mergeable state UNKNOWN | Skip with warning; include in `skipped` count |
| `gh pr list` fails for a repo | Log warning, skip that repo, continue others |
| `gh pr merge --auto` fails for a PR | Record `result: failed`; continue others |
| pr-polish BLOCKED (unresolvable conflicts) | Record `result: blocked`; skip auto-merge for that PR |
| pr-polish PARTIAL (max iterations hit) | Record `result: polished_partial`; skip auto-merge |
| Worktree creation fails | Record `result: failed`; release claim; continue others |
| Worktree cleanup fails | Log warning; do NOT fail skill result |
| Claim race condition | Record `result: failed, error: claim_race_condition` |
| `--since` parse error | Immediate error in Step 1; show format hint |
| Slack notification fails | Log warning only; do NOT fail skill result |

## Sub-skills Used

- `pr-polish` — three-phase PR fix workflow (conflict resolution + pr-review-dev + local-review loop)
- `pr-review-dev` — invoked by pr-polish for CI failures and review comments
- `local-review` — invoked by pr-polish for iterative clean-pass loop

## Integration Tests

Integration tests are in `tests/integration/skills/merge_sweep/test_merge_sweep_integration.py`.
Run with: `uv run pytest tests/integration/skills/merge_sweep/ -m unit -v`

**Note**: The test suite from v2.1.0 (OMN-2635) references `--gate-attestation` and `auto-merge`
sub-skill patterns that no longer apply in v3.0.0. Tests must be updated to verify:
- `gh pr merge --auto` in prompt.md (not `gh pr merge` directly)
- `pr-polish` sub-skill dispatch in prompt.md
- `needs_polish()` predicate documented in SKILL.md
- No `--gate-attestation` arg in either file
- `queued` status value in ModelSkillResult

## Changelog

- **v3.0.0**: Replace HIGH_RISK Slack gate with GitHub native auto-merge (`gh pr merge --auto`).
  Add Track B: dispatch `pr-polish` on PRs with CI failures, conflicts, or changes-requested.
  PRs polished to merge-ready also get auto-merge enabled. Remove `--gate-attestation` and
  `--gate-timeout-minutes` (no longer needed). Add `--skip-polish`, `--max-parallel-polish`,
  `--polish-clean-runs`. Update ModelSkillResult status values and counters.
- **v2.1.0** (OMN-2633 + OMN-2635): Migrate legacy bypass flags to `--gate-attestation=<token>`.
  Add integration test suite.
- **v2.0.0** (OMN-2629): Add `--since` date filter, `--label` filter, reply polling,
  `--gate-timeout-minutes` override, post-sweep Slack summary.
- **v1.0.0** (OMN-2616): Initial implementation.

## See Also

- `pr-polish` skill — three-phase PR fix workflow (Track B sub-skill)
- `pr-review-dev` skill — PR review comments + CI failures
- `local-review` skill — iterative local review loop
- `pr-queue-pipeline` skill — orchestrates fix-prs → merge-sweep in sequence
- `fix-prs` skill — alternative repair skill (merge-sweep now handles this inline via Track B)
