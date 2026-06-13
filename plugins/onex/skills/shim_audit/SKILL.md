---
description: Scan all OmniNode repos for expired or expiring @shim decorator annotations and create Linear
  tickets for each expired shim. Dispatches to node_shim_scanner; creates no tickets in dry-run mode.
mode: full
version: 1.0.0
level: advanced
debug: false
category: verification
tags:
  - shim
  - tech-debt
  - sweep
  - close-out
  - dispatch-only
  - routing-enforced
author: omninode
composable: true
args:
  - name: --paths
    description: string list arg
    required: false
  - name: --reference-date
    description: string arg
    required: false
  - name: --warn-days-before-expiry
    description: integer arg
    required: false
skill_kind: dispatch
---

# /onex:shim_audit — one command, one typed result

**Skill ID**: `onex:shim_audit` · **Command**: `uv run onex skill shim_audit` (omnibase_infra) · **Backing node**: `node_shim_scanner` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelShimScanResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_shim_scanner.models.model_shim_scan_result.ModelShimScanResult`
