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
boundary_exempt: true
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
  - name: --auto-prune
    description: "Ticket-close-keyed prune: remove worktrees whose TICKET closed and whose tree is provably safe, triage-report everything else (wraps scripts/worktree_auto_prune.py)"
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
    description: "Override worktrees root path (default: $ONEX_WORKTREES_ROOT)"
    required: false
---

# Worktree Manager

## Dispatch Surface

**Target**: Agent Teams

---

## Purpose

Unified worktree management skill. Consolidates health auditing, classification triage, and
lifecycle garbage collection into a single entry point with four mode flags and one modifier:

| Flag | Former Skill | Description |
|------|-------------|-------------|
| `--audit` | `worktree_sweep` | Health audit: SAFE_TO_DELETE, LOST_WORK, STALE, ACTIVE, DIRTY_ACTIVE |
| `--triage` | `worktree_triage` | Classify ship_it/archive/prune, auto-PR ship_it, remove prune targets |
| `--prune` | `worktree_lifecycle` | GC merged worktrees via prune-worktrees.sh |
| `--auto-prune` | (new) | Ticket-close-keyed prune via worktree_auto_prune.py |
| `--cron` | (shared) | Schedule recurring execution of whichever mode is active |

Exactly one of `--audit`, `--triage`, `--prune`, or `--auto-prune` must be specified per
invocation. `--cron` is an additive modifier that schedules the chosen mode.

