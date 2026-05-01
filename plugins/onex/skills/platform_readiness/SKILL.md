---
description: Thin dispatch-only shim for the platform readiness gate. Routes to node_platform_readiness in omnimarket, which aggregates 7 verification dimensions (contract completeness, golden chain, data flow, runtime wiring, dashboard, cost, CI) into a tri-state PASS/WARN/FAIL report. No inline probe aggregation.
mode: full
version: 2.0.0
level: advanced
debug: false
category: verification
tags:
  - readiness
  - gate
  - verification
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: false
inputs:
  - name: json_output
    type: bool
    description: "Surface the node JSON directly instead of rendering a markdown table"
    required: false
outputs:
  - name: overall
    type: str
    description: '"PASS" | "WARN" | "FAIL"'
  - name: dimensions
    type: list
    description: "Per-dimension status, freshness, details"
  - name: blockers
    type: list
    description: "FAIL dimensions with actionable items"
  - name: degraded
    type: list
    description: "WARN dimensions with actionable recommendations"
args:
  - name: --json
    description: "Surface the node JSON directly instead of rendering a markdown table"
    required: false
---

# /onex:platform_readiness — dispatch-only shim

**Skill ID**: `onex:platform_readiness` · **Backing node**: `omnimarket/src/omnimarket/nodes/node_platform_readiness/` · **Ticket**: OMN-8755

## Routing Contract

- **Classification**: Deterministic
- **Dispatch**: see `prompt.md` — single `uv run onex run-node node_platform_readiness --input` invocation from the omnimarket worktree
- **No inline probe aggregation**: the 7 dimensions (contract, golden chain, data flow, runtime, dashboard, cost, CI) live in the node, not this skill
- **Routing failure envelope**: on non-zero exit, `SkillRoutingError` JSON is surfaced verbatim — do not produce prose

See `prompt.md` for the exact dispatch invocation.
