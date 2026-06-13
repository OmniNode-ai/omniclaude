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
inputs:
  - name: pr_number
    type: int
    description: GitHub PR number to merge
    required: true
  - name: repo
    type: str
    description: "GitHub repo slug (org/repo)"
    required: true
  - name: strategy
    type: str
    description: "Merge strategy: squash | merge | rebase (default: squash)"
    required: false
  - name: gate_timeout_hours
    type: float
    description: "Wall-clock budget in hours for the CI readiness poll. Default: 24."
    required: false
  - name: delete_branch
    type: bool
    description: Delete branch after merge (default true)
    required: false
  - name: ticket_id
    type: str
    description: "Linear ticket identifier (e.g. OMN-1234) to mark Done after merge"
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to $ONEX_STATE_DIR/skill-results/{context_id}/auto_merge.json"
args:
  - name: pr_number
    description: GitHub PR number to merge
    required: true
  - name: repo
    description: "GitHub repo slug (org/repo)"
    required: true
  - name: --strategy
    description: "Merge strategy: squash|merge|rebase (default squash)"
    required: false
  - name: --gate-timeout-hours
    description: Hours to wait for CI readiness (default 24)
    required: false
  - name: --no-delete-branch
    description: Don't delete branch after merge
    required: false
  - name: --ticket-id
    description: Linear ticket ID to mark Done after merge (e.g. OMN-1234)
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
