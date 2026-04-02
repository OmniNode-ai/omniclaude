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
    description: "Stall timeout in seconds (default: 120 = 2 minutes)"
    required: false
  - name: --action
    description: "Recovery action on stall: report | cancel | redispatch (default: redispatch)"
    required: false
  - name: --check-interval
    description: "Polling interval in seconds (default: 30)"
    required: false
  - name: --max-redispatches
    description: "Max redispatch attempts per task before escalation (default: 2)"
    required: false
---

# Agent Dispatch Watchdog

## Purpose

Detect when dispatched Task() subagents stall (stop producing tool calls) and trigger
recovery actions. This addresses the recurring failure mode where agents appear active
but make no progress, consuming context window and wall-clock time without useful output.

## Stall Detection Criteria

An agent is considered **stalled** when ALL of the following are true:

1. **No tool calls** for `--timeout` seconds (default: 120 = 2 minutes)
2. **Task status** is still `in_progress` (not `completed` or `failed`)
3. **No output growth** -- the agent's response buffer has not grown

### Bash Long-Timeout Exemption

If the agent's last tool call was `Bash` with a timeout parameter >120 seconds
(e.g., a long-running build, test suite, or deployment), the stall threshold is
extended to `bash_timeout + 60s`. This prevents false positives from legitimate
long-running shell commands.

The exemption is detected by inspecting the last tool call metadata from TaskGet:
- `last_tool_name == "Bash"` AND `last_tool_timeout_ms > 120000`
- Extended threshold: `(last_tool_timeout_ms / 1000) + 60` seconds

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
    task_status = TaskGet(task_id=active_task.id)
    last_activity = get_last_tool_call_timestamp(task_status)
    elapsed = now() - last_activity

    # Apply Bash long-timeout exemption
    effective_timeout = timeout
    if task_status.last_tool_name == "Bash" and task_status.last_tool_timeout_ms > 120000:
        effective_timeout = max(timeout, task_status.last_tool_timeout_ms / 1000 + 60)

    if elapsed > effective_timeout:
        stall_detected(active_task)
        redispatch_count = get_redispatch_count(active_task.ticket_id)

        # Log stall event to NDJSON dispatch log
        log_dispatch_event(
            event="stall_detected",
            ticket_id=active_task.ticket_id,
            agent_id=active_task.id,
            stall_reason="inactivity",
            idle_seconds=elapsed,
            bash_timeout_exemption=(effective_timeout > timeout),
            redispatch_attempt=redispatch_count + 1,
        )

        if action == "report":
            log_stall_event(active_task, elapsed)

        elif action == "cancel":
            SendMessage(to=active_task.id, message='{"type":"shutdown_request"}')
            log_stall_event(active_task, elapsed, recovery="cancelled")

        elif action == "redispatch":
            if redispatch_count >= max_redispatches:
                # Escalation: move to Blocked + write friction event
                escalate_to_blocked(active_task.ticket_id, redispatch_count)
            else:
                # Kill stalled agent
                SendMessage(to=active_task.id, message='{"type":"shutdown_request"}')
                # Redispatch with narrower scope
                remaining = summarize_remaining_work(active_task)
                redispatch_with_narrow_scope(active_task, remaining, redispatch_count + 1)
```

## State File Schema

The watchdog reads from and writes to the epic state directory:

**Reads**: `$ONEX_STATE_DIR/epics/<epic_id>/state.yaml`
- `current_wave.tasks[]` -- list of active Task() dispatches
- `current_wave.dispatched_at` -- wave dispatch timestamp

**Writes**: `$ONEX_STATE_DIR/epics/<epic_id>/watchdog.json`
```json
{
  "schema_version": "1.1",
  "epic_id": "OMN-2000",
  "check_timestamp": "2026-04-02T10:00:00Z",
  "stalls_detected": [
    {
      "task_id": "task-abc123",
      "ticket_id": "OMN-2001",
      "last_activity": "2026-04-02T09:58:00Z",
      "elapsed_seconds": 145,
      "bash_timeout_exemption": false,
      "action_taken": "redispatch",
      "redispatch_attempt": 1,
      "recovery_task_id": "task-xyz789"
    }
  ],
  "healthy_tasks": ["task-def456", "task-ghi789"],
  "blocked_tasks": ["OMN-2003"],
  "summary": {
    "total_tasks": 5,
    "healthy": 3,
    "stalled": 1,
    "blocked": 1,
    "redispatched": 1
  }
}
```

## Recovery Strategies

| Strategy | When to Use | Risk |
|----------|-------------|------|
| `report` | Observation only. Log event, do not intervene. | None -- observation only |
| `cancel` | Agent is clearly stuck. Stop wasting tokens. | Ticket left incomplete |
| `redispatch` | Default. Kill stalled agent, redispatch with narrower scope. | Duplicate work if agent was actually progressing slowly |

### Targeted Redispatch

When `action == "redispatch"`, the watchdog:

1. **Kills** the stalled agent via `SendMessage` with `{"type": "shutdown_request"}`
2. **Summarizes** remaining work from the checkpoint/task state
3. **Redispatches** a fresh agent with:
   - Only the remaining (uncompleted) tasks
   - A summary of what was already done
   - Instructions to use targeted reads (offset/limit) to avoid context exhaustion
   - The checkpoint path for state recovery

```
def redispatch_with_narrow_scope(task, remaining_work, attempt):
    """Redispatch with narrower scope to avoid repeating the stall."""
    checkpoint = write_recovery_checkpoint(
        ticket_id=task.ticket_id,
        completed_work=task.completed_items,
        remaining_work=remaining_work,
        stall_reason="inactivity",
        redispatch_attempt=attempt,
    )

    Agent(
        name=f"recovery-{task.ticket_id}-attempt-{attempt}",
        team_name=task.team_name,
        prompt=f"""Recovery redispatch #{attempt} for {task.ticket_id}.

        Checkpoint: {checkpoint["path"]}
        Remaining work (ONLY do these): {remaining_work}

        RULES:
        - Do NOT re-do completed work (read checkpoint for details)
        - Use targeted file reads (offset/limit) to avoid context exhaustion
        - If stuck on the same step, write a diagnosis doc and stop
        """,
    )
