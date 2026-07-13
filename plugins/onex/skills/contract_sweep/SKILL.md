---
description: Unified contract health skill — drift mode (static cross-repo drift detection) and the node_contract_sweep field/topic compliance sweep; supersedes the earlier contract_verify skill
version: 3.1.0
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
  - verification
author: OmniClaude Team
composable: true
args:
  - name: --mode
    description: "Operation mode: drift (static drift detection), compliance (node_contract_sweep field/topic checks). Default: drift"
    required: false
  - name: --drift
    description: "Shorthand for --mode drift"
    required: false
  - name: --compliance
    description: "Shorthand for --mode compliance"
    required: false
  - name: --repos
    description: "Comma-separated repo names. REQUIRED for --compliance (harness-collected census — see Compliance Mode). Optional for --drift (default: all 8 repos)."
    required: false
  - name: --dry-run
    description: "Print findings only, no ticket creation"
    required: false
  - name: --severity-threshold
    description: "Ticket severity floor: BREAKING | ADDITIVE | NON_BREAKING (default: BREAKING). Applies to drift mode only."
    required: false
  - name: --sensitivity
    description: "Drift sensitivity: STRICT | STANDARD | LAX (default: STANDARD). Applies to drift mode only."
    required: false
  - name: --check-boundaries
    description: "Also validate Kafka boundary parity (default: true). Applies to drift mode only."
    required: false
---

# contract_sweep

**Announce at start:** "I'm using the contract-sweep skill."

Unified contract health skill combining two detection modes:

1. **Drift mode** (`--drift`) — Static cross-repo contract drift detection. Wraps the
   `check-drift` infrastructure from `onex_change_control` to scan all repos for contracts
   that have drifted from their pinned baselines and Kafka boundaries that have become stale.

2. **Compliance mode** (`--compliance`) — Static field/topic/node_type compliance sweep of
   `contract.yaml` files via `node_contract_sweep` (`omnimarket`). Checks required fields,
   `onex.{cmd|evt|intent}.producer.event.vN` topic naming, and declared `node_type` against
   the canonical set. This is a pure filesystem check — it does NOT connect to a running
   system, and it has no "registration_only" or live-runtime probe mode (an earlier
   revision of this file documented a `registration_only` field and an
   `onex run-node node_contract_sweep` invocation that never existed on the node's actual
   request model, which is `extra="forbid"` and would reject that input outright — that
   fictional Runtime Mode section has been removed).

Default mode when no flag is specified: `--drift`.

## Usage

```
/contract-sweep --drift
/contract-sweep --compliance --repos omnimarket
/contract-sweep --drift --dry-run
/contract-sweep --drift --repos omnibase_infra,omnibase_core
/contract-sweep --drift --severity-threshold ADDITIVE
/contract-sweep --drift --sensitivity STRICT
/contract-sweep --drift --check-boundaries false
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
- `--severity-threshold` → minimum ticket-creation severity (default: BREAKING)
- `--sensitivity` → STRICT | STANDARD | LAX (default: STANDARD)
- `--check-boundaries` → validate Kafka boundary YAML parity (default: true)

### Step 2 — Run contract drift check

Run the `check_contract_drift.py` script from `onex_change_control` once per repo:

```bash
cd $ONEX_WORKTREES_ROOT/<ticket>/onex_change_control
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
using the same key. If found, update or comment. If prior ticket is
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

## Compliance Mode

Static field/topic/node_type compliance sweep via `node_contract_sweep` (`omnimarket`).
This is a pure filesystem COMPUTE check — no live-runtime connection, no registration
probe, no "registration_only" input. It reads `contract.yaml` files under the requested
repos and checks: required fields (`name`, `contract_version`, `node_type`,
`node_version`, `description`), `node_type` against the canonical set, and
`event_bus.publish_topics` / `subscribe_topics` naming
(`onex.{cmd|evt|intent}.producer.event.vN`).

### Compliance Mode Execution

`--repos` is REQUIRED on the underlying CLI — there is no "scan everything"
default. The census must come from a real filesystem probe run by the caller (a CI
workflow step, `scripts/ci/run_contract_sweep_gate.py`, or an equivalent harness) — never
an operator-typed convenience value and never prose in this file:

```bash
uv run python -m omnimarket.nodes.node_contract_sweep --repos omnimarket
```

Prints a `ContractSweepResult` JSON to stdout (`violations`, `contracts_checked`,
`scanned_count`, `summary`, `status`, `missing_repos`, `scope_error`).

### Compliance Exit Codes

| Code | `status` | Meaning | Action |
|------|----------|---------|--------|
| 0 | `PASS` | Scope resolved (`scanned_count > 0`), zero violations | none |
| 1 | `FAIL` | Scope resolved, violations found | route to failure-to-ticket |
| 1 | `ERROR` | Scope could not be trusted — `OMNI_HOME` unset, a requested repo missing on disk, or `scanned_count == 0` | investigate the census/harness; never treat as a clean sweep |

`ERROR` and `FAIL` both exit 1 — a caller distinguishing them should read `status` in the
JSON body, not just the exit code.

### Deduplication

Compliance failure tickets are keyed by `node_name:violation_type`. Repeated failures do
not create duplicate tickets — they update or comment on the existing open ticket.

---

Ticket Priority mapping:
- BREAKING → Critical
- ADDITIVE → Major
- NON_BREAKING → Minor

- **close-day**: Drift mode runs as end-of-day contract health check
- **integration-sweep**: Complementary (integration-sweep validates DoD; contract-sweep validates drift + field/topic compliance)
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
- `python -m omnimarket.nodes.node_contract_sweep --repos <repo,...>` (required-field +
  topic-naming compliance sweep, compliance mode — `--repos` is required, see above)
- `onex_change_control/scripts/validation/check_contract_drift.py` (hash-based drift, drift mode)
- `onex_change_control/handlers/handler_drift_analysis.py` (field-level analysis, drift mode)
- `onex_change_control/boundaries/kafka_boundaries.yaml` (boundary manifest, drift mode)

## See Also

- `contract-compliance-check` skill -- Pre-merge seam validation (per-ticket, per-branch)
- `NodeContractDriftCompute` in `onex_change_control` -- The underlying ONEX node
- `kafka_boundaries.yaml` -- Cross-repo Kafka boundary manifest
