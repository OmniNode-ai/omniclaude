---
description: "Dispatch-only shim for the unified session orchestrator. All phases (health gate, RSD scoring, dispatch) execute in node_session_orchestrator (omnimarket). The skill parses --mode/--phase/--dry-run/--skip-health and dispatches; no inline orchestration."
version: 2.0.0
mode: full
level: advanced
debug: false
category: workflow
tags: [session, orchestrator, shim, dispatch-only]
author: OmniClaude Team
composable: false
args:
  - name: --mode
    description: "interactive | autonomous (default: interactive)"
    required: false
  - name: --phase
    description: "0 = all phases, 1/2/3 = single phase (default: 0)"
    required: false
  - name: --dry-run
    description: "Print plan without dispatching (default: false)"
    required: false
  - name: --skip-health
    description: "Skip Phase 1 health gate (emergency only, default: false)"
    required: false
  - name: --standing-orders
    description: "Path to standing_orders.json (default: .onex_state/session/standing_orders.json)"
    required: false
inputs:
  - name: mode
    description: "interactive | autonomous"
outputs:
  - name: status
    description: "complete | halted | error"
  - name: halt_reason
    description: "Phase and reason that caused halt, empty on complete"
  - name: session_id
    description: "sess-{date}-{time} correlation prefix"
---

# /onex:session — dispatch-only shim

**Skill ID**: `onex:session` · **Backing node**: `omnimarket/src/omnimarket/nodes/node_session_orchestrator/` · **Ticket**: OMN-8750

## Routing Contract

- **Classification**: Deterministic
- **Dispatch**: single invocation of `node_session_orchestrator` — see `prompt.md` for the exact dispatch command
- **No inline orchestration**: phases 1/2/3 live in the handler, not this skill
- **No prose fallback**: on dispatch failure, raise `SkillRoutingError` — surface it directly, do not produce prose
