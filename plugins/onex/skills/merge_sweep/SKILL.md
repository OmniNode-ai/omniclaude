---
description: Org-wide PR sweep — enables GitHub auto-merge on ready PRs and runs pr-polish on PRs with blocking issues (CI failures, conflicts, changes requested)
mode: full
version: 3.4.0
level: advanced
debug: false
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
    description: "Comma-separated repo names to scan (default: all repos in omni_home)"
    required: false
  - name: --dry-run
    description: Print candidates without enabling auto-merge or running pr-polish; zero filesystem writes including claim files
    required: false
  - name: --merge-method
    description: "Merge strategy: squash | merge | rebase (default: squash)"
    required: false
  - name: --require-approval
    description: "Require GitHub review approval (default: true)"
    required: false
  - name: --require-up-to-date
    description: "Branch update policy: always | never | repo (default: repo — respect branch protection)"
    required: false
  - name: --max-total-merges
    description: "Hard cap on auto-merge candidates per run (default: 0 = unlimited). Set to a positive number to limit."
    required: false
  - name: --max-parallel-prs
    description: "Concurrent auto-merge enable operations (default: 5)"
    required: false
  - name: --max-parallel-repos
    description: "Repos scanned in parallel (default: 3)"
    required: false
  - name: --max-parallel-polish
    description: "Concurrent pr-polish agents (default: 2; pr-polish is resource-intensive)"
    required: false
  - name: --skip-polish
    description: Skip Track B entirely; only process merge-ready PRs
    required: false
  - name: --polish-clean-runs
    description: "Consecutive clean local-review passes required during pr-polish (default: 2)"
    required: false
  - name: --authors
    description: "Limit to PRs by these GitHub usernames (comma-separated; default: all)"
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

## Mode Declaration

**This skill operates in CLOSE-OUT mode only.**

Merge-sweep is not a build skill. It does not create new features, implement tickets, or modify
application logic. Its purpose is to drain the PR queue by enabling auto-merge on ready PRs and
polishing PRs with fixable blocking issues.

**First output line** must always be:
```
[merge-sweep] MODE: close-out | run: <run_id>
```

No tool calls, file reads, or bash commands may precede this output. Announce this line
immediately when the skill is invoked, before any scanning or classification.

**Pre-condition check**: Merge-sweep must not be invoked in a session that is actively running
epic-team (build mode). If the session has an active epic run (`$ONEX_STATE_DIR/epics/*/state.yaml`
with `status: monitoring`), emit a warning:
```
WARNING: Active epic run detected. Merge-sweep during active build may conflict with in-flight PRs.
Proceed? (default: yes — merge-sweep is safe to run concurrently)
```
Then proceed without waiting for input (this is a headless-compatible warning, not a gate).

## Headless Mode (Overnight Pipelines)

Use `plugins/onex/skills/merge_sweep/run.sh` for overnight/unattended runs:

```bash
# Full headless sweep
plugins/onex/skills/merge_sweep/run.sh

# Limit repos
plugins/onex/skills/merge_sweep/run.sh --repos omniclaude,omnibase_core

# Skip polish (fast, merge-only sweep)
plugins/onex/skills/merge_sweep/run.sh --skip-polish
```

**Minimum tool allowlist for headless merge-sweep:**
```
Bash, Read, Write, Edit, Glob, Grep, Task, TaskCreate, TaskUpdate,
TaskGet, TaskList, SendMessage, mcp__linear-server__save_comment
```

**Failure doctrine in headless mode:**
- **Missing credentials** (`gh auth` not configured): exit 2 immediately, structured JSON to stderr
- **Ambiguity** (conflicting PR state, claim race): write
  `$ONEX_STATE_DIR/merge-sweep/ambiguity_<ts>.json`, exit 3 — never guess
- **Blocked tool** (not in allowlist): log denial, exit 4 — never silently substitute
- **Partial failure** (some repos failed): record in ModelSkillResult `details` array and
  continue remaining repos — partial completion is acceptable; exit 5 only if ALL repos fail
- **Slack notification failure**: log warning only — never fail the skill for notification issues

**Idempotency**: The claim registry and idempotency ledger in
`$ONEX_STATE_DIR/pr-queue/<date>/run_<run_id>.json` ensure safe re-runs. Re-running
merge-sweep with the same `--run-id` skips PRs already processed in the current run.

