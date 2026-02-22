---
name: pr-watch
description: Poll a PR for review comments and automatically invoke pr-review-dev to fix them — replaces the manual review-check-and-fix step
version: 1.0.0
category: workflow
tags:
  - pr
  - github
  - review
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
    description: Ticket ID context for Slack messages
    required: false
  - name: --timeout-hours
    description: "Max hours to wait for approval (default: 24)"
    required: false
  - name: --max-review-cycles
    description: "Max fix cycles before capping (default: 3)"
    required: false
  - name: --fix-nits
    description: Also fix nit-level comments (default: false)
    required: false
inputs:
  - name: pr_number
    description: int — PR number to watch
  - name: ticket_id
    description: str — context ticket ID
  - name: policy
    description: PrWatchPolicy — timeout_hours, max_review_cycles, auto_fix_nits
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: approved | capped | timeout | failed"
---

# PR Watch

## Overview

Composable sub-skill that polls a PR for new review comments and automatically invokes
`pr-review-dev` to fix Critical/Major/Minor issues when reviews arrive. Replaces the manual
"check for PR review → invoke pr-review-dev" step in the autonomous ticket pipeline.

**Announce at start:** "I'm using the pr-watch skill for PR #{pr_number}."

## Quick Start

```
/pr-watch --pr 142 --ticket-id OMN-2356
/pr-watch --pr 142 --timeout-hours 48 --max-review-cycles 5
/pr-watch --pr 142 --fix-nits    # Also fix nit comments
```

## Policy Defaults

```yaml
pr_review_timeout_hours: 24     # Max hours waiting for approval before timeout
max_pr_review_cycles: 3         # Max fix cycles before Slack MEDIUM_RISK gate
auto_fix_nits: false            # Nits skipped by default
poll_interval_minutes: 10       # Minutes between review status checks
halfway_notification_hours: 12  # Slack MEDIUM_RISK notification at halfway mark
```

## Polling Loop

```
Initialize:
  pr_review_cycle = 0
  start_time = now()
  halfway_notified = false
  last_seen_review_ids = set()

Loop:
  elapsed = now() - start_time

  → If elapsed >= halfway_notification_hours * 3600 AND NOT halfway_notified:
      → Slack MEDIUM_RISK notification: "PR #{pr_number} still awaiting review ({elapsed // 3600:.1f}h elapsed)"
      → halfway_notified = true

  → Run: gh pr view {pr_number} --json reviewDecision,reviews

  → If reviewDecision == APPROVED AND no unresolved CHANGES_REQUESTED:
      → Return status: approved

  → If elapsed >= timeout_hours * 3600:
      → Slack MEDIUM_RISK gate: "PR #{pr_number} timeout — no approval in {timeout_hours}h"
      → Return status: timeout

  → If new CHANGES_REQUESTED reviews since last check:
      pr_review_cycle += 1
      If pr_review_cycle > max_pr_review_cycles:
        → Slack MEDIUM_RISK gate: "PR #{pr_number} blocked — {N} review cycles with no approval"
        → Return status: capped
      → Invoke pr-review-dev to fix issues (see Fix Invocation below)
      → Push fixes to PR branch
      → Re-request review from original reviewers
      → Continue polling

  → Update last_seen_review_ids with IDs from current gh pr view response
  → Sleep poll_interval_minutes * 60, loop
```

## Review Detection

**New review detection**: Track last-seen review IDs in local state. A review is "new" if:
- Its ID was not seen in the previous poll cycle
- Its state is `CHANGES_REQUESTED` or `COMMENTED`
- It contains at least one actionable comment (not empty body)

**Approval detection**: `reviewDecision == APPROVED` and no CHANGES_REQUESTED reviews from
any reviewer who still has that status.

## Fix Invocation

When CHANGES_REQUESTED reviews arrive:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="pr-watch: fix review comments for PR #{pr_number} (cycle {N})",
  prompt="Invoke: Skill(skill=\"onex:pr-review-dev\", args=\"{pr_number}\")

  This is review cycle {N}/{max_cycles} for ticket {ticket_id}.
  Fix all Critical, Major, and Minor issues.
  {If auto_fix_nits: 'Also fix Nit issues.'}
  {Else: 'Skip Nit issues.'}

  After fixing, DO NOT push — report back files changed for orchestrator to push."
)
```

After fix agent completes, orchestrator pushes:
```bash
git add <changed_files>
git commit -m "fix(review): address PR review comments — cycle {N} [{ticket_id}]"
git push
```

Then re-request review:
```bash
gh pr edit {pr_number} --add-reviewer {reviewer_logins}
```

## Slack Notifications

### Halfway Mark — MEDIUM_RISK Notification

Not a gate (no waiting for response); informational only:
```
[MEDIUM_RISK] pr-watch: PR #{pr_number} still awaiting review

{halfway_notification_hours} hours elapsed without approval.
Ticket: {ticket_id}
Reviewers: {reviewer_list}
```

### Cap Reached — MEDIUM_RISK Gate

```
[MEDIUM_RISK] pr-watch: PR #{pr_number} blocked — {N} review cycles with issues remaining

This PR has been through {N} automated fix cycles and still has unresolved review comments.
Manual review required.

Reply 'approve' to continue watching, 'reject' to mark as blocked.
Silence (15 min) = blocked (status: capped).
```

### Timeout — MEDIUM_RISK Gate

```
[MEDIUM_RISK] pr-watch: Timeout — {timeout_hours}h with no PR approval

PR #{pr_number}
Ticket: {ticket_id}

Reply 'extend' for 12 more hours, 'stop' to halt.
Silence (15 min) = stop (status: timeout).
```

## ModelSkillResult Output

Written to `~/.claude/skill-results/{context_id}/pr-watch.json`:

```json
{
  "status": "approved | capped | timeout | failed",
  "pr_number": 142,
  "ticket_id": "OMN-2356",
  "pr_review_cycles_used": 2,
  "watch_duration_hours": 8.5,
  "final_review_decision": "APPROVED | CHANGES_REQUESTED | pending"
}
```

## Failure Handling

| Error | Behavior |
|-------|----------|
| `gh pr view --json reviews` unavailable | Retry 3x, then `status: failed` with error |
| pr-review-dev hard-fails | Log error, continue watching without fix |
| Push fails after fix | Log error, continue watching (don't re-request review) |
| Slack unavailable for cap gate | Skip gate, apply default (status: capped) |
| Slack unavailable for timeout gate | Skip gate, apply default (status: timeout/stop) |

## See Also

- `pr-review-dev` skill — invoked to fix review comments
- `slack-gate` skill — MEDIUM_RISK gates used for cap and timeout (planned, not yet implemented)
- `auto-merge` skill — invoked after pr-watch returns `approved` (planned, not yet implemented)
- `ticket-pipeline` skill — planned integration as Phase 5 (pr_review_loop); not yet wired
