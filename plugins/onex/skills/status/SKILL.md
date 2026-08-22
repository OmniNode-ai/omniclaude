---
description: Foreground status snapshot — routes to merge-sweep-lead teammate if present, otherwise spawns a one-shot snapshot agent. Avoids inline repository polling from foreground.
mode: full
version: 1.0.1
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
boundary_exempt: true
---

# /onex:status — Foreground Status Routing

**Skill ID**: `onex:status`
**Version**: 1.0.1

**Announce at start:** "I'm using the status skill."

## What this skill does

Delivers a PR / merge-queue status snapshot to the foreground session without
inline repository polling. Foreground sessions must route state requests through
the merge-sweep pipeline's authoritative view.

Routing decision:

1. Call `TaskList` to enumerate active tasks in the current team.
2. If a task named `merge-sweep-lead` exists with status `in_progress`:
   - Send `{"type": "push_snapshot"}` via `SendMessage(to="merge-sweep-lead")`.
   - Wait for the teammate to reply with its current snapshot, then surface that
     reply to the user verbatim. Do not post-process or re-query GitHub.
3. If no `merge-sweep-lead` task is found:
   - Spawn a one-shot snapshot agent (see **One-Shot Snapshot Agent** below).
   - Surface the agent's returned snapshot to the user once it completes.

Under no circumstances should this skill or any agent it spawns query PR state
directly from the foreground session.

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

````text
You are a one-shot status snapshot agent. Your only job:

1. Run this exact standalone-CLI preflight and dispatch from the current directory:

<!-- status-snapshot-command:start -->
```sh
if ! command -v onex >/dev/null 2>&1; then
  printf '%s\n' "ERROR: Required standalone ONEX CLI was not found on PATH. Install it with: pipx install 'omnibase-core>=0.39.0'" >&2
  exit 127
fi
exec onex run-node node_pr_lifecycle_orchestrator --input '{"dry_run": true, "inventory_only": true}'
```
<!-- status-snapshot-command:end -->

2. If the command exits nonzero, send its error output verbatim to "team-lead" and stop. Do not install anything, search repository virtualenvs, or query GitHub directly.
3. On success, parse the returned ModelPrLifecycleResult JSON.
4. Emit a concise snapshot: open PRs, merge-queue state, CI failures, blocked tickets.
5. Send the snapshot text to "team-lead" via SendMessage.
6. Stop immediately after sending.

Never query repository state directly. Never open PRs or push code. Read-only
snapshot only.
````

Use `model="claude-haiku-4-5-20251001"` for the snapshot agent — this is a
read-only reporting task, not a reasoning task.

## Failure modes

| Condition | Behavior |
|-----------|----------|
| `TaskList` unavailable | Surface error; do not fall through to direct polling |
| `merge-sweep-lead` does not reply within 30 seconds | Surface timeout; suggest running `/onex:merge_sweep` to restart the lead |
| Standalone `onex` CLI missing from `PATH` | Surface the manifest-pinned install guidance from the preflight; do not auto-install or search repository virtualenvs |
| `node_pr_lifecycle_orchestrator` unavailable | Surface the node error verbatim; do not guess state |
| Agent tool unavailable in current context | Surface "Status routing requires Agent tool — run from a foreground session" |

## Why this routing exists

Foreground PR/merge-queue polling is a recurring source of stale reads,
rate-limit waste, and inconsistent snapshots. The foreground session has no
cache of the merge-sweep lead's view, and the sweep lead may act on a newer
snapshot milliseconds later.

Routing through `merge-sweep-lead` when it exists gives the foreground session
the authoritative view that the sweep lead is already maintaining.

## See Also

- `/onex:merge_sweep` — launches or resumes the merge-sweep pipeline
- `/onex:system_status` — full platform health (infra, Kafka, DB); not PR state
- omnimarket PR lifecycle orchestrator — backing node for PR inventory
