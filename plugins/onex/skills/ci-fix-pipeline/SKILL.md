---
name: ci-fix-pipeline
description: Use when CI is failing on a PR or branch and you want to automatically analyze, fix, local-review, and confirm release readiness in a single unattended pipeline — chains ci-failures, fix dispatch, local-review, and pr-release-ready with explicit policy switches governing all auto-advance decisions
version: 1.0.0
category: workflow
tags:
  - pipeline
  - automation
  - ci
  - github-actions
  - fix
  - review
author: OmniClaude Team
args:
  - name: pr_number_or_branch
    description: PR number (e.g., 42) or branch name (e.g., jonahgabriel/omn-1234-fix)
    required: true
  - name: --dry-run
    description: Analyze and pre-flight only; no commits or fixes applied
    required: false
  - name: --max-fix-files
    description: Override scope threshold (default 10); failures touching more files create a ticket instead
    required: false
  - name: --skip-to
    description: Resume from a specific phase (analyze|fix|local_review|release_ready)
    required: false
---

# CI Fix Pipeline

## Overview

Autonomous pipeline that chains CI failure analysis, targeted fixes, local review, and release readiness into a single unattended workflow. Policy switches — not agent judgment — govern all auto-advance decisions.

**Announce at start:** "I'm using the ci-fix-pipeline skill to autonomously fix CI failures for {pr_number_or_branch}."

## Quick Start

```
/ci-fix-pipeline 42
/ci-fix-pipeline jonahgabriel/omn-1234-my-branch
/ci-fix-pipeline 42 --dry-run
/ci-fix-pipeline 42 --skip-to fix
/ci-fix-pipeline 42 --max-fix-files 5
```

## Pipeline Flow

```
analyze → fix_each_failure → local_review → release_ready
```

### Phase 1: analyze

Invokes the `ci-failures` skill to fetch all GitHub Actions failures for the target PR or branch. Classifies each failure by:
- **Scope**: small (≤`max_fix_files` files, single repo, no contract/node-wiring/infrastructure touches) vs large
- **Cause**: compilation error, test failure, lint violation, type check failure, timeout, infrastructure, no-verify bypass

Large-scope classification triggers ticket creation rather than an in-place fix. Ticket creation happens inside Phase 2 (`fix_each_failure`) — large-scope failures exit the fix path early and dispatch a `create-ticket` agent instead. Readers of the pipeline flow should understand that `fix_each_failure` covers both paths: small-scope → fix, large-scope → defer to ticket.

AUTO-ADVANCE to Phase 2.

### Phase 2: fix_each_failure

For each classified failure:
- **Small scope** → dispatches fix to a polymorphic agent (Polly), mirroring exact CI commands from `.github/workflows/ci.yml`
- **Large scope** → dispatches `create-ticket` to Polly with full context; marks failure as deferred

If `--dry-run` is set: logs all decisions, skips commits.

AUTO-ADVANCE to Phase 3 **only if** all dispatched agents returned `fixed`, `skipped`, or `success` (large-scope ticket created). STOP if any agent returned `preflight_failed` or `failed`.

### Phase 3: local_review

Invokes the `local-review` skill. Requires **0 blocking issues** (no Critical, Major, or Minor) to advance to Phase 4. Nits are optional.

AUTO-ADVANCE to Phase 4 only if local review passes clean.

### Phase 4: release_ready

Invokes the `pr-release-ready` skill to confirm the PR is fully ready for merge.

Pipeline STOPS. Manual merge required.

## Arguments

Parse arguments from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `pr_number_or_branch` | required | PR number (e.g., 42) or branch name (e.g., jonahgabriel/omn-1234-fix) |
| `--dry-run` | false | Analyze and pre-flight only; no commits or fixes applied |
| `--max-fix-files <n>` | 10 | Override scope threshold; failures touching more files create a ticket instead |
| `--skip-to <phase>` | none | Resume from a specific phase: `analyze`, `fix`, `local_review`, or `release_ready` |

### `--skip-to` handling

When `--skip-to` is provided, skip all earlier phases and begin execution at the named phase:

- `--skip-to analyze` — start at Phase 1 (same as default)
- `--skip-to fix` — re-run Phase 1 silently to gather failure classification data, then proceed directly to Phase 2 without pausing for orchestrator review. Phase 1 is not skipped; the skip means the orchestrator does not stop between Phase 1 and Phase 2 even if it would otherwise wait for confirmation. If the caller provides pre-classified failure context in the prompt, the orchestrator may use that in place of a fresh Phase 1 run.
- `--skip-to local_review` — skip Phases 1 and 2; go directly to Phase 3
- `--skip-to release_ready` — skip Phases 1–3; go directly to Phase 4

