---
description: Bind the current Claude Code session to a Linear ticket for cross-session correlation
mode: full
version: "1.0.0"
level: basic
debug: false
category: session
tags:
  - session
  - correlation
  - task-binding
  - pipeline
author: omninode
args:
  - name: task_id
    description: "The ticket ID to bind (e.g., OMN-1234), or --clear to unbind"
    required: true
---

# Set Session

Binds the current Claude Code session to a Linear ticket for cross-session correlation.

## Behavior

1. Accept a ticket ID argument (e.g., `/onex:set_session OMN-1234`)
2. Write `task_id: OMN-1234` to `.onex_state/active_session.yaml` (authoritative binding per Doctrine D1)
3. Set `ONEX_TASK_ID=OMN-1234` in the process environment as a derived runtime convenience
4. Emit a `session.status_changed` event with `task_id` and `status: bound`
5. Confirm: "Session bound to OMN-1234. All events will carry this task_id."

## Implementation

Use the `TaskBinding` service from `omniclaude.services.task_binding`:

```python
from omniclaude.services.task_binding import TaskBinding

binding = TaskBinding()

# Check for --clear flag
if args == "--clear":
    binding.clear()
    # Emit session.status_changed with status: unbound
    print("Session unbound. Events will no longer carry a task_id.")
else:
    # Check for existing binding
    existing = binding.detect_existing()
    if existing and existing != task_id:
        print(f"Replacing existing binding to {existing}.")

    binding.bind(task_id)
    # Emit session.status_changed with status: bound
    print(f"Session bound to {task_id}. All events will carry this task_id.")
```

## Unbinding

`/onex:set_session --clear` removes the binding:
1. Remove `.onex_state/active_session.yaml`
2. Unset `ONEX_TASK_ID` from the process environment
3. Emit `session.status_changed` with `status: unbound`

## Resume Detection

On session start, if `.onex_state/active_session.yaml` exists in the working directory,
suggest: "Previous session was bound to OMN-1234. Resume? (/onex:set_session OMN-1234)"
Do NOT auto-inject -- user must explicitly opt in.

> **Note**: This skill executes directly (not via polymorphic-agent) because it is a
> synchronous, user-invoked operation with no need for agent routing.
