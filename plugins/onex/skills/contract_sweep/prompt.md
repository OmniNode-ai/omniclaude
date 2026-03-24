# contract_sweep prompt

You are executing the **contract-sweep** skill. This skill audits ONEX contracts across all repos for structural deficiencies, duplicates, orphans, and classification errors.

## Announce

Say: "I'm using the contract-sweep skill to audit ONEX contracts across all repos."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--repos <comma-list>` -- Repos to scan (default: all 8)
- `--dry-run` -- Print findings only, no ticket creation
- `--severity-threshold <CRITICAL|ERROR|WARNING>` -- Min severity for tickets (default: ERROR)

**Repo list** (hardcoded, scan all unless `--repos` overrides):
```
omnibase_core, omnibase_infra, omniclaude, omniintelligence, omnimemory, omninode_infra, omnibase_spi, onex_change_control
```

**Bare clone root**: `$OMNI_HOME` (typically `/Volumes/PRO-G40/Code/omni_home`)  <!-- local-path-ok -->

## Preamble: Pull bare clones

Before scanning, pull all bare clones to ensure findings reflect the latest `main`:

```bash
bash /Volumes/PRO-G40/Code/omni_home/omnibase_infra/scripts/pull-all.sh  # local-path-ok
```

If `pull-all.sh` exits non-zero, **abort the sweep immediately** with an error message explaining that stale clones may produce ghost findings. Do not silently continue with stale data.

## Discovery

For each repo, discover all contract files from the `main` branch:

```bash
git -C $OMNI_HOME/<repo> ls-tree -r main --name-only | grep -E '(contract|handler_contract)\.yaml$'  # local-path-ok
```

Build a list of `(repo, path)` pairs for validation.

## Validation

For each contract, read via `git show main:<path>` and run the following 10 checks in order:

### Phase A: Contract class and loader truth

**Check 1: Contract class identification**
- Parse top-level keys from YAML
- If has `node_type` but no `handler_id` -> class = `node`
- If has `handler_id` but no `node_type` -> class = `handler`
- If has BOTH `node_type` AND `handler_id` at top level -> HYBRID VIOLATION (ERROR)
- If has explicit `# Package-level architecture contract` comment -> class = `package`
- Otherwise -> class = `unknown` (WARNING)

**Check 2: No ambiguous loader directories**
- Group discovered contracts by directory
- If a directory has more than one contract-candidate file (`contract.yaml`, `handler_contract.yaml`, etc.) -> ERROR: AMBIGUOUS_CONTRACT_CONFIGURATION

**Check 3: No superseded scaffolds**
- For each contract under `contracts/handlers/`, check if a richer canonical contract exists under `src/` for the same handler
- If superseded stub still exists -> ERROR

### Phase B: Class-specific field validation

**Check 4: Required fields present**
- All classes: `name`, `contract_version`, `description` must be present at top level
- Missing any of these -> CRITICAL

**Check 5: Node-specific fields**
- For node-class contracts: require `node_type`, `node_version`, `input_model`, `output_model`
- Missing any -> ERROR (unless test fixture with explicit minimality comment)

**Check 6: Handler-specific fields**
- For handler-class contracts: require `handler_id` at top level (not buried in metadata)
- Require `descriptor` with `purity` and `timeout_ms`
- Missing -> ERROR

**Check 7: No node-only fields on handlers**
- For handler-class contracts: top-level `node_type` or `node_version` -> ERROR
- These are node-level fields that must not appear on handler contracts

### Phase C: Cross-contract and location

**Check 8: No duplicate contracts**
- Collect all `handler_id` values across all contracts
- If same `handler_id` appears at multiple paths -> ERROR

**Check 9: No orphaned contracts**
- For each contract YAML, check if a corresponding Python module exists
- YAML with no matching Python handler/node -> WARNING
- Escalate to ERROR if the contract is referenced by runtime bootstrap code

**Check 10: Package contract location**
- Package-level contracts must be at repo root or `src/<package>/contract.yaml`
- Must carry explicit `# Package-level architecture contract` marker
- Missing marker or wrong location -> WARNING

### Exception policy

- Files under `tests/`, `fixtures/`, or `examples/` are downgraded ONLY if they carry an explicit explanatory comment (e.g., `# NOTE: intentionally minimal fixture`)
- Without the comment, they are validated at normal severity
- Directory alone never grants exemption

## Triage

Classify all findings by severity:

| Severity | Criteria |
|----------|----------|
| CRITICAL | Missing name/contract_version/description |
| ERROR | Missing input_model for COMPUTE/EFFECT/ORCHESTRATOR, hybrid style, no descriptor on handler, duplicate contracts, ambiguous loader directories, superseded scaffolds with runtime references |
| WARNING | Missing node_version, orphaned contracts with no runtime impact, unmarked package-level contracts |
| INFO | Test/fixture/example contracts with explicit minimality comments |

**Severity escalation rule**: Orphaned or duplicate contracts that affect runtime resolution or loader ambiguity escalate to ERROR regardless of other field completeness.

**Ticket dedup**: Ticket identity is keyed by `(repo, path, check)`. Before creating a ticket, search Linear for an open ticket with matching repo + path + check. If found, update or comment instead of creating. If prior ticket is closed but same finding recurs, create new ticket and reference prior closure.

When multiple findings apply to one file, report all findings but drive ticket severity from the highest applicable finding.

## Report

### Write report

Create `$ONEX_STATE_DIR/contract-sweep/<run-id>/report.yaml` with this schema:

```yaml
run_id: "<YYYYMMDD-HHMMSS>"
timestamp: "<ISO-8601>"
repos_scanned: ["omnibase_core", "omnibase_infra", ...]
scan_branch: "main"
total_contracts: <count>
findings:
  - repo: "<repo>"
    path: "<contract-path>"
    contract_class: "<node|handler|package|unknown>"
    check: "<check_name>"
    severity: "<CRITICAL|ERROR|WARNING|INFO>"
    message: "<human-readable description>"
    autofixable: <true|false>
by_severity: {CRITICAL: 0, ERROR: 0, WARNING: 0, INFO: 0}
excluded_files:
  - path: "<path>"
    reason: "<reason for exclusion>"
overall_status: "<clean|degraded|critical>"
tickets_created: []  # empty in dry-run mode
```

### Print summary

Print a summary table to stdout:

```
Contract Sweep Results
======================
Repos scanned: 8
Total contracts: <N>
Branch: main

Findings by severity:
  CRITICAL: <N>
  ERROR:    <N>
  WARNING:  <N>
  INFO:     <N>

Overall status: <clean|degraded|critical>
```

If not `--dry-run` and findings exist above threshold, create Linear tickets for each finding. Use the ticket dedup logic from Step 4.

### Status determination

- `clean` -- Zero CRITICAL, zero ERROR, zero WARNING (INFO-only or no findings)
- `degraded` -- Zero CRITICAL, zero ERROR, one or more WARNING
- `critical` -- Any CRITICAL or ERROR finding present