If `--skip-to` names an unknown phase, STOP and report: `Error: unknown phase '{value}'. Valid values: analyze, fix, local_review, release_ready`

**Note:** When skipping Phase 1, the orchestrator has no failure classification data. The agent must infer context from git log or a prior run. If context is insufficient to execute the target phase, STOP and report.

## Pipeline Policy

All auto-advance behavior is governed by explicit policy switches, not agent judgment:

| Switch | Default | Description |
|--------|---------|-------------|
| `fix_all_severities` | `true` | Fix CRITICAL, MAJOR, and MINOR automatically; only Nits are optional |
| `infrastructure_always_fix` | `true` | Infrastructure failures always attempt an automated fix |
| `max_fix_files` | `10` | Failures touching more than this many files trigger ticket creation instead of a direct fix |
| `no_verify_detection` | `true` | Detect `--no-verify` bypass in commit history; flag as CRITICAL and fix the underlying cause |
| `ci_env_reproduce` | `true` | Mirror CI commands exactly by reading `.github/workflows/*.yml` |

**Large-scope definition** — any of the following triggers large-scope classification:
- More than `max_fix_files` files changed
- Changes span multiple repository roots
- Touches `contract.yaml`, node wiring files, or shared infrastructure
- Fix requires an architectural decision

## Safety Rules (Non-Negotiable)

These rules are enforced unconditionally, regardless of any flag or argument:

1. **NEVER push to main, master, or any protected branch.**
2. **NEVER force push (`git push --force` or `git push --force-with-lease`).**
3. **NEVER run destructive git commands:** `git reset --hard`, `git clean -f`, `git checkout .`, `git restore .`
4. **Pre-flight check**: run `git status` before any changes. If there are unrelated uncommitted changes, STOP and report — do not proceed.
5. **Authentication check**: run `gh auth status` before Phase 2. If not authenticated, STOP and report.
6. **Correlation tagging**: every commit must include `[corr:{correlation_id}]` in the commit message. Before starting, check git log for existing `[corr:{correlation_id}]` commits to detect re-runs and avoid duplicate work.
7. **Branch guard**: if currently on main or master, create a new branch before making any changes.
8. **Dry-run isolation**: `--dry-run` must produce zero side effects — no commits, no pushes, no ticket creation, no Linear status changes.

## Dispatch Contracts (Execution-Critical)

**This section governs how you execute the pipeline. Follow it exactly.**

You are an orchestrator. You coordinate phase transitions, pre-flight checks, policy enforcement, and result aggregation.
You do NOT analyze, fix, or review code yourself. All heavy work runs in separate agents (Polly) via `Task()`.

**Rule: The orchestrator MUST NEVER call Edit(), Write(), or Bash(code-modifying commands) directly.**
If code changes are needed, dispatch a polymorphic agent. If you find yourself wanting to make an edit, that is the signal to dispatch instead.

**Correlation ID**: Before dispatching any phase, generate a `correlation_id` using the format `ci-fix-{pr_number_or_branch}-{short_timestamp}` where `short_timestamp` includes seconds (e.g., `ci-fix-42-20260221T103045`). Use seconds resolution so that re-runs within the same minute produce distinct IDs and do not trigger the idempotency check (`grep [corr:{correlation_id}]`) prematurely. Use this same ID for all commits and dispatches within one pipeline run. Pass it as a literal string in all dispatch prompts — do not use a placeholder.

---

