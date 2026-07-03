---
description: Multi-model adversarial code review with weighted-union finding aggregation and iterative
  convergence. Cannot rubber-stamp. Use --static for static-analysis-only mode (dead code, missing error
  handling, stubs, Kafka wiring, schema mismatches, hardcoded values, missing tests).
mode: full
version: 6.0.0
level: intermediate
debug: false
category: review
tags:
  - review
  - adversarial
  - pr
  - plan
  - multi-model
  - quality
  - risk
  - convergence
  - static-analysis
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: --pr-number
    description: integer arg
    required: false
  - name: --repo
    description: string arg
    required: false
  - name: --file-path
    description: string arg
    required: false
  - name: --models
    description: string list arg
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:hostile_reviewer — one command, one typed result

**Skill ID**: `onex:hostile_reviewer` · **Command**: `uv run onex skill hostile_reviewer` (omnibase_infra) · **Backing node**: `node_hostile_reviewer_orchestrator` (omnimarket)

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelHostileReviewerCompletedEvent]` JSON to
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
- **Result model**: `omnimarket.nodes.node_hostile_reviewer_orchestrator.models.model_hostile_reviewer_completed_event.ModelHostileReviewerCompletedEvent`
