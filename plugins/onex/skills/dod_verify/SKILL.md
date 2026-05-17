---
description: Run DoD evidence checks against a ticket contract and generate a verification receipt
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
version: 2.0.0
args:
  - name: ticket_id
    description: Linear ticket ID (e.g., OMN-1234)
    required: true
  - name: --contract-path
    description: Override path to contract YAML (default auto-detect)
    required: false
---

# /onex:dod_verify — DoD Evidence Verification

**Skill ID**: `onex:dod_verify`
**Version**: 2.0.0
**Backing node**: `node_dod_verify`

## Changelog

- **2.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_dod_verify`.
- **1.0.0** — Original skill (OMN-5174).

## What this skill does

Dispatches through `onex run-node node_dod_verify`. The node locates the contract,
loads `dod_evidence[]`, runs evidence checks, and writes a receipt to
`.evidence/{ticket_id}/dod_report.json`. This shim contains no inline verification logic.

**Announce at start:** "I'm using the dod-verify skill."

## Dispatch

```bash
uv run onex run-node node_dod_verify --input '{
  "ticket_id": "<ticket_id>",
  "contract_path": null
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_dod_verify`

Command topic: `onex.cmd.omnimarket.dod-verify-start.v1`

Terminal event: `onex.evt.omnimarket.dod-verify-completed.v1`
