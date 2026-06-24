---
description: Auto-triage CodeRabbit review threads — classify severity and auto-reply to Minor/Nitpick
  findings with acknowledgment, resolving the thread so it no longer blocks merge.
mode: full
version: 2.0.0
level: intermediate
debug: false
category: quality
tags:
  - coderabbit
  - pr-review
  - triage
  - auto-reply
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --repo
    description: string arg (required)
    required: true
  - name: --pr-number
    description: integer arg (required)
    required: true
  - name: --dry-run
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:coderabbit_triage — one command, one typed result

**Skill ID**: `onex:coderabbit_triage` · **Command**: `uv run onex skill coderabbit_triage` (omnibase_infra) · **Backing node**: `node_coderabbit_triage` (omnimarket)

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelCoderabbitTriageResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_coderabbit_triage.handlers.handler_coderabbit_triage.ModelCoderabbitTriageResult`
