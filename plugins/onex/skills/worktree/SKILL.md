---
description: Unified worktree management — audit health, triage ship_it/archive/prune, prune merged worktrees, and schedule recurring GC
mode: full
version: "1.0.0"
level: intermediate
debug: false
category: maintenance
tags: [worktree, cleanup, audit, triage, lifecycle, cron, automation]
author: OmniClaude Team
composable: true
args:
  - name: --audit
    description: "Audit all worktrees for health status (categorize SAFE_TO_DELETE, LOST_WORK, STALE, ACTIVE, DIRTY_ACTIVE)"
    required: false
  - name: --triage
    description: "Classify worktrees as ship_it/archive/prune, auto-create PRs for ship_it, remove clean/empty prune targets"
    required: false
  - name: --prune
    description: "GC merged worktrees by wrapping prune-worktrees.sh (remove stale/merged branches)"
    required: false
  - name: --cron
    description: "Schedule recurring execution via CronCreate (e.g., '7d', '2h'). Applies to whichever mode flag is also passed."
    required: false
  - name: --execute
    description: "Actually perform removals/PR creation (default: dry-run report only). Applies to --audit, --triage, and --prune modes."
    required: false
  - name: --dry-run
    description: "Explicit dry-run flag (report without acting). Default behavior."
    required: false
  - name: --stale-days
    description: "Days since last commit to consider stale (default: 3 for --audit, 30 for --triage)"
    required: false
  - name: --min-diff-lines
    description: "Minimum meaningful diff lines for ship_it classification in --triage mode (default: 50)"
    required: false
  - name: --verbose
    description: "Show active and skipped worktrees in addition to stale ones (--prune mode)"
    required: false
  - name: --worktrees-root
    description: "Override worktrees root path (default: /Volumes/PRO-G40/Code/omni_worktrees)" # local-path-ok: example in YAML documentation
    required: false
---

# Worktree Manager

## Dispatch Surface

**Target**: Agent Teams

---

## Purpose

Unified worktree management skill. Consolidates health auditing, classification triage, and
lifecycle garbage collection into a single entry point with four mode flags:

| Flag | Former Skill | Description |
|------|-------------|-------------|
| `--audit` | `worktree_sweep` | Health audit: SAFE_TO_DELETE, LOST_WORK, STALE, ACTIVE, DIRTY_ACTIVE |
| `--triage` | `worktree_triage` | Classify ship_it/archive/prune, auto-PR ship_it, remove prune targets |
| `--prune` | `worktree_lifecycle` | GC merged worktrees via prune-worktrees.sh |
| `--cron` | (shared) | Schedule recurring execution of whichever mode is active |

Exactly one of `--audit`, `--triage`, or `--prune` must be specified per invocation.
`--cron` is an additive modifier that schedules the chosen mode.

**Announce at start:** "I'm using the worktree skill to [audit/triage/prune] worktrees."

---

## Runtime Model

This skill is implemented as prompt-driven orchestration, not executable Python.
Python blocks in this document are pseudocode specifying logic and data shape, not
callable runtime helpers. The LLM executes the equivalent logic through Bash, Grep,
Git, and GitHub CLI tool calls, holding intermediate state in its working context.

The typed models live in `src/omniclaude/hooks/worktree_sweep.py` and define the
report schema: `EnumWorktreeStatus`, `ModelWorktreeEntry`, `ModelWorktreeSweepReport`.

---

## Usage

```
/worktree --audit                         # audit all worktrees (dry-run)
/worktree --audit --execute               # audit + auto-remove SAFE_TO_DELETE
/worktree --audit --stale-days 7          # raise stale threshold to 7 days

/worktree --triage                        # classify all worktrees (dry-run)
/worktree --triage --execute              # prune clean, create PRs for ship_it
/worktree --triage --stale-days 14        # lower stale threshold to 14 days
/worktree --triage --min-diff-lines 20    # lower ship_it diff threshold

/worktree --prune                         # dry-run: report stale/merged worktrees
/worktree --prune --execute               # remove stale/merged worktrees
/worktree --prune --verbose               # include active worktrees in report

/worktree --audit --cron 3d               # schedule daily audit
/worktree --triage --cron 7d              # schedule weekly triage
/worktree --prune --cron 2h               # schedule GC every 2 hours
```

---

## Behavior

### Step 0: Parse arguments and validate mode <!-- ai-slop-ok: skill-step-heading -->

```python
# Pseudocode — LLM resolves from invocation context
mode = None
if args.audit:
    mode = "audit"
elif args.triage:
    mode = "triage"
elif args.prune:
    mode = "prune"
else:
    raise ValueError("One of --audit, --triage, or --prune is required.")

execute = bool(args.execute)
dry_run = not execute
cron_interval = args.cron  # e.g. "7d", "2h", or None
worktrees_root = args.worktrees_root or "/Volumes/PRO-G40/Code/omni_worktrees"  # local-path-ok: env var default fallback
```

---

## Mode: --audit (formerly worktree_sweep)

Audits all git worktrees under the worktrees root. Categorizes each by health status.
Auto-cleans merged+clean worktrees (SAFE_TO_DELETE) when `--execute` is set.
Flags lost work (LOST_WORK) for recovery tickets. Reports STALE and DIRTY_ACTIVE for
manual review.

### Step 1: Discover worktrees <!-- ai-slop-ok: skill-step-heading -->

```bash
# List all ticket directories
ls -d ${worktrees_root}/*/

# For each ticket dir, find repo subdirectories that are git worktrees
for ticket_dir in ${worktrees_root}/*/; do
  for repo_dir in ${ticket_dir}*/; do
    if [ -e "${repo_dir}/.git" ]; then
      echo "${repo_dir}"
    fi
  done
done
```

