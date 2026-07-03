---
description: Load projected session state for a task and bind the current session to it
mode: full
version: "1.2.0"
level: basic
debug: false
category: session
tags:
  - session
  - correlation
  - resume
  - registry
  - qdrant
  - decisions
  - live-state
  - verify
author: omninode
args:
  - name: task_id
    description: "The ticket ID to resume (e.g., TASK-1234), or --list to show all active sessions"
    required: true
---

# Resume Session

Loads projected state from the session registry for a task and binds the current session to it.
Combines data from all three stores: Postgres (session state), Memgraph (file conflicts),
and Qdrant (semantic decision recall).

## Behavior

0. **Re-verify live state from the latest handoff before trusting any prior-session
   state claim** — see [Live-State Re-Verification on Resume](#live-state-re-verification-on-resume).
   A resumed session never acts on prose state copied from a previous session
   without re-running that section's probe.
1. Accept a ticket ID argument (e.g., `/onex:resume_session TASK-1234`)
2. Query the `session_registry` Postgres table for the task
3. If **Found**:
   - Gather data from all available stores:
     a. Session state from Postgres (task progress, files, phase, decisions)
     b. File conflicts from Memgraph via `should_emit_conflict_signal()`
     c. Related decisions from Qdrant via `DecisionSearchClient.search_related()`
     d. Recent coordination signals (what happened while session was inactive)
   - Build full resume context via `format_full_resume_context()`
   - Bind the session via `TaskBinding` (delegates to set-session behavior)
4. If **Not Found**:
   - "No session history for TASK-1234. Starting fresh."
   - Still bind `task_id` for future correlation
5. If **Unavailable** (DB down):
   - "Session registry unavailable: {reason}. Binding task_id locally only."
   - Still bind `task_id` locally (degraded mode per Doctrine D4)

## Live-State Re-Verification on Resume

A resumed session MUST NOT trust prose state copied from a prior session. A handoff
is a snapshot written at the moment the previous session ended; the live system may
have moved on. Before acting on any claim about *current* state (bus health, lane
health, PR verdict, container state, queue depth), re-verify it against the live
surface.

### 1. Read the latest handoff (`LATEST.md`, fallback newest-mtime)

On resume, locate the candidate current-state document in this order:

1. **`LATEST.md`** — the canonical pointer to the most recent handoff. Read it
   first (in the repo's `docs/handoffs/` directory when present, otherwise the
   working-directory root).
2. **Fallback**: if `LATEST.md` is absent, select the handoff file with the
   **newest modification time (mtime)** under `docs/handoffs/`.

Only `LATEST.md` (or, on fallback, the newest-mtime handoff) is treated as the
candidate current-state document. Every older handoff under `docs/handoffs/` is
history, not current state.

### 2. Re-run `verify:` blocks in live-state sections

Within the chosen handoff, a **live-state section** is one that carries a `verify:`
block — a line of the form `verify: <date> via <command>`, or a fenced block of
probe commands. The `verify:` block *is* the probe; the result written next to it is
stale the instant the previous session ended. For every live-state section:

- Re-execute each `verify:` probe command exactly as written.
- Act only on the **freshly re-observed** result, never on the value recorded in
  the handoff.
- If the probe output differs from the recorded value, the recorded value is wrong —
  the live probe wins.

Example live-state section in a handoff:

```
### Bus health
status: BUS-IS-DOWN
verify: 2026-06-28 via rpk cluster health
```

On resume, re-run `rpk cluster health` and use *that* output; do not propagate the
recorded `BUS-IS-DOWN`.

### 3. Sections without a `verify:` block are historical

Any section that does **not** carry a `verify:` block is **historical** — narrative,
rationale, decisions made, links, design notes. It is useful context, but it is
**not authoritative for current state** and must not be used to gate an action.
Historical sections are read for understanding, never re-probed, and never trusted
as live truth.

### 4. Stale live-state alarms do not gate action

A live-state alarm carried in a handoff — for example `BUS-IS-DOWN`,
`LANE-UNHEALTHY`, or `QUEUE-WEDGED` — that has **no re-runnable `verify:` block**, or
whose `verify:` probe cannot be re-executed on resume, is treated as **stale /
historical**. A stale alarm is recorded for context only and **does not block or
gate any action**: re-probe the live surface and act on what the probe returns. The
alarm is current **only if** a freshly re-run `verify:` probe reproduces the alarm
condition; otherwise it is discarded as a snapshot artifact.

## Implementation

Use the `SessionRegistryClient` from `omniclaude.services.session_registry_client`:

```python
from omniclaude.services.session_registry_client import (
    SessionRegistryClient,
    ModelSessionFound,
    ModelSessionNotFound,
    ModelRegistryUnavailable,
)
from omniclaude.services.task_binding import TaskBinding
from omniclaude.hooks.coordination import should_emit_conflict_signal

client = SessionRegistryClient()  # reads OMNIBASE_INFRA_DB_URL from env
binding = TaskBinding()

if args == "--list":
    result = client.list_active_sessions()
    if isinstance(result, ModelRegistryUnavailable):
        print(f"Session registry unavailable: {result.reason}")
    else:
        for entry in result:
            print(f"  {entry.task_id} | {entry.current_phase} | last: {entry.last_activity}")
    return

result = client.get_session(task_id)

if isinstance(result, ModelSessionFound):
    entry = result.entry
    binding.bind(task_id)

    # -- Gather enrichment data from all stores --

    # 1. File conflicts from Memgraph
    conflicts = []
    active_sessions = client.list_active_sessions()
    if not isinstance(active_sessions, ModelRegistryUnavailable):
        current_task = {
            "task_id": task_id,
            "files_touched": entry.files_touched,
        }
        other_tasks = [
            {"task_id": s.task_id, "files_touched": s.files_touched}
            for s in active_sessions
            if s.task_id != task_id
        ]
        detected = should_emit_conflict_signal(current_task, other_tasks)
        conflicts = [
            {"other_task_id": c.other_task_id, "shared_files": c.shared_files}
            for c in detected
        ]

    # 2. Semantic decision recall from Qdrant (Doctrine D7: enrichment only)
    related_decisions = []
    try:
        from omnibase_infra.services.session_registry.decision_search import (
            DecisionSearchClient,
        )
        search_client = DecisionSearchClient()
        search_results = search_client.search_related(task_id=task_id, limit=5)
        related_decisions = [
            {
                "task_id": r.task_id,
                "decision_text": r.decision_text,
                "score": r.score,
            }
            for r in search_results
        ]
    except Exception:
        # D7: Qdrant is enrichment only -- failures are non-fatal
        pass

    # 3. Coordination signals (placeholder -- consumed from Kafka topic)
    coordination_signals = []

    # -- Build and display full context --
    context = client.format_full_resume_context(
        entry=entry,
        related_decisions=related_decisions,
        conflicts=conflicts,
        coordination_signals=coordination_signals,
    )
    print(context)

elif isinstance(result, ModelSessionNotFound):
    print(f"No session history for {task_id}. Starting fresh.")
    binding.bind(task_id)

elif isinstance(result, ModelRegistryUnavailable):
    print(f"Session registry unavailable: {result.reason}. Binding task_id locally only.")
    binding.bind(task_id)
```

## List Mode

`/onex:resume_session --list` queries all active sessions:
- Shows task_id, phase, last activity, files being touched
- Highlights conflicts: two tasks touching the same file

## Doctrine Compliance

- **D1 (Binding Authority)**: Delegates binding to `TaskBinding` which writes `.onex_state/active_session.yaml`
- **D4 (Degradation Contracts)**: Returns Found/NotFound/Unavailable -- never collapses both failure modes into None
- **D6 (Projection/Control Separation)**: Conflict display is advisory -- shown as warnings, not blocking gates
- **D7 (Semantic Recall is Enrichment)**: Qdrant decision recall is optional -- failures are caught and silently skipped; resume works without Qdrant
- **D8 (Integration Proof)**: Phase 3 proof: decision recorded -> embedded -> semantically recalled on resume

> **Note**: This skill executes directly (not via general-purpose) because it is a
> synchronous, user-invoked operation with no need for agent routing.
