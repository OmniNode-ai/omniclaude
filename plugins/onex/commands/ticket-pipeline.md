---
name: ticket-pipeline
description: Autonomous per-ticket pipeline that chains ticket-work, local-review, PR creation, pr-release-ready, and merge readiness into a single unattended workflow
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

Use the Skill tool to load the full `onex:ticket-pipeline` skill, then execute with all provided arguments.

```
Skill(skill="onex:ticket-pipeline", args="{$ARGUMENTS}")
```

Follow the skill's orchestration logic completely.
