---
description: Single-command dispatch shim. Runs `uv run onex skill merge_sweep` which resolves the declarative
  skill->node mapping, dispatches node_pr_lifecycle_orchestrator in receipt mode, and prints one typed
  ModelSkillResult. No inline logic; markdown only.
mode: full
version: 7.0.0
level: advanced
debug: false
category: workflow
tags:
  - pr
  - github
  - merge
  - autonomous
  - pipeline
  - org-wide
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: string list arg
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
  - name: --inventory-only
    description: boolean flag
    required: false
  - name: --fix-only
    description: boolean flag
    required: false
  - name: --merge-only
    description: boolean flag
    required: false
  - name: --max-parallel-polish
    description: integer arg
    required: false
  - name: --admin-fallback-threshold-minutes
    description: integer arg
    required: false
  - name: --verify
    description: boolean flag
    required: false
  - name: --verify-timeout-seconds
    description: integer arg
    required: false
skill_kind: dispatch
---

# /onex:merge_sweep — one command, one typed result

**Skill ID**: `onex:merge_sweep` · **Command**: `uv run onex skill merge_sweep` (omnibase_infra) · **Backing node**: `node_pr_lifecycle_orchestrator` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelPrLifecycleResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_pr_lifecycle_orchestrator.handlers.handler_pr_lifecycle_orchestrator.ModelPrLifecycleResult`
