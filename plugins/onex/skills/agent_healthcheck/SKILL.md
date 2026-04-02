---
description: Agent health-check and stall detection for multi-agent orchestration. Monitors dispatched sub-agents for signs of stalling (no tool calls, context overflow, rate limits), snapshots progress to checkpoint files, and relaunches fresh agents with remaining work.
mode: full
version: 1.0.0
level: advanced
debug: false
category: infrastructure
tags:
  - healthcheck
  - monitoring
  - stall-detection
  - checkpoint
  - recovery
  - epic-team
author: OmniClaude Team
composable: true
args:
  - name: --ticket-id
    description: "Ticket ID being monitored (e.g., OMN-1234)"
    required: true
  - name: --agent-id
    description: "Agent/task ID to monitor"
    required: true
  - name: --timeout-minutes
    description: "Minutes of inactivity before stall detection triggers (default: 2)"
    required: false
  - name: --context-threshold-pct
    description: "Context window usage percentage that triggers preemptive recovery (default: 80)"
    required: false
  - name: --max-redispatches
    description: "Maximum redispatch attempts per task before escalation (default: 2)"
    required: false
inputs:
  - name: ticket_id
    description: "Linear ticket identifier"
  - name: agent_id
    description: "Dispatched agent/task identifier"
outputs:
  - name: status
    description: "healthy | stalled | recovered | failed"
  - name: stall_reason
    description: "Reason for stall detection (empty if healthy)"
  - name: checkpoint_path
    description: "Path to checkpoint file written on recovery"
---

# Agent Health-Check

**Skill ID**: `onex:agent_healthcheck`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-6889
**Epic**: OMN-6886

---

## Overview

Provides stall detection and recovery for sub-agents dispatched by epic-team and other
multi-agent orchestrators. Replaces the simple circuit-breaker timeout in epic-team
with a more sophisticated health monitoring system.

**Four stall detection heuristics:**

| Heuristic | Trigger Condition | Default Threshold |
|-----------|------------------|-------------------|
| Inactivity | No tool calls for N minutes | 2 minutes |
| Bash long-timeout | Last tool call was Bash with timeout >120s | Extend threshold to timeout + 60s |
| Context overflow | Context window usage > N% | 80% |
| Rate limit | Agent reports rate-limit errors | Any rate-limit error |

**Recovery flow:**

```
Stall detected:
  1. Snapshot current progress to checkpoint file
     (using checkpoint protocol from OMN-6887)
  2. Summarize completed vs remaining work
  3. Kill stalled agent via SendMessage shutdown_request
  4. Log stall event to .onex_state/dispatch-log/{date}.ndjson
  5. Relaunch fresh agent with:
     - Summary of completed work
     - Narrower scope (only remaining tasks)
     - Checkpoint reference for state recovery
  6. Track redispatch count — max 2 per task
  7. On 3rd stall: move ticket to Blocked in Linear + write friction event
```

---

## Integration with epic-team

The epic-team skill references agent_healthcheck for stall detection during wave
execution. When a sub-agent is dispatched via `Task()`, the orchestrator monitors
for stall signals between polling intervals.

### Detection during wave monitoring

```python
# In epic-team's monitoring loop:
for ticket_id, task_info in active_tasks.items():
    agent_status = check_agent_health(
        ticket_id=ticket_id,
        agent_id=task_info["agent_id"],
        timeout_minutes=DISPATCH_TIMEOUT_MINUTES,
        context_threshold_pct=80,
    )

    if agent_status["status"] == "stalled":
        # Write checkpoint with completed/remaining work
        checkpoint = write_recovery_checkpoint(
            ticket_id=ticket_id,
            completed_work=agent_status["completed_summary"],
            remaining_work=agent_status["remaining_tasks"],
            stall_reason=agent_status["stall_reason"],
        )

        # Relaunch with fresh context
        relaunch_agent(
            ticket_id=ticket_id,
            checkpoint_path=checkpoint["path"],
            remaining_tasks=agent_status["remaining_tasks"],
        )
```

### Stall detection heuristics

#### 1. Inactivity detection

Monitor the agent's last tool call timestamp. If no tool calls for `timeout_minutes`
(default: 2), the agent is considered stalled.

```python
def check_inactivity(agent_id: str, timeout_minutes: int = 2) -> dict:
    """Check if agent has been inactive beyond the timeout threshold.

    Uses TaskGet to query the agent's current status and last activity.

    Returns:
        {"stalled": bool, "idle_minutes": float, "last_tool_call": str}
    """
    task_status = TaskGet(task_id=agent_id)
    last_activity = parse_iso(task_status["last_tool_call_at"])
    idle_minutes = (now_utc() - last_activity).total_seconds() / 60

    # Apply Bash long-timeout exemption
    effective_timeout = timeout_minutes
    if task_status.get("last_tool_name") == "Bash":
        bash_timeout_ms = task_status.get("last_tool_timeout_ms", 0)
        if bash_timeout_ms > 120_000:
            # Extend stall threshold to bash timeout + 60s buffer
            effective_timeout = max(timeout_minutes, (bash_timeout_ms / 1000 + 60) / 60)

    return {
        "stalled": idle_minutes > effective_timeout,
        "idle_minutes": idle_minutes,
        "effective_timeout_minutes": effective_timeout,
        "last_tool_call": last_activity.isoformat(),
        "bash_timeout_exemption": effective_timeout > timeout_minutes,
    }
```

