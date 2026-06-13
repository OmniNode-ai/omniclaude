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
skill_kind: dispatch
---

# /onex:platform_readiness — one command, one typed result

**Skill ID**: `onex:platform_readiness` · **Command**: `uv run onex skill platform_readiness` (omnibase_infra) · **Backing node**: `node_platform_readiness` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelPlatformReadinessResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_platform_readiness.handlers.handler_platform_readiness.ModelPlatformReadinessResult`
