---
description: Cross-repo contract drift detection — wraps the check-drift CLI from onex_change_control to scan all repos for drifted contracts and stale boundaries
version: 2.0.0
mode: full
level: advanced
debug: false
category: verification
tags:
  - contracts
  - drift
  - boundaries
  - cross-repo
  - health-check
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated repo names (default: all 8 repos)"
    required: false
  - name: --dry-run
    description: "Print findings only, no ticket creation"
    required: false
  - name: --severity-threshold
    description: "Min severity for tickets: BREAKING | ADDITIVE | NON_BREAKING (default: BREAKING)"
    required: false
  - name: --sensitivity
    description: "Drift sensitivity: STRICT | STANDARD | LAX (default: STANDARD)"
    required: false
  - name: --check-boundaries
    description: "Also validate Kafka boundary parity (default: true)"
    required: false
---

# contract_sweep

**Announce at start:** "I'm using the contract-sweep skill."

## Usage

```
/contract-sweep --dry-run
/contract-sweep --repos omnibase_infra,omnibase_core
/contract-sweep --severity-threshold ADDITIVE
/contract-sweep --sensitivity STRICT
/contract-sweep --check-boundaries false
```

## Execution

### Step 1 — Parse arguments

- `--repos` → comma-separated repo names (default: all 8)
- `--dry-run` → findings only, no ticket creation
- `--severity-threshold` → minimum severity for ticket creation (default: BREAKING)
- `--sensitivity` → STRICT | STANDARD | LAX (default: STANDARD)
- `--check-boundaries` → validate Kafka boundary YAML parity (default: true)

### Step 2 — Run contract drift check

For each repo, run the `check_contract_drift.py` script from `onex_change_control`:

```bash
cd /Volumes/PRO-G40/Code/omni_home/onex_change_control  # local-path-ok
python3 scripts/validation/check_contract_drift.py \
  --root <repo>/src \
  --check <snapshot-file>
```

Drift is classified using `handler_drift_analysis`:

| Severity | Root Keys |
|----------|-----------|
| BREAKING | `algorithm`, `input_schema`, `output_schema`, `type`, `required` |
| ADDITIVE | New fields not in breaking paths |
| NON_BREAKING | `description`, `docs`, `changelog`, `author` |

Sensitivity controls what surfaces: STRICT = all, STANDARD = BREAKING+ADDITIVE, LAX = BREAKING only.

### Step 3 — Boundary staleness check (unless `--check-boundaries false`)

Read `onex_change_control/boundaries/kafka_boundaries.yaml`. For each declared boundary verify:
1. Producer file still exists in the producer repo
2. Consumer file still exists in the consumer repo
3. Topic regex still matches content in both files
4. No undeclared cross-repo topics in code

### Step 4 — Report

Write to `$ONEX_STATE_DIR/contract-sweep/<run-id>/report.yaml`. Display:

```
Contract Drift Sweep Results
Repos scanned: 8 | Sensitivity: STANDARD
Drift: BREAKING <n> | ADDITIVE <n> | NON_BREAKING <n>
Boundaries: Stale <n> | Undeclared <n>
Overall: clean | drifted | breaking
```

### Step 5 — Ticket creation (unless `--dry-run`)

For each finding at or above `--severity-threshold`, search Linear for an existing open ticket
keyed by `(repo, contract_path, drift_type)`. If none found, create via `mcp__linear-server__save_issue`.
Stale boundaries always create tickets (boundary mismatch = potential runtime failure).

Ticket Priority mapping:
- BREAKING → Critical
- ADDITIVE → Major
- NON_BREAKING → Minor

### Step 6 — Write skill result

Write to `$ONEX_STATE_DIR/skill-results/<run-id>/contract-sweep.json`:

```json
{
  "skill": "contract-sweep",
  "status": "clean | drifted | breaking | error",
  "repos_scanned": 0,
  "drift_findings": [],
  "boundary_findings": [],
  "tickets_created": 0
}
```

## Default Repos

```
omnibase_core, omnibase_infra, omniclaude, omniintelligence,
omnimemory, omninode_infra, omnibase_spi, onex_change_control
```

## Architecture

```
SKILL.md              -> thin shell (this file)
NodeContractDriftCompute -> omnimarket/nodes/node_contract_drift_compute/ (classification)
check_drift           -> onex_change_control/scripts/validation/check_contract_drift.py
handler_drift_analysis -> onex_change_control/handlers/handler_drift_analysis.py
boundaries            -> onex_change_control/boundaries/kafka_boundaries.yaml
```
