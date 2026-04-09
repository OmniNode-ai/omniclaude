---
description: Non-compliant skill — manages FSM state inline
mode: full
version: 1.0.0
level: advanced
---

# Non-Compliant Skill: State Management

## How It Works

The skill tracks pipeline phases:

1. Load state from state_file and check current_phase = "implement"
2. Read state["phases"]["implement"]["artifacts"]
3. Write state.yaml checkpoint after each phase
4. Check ledger["OMN-1234"]["active_run_id"]

This is non-compliant because state management belongs in the node handler.
