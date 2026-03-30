# Worktree Health Sweep — Execution Prompt

## Step 0: Parse arguments <!-- ai-slop-ok: skill-step-heading -->

```python
# Pseudocode — the LLM reads arguments from skill invocation context
dry_run = args.dry_run == "true" if args.dry_run else False
worktrees_root = args.worktrees_root or "/Volumes/PRO-G40/Code/omni_worktrees"  # local-path-ok
omni_home = "/Volumes/PRO-G40/Code/omni_home"  # local-path-ok
stale_days = int(args.stale_days) if args.stale_days else 3
```

## Step 1: Discover worktrees <!-- ai-slop-ok: skill-step-heading -->

Scan all ticket directories under the worktrees root. Each ticket directory (e.g.
`OMN-1234/`) may contain one or more repo subdirectories (e.g. `omniclaude/`,
`omnibase_infra/`).

```bash
# List all ticket directories
ls -d ${worktrees_root}/*/

# For each ticket dir, find repo subdirectories that are git worktrees
# A valid worktree has a .git file (not directory) pointing to the parent repo
for ticket_dir in ${worktrees_root}/*/; do
  for repo_dir in ${ticket_dir}*/; do
    if [ -e "${repo_dir}/.git" ]; then
      echo "${repo_dir}"
    fi
  done
done
```

## Step 2: Audit each worktree <!-- ai-slop-ok: skill-step-heading -->

For each discovered worktree, collect:

```bash
# Current branch
git -C "${worktree_path}" branch --show-current

# Commits ahead of main (0 = branch is merged or at main)
git -C "${worktree_path}" fetch origin main --quiet 2>/dev/null
git -C "${worktree_path}" log --oneline origin/main..HEAD 2>/dev/null | wc -l

# Uncommitted changes (empty = clean)
git -C "${worktree_path}" status --porcelain

# Last commit date (ISO format)
git -C "${worktree_path}" log -1 --format=%aI 2>/dev/null
```

**Important**: Use `origin/main` not `main` for the merge check. The local `main` in
a worktree may be stale. Fetch first to ensure accuracy.

If `git fetch` fails (e.g. no network), fall back to local `main` ref and note the
degraded check in output.

## Step 3: Categorize <!-- ai-slop-ok: skill-step-heading -->

Apply classification rules in this order:

```python
# Pseudocode — classification logic
from datetime import datetime, timedelta, timezone

def classify(commits_ahead: int, has_uncommitted: bool, last_commit: datetime, has_open_pr: bool, stale_days: int) -> EnumWorktreeStatus:
    merged = commits_ahead == 0

    if merged and not has_uncommitted:
        return EnumWorktreeStatus.SAFE_TO_DELETE

    if merged and has_uncommitted:
        return EnumWorktreeStatus.LOST_WORK

    # Not merged from here
    stale_cutoff = datetime.now(tz=timezone.utc) - timedelta(days=stale_days)

    if not has_uncommitted and last_commit < stale_cutoff and not has_open_pr:
        return EnumWorktreeStatus.STALE

    if has_uncommitted:
        return EnumWorktreeStatus.DIRTY_ACTIVE

    return EnumWorktreeStatus.ACTIVE
```

### PR check for stale detection

To determine whether a branch has an open PR, use:

```bash
gh pr list --head "${branch_name}" --state open --json number --jq 'length'
```

A result of `0` means no open PR. Only run this check for branches that would
otherwise be classified as STALE (not merged, clean, old). Skip the PR check
for branches that are clearly ACTIVE or DIRTY_ACTIVE to avoid unnecessary API calls.

## Step 4: Execute actions <!-- ai-slop-ok: skill-step-heading -->

### SAFE_TO_DELETE: auto-remove

```bash
# Remove the worktree via the parent bare clone
repo_name=$(basename "${worktree_path}")
git -C "${omni_home}/${repo_name}" worktree remove "${worktree_path}" --force

# Clean up empty parent directory
ticket_dir=$(dirname "${worktree_path}")
rmdir "${ticket_dir}" 2>/dev/null  # Only removes if empty
```

