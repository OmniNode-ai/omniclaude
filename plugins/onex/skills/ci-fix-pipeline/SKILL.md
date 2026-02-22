---
name: ci-fix-pipeline
description: Autonomous CI failure fix pipeline — fetches failures, fixes ALL by default, creates sub-tickets for large-scope failures, notifies Slack on start and complete
version: 1.0.0
category: workflow
tags:
  - ci
  - github-actions
  - autonomous
  - pipeline
  - slack
author: OmniClaude Team
args:
  - name: --pr
    description: PR number to fix CI failures for
    required: false
  - name: --branch
    description: Branch name to fix CI failures for (default: current branch)
    required: false
  - name: --skip-patterns
    description: "Comma-separated job/step name patterns to skip (e.g., 'test_*,lint')"
    required: false
  - name: --max-fix-files
    description: "Max files in scope before creating a sub-ticket instead of fixing (default: 10)"
    required: false
  - name: --no-slack
    description: Disable Slack notifications for this run
    required: false
  - name: --ticket-id
    description: Ticket ID context (included in Slack messages and sub-ticket descriptions)
    required: false
composable: true
---

# CI Fix Pipeline

## Overview

Autonomous pipeline that fetches GitHub Actions CI failures and fixes them — ALL failures by
default. No selective mode. Failures beyond `max_fix_files` trigger sub-ticket creation and
continue with the remaining fixable failures.

**Workflow**: Fetch CI failures → Slack start → Classify + Sub-ticket large-scope → Fix ALL fixable → Commit → Slack complete → ModelSkillResult

**Announce at start:** "I'm using the ci-fix-pipeline skill to fix CI failures."

## Policy Defaults

```yaml
policy:
  fix_all: true                     # always fix all — no selective mode
  max_fix_files: 10                 # files in scope trigger sub-ticket (not skip)
  fix_preexisting_in_touched: true  # fix pre-existing issues in touched files
  slack_on_start: true              # notify Slack before fixing
  slack_on_complete: true           # notify Slack with fix summary
```

## Quick Start

```
/ci-fix-pipeline                         # Fix all CI failures on current branch
/ci-fix-pipeline --pr 42                 # Fix failures for PR #42
/ci-fix-pipeline --ticket-id OMN-1234    # Include ticket context in Slack messages
/ci-fix-pipeline --no-slack              # Suppress Slack notifications
/ci-fix-pipeline --skip-patterns "test_*"  # Skip jobs/steps matching pattern
/ci-fix-pipeline --max-fix-files 20       # Raise the sub-ticket threshold
```

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--pr <number>` | none | PR number for CI failure fetch |
| `--branch <ref>` | current | Branch name for CI failure fetch |
| `--skip-patterns <patterns>` | none | Comma-separated job/step name patterns to skip |
| `--max-fix-files <n>` | 10 | Files-in-scope threshold; above this → sub-ticket |
| `--no-slack` | false | Disable Slack notifications |
| `--ticket-id <id>` | none | Context ticket ID for Slack messages |

## Execution Phases

### Phase 1: Fetch CI Failures

Dispatch to polymorphic agent:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Fetch CI failures for ci-fix-pipeline",
  prompt="Fetch CI failures using the ci-failures skill.

    Run: ${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review {N | branch_name}

    Return the raw JSON from ci-quick-review (pass through unchanged).
    The response has structure:
    {\"repository\": str, \"pr_number\": int,
     \"summary\": {\"total\": N, \"critical\": N, \"major\": N, \"minor\": N},
     \"failures\": [{\"workflow\": str, \"job\": str, \"job_id\": str, \"step\": str,
                    \"severity\": str, \"workflow_id\": str, \"job_url\": str}],
     \"fetched_at\": str}"
)
```

### Phase 2: Slack Start Notification

If `slack_on_start: true` and Slack is available, notify:

```
ci-fix-pipeline starting
  PR/Branch: {context}
  Failures found: {N} ({critical} critical, {major} major, {minor} minor)
  Ticket: {ticket_id if provided}
```

Skip silently if Slack unavailable (non-blocking).

### Phase 3: Classify and Route Failures

For each failure:

1. **Skip check**: Does the failure `job` or `step` name match any `--skip-patterns` pattern?
   - Yes → mark as `skipped`, record reason
   - No → continue

2. **Scope check**: Does the failure `job` touch more than `max_fix_files` files?
   Determine scope by inspecting the job logs (via `gh api repos/{repo}/actions/jobs/{job_id}/logs`)
   to count affected files. If log inspection is unavailable, treat scope as within threshold.
   - Scope > max_fix_files → mark as `capped`, create Linear sub-ticket inline (see Sub-Ticket Creation below), continue to next failure
   - Scope ≤ max_fix_files → add to fix queue

Result: failures split into `skipped`, `capped`, and `to_fix` buckets.

### Phase 4: Fix Failures

