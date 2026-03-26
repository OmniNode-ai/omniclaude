# contract_sweep prompt

You are executing the **contract-sweep** skill. This skill wraps the check-drift CLI from
`onex_change_control` to scan all repos for drifted contracts and stale Kafka boundaries.

## Announce

Say: "I'm using the contract-sweep skill to detect contract drift and stale boundaries across all repos."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--repos <comma-list>` -- Repos to scan (default: all 8)
- `--dry-run` -- Print findings only, no ticket creation
- `--severity-threshold <BREAKING|ADDITIVE|NON_BREAKING>` -- Min severity for tickets (default: BREAKING)
- `--sensitivity <STRICT|STANDARD|LAX>` -- Drift sensitivity (default: STANDARD)
- `--check-boundaries <true|false>` -- Validate Kafka boundary parity (default: true)

**Repo list** (hardcoded, scan all unless `--repos` overrides):
```
omnibase_core, omnibase_infra, omniclaude, omniintelligence, omnimemory, omninode_infra, omnibase_spi, onex_change_control
```

**Bare clone root**: `$OMNI_HOME` (typically `/Volumes/PRO-G40/Code/omni_home`)  <!-- local-path-ok -->

**Change control repo**: `$OMNI_HOME/onex_change_control`  <!-- local-path-ok -->

## Preamble: Pull bare clones

Before scanning, pull all bare clones to ensure findings reflect the latest `main`:

```bash
bash /Volumes/PRO-G40/Code/omni_home/omnibase_infra/scripts/pull-all.sh  # local-path-ok
```

If `pull-all.sh` exits non-zero, **abort the sweep immediately** with an error message
explaining that stale clones may produce ghost findings. Do not silently continue with
stale data.

## Phase 1: Contract discovery

For each repo, discover all contract files from the `main` branch:

```bash
git -C $OMNI_HOME/<repo> ls-tree -r main --name-only | grep -E '(contract|handler_contract)\.yaml$'  # local-path-ok
```

Build a list of `(repo, path)` pairs. Record the total count.

## Phase 2: Drift detection via check-drift CLI

**Note**: All commands use `uv run python3` if `uv` is available in the
`onex_change_control` repo; otherwise fall back to `python3` directly.
Snapshot files are stored at `$OMNI_HOME/onex_change_control/drift/<repo>.sha256`.

For each repo, run the check-drift script to compute a canonical hash of all
event-related contract sections (`published_events`, `event_bus`):

```bash
cd $OMNI_HOME/onex_change_control  # local-path-ok
uv run python3 scripts/validation/check_contract_drift.py \
  --root $OMNI_HOME/<repo>/src --print
```

This prints a SHA-256 hash. Compare it against any existing snapshot:

```bash
# Check if a snapshot exists for this repo
SNAPSHOT_FILE="$OMNI_HOME/onex_change_control/drift/<repo>.sha256"
if [ -f "$SNAPSHOT_FILE" ]; then
  uv run python3 scripts/validation/check_contract_drift.py \
    --root $OMNI_HOME/<repo>/src --check "$SNAPSHOT_FILE"
  # Exit 0 = clean, Exit 1 = drift detected
