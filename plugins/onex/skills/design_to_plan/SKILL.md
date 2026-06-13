---
description: End-to-end design workflow — brainstorm ideas into structured implementation plans with optional launch
mode: full
version: 2.1.0
level: intermediate
debug: false
category: planning
tags:
  - design
  - brainstorming
  - planning
  - writing-plans
  - workflow
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --phase
    description: "Start at phase: brainstorm (Phase 1), plan (Phase 2), or launch (Phase 3). Default: brainstorm"
    required: false
  - name: --topic
    description: "Topic or problem to brainstorm (Phase 1)"
    required: false
  - name: --plan-path
    description: "Path to existing plan file (skip to Phase 2 or 3)"
    required: false
  - name: --no-launch
    description: "Stop after plan save — do not prompt for launch"
    required: false
skill_kind: dispatch
---

# /onex:design_to_plan — one command, one typed result

**Skill ID**: `onex:design_to_plan` · **Command**: `uv run onex skill design_to_plan` (omnibase_infra) · **Backing node**: `node_design_to_plan` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelDesignToPlanPhase3LaunchResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_design_to_plan.models.model_design_to_plan_phase3_launch.ModelDesignToPlanPhase3LaunchResult`
