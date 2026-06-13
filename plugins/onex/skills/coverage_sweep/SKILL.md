---
description: Measure test coverage across all Python repos under omni_home, flag modules below threshold,
  and auto-create Linear tickets for coverage gaps
version: 4.0.0
mode: full
level: intermediate
debug: false
category: quality
tags:
  - coverage
  - testing
  - automation
  - linear
  - org-wide
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: string list arg
    required: false
  - name: --target-pct
    description: integer arg
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:coverage_sweep — one command, one typed result

**Skill ID**: `onex:coverage_sweep` · **Command**: `uv run onex skill coverage_sweep` (omnibase_infra) · **Backing node**: `node_coverage_sweep` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[CoverageSweepResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_coverage_sweep.handlers.handler_coverage_sweep.CoverageSweepResult`
