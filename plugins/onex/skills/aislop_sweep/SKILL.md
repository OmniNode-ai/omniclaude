---
description: Detect AI-generated quality anti-patterns across all repos — phantom callables in skill markdown,
  backwards compat shims, prohibited env var patterns, hardcoded topic strings, hardcoded absolute paths
  and LAN IPs, agent-left TODO/FIXME markers, and empty implementations.
version: 3.1.0
mode: full
level: advanced
debug: false
category: quality
tags:
  - ai-quality
  - code-review
  - anti-patterns
  - org-wide
  - autonomous
author: OmniClaude Team
composable: true
args:
  - name: --target-dirs
    description: string list arg
    required: false
  - name: --checks
    description: string list arg
    required: false
  - name: --severity-threshold
    description: string arg
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:aislop_sweep — one command, one typed result

**Skill ID**: `onex:aislop_sweep` · **Command**: `uv run onex skill aislop_sweep` (omnibase_infra) · **Backing node**: `node_aislop_sweep` (omnimarket)

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[AislopSweepResult]` JSON to
stdout carrying the FULL handler result; RuntimeLocal logs and intermediate
context go to a capture file + the artifact store, never to you.

See `prompt.md` for the one command and how to present the typed result.

## Routing Contract

The `uv run onex skill aislop_sweep` entrypoint publishes to `onex.cmd.omnimarket.aislop-sweep.v1`
through receipt-mode dispatch. If routing fails, surface `SkillRoutingError` directly; do not produce prose.

## What this skill does NOT do

- Construct a payload file, `cd` anywhere, or `cat` a workflow_result.json (all internal to `onex skill`)
- Run any inline scan, probe, or orchestration — the backing node owns all logic
- Contain executable logic in this directory — markdown only

## Related

- **CLI entrypoint**: `omnibase_infra/src/omnibase_infra/cli/cli_skill.py`
- **Skill→node mapping**: `omnibase_infra/src/omnibase_infra/cli/skill_mapping.yaml`
- **Result model**: `omnimarket.nodes.node_aislop_sweep.handlers.handler_aislop_sweep.AislopSweepResult`
