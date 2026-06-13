---
description: Multi-model adversarial code review with weighted-union finding aggregation and iterative convergence. Cannot rubber-stamp. Use --static for static-analysis-only mode (dead code, missing error handling, stubs, Kafka wiring, schema mismatches, hardcoded values, missing tests).
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
  - name: pr
    description: PR number to review (mutually exclusive with --file).
    required: false
  - name: repo
    description: Target GitHub repo (e.g., OmniNode-ai/omniclaude). Required with --pr.
    required: false
  - name: file
    description: "Path to a plan file to review (mutually exclusive with --pr). Alias: --plan-path."
    required: false
  - name: plan-path
    description: "Alias for --file: path to a plan or design document to review adversarially"
    required: false
  - name: ticket_id
    description: Linear ticket ID for loading TCB constraints
    required: false
  - name: models
    description: "Comma-separated model list. Defaults to the node contract's configured models when omitted."
    required: false
  - name: passes
    description: "Fixed number of passes to run. Default: iterates until 2 consecutive clean passes."
    required: false
  - name: gate
    description: "Gate mode: structured pass/fail/block verdict suitable for merge gating."
    required: false
  - name: gate-only
    description: "Review-only gate mode (no fix-apply). Safe to invoke from sub-agent context."
    required: false
  - name: strict
    description: "In --gate mode: block on MINOR+ findings (default blocks on MAJOR+)"
    required: false
  - name: static
    description: "Static-analysis-only mode: 7 code quality checks without adversarial review."
    required: false
  - name: repos
    description: "Comma-separated repo names to scan in --static mode"
    required: false
  - name: categories
    description: "Comma-separated finding categories for --static mode"
    required: false
  - name: dry-run
    description: "In --static mode: scan and report only, no tickets created."
    required: false
  - name: ticket
    description: "In --static mode: create Linear tickets for findings"
    required: false
  - name: max-tickets
    description: "In --static mode: hard cap on tickets created per run (default: 10)"
    required: false
skill_kind: dispatch
---

# /onex:hostile_reviewer — one command, one typed result

**Skill ID**: `onex:hostile_reviewer` · **Command**: `uv run onex skill hostile_reviewer` (omnibase_infra) · **Backing node**: `node_hostile_reviewer` (omnimarket) · **Ticket**: OMN-13097

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
- **Result model**: `omnimarket.nodes.node_hostile_reviewer.models.model_hostile_reviewer_completed_event.ModelHostileReviewerCompletedEvent`
