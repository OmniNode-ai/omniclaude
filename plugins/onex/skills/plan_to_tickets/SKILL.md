---
description: Batch create Linear tickets from a plan markdown file - parses phases/milestones, creates epic if needed, links dependencies
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags:
  - linear
  - tickets
  - planning
  - batch
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: plan-file
    description: Path to plan markdown file
    required: true
  - name: --project
    description: Linear project name
    required: false
  - name: --epic-title
    description: Title for epic (overrides auto-detection from plan)
    required: false
  - name: --no-create-epic
    description: Fail if epic doesn't exist (don't auto-create)
    required: false
  - name: --dry-run
    description: Show what would be created without creating
    required: false
  - name: --skip-existing
    description: Skip tickets that already exist (don't ask)
    required: false
  - name: --team
    description: "Linear team name (default: Omninode)"
    required: false
skill_kind: dispatch
---

# /onex:plan_to_tickets — one command, one typed result

**Skill ID**: `onex:plan_to_tickets` · **Command**: `uv run onex skill plan_to_tickets` (omnibase_infra) · **Backing node**: `node_plan_to_tickets` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelPlanToTicketsResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_plan_to_tickets.handlers.handler_plan_to_tickets.ModelPlanToTicketsResult`
