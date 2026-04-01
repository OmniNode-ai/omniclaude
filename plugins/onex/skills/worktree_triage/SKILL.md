---
description: Scheduled worktree triage -- classifies worktrees as ship_it/archive/prune, auto-creates PRs for ship_it, removes empty/clean prune targets, and writes a markdown report
mode: full
version: 1.0.0
level: intermediate
debug: false
category: maintenance
tags:
  - worktrees
  - triage
  - cleanup
  - pr-creation
  - cron
  - automation
author: OmniClaude Team
composable: true
args:
  - name: --execute
    description: "Actually prune worktrees and create PRs (default: dry-run report only)"
    required: false
  - name: --schedule
    description: "Schedule recurring triage via CronCreate (e.g., '7d', '1d'). Runs --execute on each tick."
    required: false
  - name: --ship-it
    description: "Only process ship_it worktrees (create PRs, skip prune/archive)"
    required: false
  - name: --dry-run
    description: "Explicit dry-run flag (default behavior). Report classifications without acting."
    required: false
  - name: --stale-days
    description: "Days since last commit to classify as archive (default: 30)"
    required: false
  - name: --min-diff-lines
    description: "Minimum meaningful diff lines for ship_it classification (default: 50)"
    required: false
  - name: --worktrees-root
    description: "Override worktrees root path (default: /Volumes/PRO-G40/Code/omni_worktrees)" # local-path-ok
    required: false
---

# Worktree Triage

## Dispatch Surface

**Target**: Agent Teams

---

## Purpose

Scheduled hygiene skill that scans all worktrees under `/Volumes/PRO-G40/Code/omni_worktrees/`, <!-- local-path-ok -->
classifies each by freshness and content, and takes action:

| Classification | Criteria | Action |
|----------------|----------|--------|
| `ship_it` | >50 meaningful diff lines, <30 days old, has remote tracking | Auto-create PR |
| `archive` | Has changes, >30 days stale | Log in report, leave in place |
| `prune` | Clean (no diff) or empty directory | Remove via `git worktree remove` |

This is a **superset** of `worktree_lifecycle` -- it adds classification logic, PR creation
for shippable work, and a persistent markdown report. Uses `scripts/prune-worktrees.sh` for
the pruning phase.

**Announce at start:** "I'm using the worktree-triage skill to classify and action worktrees."

---

## Runtime Model

This skill is implemented as prompt-driven orchestration, not executable Python.
Python blocks in this document are pseudocode specifying logic and data shape, not
callable runtime helpers. The LLM executes the equivalent logic through Bash, Grep,
Git, and GitHub CLI tool calls, holding intermediate state in its working context.

---

## Usage

```
/worktree-triage                              # dry-run: classify all worktrees
/worktree-triage --execute                    # prune clean, create PRs for ship_it
/worktree-triage --ship-it                    # only create PRs for ship_it worktrees
/worktree-triage --schedule 7d                # schedule weekly triage
/worktree-triage --stale-days 14              # lower stale threshold to 14 days
/worktree-triage --min-diff-lines 20          # lower ship_it diff threshold
```

Schedulable via `/loop`:

```
/loop 7d /onex:worktree_triage --execute
```

---

## Behavior

### Step 1: Parse arguments <!-- ai-slop-ok: skill-step-heading -->

| Argument | Default | Description |
|----------|---------|-------------|
| `--execute` | false | Take action (prune + create PRs) vs dry-run |
| `--schedule` | none | Cron interval for recurring triage |
| `--ship-it` | false | Only process ship_it worktrees |
| `--dry-run` | true | Report only (explicit flag, same as no --execute) |
| `--stale-days` | 30 | Days since last commit for archive classification |
| `--min-diff-lines` | 50 | Minimum meaningful diff lines for ship_it |
| `--worktrees-root` | `/Volumes/PRO-G40/Code/omni_worktrees` | Worktrees root path | <!-- local-path-ok -->

### Step 2: Discover worktrees <!-- ai-slop-ok: skill-step-heading -->

Scan the worktrees root for `.git` worktree pointer files (depth <= 4):

```bash
find "$WORKTREES_ROOT" -maxdepth 4 -name ".git" -type f 2>/dev/null | sort
```

For each discovered worktree, extract:
- **Branch name**: `git -C <path> branch --show-current`
- **Remote URL**: `git -C <path> remote get-url origin`
- **Last commit date**: `git -C <path> log -1 --format=%ci`
- **Days since last commit**: computed from last commit date
- **Diff stat**: `git -C <path> diff --stat HEAD` (uncommitted changes)
- **Unpushed commits**: `git -C <path> log @{u}..HEAD --oneline` (committed but not pushed)
- **Total meaningful diff lines**: sum of insertions + deletions from `git diff --numstat` plus unpushed commit diffs
- **Remote tracking status**: whether the branch has an upstream and whether the remote branch still exists

