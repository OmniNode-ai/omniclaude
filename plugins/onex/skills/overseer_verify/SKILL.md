---
description: Run the deterministic overseer verification gate against a ticket or PR
mode: full
version: 1.0.0
level: intermediate
debug: false
category: verification
tags:
  - overseer
  - verification
  - deterministic
  - quality-gate
  - OMN-8025
author: OmniClaude Team
args:
  - name: --ticket
    description: "Linear ticket ID to verify (e.g. OMN-1234) — mutually exclusive with --pr"
    required: false
  - name: --pr
    description: "GitHub PR in '<repo>#<num>' format (e.g. omnimarket#186) — mutually exclusive with --ticket"
    required: false
  - name: --status
    description: "Task status to report to the verifier (default: completed)"
    required: false
  - name: --confidence
    description: "Model confidence score 0.0–1.0 (optional; triggers outcome_success_validation if provided)"
    required: false
  - name: --attempt
    description: "Attempt number (default: 1)"
    required: false
  - name: --dry-run
    description: "Print the resolved args without running verification"
    required: false
---

# Overseer Verify

**Skill ID**: `onex:overseer_verify`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-8025

---

## Purpose

Thin skill surface that dispatches to `node_overseer_verifier` in omnimarket.
Runs the deterministic 5-check gate against a ticket or PR and renders
the verdict with per-check detail.

The 5 checks (all pure Python, zero LLM):
1. `input_completeness` — required fields present and non-empty
2. `contract_compliance` — schema_version and domain valid
3. `allowed_action_scope` — claimed actions within permitted set
4. `invariant_preservation` — numeric invariants hold (cost ≥ 0, attempt ≥ 1)
5. `outcome_success_validation` — confidence meets threshold (if provided)

Verdict: **PASS** | **FAIL** | **ESCALATE**
- PASS → all 5 checks pass
- FAIL → at least one check failed (non-escalating failure class)
- ESCALATE → invariant violation or verifier rejection (requires human review)

---

## Usage

```
/overseer --ticket OMN-1234
/overseer --pr omnimarket#186
/overseer --ticket OMN-1234 --confidence 0.92
/overseer --ticket OMN-1234 --dry-run
```

---

## Behavior

### Step 1 — Parse arguments

Exactly one of `--ticket` or `--pr` is required.

- `--ticket OMN-XXXX` → domain=`ticket_pipeline`, node_id=`node_ticket_pipeline`
- `--pr <repo>#<num>` → domain=`build_loop`, node_id=`node_build_loop_orchestrator`
- `--status` (default: `completed`)
- `--confidence` (optional float 0.0–1.0)
- `--attempt` (default: 1)
- `--dry-run` → echo resolved args and exit 0

### Step 2 — Run node

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_overseer_verifier \
  --ticket <ticket_id>          # or --pr <repo>#<num>
  [--status <status>]
  [--confidence <float>]
  [--attempt <int>]
  [--dry-run]
```

Capture stdout (JSON verdict). Exit 0 = PASS, exit 1 = FAIL or ESCALATE.

### Step 3 — Render results

Parse JSON output and render:

```
Overseer Verification — OMN-1234
==================================================

Verdict: PASS

Check Results:
  [PASS] input_completeness
  [PASS] contract_compliance
  [PASS] allowed_action_scope
  [PASS] invariant_preservation
  [PASS] outcome_success_validation — confidence not provided; skipping threshold check.
```

On FAIL or ESCALATE:

```
Overseer Verification — OMN-1234
==================================================

Verdict: ESCALATE
Failure class: DATA_INTEGRITY
Summary: Check failed: invariant_preservation — INVARIANT_VIOLATION: cost_so_far=-1.0 must be >= 0.0

Check Results:
  [PASS] input_completeness
  [PASS] contract_compliance
  [PASS] allowed_action_scope
  [FAIL] invariant_preservation — INVARIANT_VIOLATION: cost_so_far=-1.0 must be >= 0.0
  [PASS] outcome_success_validation
```

**ESCALATE verdicts require human review.** Surface the failure class and which
check failed. Do not auto-retry or suppress the escalation.

---

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_overseer_verifier/ (pure Python gate)
contract   -> node_overseer_verifier/contract.yaml
__main__   -> omnimarket/src/omnimarket/nodes/node_overseer_verifier/__main__.py
```

This skill is a **thin wrapper** — argument parsing and result rendering only.
All 5-check logic lives in `HandlerOverseerVerifier`.

---

## Automated path (Kafka)

The same gate runs automatically in the build loop pipeline:
- **CLASSIFYING → BUILDING**: advisory check (ESCALATE logged, not blocking)
- **BUILDING phase (per-target)**: hard DoD check after each dispatch
- **VERIFYING phase**: full async correlated-wait via `onex.cmd.omnimarket.overseer-verify.v1`

This skill is the **manual trigger** for the same gate. Use it to:
- Verify a ticket before marking Done
- Spot-check a PR before requesting review
- Debug why a build loop VERIFYING phase is failing

---

## Error Handling

- If neither `--ticket` nor `--pr` provided: error with usage hint
- If `--pr` format invalid (`<repo>#<num>`): error with format example
- If node exits 1 (FAIL/ESCALATE): surface verdict, do not treat as tool error
- If `uv run` fails: report the raw error; suggest `uv sync` in omnimarket