Dispatch one polymorphic agent per severity group (critical first, then major, then minor) for all `to_fix` failures:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Fix {severity} CI failures",
  prompt="**AGENT REQUIREMENT**: You MUST be a polymorphic-agent.

    Fix the following {severity} CI failures:

    {failures_list}

    Instructions:
    1. Read each affected file
    2. Apply the fix
    3. If fix_preexisting_in_touched is true: also fix any pre-existing lint/mypy
       issues in those files (only files already in scope — not a full repo scan)
    4. Do NOT commit

    Return classification for each failure:
    {\"fixed\": [failure_ids], \"architectural\": [failure_ids], \"unfixable\": [failure_ids]}"
)
```

**Post-fix architectural check**: For each failure returned as `architectural` by the fix agent:
- Send a Slack message (via `HandlerSlackWebhook` in omnibase_infra) describing the architectural
  change and asking for human approval. Include the failure description, the proposed fix, and
  the files affected. Wait for a reply (poll or webhook callback).
- Approved (human replies "approve" or "yes") → apply fix; Declined (any other reply or timeout after 10 min) → mark `escalated`

### Phase 5: Commit Fixes

Orchestrator stages and commits inline (no dispatch needed):

```bash
git add <changed_files>
git commit -m "fix(ci): resolve {N} {severity} failures [{ticket_id}]"
```

Commit message format: `fix(ci): resolve {N} {severity} failures [{ticket_id}]`
where `{severity}` is the highest severity fixed (e.g., `critical`, `major`, `minor`) and
`{ticket_id}` is the value from `--ticket-id` (or omitted if not provided).

### Sub-Ticket Creation

For each `capped` failure (scope > max_fix_files), created inline during Phase 3:

```python
# current_team: resolved from --ticket-id parent team (via mcp__linear-server__get_issue),
# or from the first team returned by mcp__linear-server__list_teams if no ticket is provided.
mcp__linear-server__create_issue(
    title=f"CI: {failure.job} — {failure.step} (large scope)",
    team=current_team,
    description=f"""
## CI Failure Requiring Human Review

**Job**: {failure.job}
**Step**: {failure.step}
**Severity**: {failure.severity}
**Scope**: Exceeds max_fix_files={max_fix_files} threshold
**Triggered by**: ci-fix-pipeline run for {ticket_id or branch}
**Job URL**: {failure.job_url}

## Definition of Done

- [ ] All affected files reviewed and fixed
- [ ] CI passing on {branch}
    """,
    parentId=ticket_id if ticket_id else None,
    labels=["ci-failure", "needs-human"]
)
```

### Phase 6: Slack Complete Notification

If `slack_on_complete: true`, notify with diff summary:

```
ci-fix-pipeline complete
  Fixed: {N} failures
  Skipped: {M} failures (patterns: {patterns})
  Sub-tickets created: {K} (large-scope failures)
  Escalated: {L} (architectural — awaiting decision)
  Ticket: {ticket_id if provided}
  Branch: {branch}
```

## ModelSkillResult Output

Emits to `~/.claude/skill-results/{context_id}/ci-fix-pipeline.json`
where `{context_id}` is the Claude session ID (from `$CLAUDE_SESSION_ID` env var) or `default`
if the session ID is unavailable:

```json
{
  "status": "completed|capped|escalated|failed",
  "fixed_count": 5,
  "skipped_count": 1,
  "capped_count": 2,
  "escalated_count": 0,
  "unfixable_count": 0,
  "sub_tickets": ["OMN-XXXX", "OMN-XYYY"],
  "commit": "abc1234",
  "branch": "feature/my-branch",
  "ticket_id": "OMN-1234"
}
```

**Status values**:
- `completed` — All fixable failures resolved
- `capped` — Some failures deferred to sub-tickets; fixed what was in scope
- `escalated` — One or more architectural failures awaiting human decision
- `failed` — CI fetch failed or commit failed; pipeline halted

## Failure Handling

| Error | Behavior |
|-------|----------|
| CI fetch fails | Hard exit with `status: failed`, reason in output |
| Fix agent fails | Log failure, mark as `unfixable`, continue with others |
| Sub-ticket creation fails | Log warning, continue (non-blocking) |
| Slack unavailable | Skip notification, continue (non-blocking) |
| Commit fails | Exit with `status: failed`, leave changes staged |

## Sub-Ticket Threshold Policy

The `max_fix_files` threshold is a **routing decision**, not a skip:

- Failures within threshold: fixed autonomously
- Failures above threshold: sub-ticket created, pipeline continues with remaining

This ensures large-scope failures are never silently dropped — they are tracked in Linear.

## See Also

- `ci-failures` skill — fetch and analyze CI failures (read-only)
- `local-review` skill — review and fix local code changes
- `ticket-pipeline` skill — end-to-end ticket pipeline (implement → local_review → create_pr → ready_for_merge)
- `HandlerSlackWebhook` in omnibase_infra — Slack delivery infrastructure used for start/complete notifications and architectural approval gates
