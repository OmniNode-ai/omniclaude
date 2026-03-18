---
description: Set the active run ID for the current session
version: "1.0.0"
level: basic
debug: false
category: pipeline
tags:
  - pipeline
  - session
  - state
author: omninode
args:
  - name: run_id
    description: "The run ID to set as active"
    required: true
mode: full
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

> **Note**: This skill executes directly (not via polymorphic-agent) because it is a synchronous, user-invoked operation with no need for agent routing or intelligence integration.

Report the result to the user.
