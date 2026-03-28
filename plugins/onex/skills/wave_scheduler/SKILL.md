---
description: Dependency-aware wave scheduler for parallel agent dispatch. Reads plan files, builds a dependency DAG from ticket relationships, computes execution waves with configurable max concurrency, dispatches parallel agents per wave, and serializes dependent work. Integrates with agent_healthcheck for stall detection and cross-repo locks for conflict prevention.
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags:
  - wave
  - scheduler
  - parallel
  - dispatch
  - dependency
  - dag
  - epic-team
author: OmniClaude Team
composable: true
args:
  - name: plan_file
    description: "Path to plan file with ticket definitions and depends_on fields"
    required: true
  - name: --max-concurrency
    description: "Maximum number of parallel agents per wave (default: 6)"
    required: false
  - name: --dry-run
    description: "Compute waves and log dispatch plan without executing (default: false)"
    required: false
  - name: --resume
    description: "Resume from persisted wave state (skip completed tickets)"
    required: false
inputs:
  - name: plan_file
    description: "Path to plan YAML with ticket definitions"
outputs:
  - name: status
    description: "completed | partial | failed"
  - name: waves_completed
    description: "Number of waves that completed successfully"
  - name: tickets_completed
    description: "Number of tickets that completed"
  - name: tickets_failed
    description: "Number of tickets that failed"
  - name: tickets_blocked
    description: "Number of tickets blocked by failed dependencies"
---

# Wave Scheduler

**Skill ID**: `onex:wave_scheduler`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-6890
**Epic**: OMN-6886

---

## Dispatch Requirement

When invoked, your FIRST and ONLY action is to dispatch to a polymorphic-agent. Do NOT read
files, run bash, or take any other action before dispatching.

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Run wave-scheduler for <plan_file>",
  prompt="Run the wave-scheduler skill. <full context and args>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

---

## Overview

Replaces ad-hoc parallel dispatch in epic-team with a deterministic, dependency-aware
wave execution model. Given a plan file with explicit `depends_on` fields, the scheduler:

1. **Parses** the plan file to extract ticket definitions and dependencies
2. **Builds** a directed acyclic graph (DAG) of ticket dependencies
3. **Validates** the DAG (no cycles, all dependencies exist)
4. **Computes** execution waves using topological sort with level grouping
5. **Dispatches** parallel agents per wave (up to max_concurrency)
6. **Monitors** agent health during execution (via agent_healthcheck, OMN-6889)
7. **Reports** completed/failed/blocked per wave

---

## Plan File Format

The scheduler accepts plan files in YAML format with this schema:

```yaml
# plan.yaml
epic_id: OMN-6886
title: "Insights Action Plan 2026-03-28"

tickets:
  - id: OMN-6887
    title: "Implement checkpoint-based pipeline recovery"
    repo: omniclaude
    depends_on: []

  - id: OMN-6888
    title: "Encode architectural invariants"
    repo: omniclaude
    depends_on: []

  - id: OMN-6889
    title: "Build agent health-check"
    repo: omniclaude
    depends_on: [OMN-6887]

  - id: OMN-6890
    title: "Implement wave scheduler"
    repo: omniclaude
    depends_on: [OMN-6889]
```

---

## DAG Construction

```python
def build_dependency_dag(tickets: list[dict]) -> dict[str, list[str]]:
    """Build a dependency DAG from ticket definitions.

    Args:
        tickets: List of ticket dicts with 'id' and 'depends_on' fields.

    Returns:
        Adjacency list: {ticket_id: [dependent_ticket_ids]}

    Raises:
        ValueError: If a cycle is detected or a dependency references a
            ticket not in the plan.
    """
    # Build adjacency list (dependency -> dependents)
    dag = {t["id"]: [] for t in tickets}
    in_degree = {t["id"]: 0 for t in tickets}

    for ticket in tickets:
        for dep in ticket.get("depends_on", []):
            if dep not in dag:
                raise ValueError(
                    f"Ticket {ticket['id']} depends on {dep} which is not in the plan"
                )
            dag[dep].append(ticket["id"])
            in_degree[ticket["id"]] += 1

    # Cycle detection via Kahn's algorithm (see compute_waves)
    return dag, in_degree
```

---

## Wave Computation

