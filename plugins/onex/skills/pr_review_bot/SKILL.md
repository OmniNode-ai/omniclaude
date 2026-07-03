---
description: Run the ONEX PR review bot pipeline — fetches diff, dispatches multi-model adversarial review,
  posts thread comments, verifies resolutions, and posts a summary verdict. Thin wrapper over
  node_pr_review_orchestrator.
mode: full
version: 1.0.0
level: intermediate
debug: false
category: review
boundary_exempt: true
tags:
  - review
  - pr
  - automation
  - omnimarket
author: OmniClaude Team
args:
  - name: --pr-number
    description: integer arg (required)
    required: true
  - name: --repo
    description: string arg (required)
    required: true
  - name: --reviewer-models
    description: string list arg
    required: false
  - name: --judge-model
    description: string arg
    required: false
  - name: --severity-threshold
    description: string arg
    required: false
  - name: --max-findings-per-pr
    description: integer arg
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:pr_review_bot — one command, one typed result

**Skill ID**: `onex:pr_review_bot` · **Command**: `uv run onex skill pr_review_bot` (omnibase_infra) · **Backing node**: `node_skill_pr_review_bot_orchestrator` (omniclaude)

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ReviewVerdict]` JSON to
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
- **Result model**: `omnimarket.review.pr_review_io.ReviewVerdict`
