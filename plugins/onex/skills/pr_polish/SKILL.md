---
description: Full PR readiness loop — resolve merge conflicts, address all review comments and CI failures,
  then iterate local-review until N consecutive clean passes
mode: full
version: 3.0.0
level: intermediate
debug: false
category: workflow
tags:
  - pr
  - review
  - conflicts
  - code-quality
  - iteration
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: --repo
    description: string arg (required)
    required: true
  - name: --pr-number
    description: integer arg (required)
    required: true
  - name: --ticket-id
    description: string arg
    required: false
  - name: --required-clean-runs
    description: integer arg
    required: false
  - name: --max-iterations
    description: integer arg
    required: false
  - name: --skip-conflicts
    description: boolean flag
    required: false
  - name: --skip-pr-review
    description: boolean flag
    required: false
  - name: --skip-local-review
    description: boolean flag
    required: false
  - name: --no-ci
    description: boolean flag
    required: false
  - name: --no-push
    description: boolean flag
    required: false
  - name: --no-automerge
    description: boolean flag
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:pr_polish — one command, one typed result

**Skill ID**: `onex:pr_polish` · **Command**: `uv run onex skill pr_polish` (omnibase_infra) · **Backing node**: `node_pr_polish` (omnimarket)

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelPrPolishCompletedEvent]` JSON to
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
- **Result model**: `omnimarket.nodes.node_pr_polish.models.model_pr_polish_completed_event.ModelPrPolishCompletedEvent`