```python
def compute_waves(
    dag: dict[str, list[str]],
    in_degree: dict[str, int],
    max_concurrency: int = 6,
) -> list[list[str]]:
    """Compute execution waves using topological sort with level grouping.

    Each wave contains tickets whose dependencies have all been satisfied.
    Waves are capped at max_concurrency tickets.

    Args:
        dag: Adjacency list from build_dependency_dag.
        in_degree: In-degree count per ticket.
        max_concurrency: Max tickets per wave.

    Returns:
        List of waves, where each wave is a list of ticket IDs.

    Raises:
        ValueError: If a cycle is detected (not all tickets can be scheduled).
    """
    from collections import deque

    # Initialize queue with tickets that have no dependencies
    queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
    waves = []
    scheduled_count = 0

    while queue:
        # Take up to max_concurrency tickets for this wave
        wave = []
        next_queue = deque()

        while queue and len(wave) < max_concurrency:
            wave.append(queue.popleft())

        waves.append(wave)
        scheduled_count += len(wave)

        # Reduce in-degree for dependents of completed tickets
        for tid in wave:
            for dependent in dag.get(tid, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_queue.append(dependent)

        queue = next_queue

    # Cycle detection
    total_tickets = len(dag)
    if scheduled_count < total_tickets:
        unscheduled = [tid for tid, deg in in_degree.items() if deg > 0]
        raise ValueError(
            f"Cycle detected: {len(unscheduled)} tickets cannot be scheduled: {unscheduled}"
        )

    return waves
```

---

## Wave Execution

```python
def execute_waves(
    waves: list[list[str]],
    tickets: dict[str, dict],
    dry_run: bool = False,
) -> dict:
    """Execute waves sequentially, tickets within each wave in parallel.

    Args:
        waves: List of waves from compute_waves.
        tickets: Ticket definitions keyed by ID.
        dry_run: Log dispatch plan without executing.

    Returns:
        Execution report with per-wave and per-ticket status.
    """
    report = {
        "status": "completed",
        "waves_completed": 0,
        "tickets_completed": 0,
        "tickets_failed": 0,
        "tickets_blocked": 0,
        "wave_results": [],
    }

    failed_tickets = set()

    for wave_idx, wave in enumerate(waves):
        log(f"Wave {wave_idx}: dispatching {len(wave)} tickets: {wave}")

        # Check if any ticket in this wave is blocked by a failed dependency
        blocked = []
        dispatchable = []
        for tid in wave:
            deps = tickets[tid].get("depends_on", [])
            if any(d in failed_tickets for d in deps):
                blocked.append(tid)
                report["tickets_blocked"] += 1
            else:
                dispatchable.append(tid)

        if blocked:
            log(f"  Blocked by failed dependencies: {blocked}")

        if dry_run:
            log(f"  [DRY RUN] Would dispatch: {dispatchable}")
            report["wave_results"].append({
                "wave": wave_idx,
                "dispatched": dispatchable,
                "blocked": blocked,
                "dry_run": True,
            })
            report["waves_completed"] += 1
            continue

        # Dispatch all tickets in this wave as parallel Task() calls
        # Each Task() invokes ticket-pipeline for the ticket
        wave_results = dispatch_parallel_tickets(dispatchable, tickets)

        # Collect results
        wave_report = {
            "wave": wave_idx,
            "dispatched": dispatchable,
            "blocked": blocked,
            "results": {},
        }

        for tid, result in wave_results.items():
            wave_report["results"][tid] = result["status"]
            if result["status"] in ("completed", "merged"):
                report["tickets_completed"] += 1
            else:
                report["tickets_failed"] += 1
                failed_tickets.add(tid)

        report["wave_results"].append(wave_report)
        report["waves_completed"] += 1

    # Determine overall status
    if report["tickets_failed"] > 0 or report["tickets_blocked"] > 0:
        report["status"] = "partial"
    if report["tickets_completed"] == 0:
        report["status"] = "failed"

    return report
```

### Parallel dispatch within a wave

```python
def dispatch_parallel_tickets(
    ticket_ids: list[str],
    tickets: dict[str, dict],
) -> dict[str, dict]:
    """Dispatch ticket-pipeline for each ticket in parallel via Task().

    All Task() calls are made in a SINGLE message for true parallelism.
    Results are collected when all tasks complete.
    """
    # Dispatch all in parallel (single message with multiple Task calls)
    tasks = {}
    for tid in ticket_ids:
        ticket = tickets[tid]
        tasks[tid] = Task(
            subagent_type="onex:polymorphic-agent",
            description=f"wave-scheduler: ticket-pipeline for {tid}",
            prompt=f"""Execute ticket-pipeline for {tid}: {ticket['title']}

    Invoke: Skill(skill="onex:ticket_pipeline", args="{tid}")

    Repo: {ticket['repo']}
    Execute end-to-end. Create worktree, implement, review, create PR, merge.
    Report back with: status (completed|failed|blocked), pr_url, blockers.
    """,
        )

    # Collect results
    return {tid: task.result() for tid, task in tasks.items()}
```

