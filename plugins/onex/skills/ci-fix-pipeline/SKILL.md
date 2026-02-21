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

Dispatches an agent to fetch CI failures via gh CLI for the target PR or branch. Classifies each failure by:
- **Scope**: small (≤`max_fix_files` files, single repo, no contract/node-wiring/infrastructure touches) vs large
- **Cause**: compilation error, test failure, lint violation, type check failure, timeout, infrastructure, no-verify bypass

Large-scope classification triggers ticket creation rather than an in-place fix. Ticket creation happens inside Phase 2 (`fix_each_failure`) — large-scope failures exit the fix path early and dispatch a `create-ticket` agent instead. Readers of the pipeline flow should understand that `fix_each_failure` covers both paths: small-scope → fix, large-scope → defer to ticket.

AUTO-ADVANCE to Phase 2.

### Phase 2: fix_each_failure

For each classified failure:
- **Small scope** → dispatches fix to a polymorphic agent (Polly), mirroring exact CI commands from `.github/workflows/ci.yml`
- **Large scope** → dispatches `create-ticket` to Polly with full context; marks failure as deferred

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
| `--skip-to <phase>` | none | Resume from a specific phase: `analyze`, `fix` (no-op today; reserved for future confirmation gate), `local_review`, or `release_ready` |

### `--skip-to` handling

When `--skip-to` is provided, begin execution at the named phase. Note that Phase 1 data (failure classification) is required by Phase 2 and later phases, so `--skip-to fix` does NOT skip Phase 1 — it re-runs Phase 1 silently and immediately advances to Phase 2. Only `--skip-to local_review` and `--skip-to release_ready` genuinely bypass earlier phases.

- `--skip-to analyze` — start at Phase 1 (same as default)
- `--skip-to fix` — re-run Phase 1 silently (required to produce failure classification data), then immediately advance to Phase 2 without any inter-phase pause. This is equivalent to the default auto-advance behavior: the pipeline already auto-advances from Phase 1 to Phase 2 with no confirmation gate between them, so `--skip-to fix` is a no-op today. It exists as a forward-compatibility hook in case a confirmation gate is added between Phase 1 and Phase 2 in the future. If the caller provides pre-classified failure context in the prompt, the orchestrator may use that in place of a fresh Phase 1 run.
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
6. **Correlation tagging**: every commit must include `[corr:{correlation_id}:{failure_index}]` in the commit message, where `failure_index` is the 0-based position of that failure in the failures list. Before starting, check git log for existing `[corr:{correlation_id}:{failure_index}]` commits to detect re-runs and avoid duplicate work. Using a per-failure tag ensures parallel agents fixing different failures do not falsely detect each other's commits as "already fixed".
7. **Branch guard**: if currently on main or master, create a new branch before making any changes.
8. **Dry-run isolation**: `--dry-run` must produce zero side effects — no commits, no pushes, no ticket creation, no Linear status changes.

## Dispatch Contracts (Execution-Critical)

**This section governs how you execute the pipeline. Follow it exactly.**

You are an orchestrator. You coordinate phase transitions, pre-flight checks, policy enforcement, and result aggregation.
You do NOT analyze, fix, or review code yourself. All heavy work runs in separate agents (Polly) via `Task()`.

**Rule: The orchestrator MUST NEVER call Edit(), Write(), or Bash(code-modifying commands) directly.**
If code changes are needed, dispatch a polymorphic agent. If you find yourself wanting to make an edit, that is the signal to dispatch instead.

**Correlation ID**: Before dispatching any phase, generate a `correlation_id` using the format `ci-fix-{pr_number_or_branch}-{short_timestamp}` where `short_timestamp` includes seconds (e.g., `ci-fix-42-20260221T103045`). Use seconds resolution so that re-runs within the same minute produce distinct IDs and do not trigger the idempotency check (`grep [corr:{correlation_id}]`) prematurely. **Sanitize `pr_number_or_branch` before embedding it in the correlation_id**: replace every `/` with `-` so that branch names like `jonahgabriel/omn-1234-fix` become `jonahgabriel-omn-1234-fix` and the resulting ID contains no path separators (e.g., `ci-fix-jonahgabriel-omn-1234-fix-20260221T103045`). **Truncate the branch-name portion to at most 30 characters** after sanitization to prevent the correlation_id from pushing commit subject lines past 72 characters (e.g., `jonahgabriel-omn-1234-fix-my-` if the sanitized branch exceeds 30 chars). Use this same ID for all commits and dispatches within one pipeline run. Pass it as a literal string in all dispatch prompts — do not use a placeholder.

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
- If `status: partial` (some failures classified, some not): dispatch Phase 2 agents **only** for the fully-classified failures. Log a warning listing each unclassified failure (job name and available error excerpt) and mark them as `unresolved` in the final summary. Do NOT dispatch fix or ticket agents for unclassified failures.
- Otherwise, AUTO-ADVANCE to Phase 2.

---

### Phase 2: fix_each_failure — dispatch to polymorphic agent (one per small-scope failure)

For each **small-scope** failure, dispatch one Polly. For each **large-scope** failure, dispatch one Polly with `create-ticket` invocation.

