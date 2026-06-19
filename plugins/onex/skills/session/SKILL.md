---
description: Dispatch-only shim for the unified session orchestrator. All phases (health gate, RSD scoring,
  dispatch) execute in node_session_orchestrator (omnimarket). The skill parses --mode/--phase/--dry-run/--skip-health
  and dispatches; no inline orchestration.
version: 2.0.0
mode: full
level: advanced
debug: false
category: workflow
tags:
  - session
  - orchestrator
  - shim
  - dispatch-only
author: OmniClaude Team
composable: false
args:
  - name: --mode
    description: string arg
    required: false
  - name: --phase
    description: string arg
    required: false
  - name: --skip-health
    description: boolean flag
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
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

## Routing Contract

The `uv run onex skill session` entrypoint publishes to `onex.cmd.omnimarket.session-orchestrator.v1`
through receipt-mode dispatch. If routing fails, surface `SkillRoutingError` directly; do not produce prose.

## What this skill does NOT do

- Construct a payload file, `cd` anywhere, or `cat` a workflow_result.json (all internal to `onex skill`)
- Run any inline scan, probe, or orchestration — the backing node owns all logic
- Contain executable logic in this directory — markdown only

## Related

- **CLI entrypoint**: `omnibase_infra/src/omnibase_infra/cli/cli_skill.py`
- **Skill→node mapping**: `omnibase_infra/src/omnibase_infra/cli/skill_mapping.yaml`
- **Result model**: `omnimarket.nodes.node_session_orchestrator.handlers.handler_session_orchestrator.ModelSessionOrchestratorResult`