---

## Cross-Repo Locks

When multiple tickets in the same wave target the same repo, the scheduler prevents
conflicting edits by acquiring a per-repo lock before dispatch.

```python
REPO_LOCKS = {}  # {repo_name: lock_holder_ticket_id}

def acquire_repo_lock(repo: str, ticket_id: str) -> bool:
    """Acquire a repo lock for a ticket. Returns False if already held."""
    if repo in REPO_LOCKS and REPO_LOCKS[repo] != ticket_id:
        return False
    REPO_LOCKS[repo] = ticket_id
    return True

def release_repo_lock(repo: str, ticket_id: str) -> None:
    """Release a repo lock after ticket completes."""
    if REPO_LOCKS.get(repo) == ticket_id:
        del REPO_LOCKS[repo]
```

**Conflict resolution strategy:**
- If two tickets in the same wave target the same repo, one is deferred to the next wave
- The ticket with fewer dependencies gets priority (lower in-degree first)
- Deferred tickets are re-queued, not failed

---

## Health-Check Integration (OMN-6889)

During wave execution, the scheduler monitors dispatched agents using the
`agent_healthcheck` skill. Between polling intervals:

1. Check each active agent for stall signals (inactivity, context overflow, rate limits)
2. On stall detection: invoke agent_healthcheck recovery protocol
3. Recovery writes a checkpoint and relaunches the agent
4. If max recovery attempts (3) exceeded: mark ticket as failed, continue wave

---

## State Persistence

Wave execution state is persisted to allow resume after interruption:

```yaml
# .onex_state/wave_scheduler/{epic_id}/state.yaml
schema_version: "1.0.0"
epic_id: OMN-6886
plan_file: docs/plans/2026-03-28-insights-plan.yaml
started_at: 2026-03-28T22:00:00Z
status: in_progress
max_concurrency: 6

waves:
  - wave: 0
    tickets: [OMN-6887, OMN-6888, OMN-6891]
    status: completed
    completed_at: 2026-03-28T22:30:00Z
    results:
      OMN-6887: completed
      OMN-6888: completed
      OMN-6891: completed
  - wave: 1
    tickets: [OMN-6889]
    status: in_progress
    started_at: 2026-03-28T22:31:00Z
    results: {}
  - wave: 2
    tickets: [OMN-6890]
    status: pending
```

### Resume behavior

With `--resume`, the scheduler:
1. Reads persisted state from `.onex_state/wave_scheduler/{epic_id}/state.yaml`
2. Skips completed waves
3. Re-dispatches in-progress wave tickets that are not yet completed
4. Continues from the last incomplete wave

---

## Policy Switches

| Switch | Default | Description |
|--------|---------|-------------|
| `max_concurrency` | `6` | Maximum parallel agents per wave |
| `dispatch_timeout_minutes` | `30` | Per-agent timeout before circuit breaker |
| `max_recovery_attempts` | `3` | Max health-check recovery relaunches per ticket |
| `fail_fast` | `false` | Stop entire execution on first ticket failure |
| `defer_repo_conflicts` | `true` | Defer conflicting same-repo tickets to next wave |

---

## Example

Given the OMN-6886 plan:

```
Wave 0: [OMN-6887, OMN-6888, OMN-6891]  (no dependencies, parallel)
Wave 1: [OMN-6889]                        (depends on OMN-6887)
Wave 2: [OMN-6890]                        (depends on OMN-6889)
```

```bash
/wave-scheduler docs/plans/2026-03-28-insights-plan.yaml --max-concurrency 6
/wave-scheduler docs/plans/2026-03-28-insights-plan.yaml --dry-run
/wave-scheduler docs/plans/2026-03-28-insights-plan.yaml --resume
```

---

## See Also

- `epic-team` skill (current ad-hoc wave execution, to be replaced)
- `agent_healthcheck` skill (stall detection, OMN-6889)
- `checkpoint` skill (checkpoint protocol, OMN-6887)
- `ticket-pipeline` skill (per-ticket execution)
- `decompose-epic` skill (plan decomposition)