**IMPORTANT — parallel dispatch required**: All small-scope fix Task calls and all large-scope ticket Task calls MUST be sent as parallel `Task()` invocations in a single message. Do NOT dispatch them sequentially (one at a time, waiting for each to finish before starting the next). Sending all dispatches in a single message is required by ONEX parallel execution standards and minimizes wall-clock time.

**Small-scope fix dispatch:**

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="ci-fix-pipeline: Phase 2 fix {cause} failure in {job_name}/{step_name}",
  prompt="You are fixing CI failure #{failure_index} (0-based index in the failures list) for PR/branch: {pr_number_or_branch}.

    Pre-flight (MANDATORY before any changes):
    1. Run: git status
       - If unrelated uncommitted changes exist: STOP, do not proceed, report in RESULT.
    2. Run: gh auth status
       - If not authenticated: STOP, do not proceed, report in RESULT.
    3. Run: git log --oneline -100 | grep -F "[corr:${correlation_id}:${failure_index}]"
       where ${correlation_id} and ${failure_index} are substituted as literal strings before the command runs (not shell variables). Always quote the grep pattern as shown — if the pattern is unquoted and correlation_id contains shell-special characters (e.g., slashes), the command will fail silently and the idempotency check will be bypassed. Note: the correlation_id passed here must already be the sanitized form (all `/` replaced with `-`) as produced by the orchestrator.
       - If corr commits already exist for this failure: log 'already fixed' and STOP (idempotent).
       - WARNING: On branches with more than 100 commits the -100 window may not cover the full history. If this branch has more than 100 commits, log a warning: 'idempotency not guaranteed — branch exceeds 100-commit window'. Do not abort; continue with the fix attempt.
       Note: {failure_index} is the 0-based position of this failure in the failures list, passed to you in this prompt. This makes the idempotency check per-failure so parallel agents fixing different failures do not interfere with each other.
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
    - Commit with message: 'fix({cause}): {error_summary} [corr:{correlation_id}:{failure_index}]'
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
- Wait for ALL parallel agents to complete before evaluating results. Do NOT abort early when the first `preflight_failed` is seen — collect every agent's RESULT first, then evaluate.
- If any agent returned `preflight_failed`: STOP and report all preflight failures after aggregating all results — do not proceed to Phase 3.
- If any small-scope fix agent returned `large_scope` mid-fix (i.e., the agent determined during fixing that the actual scope exceeded the threshold): dispatch a large-scope ticket-creation agent for each such failure using the same large-scope ticket dispatch template defined above in this phase. These ticket-creation dispatches MUST be sent as parallel `Task()` invocations in a single message. Wait for all ticket-creation agents to complete before evaluating the AUTO-ADVANCE condition. Only after all mid-fix `large_scope` tickets are created may the orchestrator treat those failures as `success` (ticket created) and advance.
- If all failures are `fixed`, `skipped`, `large_scope` (ticket now created per the step above), or `success` (large-scope → ticket created): AUTO-ADVANCE to Phase 3.
- If any `failed` (not preflight): STOP, set status=`fix_partially_failed`, and report clearly which failures were not resolved. Do NOT advance to Phase 3. Manual intervention is required before resuming the pipeline.

---

### Phase 3: local_review — dispatch to polymorphic agent

Before dispatching Phase 3, determine the base branch:
- If `{pr_number_or_branch}` is a PR number: run `gh pr view {pr_number_or_branch} --json baseRefName --jq '.baseRefName'` to get the base branch (e.g., `main`, `develop`). Use `origin/{base_branch}` as the `--since` argument.
- If `{pr_number_or_branch}` is a branch name: detect the repo's actual default branch by running `gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name'`. Use `origin/{detected_default_branch}` as the `--since` argument. Do NOT hard-code `origin/main` — repos may use `develop` or another default.

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
- Parse `blocking issues found: <count>` from the output to extract the integer count. If parsing fails or the field is absent, treat the result conservatively: assume blocking issues exist, STOP, and report that Phase 3 result could not be parsed — do not advance to Phase 4.
- If `status: passed` and parsed count is 0: AUTO-ADVANCE to Phase 4.
- If `status: failed`: STOP and report — local review did not pass. Manual fix and re-run of Phase 3 is required.
- If `status: passed` but parsed count > 0: STOP and report — review reported pass but issues remain (contradiction; investigate).

---

### Phase 4: release_ready — dispatch to polymorphic agent

Before dispatching Phase 4, resolve `{pr_number_or_branch}` to a PR number using the following steps:

```
# Variable capture — run this before dispatching Phase 4
if {pr_number_or_branch} is numeric:
    resolved_pr_number = {pr_number_or_branch}
else:
    # Run: gh pr list --state open --head {pr_number_or_branch} --json number --jq '.[0].number'
    # Extract the first result's `.number` field (an integer).
    # Assign it to resolved_pr_number.
    # Example: gh pr list --state open --head jonahgabriel/omn-1234-fix --json number --jq '.[0].number'
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

    IMPORTANT: Replace {resolved_pr_number} in the args string above with the actual integer PR
    number (e.g., 42) before creating this Task. The orchestrator must substitute the real integer
    value — never pass a template placeholder like '{resolved_pr_number}' literally.
    For example, if the PR number is 42, the args value is the string \"42\".
    This substitution applies to BOTH the prompt body AND the description field of the Task
    (which also contains '{resolved_pr_number}'). Replace it in both locations before the Task
    is created.

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