## Execution Rules

Execute end-to-end without stopping between tasks. If blocked on one task, record a skip note
and continue to the next. Only pause for: (a) credentials not available in the session,
(b) a destructive action not explicitly covered by the plan, or (c) an explicit user gate in
the plan. Do not exit plan mode or stop to "await direction" in any other circumstance.

**If subagent dispatch fails** (auth error, "Not logged in", tool unavailable, Agent tool blocked,
or any subagent execution error): **STOP immediately. Do NOT fall back to direct Bash, Read, Edit,
Write, or Glob calls.** Report the exact error to the user and wait for direction. Falling back to
direct tools bypasses ONEX observability, context management, and the orchestration layer. There
is no acceptable workaround — surface the failure.

---

## Overview

Composable skill that scans all repos in `omni_home` for open PRs and handles them in three tracks:

**Track A-update — Proactive Branch Updates**: PRs that are merge-ready but have stale branches
(`mergeStateStatus` BEHIND or UNKNOWN), or PRs where GitHub hasn't computed mergeable state
(`mergeable` UNKNOWN), get their branches updated via `gh api -X PUT .../update-branch`
BEFORE auto-merge is attempted. This prevents the chicken-and-egg deadlock where strict branch
protection requires branches to be current but auto-merge does not trigger updates. Updated PRs
are picked up on the next sweep pass after CI re-runs.

**Track A — GitHub Auto-Merge**: PRs that are already merge-ready with current branches get
`gh pr merge --auto` enabled immediately. GitHub merges them automatically when all required
checks pass — no polling, no waiting, no human gate required.

**Track B — Polish**: PRs with fixable blocking issues get dispatched to `pr-polish` in a
temporary worktree. pr-polish resolves conflicts, fixes CI failures, addresses review comments,
and runs a local-review loop. If a PR becomes merge-ready after polishing, auto-merge is
enabled on it too.

Designed as the daily close-out command — one sweep drains both the merge queue and the fix queue.

**Announce at start:** "I'm using the merge-sweep skill."

> **Autonomous execution**: No Human Confirmation Gate. This skill runs end-to-end without
> human confirmation. After classification, proceed directly to Phase A and Phase B. Do not
> pause to ask the user. Do not include conditional or opt-out phrasing. `--dry-run` is the
> only preview mechanism; absence of `--dry-run` means "execute everything automatically."

## Quick Start

```
/merge-sweep                                       # Scan all repos, enable auto-merge + polish
/merge-sweep --dry-run                             # Print candidates only (no mutations)
/merge-sweep --repos omniclaude,omnibase_core      # Limit to specific repos
/merge-sweep --skip-polish                         # Only enable auto-merge on ready PRs
/merge-sweep --authors jonahgabriel                # Only PRs by this author
/merge-sweep --max-total-merges 5                  # Cap auto-merge queue at 5 (default: unlimited)
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
def needs_branch_update(pr) -> bool:
    """Track A-update: PR needs branch update before merge can proceed.
    Catches two cases:
    1. mergeable=MERGEABLE but mergeStateStatus is BEHIND/UNKNOWN (stale branch)
    2. mergeable=UNKNOWN (GitHub hasn't computed state — update forces recomputation)
    Checked BEFORE is_merge_ready() — first match wins.
    mergeStateStatus values: BEHIND, BLOCKED, CLEAN, DIRTY, DRAFT, HAS_HOOKS, UNKNOWN, UNSTABLE
    """
    if pr["isDraft"]:
        return False
    if pr["mergeable"] == "MERGEABLE":
        return pr.get("mergeStateStatus", "").upper() in ("BEHIND", "UNKNOWN")
    if pr["mergeable"] == "UNKNOWN":
        return True  # stale PR — update branch to force GitHub recomputation
    return False

def is_merge_ready(pr, require_approval=True) -> bool:
    """Track A: PR is safe to auto-merge immediately (branch is current)."""
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
    # Note: UNKNOWN mergeable PRs are caught by needs_branch_update() first (classification is first-match-wins)
    if pr["mergeable"] == "UNKNOWN":
        return False  # should not reach here — needs_branch_update() handles UNKNOWN
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

def needs_thread_resolution(pr, require_approval=True) -> bool:
    """Track A-resolve: PR is BLOCKED only by unresolved review threads.
    Catches: MERGEABLE + BLOCKED + ALL_GREEN — the only remaining blocker
    is `required_conversation_resolution` branch protection.
    These PRs need their review threads assessed and resolved before merge.
    """
    if pr["isDraft"]:
        return False
    if pr["mergeable"] != "MERGEABLE":
        return False
    if pr.get("mergeStateStatus", "").upper() != "BLOCKED":
        return False
    if not is_green(pr):
        return False
    # At this point: MERGEABLE + BLOCKED + GREEN
    # The only known cause is required_conversation_resolution with unresolved threads.
    # (review requirement is already excluded: require_approval check uses APPROVED/None)
    return True
```

