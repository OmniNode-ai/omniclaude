---
description: Merge a GitHub PR when all gates pass; proceeds automatically after CI is clean
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags:
  - pr
  - github
  - merge
  - automation
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --pr-number
    description: integer arg (required)
    required: true
  - name: --repo
    description: string arg (required)
    required: true
  - name: --strategy
    description: string arg
    required: false
  - name: --delete-branch
    description: boolean flag
    required: false
  - name: --ticket-id
    description: string arg
    required: false
  - name: --gate-timeout-hours
    description: integer arg
    required: false
skill_kind: dispatch
---

# /onex:auto_merge — one command, one typed result

**Skill ID**: `onex:auto_merge` · **Command**: `uv run onex skill auto_merge` (omnibase_infra) · **Backing node**: `node_auto_merge_effect` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelAutoMergeResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_auto_merge_effect.models.model_auto_merge_result.ModelAutoMergeResult`
