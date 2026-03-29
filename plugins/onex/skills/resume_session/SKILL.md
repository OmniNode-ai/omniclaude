---
description: Load projected session state for a task and bind the current session to it
mode: full
version: "1.0.0"
level: basic
debug: false
category: session
tags:
  - session
  - correlation
  - resume
  - registry
author: omninode
args:
  - name: task_id
    description: "The ticket ID to resume (e.g., OMN-1234), or --list to show all active sessions"
    required: true
---

# Resume Session

Loads projected state from the session registry for a task and binds the current session to it.

## Behavior

1. Accept a ticket ID argument (e.g., `/onex:resume_session OMN-1234`)
2. Query the `session_registry` Postgres table for the task
3. If **Found**:
   - Display summary: phase, files touched, decisions made, dependencies, last activity
   - Bind the session via `TaskBinding` (delegates to set-session behavior)
   - Read recent coordination signals: "While you were gone: OMN-1230 merged PR #47"
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

client = SessionRegistryClient()  # reads OMNIBASE_INFRA_DB_URL from env
binding = TaskBinding()

if args == "--list":
    result = client.list_active_sessions()
    if isinstance(result, ModelRegistryUnavailable):
        print(f"Session registry unavailable: {result.reason}")
    else:
        for entry in result:
            print(f"  {entry['task_id']} | {entry['current_phase']} | last: {entry['last_activity']}")
        # Highlight file conflicts between active sessions
    return

result = client.get_session(task_id)

if isinstance(result, ModelSessionFound):
    context = client.format_resume_context(result.entry)
    print(context)
    binding.bind(task_id)
    # TODO: Read coordination signals when coordination consumer is wired (OMN-6857)

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
- **D8 (Integration Proof)**: End-to-end proof: bind -> emit -> project -> resume round-trip (Phase 1 gate)

> **Note**: This skill executes directly (not via polymorphic-agent) because it is a
> synchronous, user-invoked operation with no need for agent routing.