`--prune` and `--auto-prune` key on **different things and disagree on purpose**: `--prune` is
merge-keyed (a PR merged, or the remote branch vanished), `--auto-prune` is ticket-keyed (the
owning ticket closed). See [Mode: --auto-prune](#mode---auto-prune-ticket-close-keyed) for why
the merge-keyed predicate alone is unsafe.

**Announce at start:** "I'm using the worktree skill to [audit/triage/prune/auto-prune] worktrees."

---

## Runtime Model

This skill is implemented as prompt-driven orchestration, not executable Python.
Python blocks in this document are pseudocode specifying logic and data shape, not
callable runtime helpers. The LLM executes the equivalent logic through Bash, Grep,
Git, and GitHub CLI tool calls, holding intermediate state in its working context.

**Honest node-backing state**: none of `--audit`, `--triage`, or `--prune` is backed by an
executable ONEX node today. There is no `worktree*` entry in
`omnibase_infra/src/omnibase_infra/cli/skill_mapping.yaml` — this skill is prompt-driven
end-to-end, not node-dispatched. A candidate backing node for the `--prune` op,
`node_pr_lifecycle_worktree_prune_effect` (omnimarket), had its contract routing fixed in
<TICKET>, but it is **not wired to this skill**. Wiring it is tracked as follow-up work,
out of scope here — do not treat `--prune` as node-backed until that wiring lands and this
section is updated.

The typed models live in `src/omniclaude/hooks/worktree_sweep.py` and define the
report schema: `EnumWorktreeStatus`, `ModelWorktreeEntry`, `ModelWorktreeSweepReport`.

The durability-sweep helpers (<TICKET>) are pure, no-I/O functions in
`src/omniclaude/hooks/lib/worktree_health.py`: `extract_ticket_id`,
`is_no_ticket_worktree`, `plan_referenced_dirty_files`, `build_rescue_ref`,
`offvolume_backup_satisfied`, and the `ModelWorktreeDurabilityFlags` model. The
LLM drives the git/`gh` side effects; these helpers compute the flags.

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

/worktree --auto-prune                    # dry-run: classify by ticket closure + tree safety
/worktree --auto-prune --execute          # remove the proven-safe set, triage-report the rest

/worktree --audit --cron 3d               # schedule daily audit
/worktree --triage --cron 7d              # schedule weekly triage
/worktree --prune --cron 2h               # schedule GC every 2 hours
/worktree --auto-prune --cron 1d          # schedule the ticket-keyed sweep daily
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
elif args.auto_prune:
    mode = "auto_prune"
else:
    raise ValueError("One of --audit, --triage, --prune, or --auto-prune is required.")

execute = bool(args.execute)
dry_run = not execute
cron_interval = args.cron  # e.g. "7d", "2h", or None
worktrees_root = args.worktrees_root or os.path.join(os.environ["OMNI_HOME"], "omni_worktrees")
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

# Resolve the repo's actual integration branch — do NOT hardcode main or dev.
# Prefer the remote's default branch; fall back to origin/dev (every OmniNode
# repo's integration branch is dev, not main).
integration_branch=$(git -C "${worktree_path}" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
integration_branch="${integration_branch:-dev}"

git -C "${worktree_path}" fetch origin "${integration_branch}" --quiet 2>/dev/null
git -C "${worktree_path}" log --oneline "origin/${integration_branch}..HEAD" 2>/dev/null | wc -l
git -C "${worktree_path}" status --porcelain
git -C "${worktree_path}" log -1 --format=%aI 2>/dev/null
```

**Important**: Diff against the repo's actual integration branch (`origin/${integration_branch}`,
resolved dynamically above — falls back to `origin/dev`), never a hardcoded `origin/main` or
bare `main`. Every OmniNode repo's integration branch is `dev`; diffing against `origin/main`
produces meaningless ahead-counts in the hundreds/thousands and misclassifies merged worktrees
as STALE or DIRTY_ACTIVE instead of SAFE_TO_DELETE.

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
git -C "${WORKSPACE_ROOT}/${repo_name}" worktree remove "${worktree_path}" --force
ticket_dir=$(dirname "${worktree_path}")
rmdir "${ticket_dir}" 2>/dev/null
```

**LOST_WORK — create recovery ticket via `tracker.save_issue`:**
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

### Step 6: Durability sweep (<TICKET>) <!-- ai-slop-ok: skill-step-heading -->

Layered on top of the health classification above, the durability sweep flags
worktrees at risk of stranding or losing work. Backed by the pure helpers in
`src/omniclaude/hooks/lib/worktree_health.py` (`extract_ticket_id`,
`is_no_ticket_worktree`, `plan_referenced_dirty_files`, `build_rescue_ref`,
`offvolume_backup_satisfied`) and `ModelWorktreeDurabilityFlags`. Run these
checks for every worktree discovered in Step 1.

#### 6a. NO-TICKET detection

A worktree whose **directory name contains no `OMN-XXXX` identifier** is flagged
`NO-TICKET`. These are off-ledger and cannot be reconciled against Linear, so
their work is invisible to triage. Per Operating Rule 9, every piece of code work
must live under `$ONEX_WORKTREES_ROOT/<ticket>/<repo>/`.

```python
# Pseudocode — LLM resolves from the discovered worktree path
ticket_id = extract_ticket_id(worktree_path)   # regex OMN-\d+, case-insensitive
is_no_ticket = ticket_id is None               # → flag NO-TICKET
```

Action: flag for review. If the worktree is also dirty, treat it as LOST_WORK-class
risk and create a recovery ticket so the work is reattached to the ledger.

#### 6b. Dirty plan/handoff-referenced file detection

A **dirty** worktree (unstaged/uncommitted changes) is escalated when any of those
changed files is **referenced by a `docs/plans/` or `docs/handoffs/` document**.
Losing such a worktree would strand work that an active plan or handoff depends on.

```bash
# Files with unstaged/uncommitted changes in the worktree:
git -C "${worktree_path}" status --porcelain | awk '{print $2}'

# Files referenced by any plan/handoff doc (path-like tokens):
grep -rhoE '[A-Za-z0-9_./-]+\.(py|ts|tsx|md|yaml|yml|json|sh)' \
  docs/plans/ docs/handoffs/ | sort -u
```

```python
# Pseudocode — intersect the two sets
dirty_plan_files = plan_referenced_dirty_files(changed_files, plan_referenced_files)
is_dirty_plan_worktree = bool(dirty_plan_files)   # → escalate, do not silently prune
```

Action: flag with the offending file list. A `DIRTY_ACTIVE` worktree that also
touches plan/handoff-referenced files must NOT be auto-pruned.

#### 6c. Rescue-ref auto-creation on handoff-block

Before the skill **blocks** a worktree removal/handoff because of dirty
plan/handoff-referenced state (6b), it MUST first mint a recoverable rescue ref so
the work survives even if the worktree is later pruned. Run `git stash create`
(produces a dangling commit without touching the working tree) and tag it
`rescue/<ticket>/<timestamp>` **before** raising the block:

```bash
ts="$(date -u +%Y%m%dT%H%M%SZ)"
stash_commit="$(git -C "${worktree_path}" stash create "durability-rescue ${ticket}")"
if [ -n "${stash_commit}" ]; then
  # rescue_ref == build_rescue_ref(ticket, ts) == rescue/<ticket>/<timestamp>
  git -C "${worktree_path}" tag -f "rescue/${ticket}/${ts}" "${stash_commit}"
fi
# Only AFTER the rescue ref exists, block the handoff and report rescue_ref.
```

For a NO-TICKET worktree, substitute the `NO-TICKET` sentinel for `<ticket>` in the
rescue ref. Record `rescue_ref` on the `ModelWorktreeDurabilityFlags` entry.

#### 6d. Off-volume backup requirement (DoD)

A demo-critical fix saved only as a local `.onex_state` backup does **not** count
toward Definition of Done — the work volume is a single point of failure. The fix
must also have an **off-volume copy**: either a Linear ticket attachment or a
committed docs-branch artifact.

```python
# Pseudocode — only off-volume copies satisfy DoD
offvolume_backup_ok = offvolume_backup_satisfied(
    has_ticket_attachment=...,    # fix attached to its Linear ticket
    has_docs_branch_commit=...,   # fix committed on a docs branch
)
# A bare .onex_state backup with neither → offvolume_backup_ok is False → NOT done.
```

Action: when `offvolume_backup_ok` is `False`, the backup is reported as incomplete
and the worktree is not eligible for cleanup until an off-volume copy exists.

#### Durability summary

```
Durability Sweep Summary
| Flag              | Count | Action                         |
| NO-TICKET         | N     | Flagged (recovery if dirty)    |
| DIRTY-PLAN-FILE   | N     | Escalated, prune blocked       |
| RESCUE-REF minted | N     | rescue/<ticket>/<timestamp>    |
| OFF-VOLUME missing| N     | Backup incomplete, not Done    |
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

**ship_it:** Check for existing PR, then stage uncommitted changes, push, and create PR
against the repo's actual integration branch (resolve dynamically as in Step 2 of
`--audit` mode; do not hardcode `main` — every OmniNode repo integrates via `dev`):
```bash
integration_branch=$(git -C "$REPO_SLUG" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
integration_branch="${integration_branch:-dev}"

gh pr create --repo "$REPO_SLUG" --head "$BRANCH" --base "$integration_branch" \
  --title "chore: ship stale worktree $BRANCH" \
  --body "Auto-created by worktree skill (--triage)."
```

**archive:** No action. Logged for manual review.

### Report <!-- ai-slop-ok: skill-step-heading -->

Write to `docs/tracking/YYYY-MM-DD-worktree-triage.md` in the canonical registry.
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

## Mode: --auto-prune (ticket-close keyed)

Removes worktrees whose **ticket has closed** and whose tree is provably safe, and emits a
triage row for every worktree that is not prunable. Wraps `scripts/worktree_auto_prune.py`
(no reimplementation), whose predicate lives as a pure function in
`src/omniclaude/hooks/lib/worktree_prune_policy.py`.

**Why this exists next to `--prune`.** `--prune` keys on a PR merging. That predicate is
anti-correlated with liveness: clean + pushed + merged is exactly the state a
live lane occupies between push and post-merge verification, and a measured dry run over 192
worktrees found its only two deletions were both live-claimed. Pruning is keyed to the
**ticket closing** instead — a ticket spans multiple PRs and OCC companions and worktrees are
keyed by ticket directory, so a merged PR is an *input to the safety check* (it is what makes
the tree-diff against `dev` empty) while ticket completion is what *fires* eligibility.

Two parts, evaluated in order — eligibility fires, safety gates:

1. **Eligibility** — the ticket directory resolves to a ticket in `Done`/`Canceled`, or (only
   when that state is unresolvable) the work ledger shows a `TERMINAL` row with no newer open
   `CLAIM`. An open / In Progress ticket is **never** eligible, however clean the tree.
2. **Safety** — clean tree, nothing unmerged ahead of `origin/dev` (a squash-merged branch
   with an empty tree-diff counts as merged), no stash attributable to the branch.

Everything else is a triage row — never a deletion.

### Step 1: Run worktree_auto_prune.py <!-- ai-slop-ok: skill-step-heading -->

```bash
# REPORT_DIR is the workspace tracking-docs directory; resolve it from the caller,
# never from a machine-specific literal.
REPORT_DIR="${REPORT_DIR:?set REPORT_DIR to the tracking docs directory}"

uv run python scripts/worktree_auto_prune.py ${execute_flag} ${root_flag} \
  --report-md "$REPORT_DIR/$(date +%F)-worktree-prune.md" \
  --report-json "$REPORT_DIR/$(date +%F)-worktree-prune.json"
```

Dry run is the default. The script refuses to run at all when the work ledger is unreadable
(exit 2) — a prune with no claim-awareness is the whole hazard this mode exists to avoid, so
that is a hard stop, not a degraded mode. Removal uses plain `git worktree remove`, never `--force`.

### Step 2: Report results <!-- ai-slop-ok: skill-step-heading -->

```
Scanned: N   Safe: N   Triage: N   Removed: N
```

Never hand-delete a worktree the classifier put in triage. If you disagree with it, record the
disagreement — the classifier wins.

**Scheduled form.** The daily backstop runner is the committed named workflow
`.claude/workflows/morning-worktree-prune.js` in the workspace registry root; its format
contract is `docs/workflows/morning-worktree-prune/README.md` there. That workflow, not this skill, is
the surface the morning session arms.

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
- **worktree_auto_prune.py**: Used by `--auto-prune` mode (no reimplementation); its predicate
  is the pure `worktree_prune_policy.classify_worktree_prune`, which a future ticket-closed
  event hook calls directly — the daily sweep is the backstop, not the design
- **close-out / begin-day**: Run `--audit` at day start; `--triage` weekly
- **autopilot**: `--audit` runs as Step 0 in close-out mode before merge-sweep
- **`/loop`**: Alternative scheduling: `/loop 7d /onex:worktree --triage --execute`
