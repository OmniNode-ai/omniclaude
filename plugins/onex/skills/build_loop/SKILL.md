---
description: Single-command dispatch shim. Runs `uv run onex skill build_loop` which resolves the declarative
  skill->node mapping, dispatches node_build_loop in receipt mode, and prints one typed ModelSkillResult.
  No inline logic; markdown only.
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags:
  - build-loop
  - autonomous
  - automation
  - orchestrator
author: OmniClaude Team
composable: true
args:
  - name: --max-cycles
    description: integer arg
    required: false
  - name: --skip-closeout
    description: boolean flag
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:build_loop — one command, one typed result

**Skill ID**: `onex:build_loop` · **Command**: `uv run onex skill build_loop` (omnibase_infra) · **Backing node**: `node_build_loop` (omnimarket)

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelLoopState]` JSON to
stdout carrying the FULL handler result; RuntimeLocal logs and intermediate
context go to a capture file + the artifact store, never to you.

See `prompt.md` for the one command and how to present the typed result.

## Routing Contract

The `uv run onex skill build_loop` entrypoint publishes to `onex.cmd.omnimarket.build-loop.v1`
through receipt-mode dispatch. If routing fails, surface `SkillRoutingError` directly; do not produce prose.

## What this skill does NOT do

- Construct a payload file, `cd` anywhere, or `cat` a workflow_result.json (all internal to `onex skill`)
- Run any inline scan, probe, or orchestration — the backing node owns all logic
- Contain executable logic in this directory — markdown only

## Related

- **CLI entrypoint**: `omnibase_infra/src/omnibase_infra/cli/cli_skill.py`
- **Skill→node mapping**: `omnibase_infra/src/omnibase_infra/cli/skill_mapping.yaml`
- **Result model**: `omnimarket.nodes.node_build_loop.models.model_loop_state.ModelLoopState`