```

### Escalation Policy

When a task exceeds `--max-redispatches` (default: 2):

1. **Move ticket to Blocked** in Linear with a comment explaining the stall history
2. **Write a friction event** to `.onex_state/friction/` with:
   - Ticket ID and stall count
   - Links to dispatch log and checkpoint
   - Root cause hypothesis
3. **Log escalation** to `.onex_state/dispatch-log/{date}.ndjson`

```
def escalate_to_blocked(ticket_id, attempt_count):
    """Escalate a repeatedly-stalling task."""
    # Move to Blocked in Linear
    linear.save_issue(
        identifier=ticket_id,
        status="Blocked",
        comment=f"Auto-blocked: agent stalled {attempt_count} times. "
                "Requires manual investigation. See dispatch log.",
    )

    # Write friction event
    friction_path = f".onex_state/friction/{date_today()}-stall-escalation-{ticket_id.lower()}.md"
    write_friction_event(friction_path, ticket_id, attempt_count)

    # Log to dispatch log
    log_dispatch_event(
        event="escalated_to_blocked",
        ticket_id=ticket_id,
        attempt_count=attempt_count,
        friction_path=friction_path,
    )
```

## NDJSON Dispatch Log

All watchdog events are appended to `.onex_state/dispatch-log/{YYYY-MM-DD}.ndjson`.
One JSON object per line, never pretty-printed.

**Event types:**

| Event | When | Key Fields |
|-------|------|------------|
| `stall_detected` | Agent exceeds inactivity threshold | `ticket_id`, `agent_id`, `idle_seconds`, `bash_timeout_exemption` |
| `agent_killed` | Agent terminated via shutdown_request | `ticket_id`, `agent_id` |
| `redispatch` | Fresh agent launched with narrower scope | `ticket_id`, `redispatch_attempt`, `remaining_tasks` |
| `escalated_to_blocked` | Max redispatches exceeded | `ticket_id`, `attempt_count`, `friction_path` |
| `healthy` | Periodic health check passed | `ticket_id`, `agent_id`, `idle_seconds` |

**Schema:**
```json
{
  "timestamp_utc": "2026-04-02T14:30:00Z",
  "event": "stall_detected",
  "ticket_id": "OMN-1234",
  "agent_id": "task-abc123",
  "stall_reason": "inactivity",
  "idle_seconds": 145,
  "bash_timeout_exemption": false,
  "redispatch_attempt": 1,
  "max_redispatches": 2,
  "action_taken": "redispatch"
}
```

## Friction Event Schema

Friction events written on escalation follow the standard friction format:

**Path**: `.onex_state/friction/{YYYY-MM-DD}-stall-escalation-{ticket-id}.md`

```markdown
# Agent Stall Escalation: {TICKET_ID}

## Summary
Agent stalled {N} times, exceeding max redispatch limit of 2.

## Evidence
- Dispatch log: .onex_state/dispatch-log/{date}.ndjson
- Checkpoint: .onex_state/pipeline_checkpoints/{ticket_id}/recovery-*.yaml

## Root Cause Hypothesis
[Auto-generated based on stall pattern — context exhaustion, blocking dependency, etc.]

## Recommended Action
Manual investigation required.
```

## Heuristics for False Positive Avoidance

Not all long pauses are stalls. The watchdog applies these filters:

1. **Bash long-timeout exemption**: If the agent's last tool call was `Bash` with
   timeout >120s, extend the stall threshold to `bash_timeout + 60s`
2. **Rate limit backoff**: If the agent's last output mentions "rate limit" or "retry",
   extend the timeout by 2x before declaring a stall
3. **CI polling**: If the agent's last tool call was `gh run watch` or similar polling
   command, extend timeout to 10 minutes

## Limitations

- **Cannot inspect agent internal state**: The watchdog observes task metadata and
  timestamps, not the agent's reasoning or context window usage
- **No cross-session monitoring**: Only monitors tasks dispatched within the current
  epic-team session
- **Polling-based**: Checks at intervals, not event-driven. Minimum detection latency
  equals `--check-interval`
