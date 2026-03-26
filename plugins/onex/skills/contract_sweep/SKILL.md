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

Cross-repo contract drift detection. Wraps the `check-drift` infrastructure from
`onex_change_control` to scan all repos for contracts that have drifted from their
pinned baselines and Kafka boundaries that have become stale.

This skill combines two detection modes:

1. **Contract drift** -- Uses `check_contract_drift.py` and the `handler_drift_analysis`
   handler from `onex_change_control` to compute canonical hashes of all contracts and
   compare them against pinned snapshots. When drift is detected, performs field-level
   analysis to classify changes as BREAKING, ADDITIVE, or NON_BREAKING.

2. **Boundary staleness** -- Validates that cross-repo Kafka topic boundaries declared in
   `kafka_boundaries.yaml` still match the actual producer/consumer files in each repo.

## Usage

```
/contract-sweep --dry-run
/contract-sweep --repos omnibase_infra,omnibase_core
/contract-sweep --severity-threshold ADDITIVE
/contract-sweep --sensitivity STRICT
/contract-sweep --check-boundaries false
```

## Drift Detection Pipeline

The skill delegates to the ONEX contract drift node pipeline in `onex_change_control`:

```
NodeContractDriftCompute (detect + classify)
    -> NodeContractDriftReducer (accumulate history)
    -> NodeContractDriftEffect (emit events)
```

For CLI-level invocation, it uses:

```bash
# Per-repo hash check
python3 onex_change_control/scripts/validation/check_contract_drift.py \
  --root <repo>/src --check <snapshot-file>

# Cross-repo boundary parity
python3 onex_change_control/scripts/validation/check_boundary_parity.py \
  --boundaries onex_change_control/src/onex_change_control/boundaries/kafka_boundaries.yaml \
  --omni-home $OMNI_HOME
```

## Drift Classification

Field-level changes are classified using the `handler_drift_analysis` module:

| Classification | Root Keys | Meaning |
|---------------|-----------|---------|
| **BREAKING** | `algorithm`, `input_schema`, `output_schema`, `type`, `required`, `parallel_processing`, `transaction_management` | Changes to the observable contract interface |
| **ADDITIVE** | New fields not in breaking paths | Non-breaking additions |
| **NON_BREAKING** | `description`, `docs`, `changelog`, `comments`, `author`, `license` | Documentation/metadata changes |

Sensitivity levels control which changes surface:

| Sensitivity | Surfaces |
|-------------|----------|
| **STRICT** | All changes including NON_BREAKING |
| **STANDARD** | BREAKING + ADDITIVE (default) |
| **LAX** | BREAKING only |

## Boundary Staleness Checks

When `--check-boundaries` is enabled (default), the skill also validates:

1. **Producer file exists** -- The declared producer file still exists in the producer repo
2. **Consumer file exists** -- The declared consumer file still exists in the consumer repo
3. **Topic pattern match** -- The topic regex still matches content in both files
4. **No undeclared cross-repo topics** -- Topics in code that cross repo boundaries but are not in the boundary manifest

## Severity and Ticket Creation

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

## Output

### Report file

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
overall_status: "<clean|drifted|breaking>"
tickets_created: []
```

### Summary output

```
Contract Drift Sweep Results
=============================
Repos scanned: 8
Total contracts: <N>
Sensitivity: STANDARD

Drift findings:
  BREAKING:     <N>
  ADDITIVE:     <N>
  NON_BREAKING: <N>

Boundary findings:
  Stale:      <N>
  Undeclared: <N>

Overall status: <clean|drifted|breaking>
```

### Status determination

- `clean` -- No drift detected, all boundaries valid
- `drifted` -- ADDITIVE or NON_BREAKING drift only, no boundary issues
- `breaking` -- Any BREAKING drift or stale boundary found

## Integration

- **close-day**: Run as end-of-day contract health check
- **integration-sweep**: Complementary (integration-sweep validates DoD; contract-sweep validates drift)
- **ci-watch**: Can be triggered after CI passes to verify no contract drift was introduced

## Repo List

Default scan targets (8 repos):

```
omnibase_core, omnibase_infra, omniclaude, omniintelligence,
omnimemory, omninode_infra, omnibase_spi, onex_change_control
```

## Architecture

```
SKILL.md   -> descriptive documentation (this file)
prompt.md  -> execution instructions for the agent
```

The skill wraps:
- `onex_change_control/scripts/validation/check_contract_drift.py` (hash-based drift)
- `onex_change_control/handlers/handler_drift_analysis.py` (field-level analysis)
- `onex_change_control/boundaries/kafka_boundaries.yaml` (boundary manifest)

## See Also

- `contract-compliance-check` skill -- Pre-merge seam validation (per-ticket, per-branch)
- `NodeContractDriftCompute` in `onex_change_control` -- The underlying ONEX node
- `kafka_boundaries.yaml` -- Cross-repo Kafka boundary manifest
- OMN-5162 -- Original check-drift script
- OMN-6725 -- This skill's tracking ticket
