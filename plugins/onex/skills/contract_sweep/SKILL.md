---
description: Unified contract health skill — drift mode (static cross-repo drift detection) and runtime mode (live compliance verification); replaces contract_verify (OMN-8073)
version: 3.0.0
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
  - runtime
  - verification
author: OmniClaude Team
composable: true
args:
  - name: --mode
    description: "Operation mode: drift (static drift detection), runtime (live runtime verification), full (both). Default: drift"
    required: false
  - name: --drift
    description: "Shorthand for --mode drift"
    required: false
  - name: --runtime
    description: "Shorthand for --mode runtime"
    required: false
  - name: --full
    description: "Shorthand for --mode full (drift + runtime)"
    required: false
  - name: --repos
    description: "Comma-separated repo names (default: all 8 repos). Applies to drift mode only."
    required: false
  - name: --dry-run
    description: "Print findings only, no ticket creation"
    required: false
  - name: --severity-threshold
    description: "Min severity for tickets: BREAKING | ADDITIVE | NON_BREAKING (default: BREAKING). Applies to drift mode only."
    required: false
  - name: --sensitivity
    description: "Drift sensitivity: STRICT | STANDARD | LAX (default: STANDARD). Applies to drift mode only."
    required: false
  - name: --check-boundaries
    description: "Also validate Kafka boundary parity (default: true). Applies to drift mode only."
    required: false
  - name: --all
    description: "Run full 52-contract runtime verification (default: registration-only). Applies to runtime mode only."
    required: false
---

# contract_sweep

**Announce at start:** "I'm using the contract-sweep skill."

Unified contract health skill combining two detection modes:

1. **Drift mode** (`--drift`) — Static cross-repo contract drift detection. Wraps the
   `check-drift` infrastructure from `onex_change_control` to scan all repos for contracts
   that have drifted from their pinned baselines and Kafka boundaries that have become stale.

2. **Runtime mode** (`--runtime`) — Live runtime contract compliance verification. Reads
   `contract.yaml` files from the `omnibase_infra` verification subsystem and verifies that
   the running system matches the declarations: registered handlers, subscribed topics,
   published events, and cross-contract references.

3. **Full mode** (`--full`) — Runs both drift and runtime modes sequentially.

Default mode when no flag is specified: `--drift`.

## Usage

```
/contract-sweep --drift
/contract-sweep --runtime
/contract-sweep --full
/contract-sweep --drift --dry-run
/contract-sweep --drift --repos omnibase_infra,omnibase_core
/contract-sweep --drift --severity-threshold ADDITIVE
/contract-sweep --drift --sensitivity STRICT
/contract-sweep --drift --check-boundaries false
/contract-sweep --runtime --all
```

---

## Drift Mode

Cross-repo contract drift detection. Wraps the `check-drift` infrastructure from
`onex_change_control` to scan all repos for contracts that have drifted from their
pinned baselines and Kafka boundaries that have become stale.

This mode combines two detection sub-modes:

1. **Contract drift** -- Uses `check_contract_drift.py` and the `handler_drift_analysis`
   handler from `onex_change_control` to compute canonical hashes of all contracts and
   compare them against pinned snapshots. When drift is detected, performs field-level
   analysis to classify changes as BREAKING, ADDITIVE, or NON_BREAKING.

2. **Boundary staleness** -- Validates that cross-repo Kafka topic boundaries declared in
   `kafka_boundaries.yaml` still match the actual producer/consumer files in each repo.

### Drift Detection Pipeline

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

### Drift Classification

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

### Boundary Staleness Checks

When `--check-boundaries` is enabled (default), the skill also validates:

1. **Producer file exists** -- The declared producer file still exists in the producer repo
2. **Consumer file exists** -- The declared consumer file still exists in the consumer repo
3. **Topic pattern match** -- The topic regex still matches content in both files
4. **No undeclared cross-repo topics** -- Topics in code that cross repo boundaries but are not in the boundary manifest

### Severity and Ticket Creation

| Drift Severity | Ticket Priority | Action |
|---------------|-----------------|--------|
| **BREAKING** | Critical | Always create ticket |
| **ADDITIVE** | Major | Create if threshold <= ADDITIVE |
| **NON_BREAKING** | Minor | Create if threshold <= NON_BREAKING |
| **Stale boundary** | Critical | Always create ticket (boundary mismatch = potential runtime failure) |
| **Undeclared boundary** | Major | Create if threshold <= ADDITIVE |

Ticket dedup: keyed by `(repo, contract_path, drift_type)`. Before creating, search Linear
for an open ticket matching the same key. If found, update or comment. If prior ticket is
closed but same drift recurs, create new ticket referencing the prior closure.

### Drift Mode Output

