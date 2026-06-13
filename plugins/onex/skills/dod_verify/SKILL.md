---
description: Run DoD evidence checks against a ticket contract and generate a verification receipt. Includes DurableEvidenceGate pre-Linear-Done checks (RECEIPT_TRACKED, CONTRACT_CITES_MERGE_COMMIT, CONTRACT_ON_OCC_MAIN).
mode: full
level: intermediate
debug: false
category: verification
tags:
  - dod
  - evidence
  - verification
  - contracts
  - quality
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
version: 2.1.0
args:
  - name: ticket_id
    description: Linear ticket ID (e.g., OMN-1234)
    required: true
  - name: --contract-path
    description: Override path to contract YAML (default auto-detect)
    required: false
skill_kind: dispatch
---

# /onex:dod_verify — one command, one typed result

**Skill ID**: `onex:dod_verify` · **Command**: `uv run onex skill dod_verify` (omnibase_infra) · **Backing node**: `node_dod_verify` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelDodVerifyState]` JSON to
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
- **Result model**: `omnimarket.nodes.node_dod_verify.models.model_dod_verify_state.ModelDodVerifyState`
