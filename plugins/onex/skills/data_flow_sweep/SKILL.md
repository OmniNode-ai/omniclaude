---
description: End-to-end data flow verification — dispatches to node_data_flow_sweep which handles all
  metadata collection (rpk/psql probes) and flow classification internally.
mode: full
version: 2.0.0
level: advanced
debug: false
category: verification
tags:
  - data-flow
  - kafka
  - projections
  - sweep
  - close-out
author: omninode
composable: true
args:
  - name: --flows
    description: string list arg
    required: false
  - name: --collect
    description: boolean flag
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:data_flow_sweep — one command, one typed result

**Skill ID**: `onex:data_flow_sweep` · **Command**: `uv run onex skill data_flow_sweep` (omnibase_infra) · **Backing node**: `node_data_flow_sweep` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[DataFlowSweepResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_data_flow_sweep.handlers.handler_data_flow_sweep.DataFlowSweepResult`
