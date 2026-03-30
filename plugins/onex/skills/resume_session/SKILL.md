---
description: Load projected session state for a task and bind the current session to it
mode: full
version: "1.1.0"
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
author: omninode
args:
  - name: task_id
    description: "The ticket ID to resume (e.g., OMN-1234), or --list to show all active sessions"
    required: true
---

# Resume Session

Loads projected state from the session registry for a task and binds the current session to it.
Combines data from all three stores: Postgres (session state), Memgraph (file conflicts),
and Qdrant (semantic decision recall).

## Behavior

1. Accept a ticket ID argument (e.g., `/onex:resume_session OMN-1234`)
2. Query the `session_registry` Postgres table for the task
3. If **Found**:
   - Gather data from all available stores:
     a. Session state from Postgres (task progress, files, phase, decisions)
     b. File conflicts from Memgraph via `should_emit_conflict_signal()` (OMN-6861)
     c. Related decisions from Qdrant via `DecisionSearchClient.search_related()` (OMN-6864)
     d. Recent coordination signals (what happened while session was inactive)
   - Build full resume context via `format_full_resume_context()` (OMN-6865)
   - Bind the session via `TaskBinding` (delegates to set-session behavior)
4. If **Not Found**:
   - "No session history for OMN-1234. Starting fresh."
   - Still bind `task_id` for future correlation
5. If **Unavailable** (DB down):
   - "Session registry unavailable: {reason}. Binding task_id locally only."
   - Still bind `task_id` locally (degraded mode per Doctrine D4)

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

    # 1. File conflicts from Memgraph (OMN-6861)
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

    # 2. Semantic decision recall from Qdrant (OMN-6864, Doctrine D7: enrichment only)
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

> **Note**: This skill executes directly (not via polymorphic-agent) because it is a
> synchronous, user-invoked operation with no need for agent routing.
