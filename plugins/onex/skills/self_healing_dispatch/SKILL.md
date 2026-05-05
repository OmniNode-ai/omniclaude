---
description: Self-healing orchestration wrapper — accepts ticket list or epic ID, groups by repo, dispatches via TeamCreate (enforced), monitors workers via agent_healthcheck, auto-recovers stalls with bounded retry (max 2 redispatches per task), logs all events to structured NDJSON.
version: 1.0.0
mode: full
level: advanced
debug: false
category: workflow
tags:
  - orchestration
  - self-healing
  - stall-recovery
  - team-create
  - epic-team
  - dispatch-enforcement
  - workstream-b
author: OmniClaude Team
composable: true
args:
  - name: --tickets
    description: "Comma-separated ticket IDs to orchestrate (e.g. OMN-1234,OMN-5678). Mutually exclusive with --epic-id."
    required: false
  - name: --epic-id
    description: "Linear epic ID. Decomposes the epic into child tickets via decompose_epic, then orchestrates. Mutually exclusive with --tickets."
    required: false
  - name: --repo-hints
    description: "JSON object mapping ticket IDs to repo names (e.g. '{\"OMN-1234\":\"omniclaude\"}'). Optional; unassigned tickets get their repo resolved from Linear metadata."
    required: false
  - name: --run-id
    description: "Correlation ID for this orchestration run. Auto-generated if omitted."
    required: false
  - name: --dry-run
    description: "Plan dispatch groups and emit log entry without launching workers. Default: false."
    required: false
inputs:
  - name: ticket_ids
    description: "List of Linear ticket IDs (OMN-XXXX format)"
  - name: epic_id
    description: "Linear epic ID to decompose into tickets"
outputs:
  - name: run_id
    description: "Unique correlation ID for this orchestration run"
  - name: groups
    description: "Dispatch groups: repo -> list of ticket IDs"
  - name: log_path
    description: "Path to NDJSON dispatch log for this run"
  - name: escalated
    description: "Ticket IDs escalated to Blocked (exceeded max redispatches)"
---

# /onex:self_healing_dispatch — Self-Healing Orchestration Wrapper

**Skill ID**: `onex:self_healing_dispatch` · **Ticket**: OMN-7259 · **Epic parent**: OMN-7253
**Workstream**: B Phase 3 — built on OMN-7255 (stall detection) + OMN-7257 (dispatch enforcement)

## Purpose

Single orchestration entrypoint that combines:
- **Phase 1 signals** — stall detection and bounded redispatch from `agent_healthcheck`
- **Phase 2 enforcement** — TeamCreate dispatch (not advisory) from the dispatch-mode guardrail

Handles workloads of ≤10 tickets across ≤4 repos without human intervention.

## Invocation

```
/onex:self_healing_dispatch --tickets OMN-1234,OMN-5678,OMN-9012
/onex:self_healing_dispatch --epic-id OMN-7253
/onex:self_healing_dispatch --epic-id OMN-7253 --dry-run
```

**Announce at start:**
```
[self_healing_dispatch] Starting orchestration run <run_id> | tickets: N | mode: <live|dry-run>
```

## Execution Protocol

### Phase 0 — Input Resolution

1. If `--tickets` given: parse and validate each as `OMN-\d+`. Fail fast on invalid IDs.
2. If `--epic-id` given: call `decompose_epic` to get child ticket list. Fail fast if decompose returns empty.
3. Exactly one of `--tickets` / `--epic-id` must be provided. Emit usage error and stop if neither or both.

```
ERROR: Provide exactly one of --tickets or --epic-id.
Usage:
  /onex:self_healing_dispatch --tickets OMN-1234,OMN-5678
  /onex:self_healing_dispatch --epic-id OMN-7253
```

### Phase 1 — Repo Grouping

Call the Python orchestrator:
```python
from omniclaude.hooks.self_healing_orchestrator import orchestrate, group_by_repo

result = orchestrate(
    ticket_ids=["OMN-1234", "OMN-5678"],
    epic_id="OMN-7253",   # or None
    repo_hints={"OMN-1234": "omniclaude"},  # or None
    run_id="orch-20260405T120000Z",
)
```

The orchestrator emits an `orchestration_planned` NDJSON event and returns a `OrchestratorResult`.

**Grouping rules:**
- Tickets with repo hints land in that repo's group.
- Tickets without hints: resolve from Linear ticket metadata (`labels` field or `team` field).
- Tickets that cannot be resolved land in the `unassigned` group — surface a warning and stop.

```
WARNING: Cannot resolve repo for OMN-9999. Provide --repo-hints or set the ticket's repo label in Linear before orchestrating.
```

### Phase 2 — TeamCreate Dispatch (enforced)

For each dispatch group, spawn a named worker via TeamCreate. **Never use a bare Agent() call** — the dispatch-mode guardrail (OMN-7257) will fire an advisory, and this skill enforces TeamCreate unconditionally.