In `--dry_run` mode, print what would be removed but do not execute.

### LOST_WORK: create recovery ticket

For each LOST_WORK worktree, create a Linear ticket:

```python
# Pseudocode — executed via mcp__linear-server__save_issue
diff_stat = bash(f"git -C {worktree_path} diff --stat")
untracked = bash(f"git -C {worktree_path} ls-files --others --exclude-standard")

mcp__linear-server__save_issue(
    title=f"recover: uncommitted work in {ticket_id}/{repo_name}",
    team="Omninode",
    project="Active Sprint",
    priority=2,  # High
    description=f"""## Lost Work Recovery

**Worktree**: `{worktree_path}`
**Branch**: `{branch_name}`
**Status**: Branch merged to main but worktree has uncommitted changes.

### Changes (git diff --stat)
```
{diff_stat}
```

### Untracked files
```
{untracked}
```

### Recovery steps
1. `cd {worktree_path}`
2. Review uncommitted changes: `git diff`
3. If valuable, stash and apply to a new branch: `git stash && git checkout -b recover/{ticket_id} && git stash pop`
4. If not needed, clean up: `git -C {omni_home}/{repo_name} worktree remove {worktree_path} --force`

### Definition of Done
- [ ] Uncommitted work reviewed
- [ ] Valuable changes recovered or confirmed not needed
- [ ] Worktree removed after recovery
""",
)
```

In `--dry_run` mode, print the diff stat but do not create tickets.

### STALE / DIRTY_ACTIVE: flag for review

Print a warning table but take no automated action:

```
WARNING: The following worktrees need manual review:

| Path | Branch | Status | Last Commit | Notes |
|------|--------|--------|-------------|-------|
| /omni_worktrees/OMN-1234/omniclaude | jonah/omn-1234-feat | STALE | 2026-03-20 | No open PR, 8 days old |
| /omni_worktrees/OMN-1235/omnibase_infra | jonah/omn-1235-fix | DIRTY_ACTIVE | 2026-03-27 | 3 files modified |
```

### ACTIVE: leave alone

No action. Include in summary counts only.

## Step 5: Emit completion event <!-- ai-slop-ok: skill-step-heading -->

After all worktrees are processed, emit a structured event:

```python
# Pseudocode — use cli_emit or event emission hook
event = {
    "type": "worktree.sweep.completed",
    "counts": {
        "safe_to_delete": n,
        "lost_work": n,
        "stale": n,
        "active": n,
        "dirty_active": n,
    },
    "cleaned": cleaned_count,
    "tickets_created": tickets_created_count,
    "dry_run": dry_run,
}
```

Use the `cli_emit` helper if available, otherwise log the event as structured JSON output.

## Step 6: Print summary report <!-- ai-slop-ok: skill-step-heading -->

```
============================================================
Worktree Health Sweep Summary
============================================================

Worktrees root: /Volumes/PRO-G40/Code/omni_worktrees <!-- local-path-ok -->
Total worktrees audited: 45
Stale threshold: 3 days

| Status         | Count | Action Taken          |
|----------------|-------|-----------------------|
| SAFE_TO_DELETE | 12    | Removed (auto)        |
| LOST_WORK      | 3     | Ticket created        |
| STALE          | 5     | Flagged for review    |
| ACTIVE         | 20    | None                  |
| DIRTY_ACTIVE   | 5     | Flagged for review    |

Cleaned: 12 worktrees removed
Tickets created: 3
Empty directories cleaned: 8
```

## Error Handling

- If a worktree's `.git` pointer is broken (dangling reference), skip it and log a warning.
- If `git worktree remove` fails, log the error and continue with remaining worktrees.
- If Linear ticket creation fails, log the error and continue. Do not block cleanup on ticket failures.
- If `gh pr list` rate-limits, batch PR checks and add brief pauses between batches.