Written to `$ONEX_STATE_DIR/contract-sweep/<run-id>/report.yaml`:

```yaml
run_id: "<YYYYMMDD-HHMMSS>"
timestamp: "<ISO-8601>"
repos_scanned: ["omnibase_core", ...]
sensitivity: "STANDARD"
total_contracts: <count>
drift_findings:
  - repo: "<repo>"
    path: "<contract-path>"
    severity: "BREAKING"
    current_hash: "<sha256>"
    pinned_hash: "<sha256>"
    field_changes:
      - path: "input_schema.type"
        change_type: "modified"
        is_breaking: true
    summary: "<one-line>"
boundary_findings:
  - boundary_name: "<topic>"
    issue: "producer_file_missing"
    producer_repo: "<repo>"
    consumer_repo: "<repo>"
    message: "<description>"
by_severity: {BREAKING: 0, ADDITIVE: 0, NON_BREAKING: 0}
stale_boundaries: 0
repos_not_found: []
baseline_missing: []
overall_status: "<clean|drifted|breaking>"
tickets_created: []
```

---

## Runtime Mode

Runtime contract compliance verification. Reads `contract.yaml` files from the
`omnibase_infra` verification subsystem and verifies that the running system matches
the declarations: registered handlers, subscribed topics, published events, and
cross-contract references.

### Runtime Mode Execution

```bash
# Compliance sweep (required fields, topic naming, node_type) via omnimarket node
onex run node_contract_sweep -- [--repos <comma-separated>] [--dry-run]

# Registration-only (default)
uv run python -m omnibase_infra.verification.cli --registration-only --json

# Full 52-contract verification (--all flag)
uv run python -m omnibase_infra.verification.cli --json

# With explicit output path
uv run python -m omnibase_infra.verification.cli --registration-only --json \
  --output-path "$ONEX_STATE_DIR/contract-sweep/<run_id>/runtime-report.json"
```

### Runtime Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | PASS | All checks passed |
| 1 | FAIL | One or more checks failed — route to failure-to-ticket |
| 2 | QUARANTINE | Checks could not run (infra down, missing contracts) — warn only |

### Runtime Result Handling

On PASS (exit 0): Print `CONTRACT_VERIFY: PASS (N checks passed)`.

On FAIL (exit 1): Print failure summary and route to `auto_ticket_from_findings`.
Do not create tickets for QUARANTINE results.

### Sustained PASS Auto-Close

When runtime verification produces PASS for 2 consecutive runs:
- Query open tickets with label `contract-verify` matching the now-passing checks
- Auto-close with comment: `Sustained PASS across 2 consecutive runs. Auto-closing.`

### Deduplication

Runtime failure tickets are keyed by `contract_name:check_type`. Repeated failures do
not create duplicate tickets — they update or comment on the existing open ticket.

---

Ticket Priority mapping:
- BREAKING → Critical
- ADDITIVE → Major
- NON_BREAKING → Minor

- **close-day**: Drift mode runs as end-of-day contract health check; runtime mode runs as Phase B6
- **integration-sweep**: Complementary (integration-sweep validates DoD; contract-sweep validates drift + runtime compliance)
- **ci-watch**: Drift mode can be triggered after CI passes to verify no contract drift was introduced

## Repo List (Drift Mode)

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
node_contract_sweep   -> omnimarket/nodes/node_contract_sweep/ (compliance sweep: fields, topics, node_type)
NodeContractDriftCompute -> omnimarket/nodes/node_contract_drift_compute/ (classification)
check_drift           -> onex_change_control/scripts/validation/check_contract_drift.py
handler_drift_analysis -> onex_change_control/handlers/handler_drift_analysis.py
boundaries            -> onex_change_control/boundaries/kafka_boundaries.yaml
```

The skill wraps:
- `onex run node_contract_sweep` (required-field + topic-naming compliance sweep, runtime mode)
- `onex_change_control/scripts/validation/check_contract_drift.py` (hash-based drift, drift mode)
- `onex_change_control/handlers/handler_drift_analysis.py` (field-level analysis, drift mode)
- `onex_change_control/boundaries/kafka_boundaries.yaml` (boundary manifest, drift mode)
- `omnibase_infra.verification.cli` (registration verification, runtime mode)

## See Also

- `contract-compliance-check` skill -- Pre-merge seam validation (per-ticket, per-branch)
- `NodeContractDriftCompute` in `onex_change_control` -- The underlying ONEX node
- `kafka_boundaries.yaml` -- Cross-repo Kafka boundary manifest
- OMN-5162 -- Original check-drift script
- OMN-6725 -- contract-sweep drift tracking ticket
- OMN-7040 -- contract-verify original ticket (merged into contract-sweep via OMN-8073)
- OMN-8073 -- Merge contract_verify into contract_sweep
