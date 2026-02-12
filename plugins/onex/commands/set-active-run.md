---
name: set-active-run
description: Set the active run ID for the current session
arguments:
  - name: run_id
    description: The run ID to set as active
    required: true
---

# Set Active Run

Sets the active run ID in the session state index (`~/.claude/state/session.json`).

This is used when multiple concurrent pipelines are running and you need to designate which run is the "active" one for interactive commands.

## Usage

```
/set-active-run <run_id>
```

## Implementation

Run the session state adapter to set the active run:

```bash
echo '{"run_id": "{{run_id}}"}' | python3 plugins/onex/hooks/lib/node_session_state_adapter.py set-active-run
```

Report the result to the user.