#### 2. Context overflow detection

Check the agent's context window usage. If above the threshold, preemptively
recover before the agent hits a hard limit.

```python
def check_context_usage(agent_id: str, threshold_pct: int = 80) -> dict:
    """Check if agent's context window is approaching capacity.

    Returns:
        {"stalled": bool, "usage_pct": float, "tokens_used": int, "tokens_max": int}
    """
    usage = get_agent_context_usage(agent_id)
    pct = (usage["tokens_used"] / usage["tokens_max"]) * 100

    return {
        "stalled": pct > threshold_pct,
        "usage_pct": pct,
        "tokens_used": usage["tokens_used"],
        "tokens_max": usage["tokens_max"],
    }
```

#### 3. Rate-limit detection

Detect rate-limit errors from the agent's output stream.

```python
def check_rate_limits(agent_id: str) -> dict:
    """Check if agent has encountered rate-limit errors.

    Returns:
        {"stalled": bool, "rate_limit_count": int, "last_error": str}
    """
    errors = get_agent_errors(agent_id)
    rate_limits = [e for e in errors if "rate" in e.lower() or "429" in e]

    return {
        "stalled": len(rate_limits) > 0,
        "rate_limit_count": len(rate_limits),
        "last_error": rate_limits[-1] if rate_limits else "",
    }
```

---

## Recovery Protocol

### Stall event logging

All stall events are logged as NDJSON to `.onex_state/dispatch-log/{date}.ndjson`.
Each line is a self-contained JSON object:

```json
{
  "timestamp_utc": "2026-04-02T14:30:00Z",
  "event": "stall_detected",
  "ticket_id": "OMN-1234",
  "agent_id": "task-abc123",
  "stall_reason": "inactivity",
  "idle_minutes": 3.2,
  "bash_timeout_exemption": false,
  "redispatch_attempt": 1,
  "max_redispatches": 2,
  "action": "kill_and_redispatch"
}
```

Events with `"event": "escalated_to_blocked"` indicate the task hit the redispatch
limit and was moved to Blocked in Linear.

### Kill protocol

On stall detection, the stalled agent is terminated before redispatch:

```python
def kill_stalled_agent(agent_id: str, ticket_id: str) -> None:
    """Kill a stalled agent via SendMessage shutdown_request.

    Sends a shutdown_request message to the stalled agent, then logs the kill.
    """
    SendMessage(
        to=agent_id,
        message=json.dumps({"type": "shutdown_request", "reason": "stall_detected"}),
    )
    log_dispatch_event(
        event="agent_killed",
        ticket_id=ticket_id,
        agent_id=agent_id,
    )
```

### Checkpoint writing

On stall detection, write a checkpoint using the checkpoint protocol (OMN-6887):

```python
def write_recovery_checkpoint(
    ticket_id: str,
    completed_work: list[str],
    remaining_work: list[str],
    stall_reason: str,
    redispatch_attempt: int,
) -> dict:
    """Write a recovery checkpoint for a stalled agent.

    Checkpoint is written to:
    $OMNI_HOME/.onex_state/pipeline_checkpoints/{ticket_id}/recovery-{timestamp}.yaml

    Returns:
        {"path": str, "timestamp": str}
    """
    checkpoint = {
        "schema_version": "1.1.0",
        "ticket_id": ticket_id,
        "timestamp_utc": now_utc().isoformat(),
        "stall_reason": stall_reason,
        "completed_work": completed_work,
        "remaining_work": remaining_work,
        "redispatch_attempt": redispatch_attempt,
        "recovery_action": "relaunch_fresh_agent",
    }

    path = f".onex_state/pipeline_checkpoints/{ticket_id}/recovery-{now_utc().strftime('%Y%m%dT%H%M%S')}.yaml"
    write_yaml(path, checkpoint)

    return {"path": path, "timestamp": checkpoint["timestamp_utc"]}
```

### Agent redispatch with narrower scope

Redispatch a fresh agent with only the remaining work and a narrower task scope.
The redispatched agent receives a summary of what was completed and explicit
instructions to NOT re-read large files or repeat completed steps.

