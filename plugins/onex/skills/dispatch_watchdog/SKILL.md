---
description: Detect and recover from stalled agent dispatches in epic-team wave execution. Monitors Task() subagents for progress and triggers recovery when agents stop producing tool calls.
version: 1.0.0
mode: full
level: advanced
debug: false
category: observability
tags:
  - watchdog
  - stall-detection
  - agent-health
  - epic-team
  - recovery
author: OmniClaude Team
composable: true
args:
  - name: --epic-id
    description: Epic ID to monitor (reads state from $ONEX_STATE_DIR/epics/<id>/state.yaml)
    required: false
  - name: --timeout
    description: "Stall timeout in seconds (default: 300 = 5 minutes)"
    required: false
  - name: --action
    description: "Recovery action on stall: report | cancel | restart (default: report)"
    required: false
  - name: --check-interval
    description: "Polling interval in seconds (default: 60)"
    required: false
---

# Agent Dispatch Watchdog

## Purpose

Detect when dispatched Task() subagents stall (stop producing tool calls) and trigger
recovery actions. This addresses the recurring failure mode where agents appear active
but make no progress, consuming context window and wall-clock time without useful output.

## Stall Detection Criteria

An agent is considered **stalled** when ALL of the following are true:

1. **No tool calls** for `--timeout` seconds (default: 5 minutes)
2. **Task status** is still `in_progress` (not `completed` or `failed`)
3. **No output growth** -- the agent's response buffer has not grown

## Integration Points

This skill is designed to be composed into `epic-team` wave dispatch as a monitoring
sidecar. It does NOT replace the dispatch mechanism -- it observes and reports.

### As a Composable Sub-Skill

```
# epic-team invokes watchdog after dispatching a wave
Skill(skill="onex:dispatch_watchdog", args="--epic-id OMN-2000 --timeout 300 --action report")
```

### Standalone Health Check

```
# Check if any agents in an epic run are stalled
/dispatch-watchdog --epic-id OMN-2000
```

## Detection Algorithm

```
for each active_task in epic_state.current_wave.tasks:
    last_activity = get_last_tool_call_timestamp(active_task)
    elapsed = now() - last_activity

    if elapsed > timeout:
        stall_detected(active_task)

        if action == "report":
            log_stall_event(active_task, elapsed)
            post_slack_warning(epic_id, active_task)

        elif action == "cancel":
            cancel_task(active_task)
            log_stall_event(active_task, elapsed, recovery="cancelled")

        elif action == "restart":
            cancel_task(active_task)
            redispatch_task(active_task)
            log_stall_event(active_task, elapsed, recovery="restarted")
```

## State File Schema

The watchdog reads from and writes to the epic state directory:

**Reads**: `$ONEX_STATE_DIR/epics/<epic_id>/state.yaml`
- `current_wave.tasks[]` -- list of active Task() dispatches
- `current_wave.dispatched_at` -- wave dispatch timestamp

**Writes**: `$ONEX_STATE_DIR/epics/<epic_id>/watchdog.json`
```json
{
  "schema_version": "1.0",
  "epic_id": "OMN-2000",
  "check_timestamp": "2026-03-29T10:00:00Z",
  "stalls_detected": [
    {
      "task_id": "task-abc123",
      "ticket_id": "OMN-2001",
      "last_activity": "2026-03-29T09:50:00Z",
      "elapsed_seconds": 600,
      "action_taken": "report|cancel|restart",
      "recovery_task_id": null
    }
  ],
  "healthy_tasks": ["task-def456", "task-ghi789"],
  "summary": {
    "total_tasks": 5,
    "healthy": 4,
    "stalled": 1,
    "recovered": 0
  }
}
```

## Recovery Strategies

| Strategy | When to Use | Risk |
|----------|-------------|------|
| `report` | Default. Alert human, do not intervene. | None -- observation only |
| `cancel` | Agent is clearly stuck (>15 min). Stop wasting tokens. | Ticket left incomplete |
| `restart` | Transient stall (context pollution). Fresh dispatch may succeed. | Duplicate work if agent was actually progressing slowly |

## Heuristics for False Positive Avoidance

Not all long pauses are stalls. The watchdog applies these filters:

1. **Rate limit backoff**: If the agent's last output mentions "rate limit" or "retry",
   extend the timeout by 2x before declaring a stall
2. **Large file operations**: If the agent is reading/writing files >10KB, allow extra time
3. **CI polling**: If the agent's last tool call was `gh run watch` or similar polling
   command, extend timeout to 10 minutes

## Slack Notifications

When a stall is detected and `action != report`, the watchdog posts to the epic's
Slack thread:

```
:warning: Agent stall detected in OMN-2000 wave 1
- Ticket: OMN-2001 (stalled for 8m 23s)
- Last activity: Read tool at 09:50 UTC
- Action: cancelled -- ticket will be retried in next wave
```

## Limitations

- **Cannot inspect agent internal state**: The watchdog observes task metadata and
  timestamps, not the agent's reasoning or context window usage
- **No cross-session monitoring**: Only monitors tasks dispatched within the current
  epic-team session
- **Polling-based**: Checks at intervals, not event-driven. Minimum detection latency
  equals `--check-interval`