fi
```

If no snapshot file exists for a repo, record it as `baseline_missing` (not an error, but
note it in the report).

For repos where drift is detected (exit code 1), proceed to Phase 3 for field-level analysis.

## Phase 3: Field-level drift analysis

For each drifted contract, perform detailed field-level analysis. Read the contract content
from the repo and compare against any pinned baseline.

For each contract YAML discovered in Phase 1:

1. Read current content:
   ```bash
   git -C $OMNI_HOME/<repo> show main:<path>
   ```

2. Compute canonical hash using the same algorithm as `handler_drift_analysis.py`:
   ```python
   import hashlib, json
   canonical = json.dumps(contract_dict, sort_keys=True, default=str)
   current_hash = hashlib.sha256(canonical.encode()).hexdigest()
   ```

3. If a pinned hash is available (from snapshot or drift history), compare:
   - **Hashes match** -> NONE severity, skip
   - **Hashes differ** -> Perform recursive dict diff

4. Classify each field change:
   - Fields under `algorithm`, `input_schema`, `output_schema`, `type`, `required`,
     `parallel_processing`, `transaction_management` -> BREAKING
   - New fields not in breaking paths -> ADDITIVE
   - Fields under `description`, `docs`, `changelog`, `comments`, `author`, `license` -> NON_BREAKING
   - Removed fields -> always BREAKING

5. Determine overall severity per contract:
   - Any BREAKING change -> BREAKING
   - If sensitivity is LAX and no BREAKING -> NONE
   - Any ADDITIVE change -> ADDITIVE
   - Otherwise -> NON_BREAKING

Apply the configured `--sensitivity`:
- STRICT: surface all changes
- STANDARD: surface BREAKING + ADDITIVE
- LAX: surface BREAKING only

## Phase 4: Boundary staleness check

If `--check-boundaries` is true (default), validate the Kafka boundary manifest:

```bash
BOUNDARIES="$OMNI_HOME/onex_change_control/src/onex_change_control/boundaries/kafka_boundaries.yaml"
```

For each boundary entry in the YAML:

1. **Producer file exists**:
   ```bash
   git -C $OMNI_HOME/<producer_repo> show main:<producer_file> > /dev/null 2>&1
   ```
   If not found -> stale boundary (CRITICAL)

2. **Consumer file exists**:
   ```bash
   git -C $OMNI_HOME/<consumer_repo> show main:<consumer_file> > /dev/null 2>&1
   ```
   If not found -> stale boundary (CRITICAL)

3. **Topic pattern match**:
   ```bash
   git -C $OMNI_HOME/<producer_repo> show main:<producer_file> | grep -qE "<topic_pattern>"
   git -C $OMNI_HOME/<consumer_repo> show main:<consumer_file> | grep -qE "<topic_pattern>"
   ```
   If pattern not found in either file -> stale boundary (CRITICAL)

Record all stale boundaries with their specific failure reason.

## Phase 5: Triage and report

### Build findings list

Combine drift findings (Phase 3) and boundary findings (Phase 4) into a unified report.

### Write report

Create `$ONEX_STATE_DIR/contract-sweep/<run-id>/report.yaml` with this schema:

```yaml
run_id: "<YYYYMMDD-HHMMSS>"
timestamp: "<ISO-8601>"
repos_scanned: ["omnibase_core", "omnibase_infra", ...]
sensitivity: "<STRICT|STANDARD|LAX>"
total_contracts: <count>
drift_findings:
  - repo: "<repo>"
    path: "<contract-path>"
    severity: "<BREAKING|ADDITIVE|NON_BREAKING>"
    current_hash: "<sha256>"
    pinned_hash: "<sha256>"
    drift_detected: true
    field_changes:
      - path: "<dotted.field.path>"
        change_type: "<added|removed|modified>"
        old_value: "<value>"
        new_value: "<value>"
        is_breaking: <true|false>
    breaking_changes: ["<summary>", ...]
    additive_changes: ["<summary>", ...]
    non_breaking_changes: ["<summary>", ...]
    summary: "<one-line>"
boundary_findings:
  - boundary_name: "<topic>"
    issue: "<producer_file_missing|consumer_file_missing|pattern_not_found>"
    producer_repo: "<repo>"
    consumer_repo: "<repo>"
    producer_file: "<path>"
    consumer_file: "<path>"
    message: "<human-readable description>"
by_severity: {BREAKING: 0, ADDITIVE: 0, NON_BREAKING: 0}
stale_boundaries: 0
repos_not_found: []
baseline_missing: ["<repo>", ...]
overall_status: "<clean|drifted|breaking>"
tickets_created: []
```

### Print summary

```
Contract Drift Sweep Results
=============================
Repos scanned: <N>
Total contracts: <N>
Sensitivity: <STRICT|STANDARD|LAX>

Drift findings:
  BREAKING:     <N>
  ADDITIVE:     <N>
  NON_BREAKING: <N>

Boundary findings:
  Stale:      <N>

Repos without baseline snapshot: <list or "none">

