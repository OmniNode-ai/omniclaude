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
args:
  - name: ticket_id
    description: Linear ticket ID (e.g., OMN-1234)
    required: true
  - name: --contract-path
    description: Override path to contract YAML (default auto-detect)
    required: false
mode: full
---

# dod-verify

**Skill ID**: `onex:dod_verify`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-5174

---

## Purpose

Run DoD evidence checks for a ticket and generate a structured verification receipt.
This is the voluntary verification entry point that agents can invoke before marking
a ticket as Done.

---

## Usage

```
/dod-verify OMN-1234
/dod-verify OMN-1234 --contract-path contracts/OMN-1234.yaml
```

---

## Behavior

1. **Locate ticket contract:**
   - If `--contract-path` is provided, use that path directly
   - Otherwise, check `$ONEX_CC_REPO_PATH/contracts/{ticket_id}.yaml`
   - If neither works, offer to run `onex:generate-ticket-contract {ticket_id}` first

2. **Load contract and extract `dod_evidence[]`:**
   - Parse the YAML contract
   - If `dod_evidence` is empty or missing, report "No DoD evidence items to verify"
     and exit cleanly

3. **Run evidence checks:**
   Use the shared runner at `plugins/onex/skills/_lib/dod-evidence-runner/dod_evidence_runner.py`:
   ```python
   from dod_evidence_runner import run_dod_evidence, write_evidence_receipt
   result = run_dod_evidence(contract["dod_evidence"])
   receipt_path = write_evidence_receipt(ticket_id, contract_path, result)
   ```

4. **Write evidence receipt:**
   Receipt is written to `.evidence/{ticket_id}/dod_report.json` in the current
   working directory. This receipt is checked by the PreToolUse completion guard hook.

5. **Output human-readable summary:**

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