### Phase 1: analyze — dispatch to polymorphic agent

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="ci-fix-pipeline: Phase 1 analyze CI failures for {pr_number_or_branch}",
  prompt="You are analyzing CI failures for PR/branch: {pr_number_or_branch}.

    Fetch CI failures by running the following bash commands directly:

    If {pr_number_or_branch} is a PR number:
      First resolve the PR number to its head branch:
        Run: gh pr view {pr_number_or_branch} --json headRefName --jq '.headRefName'
        This returns the head branch name (e.g., jonahgabriel/omn-1234-fix). Call it {headBranch}.
      Then list runs filtered to that branch:
        Run: gh run list --branch {headBranch} --json databaseId,status,conclusion,headBranch --limit 10
      Then for each failed run: gh run view <run_id> --log-failed

    If {pr_number_or_branch} is a branch name:
      Run: gh run list --branch {pr_number_or_branch} --json databaseId,status,conclusion --limit 10
      Then for each failed run: gh run view <run_id> --log-failed

    Also run: gh run list --json databaseId,headBranch,status,conclusion,name --limit 20
    to list all recent runs and identify those for this PR/branch.

    Collect all job failure output, step names, and error messages from the logs.

    After collecting failures, classify each one with:
    - severity: CRITICAL | MAJOR | MINOR | NIT
    - scope: small | large
    - cause: one of (compilation_error | test_failure | lint_violation | type_check |
        timeout | infrastructure | no_verify_bypass | other)
    - files_affected: list of files that would need to change
    - large_scope_reason: (if large) which large-scope rule triggered

    Large-scope rules (any one triggers large scope):
    - files_affected count > {max_fix_files} (default 10)
    - changes span multiple repository roots
    - touches contract.yaml, node wiring files, or shared infrastructure
    - fix requires an architectural decision

    Also check: does git log contain '--no-verify' in any recent commit?
    If yes, classify as CRITICAL no_verify_bypass regardless of other failures.

    RESULT:
    status: success | partial | failed
    output: |
      Structured list of classified failures:
      [
        {
          severity: CRITICAL|MAJOR|MINOR|NIT,
          scope: small|large,
          cause: <cause>,
          job_name: <CI job name>,
          step_name: <CI step name>,
          error_summary: <one-line description>,
          files_affected: [<file paths>],
          large_scope_reason: <reason if large, else null>,
          suggested_fix: <brief fix description>
        },
        ...
      ]
      total_failures: <N>
      small_scope_count: <N>
      large_scope_count: <N>
    error: <error message if status is failed, else null>"
)
```

**Orchestrator action after Phase 1:**
- If `status: failed`, STOP and report the error.
- If `total_failures: 0`, log "No CI failures found — pipeline complete." and STOP.
- If `--dry-run`, log the classified failure list and STOP (do not advance).
- Otherwise, AUTO-ADVANCE to Phase 2.

---

### Phase 2: fix_each_failure — dispatch to polymorphic agent (one per small-scope failure)

For each **small-scope** failure, dispatch one Polly. For each **large-scope** failure, dispatch one Polly with `create-ticket` invocation.

**Small-scope fix dispatch:**

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="ci-fix-pipeline: Phase 2 fix {cause} failure in {job_name}/{step_name}",
  prompt="You are fixing a CI failure for PR/branch: {pr_number_or_branch}.

    Pre-flight (MANDATORY before any changes):
    1. Run: git status
       - If unrelated uncommitted changes exist: STOP, do not proceed, report in RESULT.
    2. Run: gh auth status
       - If not authenticated: STOP, do not proceed, report in RESULT.
    3. Run: git log --oneline -20 | grep -F "[corr:{correlation_id}]"
       - If corr commits already exist for this failure: log 'already fixed' and STOP (idempotent).
    4. If on main or master: create a new branch before any changes.

    Failure to fix:
    - Job: {job_name}
    - Step: {step_name}
    - Severity: {severity}
    - Cause: {cause}
    - Error: {error_summary}
    - Files likely affected: {files_affected}

    CI reproduction rule: Read .github/workflows/ci.yml and mirror the EXACT command used
    in this job/step. Run it locally to confirm the fix works before committing.

    Fix the failure. Then run the mirrored CI command to confirm it passes.

    If fix requires more than {max_fix_files} files: STOP, do not commit, report as large-scope
    in RESULT so the orchestrator can create a ticket instead.

    After confirming the fix passes locally:
    - Commit with message: 'fix({cause}): {error_summary} [corr:{correlation_id}]'
    - NEVER use --no-verify when committing.
    - If a pre-commit hook fails: fix the hook failure first, then commit again.

    RESULT:
    status: fixed | skipped | large_scope | preflight_failed | failed
    output: |
      What was done (files changed, commands run, test output confirming fix)
    error: <error message if status is failed or preflight_failed, else null>"
)
```

