---
description: "Dispatch-only shim for agent stall detection and recovery. All detection and recovery logic lives in node_worker_stall_recovery (omnimarket, OMN-9403). The skill parses args, builds the input envelope, dispatches to the node, and renders the receipt."
version: 2.0.0
mode: full
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
  - dispatch-only
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
  - name: --dry-run
    description: "Check health without taking any recovery action (default: false)"
    required: false
inputs:
  - name: ticket_id
    description: "Linear ticket identifier"
  - name: agent_id
    description: "Dispatched agent/task identifier"
outputs:
  - name: status
    description: "healthy | stalled | recovered | failed | escalated"
  - name: stall_reason
    description: "Reason for stall detection (empty if healthy)"
  - name: checkpoint_path
    description: "Path to checkpoint file written on recovery"
  - name: redispatch_count
    description: "Number of redispatches performed"
  - name: error
    description: "Error message if status == failed"
---

# /onex:agent_healthcheck — dispatch-only shim

**Skill ID**: `onex:agent_healthcheck` · **Backing node**: `omnimarket/src/omnimarket/nodes/node_worker_stall_recovery/` · **Ticket**: OMN-10428 · **Epic**: OMN-10424

## Routing Contract

- **Classification**: Deterministic
- **Dispatch**: single invocation of `node_worker_stall_recovery`
- **No inline stall detection**: all heuristics (inactivity, context overflow, rate limits, Bash long-timeout) live in the handler, not this skill
- **Routing failure handling**: on dispatch failure, raise `SkillRoutingError` — surface it directly, do not produce prose

## Dispatch

This skill is a **thin shim** — all stall detection and recovery logic lives in
`node_worker_stall_recovery` (omnimarket, OMN-9403).

```bash
INPUT_JSON='{"ticket_id":"<ticket_id>","agent_id":"<agent_id>","timeout_minutes":2,"context_threshold_pct":80,"max_redispatches":2,"dry_run":true}'
uv run onex run-node node_worker_stall_recovery --input "${INPUT_JSON}"
```

The node returns `ModelStallRecoveryResult`:
- `status`: `healthy | stalled | recovered | failed | escalated`
- `stall_reason`: non-empty string if stalled
- `checkpoint_path`: path written on recovery
- `redispatch_count`: number of redispatches performed
- `error`: error message if `status == failed`

Checkpoint and relaunch semantics remain governed by the OMN-6887 recovery
protocol. The backing node writes the recovery checkpoint, captures completed
and remaining work, and relaunches or redispatches a fresh agent when recovery
is required; this shim only forwards the invocation and returns the receipt.

Surface the JSON output directly. Do not implement detection inline.

**Backing node:** `omnimarket/src/omnimarket/nodes/node_worker_stall_recovery/`
**Contract:** `node_worker_stall_recovery/contract.yaml`
