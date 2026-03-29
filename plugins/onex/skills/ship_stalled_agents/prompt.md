# Ship Stalled Agents — Execution Prompt

> **PR Safety**: This skill uses `@_lib/pr-safety/helpers.md` for all PR mutations.

You are executing the `ship_stalled_agents` skill. Follow these steps exactly.

## Step 1: Parse arguments <!-- ai-slop-ok: skill-step-heading -->

| Argument | Default | Description |
|----------|---------|-------------|
| `--dry-run` | false | Report only, no shipping actions |
| `--worktrees-root` | `/Volumes/PRO-G40/Code/omni_worktrees` | Root path to scan | <!-- local-path-ok -->

## Step 2: Scan worktrees <!-- ai-slop-ok: skill-step-heading -->

List all worktree directories under the worktrees root. Each ticket directory
(e.g., `OMN-1234/`) may contain one or more repo worktrees.

```bash
find ${worktrees_root} -maxdepth 2 -name ".git" -type f 2>/dev/null | while read gitfile; do
  worktree_dir=$(dirname "$gitfile")
  # Extract repo name from directory name
  # Extract branch from: git -C "$worktree_dir" branch --show-current
done
```

For each worktree, build a `ModelStallDetection` by running:

1. **Branch**: `git -C <path> branch --show-current`
2. **Staged changes**: `git -C <path> diff --cached --quiet` (exit 1 = has staged)
3. **Unstaged changes**: `git -C <path> diff --quiet` (exit 1 = has unstaged)
4. **Untracked files**: `git -C <path> ls-files --others --exclude-standard` (non-empty = has untracked)
5. **Unpushed commits**: `git -C <path> log --oneline @{u}..HEAD 2>/dev/null | wc -l`
6. **Has remote**: `git -C <path> config --get branch.<branch>.remote` (exit 0 = has remote)
7. **Has PR**: `gh pr list --repo OmniNode-ai/<repo> --head <branch> --state open --json number --jq length`

## Step 3: Filter stalled worktrees <!-- ai-slop-ok: skill-step-heading -->

A worktree needs shipping if ANY of:
- Has staged, unstaged, or untracked changes (uncommitted work)
- Has commits not pushed to remote (`commits_unpushed > 0`)
- Has been pushed but no PR exists

Skip worktrees on `main` or `master` branches.

If `--dry-run`, print the detection report and stop here.

## Step 4: Ship each stalled worktree <!-- ai-slop-ok: skill-step-heading -->

For each stalled worktree, apply escalating actions:

### 4a: Stage and commit (if uncommitted work exists)

```bash
cd <worktree_path>
git add -A
pre-commit run --all-files
```

**If pre-commit passes**:
```bash
git commit -m "chore: auto-ship stalled agent work [<ticket>]"
```

**If pre-commit fails**: Skip this worktree. Record `action_taken = RECOVERY_TICKET`.
Create a Linear ticket:
- Title: `[auto-ship recovery] <branch> — pre-commit failed`
- Description: Include the pre-commit error output and a `git diff --stat` summary
- Project: Active Sprint
- Priority: Normal

### 4b: Push (if unpushed commits exist)

Use the pr-safety mutation surface (`@_lib/pr-safety/helpers.md`) to push:

```
mutate_pr(pr_key, action="push_fix", run_id, fn=<push logic>, ...)
```

Record `action_taken = PUSHED`.

### 4c: Create PR (if pushed but no PR exists)

Create the PR via `gh pr create`, then enable auto-merge using the pr-safety
mutation surface (`@_lib/pr-safety/helpers.md`):

```
mutate_pr(pr_key, action="merge", run_id, fn=<enable auto-merge>, ...)
```

The PR should have:
- Title: `[auto-shipped] <branch>`
- Body: reference OMN-6868 and note it was auto-shipped from a stalled worktree

Record `action_taken = PR_CREATED` and capture the PR URL.

## Step 5: Report results <!-- ai-slop-ok: skill-step-heading -->

Print a summary table:

```
Ship Stalled Agents Report
==========================
Scanned:  12 worktrees
Shipped:   3
Failed:    1
No-op:     8

SHIPPED: /omni_worktrees/OMN-1234/omniclaude → PR #456
SHIPPED: /omni_worktrees/OMN-1235/omnibase_core → pushed (PR already exists)
SHIPPED: /omni_worktrees/OMN-1236/omnibase_infra → committed + pushed + PR #457
FAILED:  /omni_worktrees/OMN-1237/omniclaude → recovery ticket OMN-1238 (pre-commit failed)
```

## Safety Rules

- **Never force-push** or amend existing commits
- **Never ship work on main/master** branches
- **Always run pre-commit** before committing — if it fails, create recovery ticket
- **Tag auto-shipped PRs** with `[auto-shipped]` prefix in title
- **Never delete or reset** any worktree content