### Step 2: Audit each worktree <!-- ai-slop-ok: skill-step-heading -->

```bash
git -C "${worktree_path}" branch --show-current
git -C "${worktree_path}" fetch origin main --quiet 2>/dev/null
git -C "${worktree_path}" log --oneline origin/main..HEAD 2>/dev/null | wc -l
git -C "${worktree_path}" status --porcelain
git -C "${worktree_path}" log -1 --format=%aI 2>/dev/null
```

**Important**: Use `origin/main` not `main` for the merge check.

### Step 3: Categorize <!-- ai-slop-ok: skill-step-heading -->

```python
stale_days = int(args.stale_days) if args.stale_days else 3

def classify(commits_ahead, has_uncommitted, last_commit, has_open_pr, stale_days):
    merged = commits_ahead == 0
    if merged and not has_uncommitted:
        return EnumWorktreeStatus.SAFE_TO_DELETE
    if merged and has_uncommitted:
        return EnumWorktreeStatus.LOST_WORK
    stale_cutoff = datetime.now(tz=timezone.utc) - timedelta(days=stale_days)
    if not has_uncommitted and last_commit < stale_cutoff and not has_open_pr:
        return EnumWorktreeStatus.STALE
    if has_uncommitted:
        return EnumWorktreeStatus.DIRTY_ACTIVE
    return EnumWorktreeStatus.ACTIVE
```

PR check (only for potential STALE worktrees):
```bash
gh pr list --head "${branch_name}" --state open --json number --jq 'length'
```

### Step 4: Execute actions (if --execute) <!-- ai-slop-ok: skill-step-heading -->

**SAFE_TO_DELETE — auto-remove:**
```bash
repo_name=$(basename "${worktree_path}")
git -C "${omni_home}/${repo_name}" worktree remove "${worktree_path}" --force
ticket_dir=$(dirname "${worktree_path}")
rmdir "${ticket_dir}" 2>/dev/null
```

**LOST_WORK — create recovery ticket via `mcp__linear-server__save_issue`:**
- Title: `recover: uncommitted work in {ticket_id}/{repo_name}`
- High priority, includes diff stat and recovery steps.

**STALE / DIRTY_ACTIVE — flag for review (no automated action).**

**ACTIVE — leave alone.**

### Step 5: Print summary report <!-- ai-slop-ok: skill-step-heading -->

```
Worktree Health Sweep Summary
Total audited: N
| Status         | Count | Action          |
| SAFE_TO_DELETE | N     | Removed (auto)  |
| LOST_WORK      | N     | Ticket created  |
| STALE          | N     | Flagged         |
| ACTIVE         | N     | None            |
| DIRTY_ACTIVE   | N     | Flagged         |
```

---

## Mode: --triage (formerly worktree_triage)

Scans all worktrees, classifies each as ship_it/archive/prune, auto-creates PRs for
shippable work, and writes a markdown report.

### Classification rules <!-- ai-slop-ok: skill-step-heading -->

```python
stale_days = int(args.stale_days) if args.stale_days else 30
min_diff_lines = int(args.min_diff_lines) if args.min_diff_lines else 50

# Classification order:
# 1. Clean AND no unpushed commits → prune
# 2. diff_lines >= min_diff_lines AND days < stale_days AND has remote → ship_it
# 3. days >= stale_days AND has changes → archive
# 4. has changes but below min_diff_lines AND days < stale_days → archive
```

**Edge cases:**
- Detached HEAD → archive (log warning)
- No remote origin → archive (cannot create PR)
- Branch already has open PR → ship_it with note "PR exists"

### Actions (if --execute) <!-- ai-slop-ok: skill-step-heading -->

**prune:** Verify clean state, then `git -C "$CANONICAL_ROOT" worktree remove --force "$wt"`

**ship_it:** Check for existing PR, then stage uncommitted changes, push, and create PR:
```bash
gh pr create --repo "$REPO_SLUG" --head "$BRANCH" --base main \
  --title "chore: ship stale worktree $BRANCH" \
  --body "Auto-created by worktree skill (--triage)."
```

**archive:** No action. Logged for manual review.

### Report <!-- ai-slop-ok: skill-step-heading -->

Write to `docs/tracking/YYYY-MM-DD-worktree-triage.md` in the `omni_home` repository.
Tables: ship_it (with PR URLs), archive (with age/diff), prune (removed).

---

## Mode: --prune (formerly worktree_lifecycle)

Manages lifecycle of merged worktrees. Wraps `scripts/prune-worktrees.sh`.

A worktree is stale when:
- Its branch's PR has been merged (`gh pr list --state merged`)
- Its remote branch no longer exists

### Step 1: Run prune-worktrees.sh <!-- ai-slop-ok: skill-step-heading -->

```bash
bash scripts/prune-worktrees.sh ${execute_flag} ${verbose_flag} ${root_flag}
```

### Step 2: Report results <!-- ai-slop-ok: skill-step-heading -->

```
Active: N   Stale: N   Removed: N
```

---

## Scheduling (--cron modifier)

When `--cron <interval>` is provided alongside any mode flag, schedule recurring execution:

```
CronCreate(
  cron="<parsed from interval>",
  prompt="/worktree --<mode> --execute",
  recurring=true
)
```

Report the cron job ID for later cancellation via CronDelete.

---

## Integration Points

- **prune-worktrees.sh**: Used by `--prune` mode (no reimplementation)
- **close-out / begin-day**: Run `--audit` at day start; `--triage` weekly
- **autopilot**: `--audit` runs as Step 0 in close-out mode before merge-sweep
- **`/loop`**: Alternative scheduling: `/loop 7d /onex:worktree --triage --execute`
