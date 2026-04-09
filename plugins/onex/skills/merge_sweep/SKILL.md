---
description: Org-wide PR sweep — enables GitHub auto-merge on ready PRs and runs pr-polish on PRs with blocking issues (CI failures, conflicts, changes requested)
mode: full
version: 4.0.0
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
    description: "Comma-separated org/repo names (default: all OmniNode repos)"
    required: false
  - name: --dry-run
    description: Print classification without enabling auto-merge or running pr-polish
    required: false
  - name: --merge-method
    description: "Merge strategy: squash | merge | rebase (default: squash)"
    required: false
  - name: --require-approval
    description: "Require GitHub review approval (default: true)"
    required: false
  - name: --max-total-merges
    description: "Hard cap on Track A candidates per run (default: 0 = unlimited)"
    required: false
  - name: --skip-polish
    description: Skip Track B entirely; only process merge-ready PRs
    required: false
  - name: --authors
    description: "Limit to PRs by these GitHub usernames (comma-separated)"
    required: false
  - name: --since
    description: "Filter PRs updated after this date (ISO 8601: YYYY-MM-DD)"
    required: false
  - name: --require-up-to-date
    description: "Require PR branch to be up-to-date with base before auto-merge (default: true)"
    required: false
inputs:
  - name: repos
    description: "list[str] — org/repo names to scan; empty = all"
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: queued | nothing_to_merge | partial | error"
---

# Merge Sweep

**Mode: CLOSE-OUT only.** Does not create features or implement tickets.

**Announce at start:** "I'm using the merge-sweep skill."

**First output line:**
```
[merge-sweep] MODE: close-out | run: <run_id>
```

## Usage

```
/merge-sweep                                       # Scan all repos
/merge-sweep --dry-run                             # Print candidates only
/merge-sweep --repos OmniNode-ai/omniclaude        # Limit repos
/merge-sweep --skip-polish                         # Merge-only, no polish
/merge-sweep --authors jonahgabriel                # Filter by author
/merge-sweep --max-total-merges 5                  # Cap Track A
/merge-sweep --since 2026-04-01                    # Only recent PRs
```

## Execution

### Step 1 — Parse arguments

Extract: repos, dry-run, merge-method, require-approval, max-total-merges,
skip-polish, authors, since. Generate a `run_id` (e.g. `merge-sweep-<timestamp>`).

### Step 2 — Classify PRs via node

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_merge_sweep \
  [--repos <comma-list>] \
  [--merge-method squash] \
  [--require-approval | --no-require-approval] \
  [--max-total-merges N] \
  [--skip-polish] \
  [--dry-run]
```

Capture stdout (JSON: `ModelMergeSweepResult`). The node fetches PRs via `gh`
and classifies each into:
- **Track A-update** — stale branch (BEHIND or UNKNOWN mergeStateStatus), needs update before merge
- **Track A** — merge-ready, enable auto-merge now
- **Track A-resolve** — BLOCKED only by unresolved review threads
- **Track B** — fixable blocking issues, needs polish
- **skip** — draft, needs human review, or REVIEW_REQUIRED

Classification order: `needs_branch_update` checked BEFORE `is_merge_ready` (first match wins).

Apply `--authors` and `--since` filters to the classification output.

If `--dry-run`: print classification tables and exit.

### Step 3 — Phase A-update: update stale branches

For each PR in `track_a_update`, use `update_pr_branch()` from `@_lib/pr-safety/helpers.md`:
```
update_pr_branch(repo=<repo>, pr=<N>)
```
Record as `branch_updated`. CI re-runs; next sweep merges.

### Step 4 — Phase A-resolve: resolve review threads

For each PR in `track_a_resolve`:
1. Fetch unresolved review threads via `gh api`
2. For each thread: read comment + current file content
3. Post a reply explaining disposition (addressed / not_applicable / intentional / deferred)
4. Resolve the thread via GraphQL mutation
5. After all threads resolved: promote to Track A for auto-merge

### Step 5 — Claim lifecycle (claim-before-mutate)

Before enabling auto-merge or dispatching pr-polish, acquire a claim via the claim registry:
- Acquire claim with `run_id` as the audit trail
- Claim guards all PR mutations (auto-merge, branch update, polish dispatch)
- Release claim after all mutations complete or on error

### Step 6 — Phase A: enable auto-merge

For each PR in `track_a_merge` (after promoting from A-resolve):
```bash
gh pr merge <N> --repo <repo> --squash --auto
# If "clean status" error: retry without --auto
gh pr merge <N> --repo <repo> --squash
```
NEVER use `--admin`. Record as `auto_merge_set` or `merged_directly`.

### Step 7 — Phase B: pr-polish (skip if `--skip-polish`)

For each PR in `track_b_polish`, dispatch a polish worker via Agent Teams:

```
TeamCreate(team_name="merge-sweep-<run_id>")
Agent(name="polish-<repo>-pr-<N>",
      team_name="merge-sweep-<run_id>",
      prompt="Run pr-polish for PR #<N> in <repo>. After polish, if merge-ready:
              gh pr merge <N> --repo <repo> --squash --auto
              SendMessage(to='team-lead') with result.")
```

Workers report back. Collect results. TeamDelete after all workers complete.

### Step 8 — Write skill result

Write to `$ONEX_STATE_DIR/skill-results/<run_id>/merge-sweep.json`:

```json
{
  "skill": "merge-sweep",
  "status": "queued | nothing_to_merge | partial | error",
  "run_id": "<run_id>",
  "repos_scanned": 0,
  "repos_failed": 0,
  "candidates_found": 0,
  "branch_update_queue_found": 0,
  "thread_resolve_queue_found": 0,
  "polish_queue_found": 0,
  "auto_merge_set": 0,
  "merged_directly": 0,
  "branches_updated": 0,
  "branches_updated_proactive": 0,
  "branch_updated": "branch_updated | skipped",
  "threads_resolved": 0,
  "polished": 0,
  "scan_failed": 0
}
```

**Failure handling / result values:**

| Condition | Result value | Notes |
|-----------|-------------|-------|
| Repo scan returned no response | `scan_failed` | Repo silently missed the scan; logged as WARNING |
| Branch already up-to-date | `branch_updated` | Proactive update succeeded |
| PR auto-merge armed | `queued` | GitHub will merge when checks pass |
| BEHIND/UNKNOWN branch updated | `branch_updated` | Track A-update |
| No PRs found across all repos | `nothing_to_merge` | |

Slack summary format: `Repos scanned: N | Scan failures: M | Track A: X queued | Track B: Y polished`

**Changelog**: 3.2.0 — added post-scan coverage assertion (OMN-4517); 3.1.0 — proactive branch updates (OMN-3818).

## Architecture

```
SKILL.md  → thin shell: parse args → node classify → execute GitHub side effects
node      → omnimarket/src/omnimarket/nodes/node_merge_sweep/  (PR classification only)
contract  → node_merge_sweep/contract.yaml
```

The node handles pure PR classification. All GitHub API side effects (auto-merge,
branch updates, thread resolution, polish dispatch) are explicit steps in this skill.
