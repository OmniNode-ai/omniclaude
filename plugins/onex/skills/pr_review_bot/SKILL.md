---
description: Run the ONEX PR review bot pipeline — fetches diff, dispatches multi-model adversarial review, posts thread comments, verifies resolutions, and posts a summary verdict. Thin wrapper over node_pr_review_bot WorkflowRunner.
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
  - name: pr
    description: "PR number to review (e.g., 42)"
    required: true
  - name: repo
    description: "GitHub repo in owner/repo format (e.g., OmniNode-ai/omnimarket). Defaults to the current repo if omitted."
    required: false
  - name: --dry-run
    description: "Skip posting comments to GitHub — review runs but no threads are created (default: false)"
    required: false
  - name: --severity-threshold
    description: "Minimum severity to post a thread: CRITICAL, MAJOR, MINOR (default: MAJOR)"
    required: false
  - name: --reviewer-models
    description: "Comma-separated reviewer model list. Required — caller must pass model keys registered in ModelInferenceBridgeConfig.model_configs (e.g. LLM_CODER_URL-backed key). Prior hardcoded defaults produced a silent-clean verdict when the keys weren't in the registry (OMN-9112)."
    required: true
  - name: --judge-model
    description: "Judge model identifier (key registered in ModelInferenceBridgeConfig). Omit to use the node contract's configured default."
    required: false
  - name: --max-findings
    description: "Cap on review threads posted per PR (default: 20)"
    required: false
skill_kind: dispatch
---

# /onex:pr_review_bot — one command, one typed result

**Skill ID**: `onex:pr_review_bot` · **Command**: `uv run onex skill pr_review_bot` (omnibase_infra) · **Backing node**: `node_pr_review_bot` (omnimarket) · **Ticket**: OMN-13097

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
- **Result model**: `omnimarket.nodes.node_pr_review_bot.models.models.ReviewVerdict`
