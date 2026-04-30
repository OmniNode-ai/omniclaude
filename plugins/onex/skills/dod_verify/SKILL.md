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
author: OmniClaude Team
version: 1.0.0
args:
  - name: ticket_id
    description: Linear ticket ID (e.g., OMN-1234)
    required: true
  - name: --contract-path
    description: Override path to contract YAML (default auto-detect)
    required: false
---

# dod-verify

**Skill ID**: `onex:dod_verify`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-5174

---

## Purpose

Thin skill surface that dispatches to the `node_dod_verify` node in omnimarket via
`onex run`. Runs DoD evidence checks for a ticket and generates a structured
verification receipt. This is the voluntary verification entry point that agents
can invoke before marking a ticket as Done.

---

## Usage

```
/dod-verify OMN-1234
/dod-verify OMN-1234 --contract-path contracts/OMN-1234.yaml
```

---

## Behavior

1. **Parse arguments:**
   - Extract `ticket_id` (required) and `--contract-path` (optional) from `$ARGUMENTS`

2. **Dispatch to node_dod_verify via onex run:**
   ```bash
   cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok: example command in documentation
   uv run onex run node_dod_verify -- \
     --ticket-id <ticket_id> \
     --contract-path <path>  # if provided
   ```

   The node handles all evidence verification internally:
   - Locates the ticket contract (auto-detect or explicit path)
   - Loads `dod_evidence[]` from the contract
   - Runs evidence checks (file existence, test execution, API content, etc.)
   - Writes the evidence receipt to `.evidence/{ticket_id}/dod_report.json`

3. **Render results from node output:**

   Parse the JSON output and render the human-readable summary:

   ```
   DoD Evidence Report for OMN-1234
   =================================

   | # | Description | Status | Duration |
   |---|------------|--------|----------|
   | dod-001 | Tests exist and pass | verified | 1.2s |
   | dod-002 | Config file created | failed | 0.1s |
   | dod-003 | API health check | skipped | - |

   Summary: 1 verified, 1 failed, 1 skipped (3 total)
   Receipt: .evidence/OMN-1234/dod_report.json

   Next steps:
   - Fix dod-002: No files matching pattern config/*.yaml
   - dod-003 was skipped (endpoint checks require live infra)
   ```

## Architecture

```
SKILL.md   -> descriptive documentation (this file)
node       -> omnimarket/src/omnimarket/nodes/node_dod_verify/ (business logic)
contract   -> node_dod_verify/contract.yaml (inputs/outputs/topics)
```

This skill is a **thin wrapper** — it parses arguments, dispatches to the omnimarket
node via `onex run node_dod_verify`, and renders results. All evidence checking
logic lives in the node handler.

---

## DurableEvidenceGate (OMN-10407)

`node_dod_verify` runs a `DurableEvidenceGate` before approving any Linear Done
transition. The gate is pure logic over three pluggable probes. A gate failure
returns `status: failed` and identifies the first failing check.

**Background:** The OMN-9855 incident closed a ticket as Done after generating a DoD
receipt locally (never committing it) and updating the Linear description to point at a
PR. The contract on `onex_change_control/main` still cited the superseded PR. The gate
was added to make this class of silent-broken-trail impossible.

### Gate checks (EnumDurableEvidenceCheck)

| Check ID | Name | What it validates | Evidence required to pass |
|----------|------|-------------------|--------------------------|
| `receipt_tracked` | RECEIPT_TRACKED | `evidence/<TICKET>/dod_report.json` is committed and tracked on `onex_change_control/main` (not local-only) | Run `git -C <occ_repo> ls-tree HEAD evidence/<ticket>/dod_report.json` — must return a blob entry |
| `contract_cites_merge_commit` | CONTRACT_CITES_MERGE_COMMIT | The contract's `dod_evidence[].pr_url` resolves to a MERGED PR and its `mergeCommit.oid` matches the SHA cited in the contract | `gh pr view <pr_number> --repo <owner>/<repo> --json mergeCommit,state` — `state` must be `MERGED`; `mergeCommit.oid` must match cited SHA |
| `contract_on_occ_main` | CONTRACT_ON_OCC_MAIN | The contract version on `onex_change_control/main` already contains the real merge commit citation — not a stale pre-merge version | `git -C <occ_repo> show HEAD:<contract_path>` must contain a non-empty `mergeCommit` field matching the verified SHA |

### Failure surface

When any check fails, the node raises `DurableEvidenceGateError` (defined in
`omnimarket/src/omnimarket/nodes/node_dod_verify/services/durable_evidence_gate.py`).
The skill renders:

```
DurableEvidenceGate FAILED for OMN-XXXX
  Check: receipt_tracked
  Message: evidence/OMN-XXXX/dod_report.json is NOT tracked on onex_change_control/main.
           Commit and push the receipt to onex_change_control before re-running the gate.
```

All three checks run; the gate result contains `checks: list[ModelDurableEvidenceCheckResult]`
with `passed: bool` and `message: str` per check. The `message` on failure carries the
remediation hint the worker should follow before re-running the gate.

### Gate model paths

- Gate service: `omnimarket/src/omnimarket/nodes/node_dod_verify/services/durable_evidence_gate.py`
- Gate models: `omnimarket/src/omnimarket/nodes/node_dod_verify/models/model_durable_evidence_gate.py`
  - `EnumDurableEvidenceCheck` — check IDs (`RECEIPT_TRACKED`, `CONTRACT_CITES_MERGE_COMMIT`, `CONTRACT_ON_OCC_MAIN`)
  - `ModelDurableEvidenceCheckResult` — per-check result (`check`, `passed`, `message`)
  - `ModelDurableEvidenceGateResult` — full gate result (`ticket_id`, `status`, `checks`)
  - `ModelCitedMergeCommit` — a single PR/merge-commit citation extracted from `dod_evidence[]`

---

## New evidence type: rendered_output

For tickets tagged with data pipeline, dashboard, or display labels:

```yaml
dod_evidence:
  - type: rendered_output
    method: api_content  # or playwright_screenshot
    url: http://localhost:3000/api/registry/nodes
    assertions:
      - field: "[0].service_name"
        op: not_matches
        expected: "^[0-9a-f]{8}-"
      - field: "length"
        op: gte
        expected: 1
```

**Verification logic:**
- `api_content`: curl the URL, parse JSON, run assertions using the shared golden_path_validate operator vocabulary. This is evidence verification.
- `playwright_screenshot`: navigate to URL, take screenshot. **Important**: `playwright_screenshot` is evidence collection, not evidence verification, unless paired with rendered-state assertions or a structured classifier result (e.g., dashboard_sweep DATA_MISMATCH detection). Image capture alone is not sufficient as standalone proof.

---

## Integration Points

- **ticket-pipeline**: The `dod_verify` phase calls this same runner
- **epic-team**: The DoD audit wave runs this across all completed tickets
- **PreToolUse hook**: The completion guard checks the receipt this skill produces
- **generate-ticket-contract**: Populates `dod_evidence[]` from Linear DoD

---

## Error Handling

- If the contract file does not exist: offer to generate it
- If the contract has no `dod_evidence`: report cleanly, exit 0
- If a check times out: mark as `failed` with timeout message
- If the runner itself errors: report the error, do not write a receipt
