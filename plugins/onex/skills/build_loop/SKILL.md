---
description: Autonomous build loop — runs the ONEX build loop workflow locally via `onex run`
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags: [build-loop, autonomous, automation, orchestrator]
author: OmniClaude Team
composable: true
args:
  - name: --max-cycles
    description: "Maximum cycles (default: 1)"
    required: false
  - name: --skip-closeout
    description: "Skip close-out phase"
    required: false
  - name: --dry-run
    description: "No side effects — simulate the full loop"
    required: false
  - name: --max-tickets
    description: "Max tickets to dispatch per fill cycle (default: 5)"
    required: false
  - name: --mode
    description: "Execution mode: build, close_out, full, observe (default: build)"
    required: false
skill_kind: dispatch
---

# /onex:build_loop — one command, one typed result

**Skill ID**: `onex:build_loop` · **Command**: `uv run onex skill build_loop` (omnibase_infra) · **Backing node**: `node_build_loop` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelLoopState]` JSON to
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
- **Result model**: `omnimarket.nodes.node_build_loop.models.model_loop_state.ModelLoopState`
