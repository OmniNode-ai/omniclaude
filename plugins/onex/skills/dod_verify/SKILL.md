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
---

# /onex:dod_verify — DoD Evidence Verification

**Skill ID**: `onex:dod_verify`
**Version**: 2.1.0
**Backing node**: `node_dod_verify`

## Changelog

- **2.1.0** — Document DurableEvidenceGate: 3-check gate blocks Linear Done when durable evidence trail is local-only, stale, or cites an unmerged PR.
- **2.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_dod_verify`.
- **1.0.0** — Original skill (OMN-5174).

## What this skill does

Dispatches through `onex run-node node_dod_verify`. The node locates the contract,
loads `dod_evidence[]`, runs evidence checks, and writes a receipt to
`.evidence/{ticket_id}/dod_report.json`. This shim contains no inline verification logic.

**Before marking a Linear ticket Done**, the node runs the `DurableEvidenceGate` — three
checks that refuse the Done transition when the durable evidence trail is local-only,
cites a non-merged PR, or is absent from `onex_change_control/main`.

**Announce at start:** "I'm using the dod-verify skill."

## DurableEvidenceGate

The gate runs automatically as part of `node_dod_verify`. All three checks must pass
before the node allows the Linear Done transition.

| Check | What it verifies | Remediation on failure |
|-------|-----------------|------------------------|
| `RECEIPT_TRACKED` | `evidence/<ticket>/dod_report.json` is tracked on `onex_change_control/main` (not local-only) | Commit and push the receipt to OCC, then re-run |
| `CONTRACT_CITES_MERGE_COMMIT` | Every `pr_url` cited in `dod_evidence` is in state `MERGED` with `mergeCommit.oid` matching the cited `commit_sha` | Update `dod_evidence` to cite the actual merged PR and real SHA, then re-run |
| `CONTRACT_ON_OCC_MAIN` | The contract on `onex_change_control/main` contains the same merge-commit citations as the local contract | Open an OCC PR to update the contract and merge it before transitioning to Done |

The gate prevents Done transitions while `onex_change_control/main` still holds
stale or incomplete evidence for the ticket.

If any check fails, the node returns `status: failed` with a structured
`ModelDurableEvidenceGateResult`. Surface the check-level messages directly — they
identify which surface is broken and the exact remediation step.

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
