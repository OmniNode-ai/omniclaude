---
description: Orchestrate full Linear housekeeping — triage ticket status, organize orphans into epics,
  then sync MASTER_TICKET_PLAN.md. Human checkpoint between triage and apply.
mode: full
version: 2.0.0
level: intermediate
debug: false
category: workflow
tags:
  - linear
  - housekeeping
  - triage
  - epics
  - documentation
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: --threshold-days
    description: integer arg
    required: false
  - name: --flag-only
    description: boolean flag
    required: false
  - name: --team
    description: string arg
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:linear_housekeeping — one command, one typed result

**Skill ID**: `onex:linear_housekeeping` · **Command**: `uv run onex skill linear_housekeeping` (omnibase_infra) · **Backing node**: `node_linear_triage` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelLinearTriageResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_linear_triage.models.model_linear_triage_state.ModelLinearTriageResult`