**Large-scope ticket dispatch:**

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="ci-fix-pipeline: Phase 2 create ticket for large-scope {cause} failure in {job_name}",
  prompt="You are creating a Linear ticket for a CI failure that is too large to fix automatically.

    Use the mcp__linear__create_issue tool directly with these exact field values:

    title: 'CI fix ({job_name}): {error_summary}'
    team: (look up the correct team ID for this repository using mcp__linear__list_teams)
    description: |
      ## CI Failure — Large-Scope Deferral

      **PR/Branch**: {pr_number_or_branch}
      **Job**: {job_name}
      **Step**: {step_name}
      **Severity**: {severity}
      **Cause**: {cause}
      **Correlation ID**: {correlation_id}

      ## Error Details

      {error_summary}

      ## Why Large-Scope

      {large_scope_reason}

      ## Files Affected

      {files_affected}

      ## Next Steps

      Manual investigation and fix required. This failure was deferred by the ci-fix-pipeline
      because it exceeded the automated fix scope threshold.
    priority: (map severity → priority: CRITICAL=1, MAJOR=2, MINOR=3, NIT=4)
    labels: ['ci-failure', 'large-scope']

    After creating the ticket, report its ID and URL.

    RESULT:
    status: success | failed
    output: |
      Linear ticket ID and URL created for this failure
    error: <error message if status is failed, else null>"
)
```

**Orchestrator action after Phase 2:**
- Collect all RESULT blocks from dispatched agents.
- If any `preflight_failed`: STOP and report — do not proceed to Phase 3.
- If all failures are `fixed`, `skipped`, or `success` (large-scope → ticket created): AUTO-ADVANCE to Phase 3.
- If any `failed` (not preflight): STOP, set status=`fix_partially_failed`, and report clearly which failures were not resolved. Do NOT advance to Phase 3. Manual intervention is required before resuming the pipeline.

---

### Phase 3: local_review — dispatch to polymorphic agent

Before dispatching Phase 3, determine the base branch:
- If `{pr_number_or_branch}` is a PR number: run `gh pr view {pr_number_or_branch} --json baseRefName --jq '.baseRefName'` to get the base branch (e.g., `main`, `develop`). Use `origin/{base_branch}` as the `--since` argument.
- If `{pr_number_or_branch}` is a branch name: default to `origin/main` as the `--since` argument.

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="ci-fix-pipeline: Phase 3 local-review after CI fixes",
  prompt="You are running local review after CI fixes were applied to PR/branch: {pr_number_or_branch}.
    Invoke: Skill(skill=\"onex:local-review\", args=\"--since {base_branch_ref}\")

    {base_branch_ref} is the resolved base branch reference (e.g., origin/main or origin/develop),
    determined by the orchestrator before this dispatch.

    The local-review skill is itself an orchestrator that handles dispatching review and fix agents.
    Your role here is only to invoke it and return its result to the ci-fix-pipeline orchestrator.
    Do NOT attempt to fix issues or re-run local-review yourself; return the result as-is.

    Requirements for pass:
    - 0 blocking issues (no Critical, Major, or Minor)
    - Nits are optional

    RESULT:
    status: passed | failed
    output: |
      Blocking issues found: <count>
      Issue descriptions: [<list>]
      Final state: clean | issues_remain
    error: <error message if status is failed, else null>"
)
```

**Orchestrator action after Phase 3:**
- If `status: passed` and `blocking issues found: 0`: AUTO-ADVANCE to Phase 4.
- If `status: failed`: STOP and report — local review did not pass. Manual fix and re-run of Phase 3 is required.
- If `status: passed` but `blocking issues found > 0`: STOP and report — review reported pass but issues remain (contradiction; investigate).

---

### Phase 4: release_ready — dispatch to polymorphic agent

Before dispatching Phase 4, resolve `{pr_number_or_branch}` to a PR number using the following steps:

```
# Variable capture — run this before dispatching Phase 4
if {pr_number_or_branch} is numeric:
    resolved_pr_number = {pr_number_or_branch}
else:
    # Run: gh pr view --head {pr_number_or_branch} --json number --jq '.number'
    # Extract the `.number` field from the JSON output (an integer).
    # Assign it to resolved_pr_number.
    # Example: gh pr view --head jonahgabriel/omn-1234-fix --json number --jq '.number'
    #          → 42
    #          resolved_pr_number = 42
    # If the command returns empty output or an error: STOP and report —
    # pr-release-ready requires a PR number to operate.
```

Pass `resolved_pr_number` (the resolved integer, not the branch name) to `pr-release-ready`.

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="ci-fix-pipeline: Phase 4 pr-release-ready for PR #{resolved_pr_number}",
  prompt="You are confirming release readiness for PR #{resolved_pr_number} (original arg: {pr_number_or_branch}).
    Invoke: Skill(skill=\"onex:pr-release-ready\", args=\"{resolved_pr_number}\")

    The goal is to confirm the PR is fully ready for merge after CI fixes were applied.

    RESULT:
    status: ready | not_ready | failed
    output: |
      PR release readiness summary:
      - Blocking issues remaining: <count>
      - Nit issues remaining: <count>
      - Overall verdict: ready | not_ready
    error: <error message if status is failed, else null>"
)
```

**Orchestrator action after Phase 4:**
- Log final pipeline summary including all phases, results, and any deferred tickets.
- Pipeline COMPLETE. Manual merge required.

---

## Dry Run Mode

`--dry-run` executes Phase 1 (analyze) and pre-flight checks only. It logs all classified failures and scope decisions, then STOPS before any commits, ticket creation, or Linear status changes. Use to preview what the pipeline would do.

## See Also

- `ci-failures` skill (Phase 1 analysis)
- `local-review` skill (Phase 3 review)
- `pr-release-ready` skill (Phase 4 release check)
- `create-ticket` skill (large-scope failure deferral)
- `.github/workflows/ci.yml` (CI commands mirrored in Phase 2)
