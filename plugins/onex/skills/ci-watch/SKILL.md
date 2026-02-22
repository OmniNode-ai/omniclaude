---
name: ci-watch
description: Poll CI status on a PR and auto-trigger ci-fix-pipeline on failure — replaces the manual notice-and-fix step
version: 1.0.0
category: workflow
tags:
  - ci
  - github-actions
  - polling
  - autonomous
  - pipeline
author: OmniClaude Team
composable: true
args:
  - name: --pr
    description: PR number to watch
    required: true
  - name: --ticket-id
    description: Ticket ID context for Slack messages and sub-ticket creation
    required: false
  - name: --timeout-minutes
    description: "Max minutes to watch CI before timing out (default: 60)"
    required: false
  - name: --max-fix-cycles
    description: "Max ci-fix-pipeline invocations before capping (default: 3)"
    required: false
  - name: --no-auto-fix
    description: Disable auto-fix; use Slack gate instead of automatic ci-fix-pipeline
    required: false
inputs:
  - name: pr_number
    description: int — PR number to watch
  - name: ticket_id
    description: str — context ticket ID
  - name: policy
    description: CiWatchPolicy — timeout_minutes, max_fix_cycles, auto_fix_ci
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: completed | capped | timeout | failed"
---

# CI Watch

## Overview

Composable sub-skill that polls CI status on a PR until pass/fail/timeout. On failure,
automatically invokes `ci-fix-pipeline`. Replaces the manual "notice CI failed →
invoke ci-fix-pipeline" step in the autonomous ticket pipeline.

**Announce at start:** "I'm using the ci-watch skill for PR #{pr_number}."

## Quick Start

```
/ci-watch --pr 142 --ticket-id OMN-2356
/ci-watch --pr 142 --timeout-minutes 90 --max-fix-cycles 5
/ci-watch --pr 142 --no-auto-fix    # Gate instead of auto-fix
```

## Policy Defaults

```yaml
ci_watch_timeout_minutes: 60    # Max watch time before timeout
max_ci_fix_cycles: 3            # Max auto-fix attempts before capping
auto_fix_ci: true               # Auto-invoke ci-fix-pipeline on failure
poll_interval_seconds: 300      # 5 minutes between CI status checks
```

## Polling Loop

```
Initialize:
  ci_fix_cycle = 0

Loop:
  → Run: gh pr checks {pr_number} --json name,state,conclusion
  → If all checks passing: return status: completed
  → If any check failed:
      ci_fix_cycle += 1
      If ci_fix_cycle > max_ci_fix_cycles:
        → Slack MEDIUM_RISK gate: "CI still failing after {N} fix attempts — manual review required"
        → Create Linear hardening sub-ticket (parentId=ticket_id)
        → Return status: capped
      If auto_fix_ci:
        → Invoke ci-fix-pipeline --pr {pr_number} --ticket-id {ticket_id}
        → Wait for ci-fix-pipeline to complete
        → Continue polling
      Else:
        → Slack LOW_RISK gate: "CI failed on PR #{pr_number} — auto-fix disabled. Approve to skip, reject to halt."
        → On approve: continue polling (human will fix manually)
        → On reject: return status: failed
  → If timeout_elapsed >= ci_watch_timeout_minutes:
      → Slack MEDIUM_RISK gate: "CI watch timed out after {timeout} minutes on PR #{pr_number}"
      → Return status: timeout
  → Sleep poll_interval_seconds, loop
```

## CI Status Polling

Uses GitHub CLI:

```bash
gh pr checks {pr_number} --json name,state,conclusion
```

**Passing condition**: All required checks have `conclusion: success`.
**Failing condition**: Any required check has `conclusion: failure | cancelled | timed_out`.
**Pending condition**: Any required check has `state: in_progress | pending | queued`.

For pending state: continue waiting (not a failure trigger).

## Auto-Fix Invocation

When CI fails and `auto_fix_ci: true`:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="ci-watch: auto-fix CI failures on PR #{pr_number} (cycle {N})",
  prompt="Invoke: Skill(skill=\"onex:ci-fix-pipeline\",
    args=\"--pr {pr_number} --ticket-id {ticket_id}\")

  Report back with: status (completed|capped|escalated), failures_fixed, failures_skipped."
)
```

After each ci-fix-pipeline invocation: wait for CI to re-run (continue polling loop).

## Slack Gates

### CI Fix Cap — MEDIUM_RISK

After `max_ci_fix_cycles` fix attempts with CI still failing:

```
[MEDIUM_RISK] ci-watch: CI still failing after {N} attempts

PR: #{pr_number}
Ticket: {ticket_id}
Fix cycles used: {N}/{max_fix_cycles}

A hardening sub-ticket has been created: {sub_ticket_id}
Reply with 'approve' to continue watching, 'reject' to stop.
Silence (15 min) = escalate to hardening ticket.
```

### Timeout — MEDIUM_RISK

After `ci_watch_timeout_minutes` elapsed:

```
[MEDIUM_RISK] ci-watch: Timeout after {timeout} min

PR: #{pr_number} — CI still not passing
Ticket: {ticket_id}

Reply 'approve' to extend 30 more minutes, 'reject' to stop.
Silence (15 min) = stop (status: timeout).
```

## Hardening Sub-Ticket

Created when `max_ci_fix_cycles` is exceeded:

```python
mcp__linear-server__create_issue(
    title=f"CI hardening: PR #{pr_number} — failing after {N} auto-fix cycles",
    team=current_team,
    description=f"""
## CI Failure Requiring Manual Hardening

PR #{pr_number} CI still failing after {N} automated fix cycles.

**Ticket**: {ticket_id}
**Fix cycles attempted**: {N}
**Last failure summary**: {last_failure_summary}

## Definition of Done

- [ ] CI passing on branch {branch}
- [ ] Root cause documented
    """,
    parentId=ticket_id,
    labels=["ci-hardening", "needs-human"]
)
```

## ModelSkillResult Output

Written to `~/.claude/skill-results/{context_id}/ci-watch.json`:

```json
{
  "status": "completed | capped | timeout | failed",
  "pr_number": 142,
  "ticket_id": "OMN-2356",
  "ci_fix_cycles_used": 2,
  "hardening_ticket": "OMN-XXXX | null",
  "watch_duration_minutes": 35,
  "final_ci_status": "passing | failing | timeout"
}
```

## Failure Handling

| Error | Behavior |
|-------|----------|
| `gh pr checks` unavailable | Retry 3x, then `status: failed` with error |
| ci-fix-pipeline hard-fails | Log error, continue watching (don't retry fix) |
| Slack unavailable for gate | Skip gate, apply default behavior for risk level |
| Linear sub-ticket creation fails | Log warning, continue |

## See Also

- `ci-fix-pipeline` skill — auto-invoked on CI failure
- `slack-gate` skill — MEDIUM_RISK gate for cap and timeout
- `ticket-pipeline` skill — invokes ci-watch as Phase 4 (ci_watch)
