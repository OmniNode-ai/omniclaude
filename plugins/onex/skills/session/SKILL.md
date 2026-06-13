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
skill_kind: dispatch
---

# /onex:session — one command, one typed result

**Skill ID**: `onex:session` · **Command**: `uv run onex skill session` (omnibase_infra) · **Backing node**: `node_session_orchestrator` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelSessionOrchestratorResult]` JSON to
stdout carrying the FULL handler result; RuntimeLocal logs and intermediate
context go to a capture file + the artifact store, never to you.

See `prompt.md` for the one command and how to present the typed result.

## What this skill does NOT do

- Construct a payload file, `cd` anywhere, or `cat` a workflow_result.json (all internal to `onex skill`)
- Run any inline scan, probe, or orchestration — the backing node owns all logic
- Contain executable logic in this directory — markdown only

## Related

- **CLI entrypoint**: `omnibase_infra/src/omnibase_infra/cli/cli_skill.py`
- **Skill→node mapping**: `omnibase_infra/src/omnibase_infra/cli/skill_mapping.yaml`
- **Result model**: `omnimarket.nodes.node_session_orchestrator.handlers.handler_session_orchestrator.ModelSessionOrchestratorResult`