**Classification order** (first match wins):
1. `needs_branch_update()` -- Track A-update (stale branch OR unknown mergeable state — update forces recomputation)
2. `is_merge_ready()` -- Track A (branch current, auto-merge immediately)
3. `needs_thread_resolution()` -- Track A-resolve (BLOCKED by unresolved conversations only)
4. `needs_polish()` -- Track B (fixable blocking issues)
5. Draft / `REVIEW_REQUIRED` / other BLOCKED -- skip silently

### Stacked PR Chain Detection (OMN-6458)

Before classifying a PR, check if it is part of a stacked chain:

```bash
# Get the PR's base branch
BASE=$(gh pr view {number} --json baseRefName -q '.baseRefName')

# If base is not main/master, this PR is stacked
if [[ "$BASE" != "main" && "$BASE" != "master" ]]; then
  # Find the base PR
  BASE_PR=$(gh pr list --head "$BASE" --json number -q '.[0].number')
  # Fix the base PR first — skip this PR until base is merged
  echo "STACKED: PR #{number} depends on PR #${BASE_PR} (base: ${BASE})"
fi
```

**Rules for stacked chains:**
1. Always fix the root PR first (the one targeting main)
2. Skip downstream PRs until their base is merged
3. Hard cap: warn if stack depth exceeds 3 — suggest collapsing

**Stack depth check:**
```bash
DEPTH=0; CURRENT_BASE="$BASE"
while [[ "$CURRENT_BASE" != "main" && "$CURRENT_BASE" != "master" && $DEPTH -lt 5 ]]; do
  DEPTH=$((DEPTH + 1))
  CURRENT_BASE=$(gh pr list --head "$CURRENT_BASE" --json baseRefName -q '.[0].baseRefName' 2>/dev/null || echo "main")
done
if [[ $DEPTH -gt 3 ]]; then
  echo "::warning::Stack depth $DEPTH exceeds recommended max of 3"
fi
```

### Track A-rebase: DIRTY PRs (OMN-6459)

**Detection**: `gh pr view {number} --json mergeStateStatus -q '.mergeStateStatus'` returns `DIRTY`

**Action**:
1. Create worktree: `git worktree add /tmp/rebase-{number} {branch}`
2. Attempt rebase: `git rebase origin/main`
3. If rebase succeeds (no conflicts): force-push with lease: `git push --force-with-lease`
4. If rebase fails (conflicts): classify as Track B (needs manual polish)
5. Clean up worktree: `git worktree remove /tmp/rebase-{number}`

**Budget**: 1 rebase attempt per PR per cycle. If rebase fails, do not retry — route to Track B.

### Merge Queue Non-Interference (OMN-6468)

**NEVER** dequeue a PR from the merge queue. If a PR is in the merge queue (`mergeStateStatus: QUEUED`):
1. Do NOT run `gh pr merge --disable-auto-merge`
2. Do NOT dequeue and re-enqueue — this doubles CI time
3. Simply wait for the merge queue to process the PR
4. If the merge queue run fails, the PR will be dequeued automatically by GitHub