### Step 3: Classify each worktree <!-- ai-slop-ok: skill-step-heading -->

Apply classification rules in order:

```
1. If working tree is clean AND no unpushed commits → prune
2. If total meaningful diff lines >= min_diff_lines AND days_since_commit < stale_days
   AND has remote tracking → ship_it
3. If days_since_commit >= stale_days AND has changes → archive
4. If has changes but below min_diff_lines AND days_since_commit < stale_days → archive
   (too small to ship, not yet stale — leave for manual review)
```

**Edge cases:**
- Detached HEAD: classify as `archive` (log warning)
- No remote origin: classify as `archive` (cannot create PR)
- Branch already has an open PR: skip PR creation, classify as `ship_it` but note "PR exists"

### Step 4: Execute actions (if --execute) <!-- ai-slop-ok: skill-step-heading -->

#### For `prune` worktrees:

Delegate to `scripts/prune-worktrees.sh --execute` or run directly:

```bash
# Safety: verify clean state before removing
DIRTY=$(git -C "$wt" status --porcelain)
UNPUSHED=$(git -C "$wt" log @{u}..HEAD --oneline 2>/dev/null || echo "")
if [[ -z "$DIRTY" ]] && [[ -z "$UNPUSHED" ]]; then
  git -C "$CANONICAL_ROOT" worktree remove --force "$wt"
fi
```

#### For `ship_it` worktrees (unless --ship-it is false):

1. Check if a PR already exists for the branch:
   ```bash
   gh pr list --repo "$REPO_SLUG" --head "$BRANCH" --state open --json number --jq '.[0].number'
   ```

2. If no open PR exists:
   - Ensure all changes are committed:
     ```bash
     git -C "$wt" add -A
     git -C "$wt" commit -m "chore: stage uncommitted changes for triage ship [OMN-7059]"
     ```
   - Push the branch:
     ```bash
     git -C "$wt" push -u origin "$BRANCH"
     ```
   - Create PR:
     ```bash
     gh pr create --repo "$REPO_SLUG" --head "$BRANCH" --base main \
       --title "chore: ship stale worktree $BRANCH" \
       --body "Auto-created by worktree-triage skill.

     **Source**: $wt
     **Days since last commit**: $DAYS
     **Diff lines**: $DIFF_LINES

     Review before merging — this was classified as shippable but may need cleanup."
     ```

3. Record the PR URL in the report.

#### For `archive` worktrees:

No action taken. Logged in report for manual review.

### Step 5: Write markdown report <!-- ai-slop-ok: skill-step-heading -->

Write report to `docs/tracking/YYYY-MM-DD-worktree-triage.md` in the `omni_home` repository:

```markdown
# Worktree Triage Report — YYYY-MM-DD

**Generated by**: `/onex:worktree_triage`
**Mode**: execute | dry-run
**Stale threshold**: 30 days
**Ship threshold**: 50 diff lines

## Summary

| Classification | Count |
|----------------|-------|
| ship_it        | N     |
| archive        | N     |
| prune          | N     |
| **Total**      | N     |

## ship_it (auto-PR)

| Worktree | Branch | Repo | Days | Diff Lines | PR |
|----------|--------|------|------|------------|----|
| /path    | branch | slug | 5    | 120        | #42 |

## archive (stale, has changes)

| Worktree | Branch | Repo | Days | Diff Lines | Notes |
|----------|--------|------|------|------------|-------|
| /path    | branch | slug | 45   | 30         | Below ship threshold |

## prune (removed)

| Worktree | Branch | Repo | Status |
|----------|--------|------|--------|
| /path    | branch | slug | Removed |
```

The report path: `/Volumes/PRO-G40/Code/omni_home/docs/tracking/YYYY-MM-DD-worktree-triage.md` <!-- local-path-ok -->

### Step 6: Schedule recurring triage (if --schedule) <!-- ai-slop-ok: skill-step-heading -->

If `--schedule` is provided, use CronCreate to schedule recurring execution:

```
CronCreate(
  cron="<parsed from interval>",
  prompt="/worktree-triage --execute",
  recurring=true
)
```

Report the cron job ID for later cancellation via CronDelete.

---

## Integration Points

- **worktree_lifecycle**: This skill supersedes worktree_lifecycle for triage purposes.
  worktree_lifecycle remains available for simple merged-branch cleanup.
- **worktree_sweep**: Complementary — worktree_sweep audits health status,
  worktree_triage takes action (PRs, pruning, reporting).
- **prune-worktrees.sh**: Used for the pruning phase (no reimplementation).
- **close-out / begin-day**: Natural companion — run triage at start of day or during close-out.
- **`/loop`**: Schedule via `/loop 7d /onex:worktree_triage --execute` for weekly hygiene.
