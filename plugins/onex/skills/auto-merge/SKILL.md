---
name: auto-merge
description: Merge a PR when CI is green, approved, and policy allows — HIGH_RISK gate requires explicit "merge" reply by default; auto_merge:true skips gate
version: 1.0.0
category: workflow
tags:
  - pr
  - github
  - merge
  - autonomous
  - pipeline
  - high-risk
author: OmniClaude Team
composable: true
args:
  - name: --pr
    description: PR number to merge
    required: true
  - name: --ticket-id
    description: Ticket ID context for Slack messages and Linear updates
    required: false
  - name: --auto-merge
    description: "Set auto_merge: true in policy — merge immediately without Slack gate (use with caution)"
    required: false
  - name: --strategy
    description: "Merge strategy: squash | merge | rebase (default: squash)"
    required: false
  - name: --no-delete-branch
    description: Keep branch after merge (default: delete)
    required: false
inputs:
  - name: pr_number
    description: int — PR number to merge
  - name: ticket_id
    description: str — context ticket ID
  - name: policy
    description: AutoMergePolicy — auto_merge, merge_strategy, delete_branch_on_merge, gate_timeout_hours
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: merged | held | failed"
---

# Auto Merge

## Overview

Composable sub-skill that merges a PR when all conditions are met. Default policy requires
an explicit Slack "merge" reply (HIGH_RISK gate). When `auto_merge: true` is set in policy,
merges immediately without human input.

**Announce at start:** "I'm using the auto-merge skill for PR #{pr_number}."

**SAFETY INVARIANT**: PR merge is a HIGH_RISK action. Silence is NEVER consent for
merge. Explicit "merge" reply required unless `auto_merge: true` is explicitly set.

## Quick Start

```
/auto-merge --pr 142 --ticket-id OMN-2356         # HIGH_RISK gate (default)
/auto-merge --pr 142 --auto-merge                  # Merge immediately (no gate)
/auto-merge --pr 142 --strategy merge              # Use merge commit (not squash)
/auto-merge --pr 142 --no-delete-branch            # Keep branch after merge
```

## Policy Defaults

```yaml
auto_merge: false             # Require explicit Slack "merge" reply
merge_strategy: squash        # squash | merge | rebase
delete_branch_on_merge: true  # Delete branch after successful merge
slack_on_merge: true          # Post Slack notification on successful merge
merge_gate_timeout_hours: 48  # Max hours waiting for merge approval
reminder_at_hours: 24         # Post reminder Slack at halfway mark
```

## Merge Conditions

All three must be true before proceeding:

1. **CI passing**: All required checks have `conclusion: success`
2. **Approved**: At least 1 approved review; no current `CHANGES_REQUESTED` reviews
3. **No unresolved comments**: All review threads resolved

**If any condition fails**: abort with `status: failed`, describe which condition failed.

## Execution Flow

### Default Mode (`auto_merge: false`)

```
1. Verify merge conditions
2. Post HIGH_RISK Slack gate:
   "PR #{pr_number} is ready to merge.
    Ticket: {ticket_id}
    Strategy: {merge_strategy}
    Branch delete: {delete_branch_on_merge}
    Reply 'merge' to proceed. Silence = hold (HIGH_RISK)."
3. Wait for explicit 'merge' reply (no timeout auto-advance)
4. At reminder_at_hours: post reminder to Slack
5. At gate_timeout_hours: post reminder + hold (still require explicit reply)
6. On 'merge' reply:
   → gh pr merge {pr_number} --{strategy} {--delete-branch if policy}
   → Post Slack: "Merged PR #{pr_number} for {ticket_id}"
   → Update Linear ticket status: Done
   → Return status: merged
7. On 'reject' / 'no' / 'cancel' reply:
   → Return status: held
```

### Auto-Merge Mode (`auto_merge: true`)

```
1. Verify merge conditions
2. Execute immediately:
   gh pr merge {pr_number} --{merge_strategy} {--delete-branch if delete_branch_on_merge}
3. Post Slack: "Auto-merged PR #{pr_number} for {ticket_id} — {PR URL}"
4. Update Linear ticket status: Done
5. Return status: merged
```

## Slack Gate (HIGH_RISK)

```
[HIGH_RISK] auto-merge: PR #{pr_number} ready to merge

Ticket: {ticket_id}
PR: {PR URL}
CI: all green
Reviews: {N} approvals, 0 changes-requested
Merge strategy: squash --delete-branch

Reply 'merge' to merge this PR.
This is HIGH_RISK — silence will NOT auto-advance.
```

**Keyword matching**: `merge`, `go`, `yes`, `approve` → approve merge;
`no`, `cancel`, `hold`, `stop`, `reject` → hold.

## 24-Hour Reminder

At `reminder_at_hours` elapsed without response:

```
[HIGH_RISK] Reminder: PR #{pr_number} still waiting for merge approval

{ticket_id} has been waiting {hours}h for explicit 'merge' reply.
Reply 'merge' to proceed or 'cancel' to stop.
```

## Ticket-Run Ledger

After a successful merge, append to the ticket-run ledger:

```
~/.claude/pipelines/{ticket_id}/ticket-run-ledger.yaml
```

```yaml
- ticket_id: OMN-2356
  pr_number: 142
  merged_at: "2026-02-21T15:30:00Z"
  merge_strategy: squash
  branch_deleted: true
  pipeline_run_id: f084b6c3
```

This ledger supports cross-session resume and audit.

## ModelSkillResult Output

Written to `~/.claude/skill-results/{context_id}/auto-merge.json`:

```json
{
  "status": "merged | held | failed",
  "pr_number": 142,
  "ticket_id": "OMN-2356",
  "merge_strategy": "squash",
  "branch_deleted": true,
  "merged_at": "2026-02-21T15:30:00Z | null",
  "held_reason": "null | explicit_reject | condition_failed: {condition}"
}
```

## Failure Handling

| Error | Behavior |
|-------|----------|
| Merge conditions not met | `status: failed`, list which conditions failed |
| `gh pr merge` fails | `status: failed`, include error message |
| Slack unavailable for gate | If `auto_merge: false`: `status: held` (safe default — don't merge without gate) |
| Linear status update fails | Log warning, merge still proceeds |
| Ledger write fails | Log warning, merge still proceeds |

## See Also

- `ticket-pipeline` skill — composable pipeline; invokes auto-merge as Phase 6 (auto_merge phase) after ready_for_merge
- `~/.claude/pipelines/{ticket_id}/ticket-run-ledger.yaml` — merge audit log
