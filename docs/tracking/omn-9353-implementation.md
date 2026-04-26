# OMN-9353 Implementation Notes

Linear: [OMN-9353](https://linear.app/omninode/issue/OMN-9353) — _Permanent fix:
auto-merge workflow handles merge method and stacked PR bases._

## Problem statement (verbatim from ticket)

OMN-9348 (shipped 2026-04-20) changed `gh pr merge --auto --merge` ->
`gh pr merge --auto --squash` in 10 repos' `.github/workflows/auto-merge.yml`.
That fixed the immediate symptom (branches with `required_linear_history=true`
rejected merge-commits from the queue) but not the root cause.

A stacked omnibase_infra PR (#1402) failed the required `Enable Auto-Merge`
check with:

```text
GraphQL: Pull request Protected branch rules not configured for this branch
(enablePullRequestAutoMerge)
```

Stacked PRs target feature branches; GitHub cannot enable auto-merge when the
base branch has no protected-branch auto-merge rules. The workflow should treat
stacked PR auto-merge enrollment as an expected no-op, not a failed required
check.

## Live verification (probed 2026-04-25)

| Check | Command | Result |
|---|---|---|
| omniclaude main protection | `gh api repos/OmniNode-ai/omniclaude/branches/main/protection` | `required_linear_history=false`, no merge-commit allowed |
| omniclaude merge queue method | GraphQL `repository.mergeQueue.configuration.mergeMethod` | `SQUASH` |
| omniclaude allow_merge_commit | `gh api repos/OmniNode-ai/omniclaude` | `false` |
| omniclaude allow_squash_merge | `gh api repos/OmniNode-ai/omniclaude` | `true` |

Conclusion: omniclaude is in the same regime as omnibase_infra was after
OMN-9547 — squash-only queue, but `enablePullRequestAutoMerge` reads the repo
default `merge_method` and may arm a PR as MERGE, which is silently dropped
from a SQUASH-only queue. Naming `--squash` removes the ambiguity.

## Diff summary

`.github/workflows/auto-merge.yml`:

1. Comment block updated to record OMN-9353.
2. New stacked-PR detection block in the `Resolve PR and author` step:
   * Reads `baseRefName` for the PR and `defaultBranchRef.name` for the repo.
   * If the two differ, sets `skip=true` (with `pr` and `actor` populated for
     log readability) and exits 0. The downstream `Enable auto-merge` step
     already gates on `skip != 'true'`, so the required check passes as a
     no-op.
3. `gh pr merge` invocation changed from `--auto` to `--auto --squash`.

The change matches the omnibase_infra implementation merged in PR #1402 / commit
`75ad3db0` (OMN-9547).

## Tests

`tests/workflows/test_auto_merge_workflow.py` — 5 tests:

* `test_stacked_pr_sets_skip_true` — base != default → `skip=true`.
* `test_default_branch_pr_sets_skip_false` — base == default → `skip=false`.
* `test_stacked_pr_short_circuit_for_non_jonah_actor` — stacked detection runs
  before the actor gate, so non-jonahgabriel stacked PRs also short-circuit.
* `test_merge_command_passes_squash_flag` — guards against `--squash` being
  removed (regression of OMN-9547 inside the omniclaude tree).
* `test_resolve_step_compares_base_to_default_branch` — guards against the
  detection block being deleted.

The first three tests extract the actual Bash from the workflow YAML, stub the
`gh` CLI on PATH so the script never reaches GitHub, and assert the contents
of `GITHUB_OUTPUT`. This keeps the test bound to the deployed logic — any
future edit to the YAML script will either pass the same assertions or fail
loudly.

```bash
$ uv run pytest tests/workflows/test_auto_merge_workflow.py -v
============================== 5 passed in 0.43s ==============================
```

## Out of scope (deliberate)

* The ticket's "Remaining Scope" section asks to audit/apply the same
  hardening to other repos that use the same template. That cross-repo sweep
  is a separate workstream — this PR only ships the omniclaude change so
  CodeRabbit / receipt-gate stays atomic.
* No changes to `auto-merge-stale-poller.yml`. The poller does not call
  `enablePullRequestAutoMerge` and therefore is not affected by either
  failure mode.