```python
def redispatch_agent(
    ticket_id: str,
    checkpoint_path: str,
    remaining_tasks: list[str],
    redispatch_attempt: int,
    max_redispatches: int = 2,
) -> None:
    """Redispatch a fresh agent for a stalled ticket with narrower scope.

    Enforces max redispatch limit. On exceeding the limit, escalates to
    Blocked status in Linear and writes a friction event.
    """
    if redispatch_attempt > max_redispatches:
        escalate_to_blocked(ticket_id, checkpoint_path, redispatch_attempt)
        return

    log_dispatch_event(
        event="redispatch",
        ticket_id=ticket_id,
        redispatch_attempt=redispatch_attempt,
        remaining_tasks=remaining_tasks,
    )

    Task(
        description=f"Recovery redispatch #{redispatch_attempt} for {ticket_id}",
        prompt=f"""You are resuming work on {ticket_id} after a previous agent stalled.
    This is redispatch attempt {redispatch_attempt} of {max_redispatches}.

    Recovery checkpoint: {checkpoint_path}
    Remaining tasks (ONLY do these): {remaining_tasks}

    IMPORTANT:
    - Read the checkpoint file for context on what was completed
    - Do NOT re-do completed work
    - Use targeted file reads (offset/limit) — avoid reading entire large files
    - If you get stuck on the same step that stalled the previous agent, write a
      diagnosis doc and stop rather than spinning

    Execute: Skill(skill="onex:ticket_pipeline", args="{ticket_id} --skip-to implement")
    """,
    )
```

### Escalation policy

When a task exceeds `max_redispatches` (default: 2), it is escalated:

```python
def escalate_to_blocked(
    ticket_id: str,
    checkpoint_path: str,
    attempt_count: int,
) -> None:
    """Escalate a repeatedly-stalling task to Blocked in Linear.

    Actions:
    1. Move ticket to Blocked status in Linear
    2. Add comment with stall history and checkpoint reference
    3. Write friction event to .onex_state/friction/
    4. Log escalation event to dispatch log
    """
    # Move to Blocked in Linear
    mcp__linear_server__save_issue(
        identifier=ticket_id,
        status="Blocked",
        comment=f"Auto-blocked: agent stalled {attempt_count} times. "
                f"Checkpoint: {checkpoint_path}. Requires manual investigation.",
    )

    # Write friction event
    friction_path = f".onex_state/friction/{date_today()}-agent-stall-escalation-{ticket_id.lower()}.md"
    write_file(friction_path, f"""# Agent Stall Escalation: {ticket_id}

## Summary
Agent stalled {attempt_count} times on {ticket_id}, exceeding the max redispatch
limit of 2. Ticket moved to Blocked in Linear.

## Stall History
- See dispatch log: .onex_state/dispatch-log/{date_today()}.ndjson
- Recovery checkpoint: {checkpoint_path}

## Root Cause Hypothesis
Agent likely hitting context exhaustion or encountering a blocking issue that
persists across redispatches (e.g., missing dependency, broken test, infra issue).

## Recommended Action
Manual investigation required. Read the checkpoint and dispatch log to determine
whether the issue is agent-side (scope too large) or environment-side (broken infra).
""")

    log_dispatch_event(
        event="escalated_to_blocked",
        ticket_id=ticket_id,
        attempt_count=attempt_count,
        friction_path=friction_path,
    )
```

---

## Observability

On stall detection, emit a Kafka event for monitoring dashboards:

**Topic**: `onex.evt.omniclaude.agent-healthcheck.v1`

**Event schema:**
```yaml
type: agent_healthcheck
ticket_id: OMN-1234
agent_id: task-abc123
status: stalled | recovered | healthy
stall_reason: inactivity | context_overflow | rate_limit
idle_minutes: 15.2
context_usage_pct: 85.0
checkpoint_path: .onex_state/pipeline_checkpoints/OMN-1234/recovery-20260328T220000.yaml
recovery_action: relaunch_fresh_agent | none
timestamp_utc: 2026-03-28T22:00:00Z
```

---

## Policy Switches

| Switch | Default | Description |
|--------|---------|-------------|
| `stall_timeout_minutes` | `2` | Minutes of inactivity before stall detection |
| `bash_long_timeout_buffer_seconds` | `60` | Extra seconds added to stall threshold when Bash timeout >120s |
| `context_threshold_pct` | `80` | Context usage percentage for preemptive recovery |
| `max_redispatches` | `2` | Max redispatch attempts per task before escalating to Blocked |
| `emit_healthcheck_events` | `true` | Emit Kafka events on health status changes |
| `dispatch_log_dir` | `.onex_state/dispatch-log/` | Directory for NDJSON dispatch event logs |

---

## See Also

- `epic-team` skill (primary consumer of health-check)
- `checkpoint` skill (checkpoint protocol, OMN-6887)
- `ticket-pipeline` skill (resumed after recovery via --skip-to)
- `autopilot/SKILL.md` (headless cron pattern, OMN-6887)
