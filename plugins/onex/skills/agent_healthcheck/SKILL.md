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
    description: "Minutes of inactivity before stall detection triggers (default: 10)"
    required: false
  - name: --context-threshold-pct
    description: "Context window usage percentage that triggers preemptive recovery (default: 80)"
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

**Three stall detection heuristics:**

| Heuristic | Trigger Condition | Default Threshold |
|-----------|------------------|-------------------|
| Inactivity | No tool calls for N minutes | 10 minutes |
| Context overflow | Context window usage > N% | 80% |
| Rate limit | Agent reports rate-limit errors | Any rate-limit error |

**Recovery flow:**

```
Stall detected:
  1. Snapshot current progress to checkpoint file
     (using checkpoint protocol from OMN-6887)
  2. Summarize completed vs remaining work
  3. Terminate stalled agent (if possible)
  4. Relaunch fresh agent with:
     - Summary of completed work
     - List of remaining tasks
     - Checkpoint reference for state recovery
  5. Emit observability event for monitoring
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
(default: 10), the agent is considered stalled.

```python
def check_inactivity(agent_id: str, timeout_minutes: int = 10) -> dict:
    """Check if agent has been inactive beyond the timeout threshold.

    Returns:
        {"stalled": bool, "idle_minutes": float, "last_tool_call": str}
    """
    last_activity = get_agent_last_activity(agent_id)
    idle_minutes = (now_utc() - last_activity).total_seconds() / 60

    return {
        "stalled": idle_minutes > timeout_minutes,
        "idle_minutes": idle_minutes,
        "last_tool_call": last_activity.isoformat(),
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

### Checkpoint writing

On stall detection, write a checkpoint using the checkpoint protocol (OMN-6887):

```python
def write_recovery_checkpoint(
    ticket_id: str,
    completed_work: list[str],
    remaining_work: list[str],
    stall_reason: str,
) -> dict:
    """Write a recovery checkpoint for a stalled agent.

    Checkpoint is written to:
    $OMNI_HOME/.onex_state/pipeline_checkpoints/{ticket_id}/recovery-{timestamp}.yaml

    Returns:
        {"path": str, "timestamp": str}
    """
    checkpoint = {
        "schema_version": "1.0.0",
        "ticket_id": ticket_id,
        "timestamp_utc": now_utc().isoformat(),
        "stall_reason": stall_reason,
        "completed_work": completed_work,
        "remaining_work": remaining_work,
        "recovery_action": "relaunch_fresh_agent",
    }

    path = f".onex_state/pipeline_checkpoints/{ticket_id}/recovery-{now_utc().strftime('%Y%m%dT%H%M%S')}.yaml"
    write_yaml(path, checkpoint)

    return {"path": path, "timestamp": checkpoint["timestamp_utc"]}
```

### Agent relaunch

Relaunch a fresh agent with only the remaining work and a reference to the checkpoint.

```python
def relaunch_agent(
    ticket_id: str,
    checkpoint_path: str,
    remaining_tasks: list[str],
) -> None:
    """Relaunch a fresh agent for a stalled ticket.

    The new agent receives:
    - The checkpoint path (for state recovery)
    - Only remaining tasks (completed work is excluded)
    - A summary of what was completed (for context)
    """
    Task(
        subagent_type="onex:polymorphic-agent",
        description=f"Recovery relaunch for {ticket_id} (stall recovery)",
        prompt=f"""You are resuming work on {ticket_id} after a previous agent stalled.

    Recovery checkpoint: {checkpoint_path}
    Remaining tasks: {remaining_tasks}

    Read the checkpoint file for context on what was completed.
    Continue from where the previous agent left off.
    Do NOT re-do completed work.

    Execute: Skill(skill="onex:ticket_pipeline", args="{ticket_id} --skip-to implement")
    """,
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
| `stall_timeout_minutes` | `10` | Minutes of inactivity before stall detection |
| `context_threshold_pct` | `80` | Context usage percentage for preemptive recovery |
| `max_recovery_attempts` | `3` | Max relaunch attempts per ticket before escalating |
| `emit_healthcheck_events` | `true` | Emit Kafka events on health status changes |

---

## See Also

- `epic-team` skill (primary consumer of health-check)
- `checkpoint` skill (checkpoint protocol, OMN-6887)
- `ticket-pipeline` skill (resumed after recovery via --skip-to)
- `autopilot/SKILL.md` (headless cron pattern, OMN-6887)