Overall status: <clean|drifted|breaking>
Report: $ONEX_STATE_DIR/contract-sweep/<run-id>/report.yaml
```

### Status determination

- `clean` -- No drift detected, all boundaries valid
- `drifted` -- ADDITIVE or NON_BREAKING drift only, no BREAKING drift, no stale boundaries
- `breaking` -- Any BREAKING drift or any stale boundary found

## Phase 6: Ticket creation

If `--dry-run` is set, skip this phase entirely. Print: "Dry run -- skipping ticket creation."

Otherwise, for each finding above `--severity-threshold`:

### Ticket dedup

Ticket identity is keyed by `(repo, contract_path, finding_type)`.

Before creating a ticket:
1. Search Linear for an open ticket with the same key components in the title
2. If found and still open -> add a comment with the latest finding details
3. If found but closed -> create a new ticket referencing the closed one
4. If not found -> create a new ticket

### Drift ticket format

```
Title: [contract-drift] BREAKING drift in <repo>/<path> [OMN-6725]

## Drift Report

**Contract**: `<repo>/<path>`
**Severity**: BREAKING
**Current hash**: `<hash>`
**Pinned hash**: `<hash>`

### Breaking Changes
- MODIFIED input_schema.type: 'string' -> 'integer'
- REMOVED required.field_name

### Additive Changes
- ADDED metadata.new_field: 'value'

## Action Required
Update the pinned snapshot or revert the contract change.

## Detection
Detected by contract-sweep skill run <run-id>.
```

### Boundary ticket format

```
Title: [boundary-stale] <topic_name> boundary broken [OMN-6725]

## Stale Boundary

**Topic**: `<topic_name>`
**Issue**: <producer_file_missing|consumer_file_missing|pattern_not_found>
**Producer**: `<producer_repo>/<producer_file>`
**Consumer**: `<consumer_repo>/<consumer_file>`

## Details
<human-readable message>

## Action Required
Update kafka_boundaries.yaml or restore the missing file/pattern.

## Detection
Detected by contract-sweep skill run <run-id>.
```

### Priority mapping

| Finding Type | Linear Priority |
|-------------|----------------|
| BREAKING drift | 1 (Urgent) |
| Stale boundary | 1 (Urgent) |
| ADDITIVE drift | 2 (High) |
| NON_BREAKING drift | 3 (Medium) |

## Error handling

- If `check_contract_drift.py` is not found at the expected path: abort with error
- If a repo is not found at `$OMNI_HOME/<repo>`: skip that repo, record in report as `repo_not_found`
- If `kafka_boundaries.yaml` is not found: skip boundary checks, warn in output
- If YAML parsing fails for a contract: record as an ERROR finding (unparseable contract)
- If `uv` is not available: fall back to `python3` directly

## Examples

### Clean sweep (no drift)

```
Contract Drift Sweep Results
=============================
Repos scanned: 8
Total contracts: 47
Sensitivity: STANDARD

Drift findings:
  BREAKING:     0
  ADDITIVE:     0
  NON_BREAKING: 0

Boundary findings:
  Stale:      0

Repos without baseline snapshot: none

Overall status: clean
Report: $ONEX_STATE_DIR/contract-sweep/20260326-143000/report.yaml
```

### Breaking drift found

```
Contract Drift Sweep Results
=============================
Repos scanned: 8
Total contracts: 47
Sensitivity: STANDARD

Drift findings:
  BREAKING:     2
  ADDITIVE:     3
  NON_BREAKING: 0

  BREAKING: omnibase_core/src/omnibase_core/nodes/node_example/contract.yaml
    - MODIFIED input_schema.type: 'string' -> 'integer'
    - REMOVED required.validation_level

  BREAKING: omniclaude/src/omniclaude/hooks/contracts/session_started.yaml
    - REMOVED published_events.session_started.fields.session_type

Boundary findings:
  Stale:      1

  STALE: onex.evt.omniclaude.prompt-submitted.v1
    Producer file missing: src/omniclaude/hooks/topics_v2.py (omniclaude)

Overall status: breaking
Report: $ONEX_STATE_DIR/contract-sweep/20260326-143000/report.yaml
Tickets created: 3 (2 drift, 1 boundary)
```