**Rationale**: Dequeuing and re-enqueuing creates a second CI run. The concurrency group has `cancel-in-progress: false`, so both runs execute sequentially, wasting ~10 min per unnecessary dequeue (F18).

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--repos` | all | Comma-separated repo names to scan |
| `--dry-run` | false | Print candidates without enabling auto-merge or polishing; zero filesystem writes |
| `--run-id` | generated | Identifier for this run; correlates logs and claim registry ownership |
| `--merge-method` | `squash` | `squash` \| `merge` \| `rebase` |
| `--require-approval` | true | Require at least one GitHub APPROVED review |
| `--require-up-to-date` | `repo` | `always` \| `never` \| `repo` (respect branch protection) |
| `--max-total-merges` | 0 (unlimited) | Hard cap on Track A candidates per run. 0 = no cap. |
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
   Initialize: repo_scan_results = {repo: None for repo in repo_list}
   For each repo:
     gh pr list --repo <repo> --state open --json \
       number,title,mergeable,mergeStateStatus,statusCheckRollup, \
       reviewDecision,headRefName,baseRefName,baseRepository, \
       headRepository,headRefOid,author,labels,updatedAt,isDraft
     On success: repo_scan_results[repo] = prs (even if [])
     On failure: leave repo_scan_results[repo] = None

2a. POST-SCAN COVERAGE ASSERTION:
   After all parallel scans complete, assert every configured repo returned a result.
   repos_scanned = count of repos with non-None result
   repos_failed = count of repos where result is still None (silent miss)
   Log WARNING for each failed repo; include in ModelSkillResult as result: scan_failed
   Scan failures do NOT abort the run — successfully scanned repos are still processed.

3. CLASSIFY (apply all filters including --authors, --since, --label;
   first match wins per PR):
   - needs_branch_update() + passes filters → branch_update_queue[] (Track A-update; includes UNKNOWN mergeable PRs)
   - is_merge_ready() + passes filters → candidates[] (Track A)
   - needs_thread_resolution() + passes filters → thread_resolve_queue[] (Track A-resolve)
   - needs_polish() + passes filters → polish_queue[] (Track B)
   - draft / REVIEW_REQUIRED / else → ignore silently
   Check claim registry; exclude PRs with active claims from other runs.
   Apply --max-total-merges cap to candidates[] (skip if 0).

4. If branch_update_queue[], candidates[], thread_resolve_queue[], and polish_queue[] are all empty:
   → emit ModelSkillResult(status=nothing_to_merge), exit

5. If --dry-run:
   → print all queues (Track A-update, Track A, and Track B tables), exit

5a. PROCEED UNCONDITIONALLY to Phase A-update.
    DO NOT present classification results and wait for user input.
    --dry-run is the only preview mechanism. Without it, execute everything.

5b. PHASE A-update — Proactive branch updates (sequential):
    For each PR in branch_update_queue[]:
      check_merge_state(repo, N)  — via @_lib/pr-safety/helpers.md
      IF mergeable_state in ("behind", "unknown"):
        IF rebaseable:
          update_pr_branch(repo, N)  — via @_lib/pr-safety/helpers.md
          record as "branch_updated" (CI will re-run; next sweep handles merge)
        ELSE:
          log WARNING — may need Track B or manual resolution
      ELIF mergeable_state == "clean":
        promote to candidates[] (race: branch was updated between scan and execution)
    Sequential processing respects GitHub rate limits.

5c. PHASE A-resolve — Assess and resolve review threads (sequential):
    For each PR in thread_resolve_queue[]:
      resolve_review_threads(repo, N)  — via @_lib/pr-safety/helpers.md
      For each unresolved thread:
        1. Read comment body, file path, and line reference
        2. Read current file at referenced location (if it still exists)
        3. Classify disposition: addressed | not_applicable | intentional | deferred
        4. Post a reply explaining WHY the thread is being resolved (1-2 sentences)
        5. Resolve the thread
      After all threads resolved: promote to candidates[] for Phase A auto-merge
      Record as "threads_resolved" with disposition breakdown
    Sequential processing to avoid GitHub API rate limits on GraphQL mutations.

    CRITICAL: Never resolve a thread without posting a reply. Silent resolution
    defeats the purpose of code review.

6. PHASE A — Enable GitHub auto-merge (parallel, up to --max-parallel-prs):
   For each candidate in candidates[]:
     acquire claim
     gh pr merge <N> --repo <repo> --<merge_method> --auto
     IF fails with "Pull request is in clean status":
       gh pr merge <N> --repo <repo> --<merge_method>   (direct merge, no --auto)
       record result as "merged_directly"
     release claim

6a. POST-MERGE SAFETY — Update remaining BEHIND branches (sequential):
    Safety net for PRs that became BEHIND between scan and auto-merge (e.g.,
    another PR merged to main during this sweep). Most BEHIND detection now
    happens proactively in Step 5b.
    For each candidate where auto-merge was successfully enabled:
      check_merge_state(repo, N)
      IF mergeable_state == "behind" AND rebaseable:
        update_pr_branch(repo, N)

7. PHASE B — pr-polish queue (parallel, up to --max-parallel-polish):
   Skip if --skip-polish or polish_queue is empty.
   For each PR in polish_queue[]:
     acquire claim
     fetch headRefName from gh pr view (OMN-6253 defense — never trust scan-time branch name)
     dispatch polymorphic-agent:
       - create worktree at ${OMNI_WORKTREES}/merge-sweep-<run_id>/<repo>-pr-<N>/
       - Skill(skill="onex:pr_polish", args="<N> --required-clean-runs <polish_clean_runs>")
       - re-check mergeable state after polish
       - if now merge-ready: gh pr merge <N> --repo <repo> --<merge_method> --auto
         (if "Pull request is in clean status" error: retry without --auto as direct merge)
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

Repos scanned: R ok | F failed
Branch updates (proactive):    P stale → updated (CI re-running)
Thread resolution:             T resolved (A addressed | B not_applicable | C intentional | D deferred)
Track A (auto-merge enabled):  N queued | D merged directly | K failed
  Post-merge branch updates:   B behind → updated
Track B (pr-polish):           M fixed → M queued | P partial | Q blocked

⚠️ Scan failures (F repo(s) not scanned — check gh auth/network):  [only if F > 0]
  • OmniNode-ai/omnimemory — scan never returned (silent miss in parallel fan-out)
  • OmniNode-ai/omninode_infra — scan never returned (silent miss in parallel fan-out)

Branches updated (CI re-running — next sweep will merge):
  • OmniNode-ai/omniclaude#260 (was BEHIND)
  • OmniNode-ai/omniclaude#263 (was UNKNOWN)

Auto-merge enabled:
  • OmniNode-ai/omniclaude#247 — feat: auto-detect
  • OmniNode-ai/omnibase_core#88 — fix: validator (after polish)

Blocked (manual intervention needed):
  • OmniNode-ai/omnidash#19 — conflict resolution failed

Status: queued | partial | error
Run: <run_id>
```

