---
description: Foreground status snapshot — routes to merge-sweep-lead teammate if present, otherwise spawns a one-shot snapshot agent. Never calls gh directly from foreground.
mode: full
version: 1.0.0
level: intermediate
debug: false
category: observability
tags:
  - status
  - merge-sweep
  - routing
  - foreground-safe
author: OmniClaude Team
composable: false
ticket: OMN-9691
---

# /onex:status — Foreground Status Routing

**Skill ID**: `onex:status`
**Version**: 1.0.0
**Ticket**: OMN-9691

**Announce at start:** "I'm using the status skill."

## What this skill does

Delivers a PR / merge-queue status snapshot to the foreground session without
calling `gh` directly. Foreground sessions must not poll GitHub state inline —
doing so blocks the session and bypasses the merge-sweep pipeline's own
authoritative view.

Routing decision:

1. Call `TaskList` to enumerate active tasks in the current team.
2. If a task named `merge-sweep-lead` exists with status `in_progress`:
   - Send `{"type": "push_snapshot"}` via `SendMessage(to="merge-sweep-lead")`.
   - Wait for the teammate to reply with its current snapshot, then surface that
     reply to the user verbatim. Do not post-process or re-query GitHub.
3. If no `merge-sweep-lead` task is found:
   - Spawn a one-shot snapshot agent (see **One-Shot Snapshot Agent** below).
   - Surface the agent's returned snapshot to the user once it completes.

Under no circumstances should this skill or any agent it spawns call `gh pr list`,
`gh pr checks`, or any GitHub API endpoint from the foreground session directly.

## Routing decision pseudocode

```
tasks = TaskList()
lead = first task in tasks where name == "merge-sweep-lead" and status == "in_progress"

if lead:
    SendMessage(to="merge-sweep-lead", message='{"type": "push_snapshot"}')
    # teammate replies with snapshot JSON; surface to user
else:
    Agent(
        name="status-snapshot",
        prompt=ONE_SHOT_SNAPSHOT_PROMPT,
        model="claude-haiku-4-5-20251001",
    )
    # surface agent output to user
```

## One-Shot Snapshot Agent

When no `merge-sweep-lead` is running, spawn a minimal snapshot agent with this
prompt (inline, no separate file):

```
You are a one-shot status snapshot agent. Your only job:

1. Run: uv run onex run-node node_pr_lifecycle_orchestrator --input '{"dry_run": true, "inventory_only": true}'
2. Parse the returned ModelPrLifecycleResult JSON.
3. Emit a concise snapshot: open PRs, merge-queue state, CI failures, blocked tickets.
4. Send the snapshot text to "team-lead" via SendMessage.
5. Stop immediately after sending.

Never call gh directly. Never open PRs or push code. Read-only snapshot only.
```

Use `model="claude-haiku-4-5-20251001"` for the snapshot agent — this is a
read-only reporting task, not a reasoning task.

## Failure modes

| Condition | Behavior |
|-----------|----------|
| `TaskList` unavailable | Surface error; do not fall through to `gh` |
| `merge-sweep-lead` does not reply within 30 seconds | Surface timeout; suggest running `/onex:merge_sweep` to restart the lead |
| `node_pr_lifecycle_orchestrator` unavailable | Surface the node error verbatim; do not guess state |
| Agent tool unavailable in current context | Surface "Status routing requires Agent tool — run from a foreground session" |

## Why this routing exists

Foreground `gh` calls for PR/merge-queue state are a recurring source of:
- Stale reads (foreground session has no cache of the merge-sweep lead's view)
- Rate-limit waste (each foreground `gh pr list` consumes API quota shared
  with the merge-sweep pipeline)
- Inconsistency (foreground sees a snapshot; merge-sweep lead acts on a
  different snapshot taken milliseconds later)

Routing through `merge-sweep-lead` when it exists gives the foreground session
the authoritative view that the sweep lead is already maintaining.

## See Also

- `/onex:merge_sweep` — launches or resumes the merge-sweep pipeline
- `/onex:system_status` — full platform health (infra, Kafka, DB); not PR state
- `node_pr_lifecycle_orchestrator` (omnimarket) — backing node for PR inventory
