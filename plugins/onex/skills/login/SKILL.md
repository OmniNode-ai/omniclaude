---
description: Bind this terminal to a named persistent agent. Establishes agent identity for the session, injects resumed context, and tags all events with the agent ID.
mode: full
level: basic
debug: false
index: true
---

# Login — Bind Terminal to Persistent Agent

## Overview

Bind the current terminal to a named agent identity. Once logged in, all session
events are tagged with the agent ID, context is injected from the agent's last
known state, and work continuity is automatic across /clear and session restarts.

## Usage

```
/login CAIA                    # Bind to CAIA
/login SENTINEL                # Bind to SENTINEL
/login                         # Show current binding status
/login --create WATCHDOG       # Create a new agent and bind
/login --release               # Unbind from current agent
```

## Execution

### Status Check (no args)

If no agent name provided, show current binding:
- If bound: "Currently logged in as **CAIA** (bound 2 hours ago from terminal-mac-3)"
- If unbound: "Not logged in to any agent. Use `/login <name>` to bind."

### Login Flow

1. **Get terminal identity**: Call `get_or_create_terminal_id()` from `terminal_identity.py`
2. **Look up agent**: Query the agent registry at `.onex_state/agents/{name}.yaml`
   - If not found and `--create` flag: create new agent, register, continue
   - If not found and no flag: "Agent '{name}' not registered. Use `/login --create {name}` to create."
3. **Check current binding**:
   - If agent is unbound: proceed to bind
   - If agent is bound to THIS terminal: "Already logged in as {name}."
   - If agent is bound to ANOTHER terminal + stale (>30 min since last activity): auto-takeover with warning
   - If agent is bound to ANOTHER terminal + active (<30 min): "CAIA is active in {terminal} ({time} ago). Force takeover? [Y/n]"
4. **Bind**: Update agent registry with new binding (terminal_id, session_id, machine, timestamp)
5. **Tag events**: Set `ONEX_AGENT_ID={name}` in the environment so all session events include it
6. **Inject context**: Query session projector for agent's last snapshot, inject as context

### Release Flow

1. Unbind agent from terminal
2. Clear `ONEX_AGENT_ID` env var
3. "Released binding to {name}."

### Create Flow

1. Create new `ModelAgentEntity` with provided name
2. Register in YAML registry
3. Proceed to normal login flow

## Graceful Degradation

- If agent registry dir doesn't exist: create it
- If session projector unavailable: login succeeds but no context injection (warn user)
- If event tagging fails: login succeeds but events won't be attributed (warn user)
- Login NEVER blocks session startup
