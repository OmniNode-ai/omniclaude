---
name: ticket-pipeline
description: Autonomous per-ticket pipeline - phased dispatch through implement, local_review, create_pr, pr_release_ready, and ready_for_merge
tags: [pipeline, automation, linear, tickets, review, pr, slack]
args:
  - name: ticket_id
    description: Linear ticket ID (e.g., OMN-1804)
    required: true
  - name: --skip-to
    description: Resume from specified phase (implement|local_review|create_pr|pr_release_ready|ready_for_merge)
    required: false
  - name: --dry-run
    description: Execute without side effects (no commits, pushes, PRs)
    required: false
  - name: --force-run
    description: Break stale lock and start fresh run
    required: false
---

# Ticket Pipeline

Autonomous per-ticket pipeline. Chains: implement -> local_review -> create_pr -> pr_release_ready -> ready_for_merge.

**Announce at start:** "I'm using the ticket-pipeline command to run the pipeline for {ticket_id}."

## Execution

1. Parse arguments from `$ARGUMENTS`:
   - `ticket_id` (required, format: `^[A-Z]+-\d+$`)
   - `--skip-to PHASE` (optional)
   - `--dry-run` (optional)
   - `--force-run` (optional)
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/ticket-pipeline/POLY_PROMPT.md`
3. Dispatch to polymorphic agent with all arguments:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Run ticket pipeline for {ticket_id}",
  prompt="<POLY_PROMPT content>\n\n## Execution Context\nTICKET_ID: {ticket_id}\nSKIP_TO: {skip_to or 'none'}\nDRY_RUN: {dry_run}\nFORCE_RUN: {force_run}"
)
```

The poly agent handles the full pipeline state machine: lock acquisition, phase loop, Slack notifications, Linear updates, and cleanup. Each pipeline phase internally dispatches to the appropriate skill (ticket-work, local-review, pr-release-ready).

4. Report the pipeline's final status to the user.