## ModelSkillResult

Written to `$ONEX_STATE_DIR/skill-results/<run_id>/merge-sweep.json`:

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
  "repos_scanned": 9,
  "repos_failed": 2,
  "candidates_found": 3,
  "branch_update_queue_found": 2,
  "thread_resolve_queue_found": 2,
  "polish_queue_found": 2,
  "auto_merge_set": 4,
  "merged_directly": 1,
  "branches_updated": 4,
  "branches_updated_proactive": 2,
  "branches_updated_post_merge": 0,
  "threads_resolved": 4,
  "thread_resolve_dispositions": {"addressed": 3, "not_applicable": 1, "intentional": 0, "deferred": 0},
  "polished": 1,
  "polish_partial": 0,
  "polish_blocked": 1,
  "skipped": 1,
  "failed": 0,
  "details": [
    {
      "repo": "OmniNode-ai/omnimemory",
      "pr": null,
      "head_sha": null,
      "track": null,
      "result": "scan_failed",
      "error": "scan never returned (silent miss in parallel fan-out)"
    },
    {
      "repo": "OmniNode-ai/omniclaude",
      "pr": 260,
      "head_sha": "e4f5a678",
      "track": "A-update",
      "result": "branch_updated",
      "prior_state": "BEHIND",
      "skip_reason": null
    },
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
- `queued` — all candidates had auto-merge enabled and/or branches updated (Track A-update/A/B)
- `nothing_to_merge` — no actionable PRs found (after all filters)
- `partial` — some queued/updated, some failed or blocked
- `error` — no PRs successfully queued or updated

Scan `result` values (per repo): `scan_failed` (repo scan never returned — silent miss)
Track A-update `result` values: `branch_updated` | `failed` | `skipped`
Track A-resolve `result` values: `threads_resolved` (promoted to Track A) | `failed` | `skipped`
Track A `result` values: `auto_merge_set` | `merged_directly` | `failed` | `skipped`
Track B `result` values: `polished_and_queued` | `polished_partial` | `blocked` | `failed` | `skipped`

## Failure Handling

| Error | Behavior |
|-------|----------|
| `gh pr list` returns no output / silent failure for a repo | Post-scan coverage assertion detects `None` in `repo_scan_results`; logs WARNING; records `result: scan_failed` in ModelSkillResult details; skips repo for this run |
| Repo scan dropped in async fan-out | Same as silent failure — detected by coverage assertion via `repo_scan_results[repo] == None` |
| PR `mergeable` state UNKNOWN | Route to Track A-update; branch update forces GitHub to recompute mergeable state. Next sweep handles the result. |
| PR `mergeStateStatus` BEHIND/UNKNOWN (scan) | Step 5b: update branch proactively; record `branch_updated`; CI re-runs; next sweep merges |
| PR becomes CLEAN between scan and Step 5b | Promote to `candidates[]` for normal auto-merge |
| PR is BEHIND but not rebaseable | Skip with warning; may need Track B or manual resolution |
| `update-branch` API fails (403/429/422) | Log warning, record `result: failed`, continue others |
| `gh pr list` fails for a repo | Log warning, skip that repo, continue others |
| Thread resolution GraphQL query fails | Log warning, record `result: failed` for that PR, continue others |
| Thread reply mutation fails | Log warning, still attempt to resolve the thread (resolution is priority) |
| Thread resolve mutation fails | Record in errors list, continue to next thread |
| All threads resolved but PR still BLOCKED | Log warning — may be non-thread branch protection issue; do NOT promote to Track A |
| `gh pr merge --auto` fails with "clean status" | Fall back to direct merge (no `--auto`); record `result: merged_directly` |
| `gh pr merge --auto` fails for other reasons | Record `result: failed`; continue others |
| PR becomes BEHIND after auto-merge armed (Step 6a) | Safety net: update branch post-merge |
| pr-polish BLOCKED (unresolvable conflicts) | Record `result: blocked`; skip auto-merge for that PR |
| pr-polish PARTIAL (max iterations hit) | Record `result: polished_partial`; skip auto-merge |
| Worktree creation fails | Record `result: failed`; release claim; continue others |
| Worktree cleanup fails | Log warning; do NOT fail skill result |
| Claim race condition | Record `result: failed, error: claim_race_condition` |
| `--since` parse error | Immediate error in Step 1; show format hint |
| Slack notification fails | Log warning only; do NOT fail skill result |
| Cascading BEHIND after branch update | Expected; subsequent sweeps handle remaining BEHIND PRs |
| `headRefName` API fetch fails at dispatch | Fall back to scan-time `headRefName` with WARNING; pr-polish Step 0 re-verifies independently |
| pr-polish branch mismatch detected | pr-polish auto-corrects via `git checkout`; if checkout fails, abort that PR with FATAL |
| Post-push SHA mismatch | WARNING logged — fixes may have been pushed to wrong branch; manual verification needed |

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

- **v3.4.0** (OMN-6253): Two-layer PR branch name defense. Dispatcher now fetches `headRefName`
  from `gh pr view` at dispatch time instead of trusting scan-time data. pr-polish agent
  independently verifies it is on the correct branch as Step 0 before any work begins. Post-push
  SHA verification confirms `headRefOid` matches local HEAD. Prevents the 2026-03-24 incident
  where all polish fixes were pushed to a non-PR branch for 4 cycles (~2 hours wasted).
- **v3.3.0** (OMN-5134): Intelligent review thread resolution. Add `needs_thread_resolution()`
  predicate for PRs that are MERGEABLE + BLOCKED + ALL_GREEN (blocked only by
  `required_conversation_resolution`). New Phase A-resolve assesses each unresolved thread
  against current code, posts a disposition reply (addressed | not_applicable | intentional |
  deferred), then resolves the thread. Promoted PRs flow into Phase A for auto-merge. Add
  `resolve_review_threads()` to `_lib/pr-safety/helpers.md`. Add `thread_resolve_queue_found`,
  `threads_resolved`, and `thread_resolve_dispositions` counters to ModelSkillResult. Also
  integrate thread resolution into pr-polish finalize phase. Replaces the previous
  BRANCH_PROTECTION_DRIFT warning (which required manual intervention) with automated handling.
  Fixes 9 PRs across 3 repos blocked on 2026-03-15 sweep.
- **v3.2.0** (OMN-4517): Post-scan repo coverage assertion. Distinguishes repos with zero PRs
  (confirmed empty scan) from repos that silently missed in the parallel fan-out. All configured
  repos are initialized to `None` before scanning; successful scans (even empty) set their entry
  to a list. After all parallel scans complete, a post-scan assertion logs `WARNING` and records
  `result: scan_failed` in `ModelSkillResult.details` for any repo still at `None`. Adds
  `repos_scanned` and `repos_failed` counters to `ModelSkillResult`. Sweep summary Slack message
  includes scan failure warnings when `repos_failed > 0`. Fixes observed silent misses of
  `omnimemory` (3 open PRs) and `omninode_infra` (1 open PR) on 2026-03-10.
- **v3.1.0** (OMN-3818): Proactive stale branch detection and update. Add `needs_branch_update()`
  predicate using `mergeStateStatus` field. PRs that are BEHIND or UNKNOWN get their branches
  updated BEFORE auto-merge is attempted (Step 5b), preventing the chicken-and-egg deadlock with
  strict branch protection. Add `branch_updated` result value, `branch_update_queue_found`,
  `branches_updated_proactive`, and `branches_updated_post_merge` counters to ModelSkillResult.
  Existing Step 6a retained as post-merge safety net. Add `mergeStateStatus` to scan fields.
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

## Tier Routing (OMN-2828)

PR scanning uses tier-aware backend selection:

| Tier | Backend | Details |
|------|---------|---------|
| `FULL_ONEX` | `node_git_effect.pr_list()` | Typed Pydantic models, structured output |
| `STANDALONE` | `_bin/pr-scan.sh` | Shell script wrapping `gh pr list` with consistent fields |
| `EVENT_BUS` | `_bin/pr-scan.sh` | Same as STANDALONE (no push-based PR list equivalent) |

Tier detection: see `@_lib/tier-routing/helpers.md`.

The scan output format is identical across all tiers -- downstream classification
(`needs_branch_update`, `is_merge_ready`, `needs_polish`) works unchanged regardless of backend.

## Idempotency Ledger

Absorbed from the former `fix-prs` skill. Per-run record at `$ONEX_STATE_DIR/pr-queue/<date>/run_<run_id>.json`:

```json
{
  "OmniNode-ai/omniclaude#247": {
    "head_sha": "cbca770e",
    "last_error_fingerprint": "SHA256(phase|error_class|check_name|first_error_line)",
    "last_result": "fixed",
    "retry_count": 1
  }
}
```

**Retry policy**: retry a PR only if `head_sha` changed OR `last_error_fingerprint` differs.
If `retry_count >= 3` and neither condition is met: skip with `result: needs_human`.

## CI Secrets Guard

Before invoking `ci-fix-pipeline` for any failing check in Track B, inspect the check name:

```
External infra indicators (skip ci-fix-pipeline for these checks):
  - Check name contains: deploy, production, prod, staging, aws, gcp, azure,
    service-account, docker-push, publish, release, upload-to

If the failing check matches any indicator:
  → record blocked_check = <check_name>
  → result = blocked_external for that check
  → do NOT invoke ci-fix-pipeline
  → continue to next check
```

If ALL failing checks are blocked_external: record PR as `result: blocked_external`, skip ci-fix-pipeline entirely.

## Retry Policy

Track B retry behavior for pr-polish failures:

- Retry only if `head_sha` changed OR `error_fingerprint` differs from last attempt
- Maximum 3 retries per PR per run
- After 3 retries with no progress: record `result: needs_human`

## See Also

- `pr-polish` skill -- three-phase PR fix workflow (Track B sub-skill)
- `pr-review-dev` skill -- PR review comments + CI failures
- `local-review` skill -- iterative local review loop
- `_bin/pr-scan.sh` -- STANDALONE PR scanning backend
- `_lib/tier-routing/helpers.md` -- tier detection and routing helpers