```python
# Pseudo-code — executed by the skill entrypoint, not the Python module
team_name = f"orch-{run_id}"

for group in result.groups:
    prompt = build_team_dispatch_prompt(group, epic_id=result.epic_id)
    Agent(
        name=f"worker-{group.repo}-{run_id}",
        team_name=team_name,
        prompt=prompt,
    )
```

Log a `worker_dispatched` event per group:
```json
{"timestamp_utc":"...","event":"worker_dispatched","run_id":"...","repo":"omniclaude","tickets":["OMN-1234"]}
```

### Phase 3 — Monitoring and Stall Recovery

After dispatching all workers, enter a polling loop. Use `onex:agent_healthcheck` as a composable sub-skill to check each active worker:

```
Skill(skill="onex:agent_healthcheck", args="--ticket-id OMN-1234 --agent-id worker-omniclaude-orch-... --timeout-minutes 2 --max-redispatches 2")
```

**On stall detected (status == stalled or failed):**

```python
from omniclaude.hooks.self_healing_orchestrator import record_stall_recovery, build_stall_recovery_prompt

should_redispatch, attempt = record_stall_recovery(
    group=group,
    ticket_id=stalled_ticket_id,
    run_id=run_id,
    completed_tickets=completed_so_far,
)

if should_redispatch:
    prompt = build_stall_recovery_prompt(group, stalled_ticket_id, attempt, completed_so_far)
    Agent(
        name=f"recovery-{stalled_ticket_id}-attempt-{attempt}",
        team_name=team_name,
        prompt=prompt,
    )
else:
    # Exceeded MAX_REDISPATCHES (2) — escalate
    linear.save_issue(identifier=stalled_ticket_id, status="Blocked",
                      comment=f"Auto-blocked: stalled {attempt} times. See dispatch log.")
```

**Recovery prompt rules:**
- Include only remaining (uncompleted) tickets — never re-scope to the full original list.
- Include the checkpoint path if written by `agent_healthcheck`.
- Cap recovery at `MAX_REDISPATCHES = 2`. Third stall → escalate to Blocked.

### Phase 4 — Completion

Exit when all workers have returned `completed` or `escalated` status.

Emit final `orchestration_complete` event:
```json
{
  "timestamp_utc": "...",
  "event": "orchestration_complete",
  "run_id": "...",
  "total_tickets": 5,
  "stalls_recovered": 1,
  "escalated": [],
  "elapsed_seconds": 430
}
```

Print final summary:
```
[self_healing_dispatch] Run <run_id> complete.
  Tickets: 5 | Recovered stalls: 1 | Escalated: 0
  Log: $ONEX_STATE_DIR/dispatch-log/2026-04-05.ndjson
```

## Constraints

| Constraint | Value |
|------------|-------|
| Max tickets | 10 |
| Max repos | 4 |
| Max redispatches per ticket | 2 |
| Stall threshold | 2 minutes (delegated to agent_healthcheck) |
| Dispatch mode | TeamCreate only — bare Agent() forbidden |

## Event Log Schema

All events append to `$ONEX_STATE_DIR/dispatch-log/{YYYY-MM-DD}.ndjson`. One JSON object per line, never pretty-printed.

| Event | Key Fields |
|-------|------------|
| `orchestration_planned` | `run_id`, `epic_id`, `ticket_count`, `group_count`, `repos` |
| `worker_dispatched` | `run_id`, `repo`, `tickets` |
| `stall_recovery_dispatched` | `run_id`, `ticket_id`, `redispatch_attempt`, `max_redispatches` |
| `escalated_to_blocked` | `run_id`, `ticket_id`, `attempt_count` |
| `orchestration_complete` | `run_id`, `total_tickets`, `stalls_recovered`, `escalated`, `elapsed_seconds` |

## Dry-Run Mode

When `--dry-run` is set:
- Run Phases 0 and 1 (resolve + group).
- Print the planned dispatch groups.
- Emit `orchestration_planned` event.
- Do NOT launch any workers (skip Phases 2–4).

```
[self_healing_dispatch] DRY RUN — no workers launched.
Planned groups:
  omniclaude: OMN-1234, OMN-5678
  omnibase_core: OMN-9012
Log: $ONEX_STATE_DIR/dispatch-log/2026-04-05.ndjson
```

## Backing Module

All grouping, prompt generation, stall accounting, and log emission logic lives in:

```
src/omniclaude/hooks/self_healing_orchestrator.py
```

Do not duplicate this logic inline. Import and call the module functions.

## See Also

- `onex:agent_healthcheck` — stall detection sub-skill (OMN-7255 backing node)
- `onex:dispatch_watchdog` — epic-level watchdog for larger wave runs
- `onex:epic_team` — full epic orchestration (use for >10 tickets or >4 repos)
