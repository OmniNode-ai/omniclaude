# Integration Branch Helpers

## Purpose

Each epic gets a dedicated integration branch. Instead of PRs going directly to `main`,
they merge into the epic integration branch first. Only the integration branch merges to main.
This prevents individual PR ordering bugs and catches epic-level integration failures early.

## Branch Naming Convention

`epic/{epic_id}/integration`

Example: `epic/OMN-2600/integration`

## `create_integration_branch(epic_id, repo)` — Procedure

```bash
# Pull latest main
git -C /Volumes/PRO-G40/Code/omni_worktrees/{ticket}/{repo} pull origin main --ff-only  # local-path-ok

# Create integration branch from main
git -C /Volumes/PRO-G40/Code/omni_worktrees/{ticket}/{repo} checkout -b epic/{epic_id}/integration  # local-path-ok

# Push to origin
git -C /Volumes/PRO-G40/Code/omni_worktrees/{ticket}/{repo} push origin epic/{epic_id}/integration  # local-path-ok
```

This is called once per epic, not once per ticket.

## `merge_pr_into_integration(pr_number, repo, epic_id)` — Procedure

Import `@_lib/pr-safety/helpers.md` before calling any mutation.

1. Confirm PR is labeled `mergeable` (check labels via `gh pr view`)
2. Confirm PR is rebased on `epic/{epic_id}/integration`, not `main`
   - If not: use `mutate_pr(pr_key, action="rebase_for_integration", run_id=run_id, fn=...)` to update the base branch
3. Merge via `mutate_pr(pr_key, action="merge_into_integration", run_id=run_id, fn=...)`:
   - Inside `fn`: invoke the squash-merge subprocess command for the PR (use `@_lib/pr-safety/helpers.md` for the merge call)
4. Log merge to `$ONEX_STATE_DIR/epics/{epic_id}/integration_log.json`:
   ```json
   { "pr_number": 1234, "merged_at": "2026-02-28T00:00:00Z", "ticket_id": "OMN-XXXX" }
   ```

## `run_integration_tests(epic_id, repo)` — Procedure

```bash
cd /Volumes/PRO-G40/Code/omni_worktrees/{any_ticket}/{repo}  # local-path-ok
git checkout epic/{epic_id}/integration
git pull origin epic/{epic_id}/integration
uv run pytest tests/ -m "not slow" --tb=short -q 2>&1 | tee $ONEX_STATE_DIR/epics/{epic_id}/integration_test_results.txt
```

Return pass/fail + counts.

## `emit_integration_report(epic_id, test_results, prs_merged)` — Procedure

Write `$ONEX_STATE_DIR/epics/{epic_id}/integration_report.md`:

```markdown
# Epic Integration Report: {epic_id}

**Branch:** epic/{epic_id}/integration
**PRs Merged:** {count}
**Tests:** {pass_count} passed, {fail_count} failed

## PRs Included
{list each pr_number, ticket_id, title}

## Test Results
{paste test output summary}

## Recommendation
{"READY TO MERGE TO MAIN" or "BLOCKED — fix failures before merging to main"}
```

Post report summary to the epic Slack thread (LOW_RISK, no gate).

## Integration Into epic-team

Call `create_integration_branch` once at epic start (after decompose-epic if needed).
Call `merge_pr_into_integration` for each PR as it becomes `mergeable`.
Call `run_integration_tests` + `emit_integration_report` when all epic tickets have PRs merged.
