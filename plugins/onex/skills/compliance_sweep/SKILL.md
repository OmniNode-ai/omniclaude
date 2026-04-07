---
description: Handler contract compliance sweep — scans all repos for imperative handlers that bypass the ONEX contract system, wire schema mismatches, and infrastructure coupling anti-patterns, reports violations, and optionally creates Linear tickets for remediation
version: 1.2.0
mode: full
level: advanced
debug: false
category: verification
tags:
  - compliance
  - contracts
  - handlers
  - cross-repo
  - quality
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated repo names to scan (default: all Python repos with handler directories)"
    required: false
  - name: --dry-run
    description: "Scan and report only -- no ticket creation even if --create-tickets is set"
    required: false
  - name: --create-tickets
    description: "Create Linear tickets for violations not already tracked by an allowlist ticket"
    required: false
  - name: --max-tickets
    description: "Maximum tickets to create per run (default: 10, prevents spam on first run)"
    required: false
  - name: --json
    description: "Output results as JSON (ModelComplianceSweepReport)"
    required: false
  - name: --allowlist-dir
    description: "Directory containing per-repo allowlist YAMLs (default: each repo root)"
    required: false
inputs:
  - name: repos
    description: "list[str] -- repos to scan; empty = all"
outputs:
  - name: skill_result
    description: "ModelComplianceSweepReport JSON with full audit details"
---

# compliance_sweep

Handler contract compliance sweep. Thin skill surface that dispatches to the
`node_compliance_sweep` node in omnimarket via `onex run`. The node wraps the
`arch-handler-contract-compliance` scanner from `onex_change_control` to audit
all handlers across all repos for imperative patterns that bypass the ONEX
contract system.

**Announce at start:** "I'm using the compliance-sweep skill."

## What This Detects

The scanner performs 7 checks:

### Checks 1-4: Per-handler contract compliance

| Check | Violation Type | What It Finds |
|-------|---------------|---------------|
| 1. Topic compliance | `HARDCODED_TOPIC`, `UNDECLARED_PUBLISH`, `UNDECLARED_SUBSCRIBE` | Topic string literals in handler code not declared in contract.yaml |
| 2. Transport compliance | `UNDECLARED_TRANSPORT`, `DIRECT_DB_ACCESS` | Handler imports transport libraries (psycopg, httpx, etc.) not declared in contract |
| 3. Handler routing | `MISSING_HANDLER_ROUTING`, `UNREGISTERED_HANDLER` | Handler files not registered in contract.yaml `handler_routing` |
| 4. Logic-in-node | `LOGIC_IN_NODE` | Business logic in node.py instead of handlers |

Detection uses AST-based analysis (not regex) to avoid false positives from comments
and docstrings.

### Checks 5-6: Wire schema validation (OMN-7362, OMN-7365)

Runs as a separate pass after Checks 1-4. Operates on wire schema contract YAMLs
(files matching `*_v*.yaml` with `topic`, `producer`, `consumer`, `required_fields`).

| Check | Violation Type | What It Finds |
|-------|---------------|---------------|
| 5. Wire schema mismatch | `WIRE_SCHEMA_MISMATCH` | Producer/consumer field names don't match the wire schema contract |
| 6. Model dump drift | `MODEL_DUMP_DRIFT` | Pydantic model's `model_json_schema()` has drifted from contract declarations |

Check 5 compares contract `required_fields`/`optional_fields` against actual model field
names. Check 6 detects type mismatches and undeclared/stale fields between the contract
and the model's JSON schema output.

**Infrastructure**:
- Scanner: `onex_change_control.scanners.wire_schema_compliance`
- Scanner: `onex_change_control.scanners.model_dump_drift`
- Model: `onex_change_control.models.model_wire_schema_contract.ModelWireSchemaContract`

### Check 7: Infrastructure coupling detection (OMN-7677)

Runs as a separate pass using regex-based pattern matching. Detects handlers that check
for infrastructure availability instead of relying on injected dependencies.

| Check | Violation Type | What It Finds |
|-------|---------------|---------------|
| 7. Infrastructure coupling | `INFRASTRUCTURE_COUPLING` | Publisher/event_bus None guards, has_publisher flags, use_filesystem_fallback, publisher_available/kafka_available checks |

**Anti-patterns detected**:
- `if self._publisher is None` / `is not None` — publisher availability guards
- `if not self._event_bus` — event bus falsy guards
- `has_publisher` as variable/parameter — infrastructure availability flags
- `use_filesystem_fallback` — fallback paths for missing publisher
- `publisher_available` / `kafka_available` — explicit availability checks
- `Optional[Publisher]` / `Publisher | None` — optional dependency type annotations
- `event_bus or InmemoryBus()` — or-fallback patterns

**Severity assignment**:
- `CRITICAL` for files in `src/*/nodes/*/handlers/` paths (handler files)
- `WARN` for orchestrator, plugin, runtime, and service files

**Standalone script**: `scripts/check_infra_coupling.py` can run this check independently
against any set of repos.

## Verdicts

| Verdict | Meaning |
|---------|---------|
| `COMPLIANT` | Handler fully contract-declared |
| `IMPERATIVE` | 2+ violations -- handler bypasses contract system |
| `HYBRID` | 1 violation -- partially compliant |
| `ALLOWLISTED` | Known violation with tracking ticket |
| `MISSING_CONTRACT` | No contract.yaml found for this node |

## Usage

```
/compliance-sweep                              # Full scan, report only
/compliance-sweep --dry-run                    # Same as above (explicit)
/compliance-sweep --repos omnibase_infra       # Scan one repo
/compliance-sweep --create-tickets             # Scan + create Linear tickets
/compliance-sweep --create-tickets --max-tickets 5
/compliance-sweep --json                       # Machine-readable output
```

## Repo List

Default scan targets (Python repos with handler directories):

```
omnibase_infra, omniintelligence, omnimemory, omnibase_core,
omniclaude, onex_change_control, omnibase_spi
```

Use `--repos` to override.

## Scanner Infrastructure

This skill wraps infrastructure from `onex_change_control`:

- **Scanner (Checks 1-4)**: `onex_change_control.scanners.handler_contract_compliance` -- AST-based
  cross-reference analysis per handler
- **Scanner (Check 5)**: `onex_change_control.scanners.wire_schema_compliance` -- cross-repo
  publisher/consumer field matching against wire schema contracts
- **Scanner (Check 6)**: `onex_change_control.scanners.model_dump_drift` -- Pydantic
  model_json_schema() drift detection against contract declarations
- **Validator**: `onex_change_control.validators.arch_handler_contract_compliance` -- CLI
  entry point with `--repo-root`, `--allowlist-path`, `--generate-allowlist`, `--json`
- **Models**: `ModelHandlerComplianceResult`, `ModelComplianceSweepReport`,
  `ModelWireSchemaContract` -- structured output compatible with omnidash consumption
- **Enums**: `EnumComplianceVerdict`, `EnumComplianceViolation` -- classification types
  (including `WIRE_SCHEMA_MISMATCH`, `MODEL_DUMP_DRIFT`, `INFRASTRUCTURE_COUPLING`)
- **Script (Check 7)**: `scripts/check_infra_coupling.py` -- regex-based infrastructure
  coupling detection with severity-based classification (CRITICAL for handlers, WARN for others)

## Ticket Creation (--create-tickets)

When `--create-tickets` is set (and `--dry-run` is NOT set):

1. Group violations by node directory (one ticket per node, not per handler)
2. For each node with violations not already tracked in the allowlist:
   - Search Linear for an existing open ticket matching the handler path
   - If found: skip (idempotent)
   - If not found: create ticket with title format:
     `fix(compliance): migrate {node_name} to declarative pattern [OMN-6843]`
3. Ticket includes: handler paths, specific violations, contract.yaml changes needed
4. Project: Active Sprint, label: `contract-compliance`
5. Max tickets per run: `--max-tickets` (default 10)

## Output

### Report file

Saved to `docs/registry/compliance-scan-<YYYY-MM-DD>.json` in `omni_home/`.

### Summary output

```
Handler Contract Compliance Sweep
===================================
Repos scanned: 7
Total handlers: 269
Compliant: 52 (19.3%)
Imperative: 180 (66.9%)
Hybrid: 25 (9.3%)
Allowlisted: 12 (4.5%)
Missing contract: 0 (0.0%)

Per-repo breakdown:
  omnibase_infra:     120 handlers (15 compliant, 89 imperative, 16 hybrid)
  omniintelligence:    45 handlers (10 compliant, 30 imperative, 5 hybrid)
  ...

Top violations:
  HARDCODED_TOPIC:           87
  MISSING_HANDLER_ROUTING:   65
  UNDECLARED_TRANSPORT:      43
  DIRECT_DB_ACCESS:          31
  ...

Tickets created: 0 (use --create-tickets to enable)
Report: docs/registry/compliance-scan-2026-03-28.json
```

## Integration

- **close-out autopilot**: Run as compliance progress check (Task 15)
- **contract-sweep**: Complementary (contract-sweep checks drift; compliance-sweep checks handler compliance)
- **aislop-sweep**: Complementary (aislop checks AI anti-patterns; compliance-sweep checks contract compliance)

## Architecture

```
SKILL.md   -> descriptive documentation (this file)
prompt.md  -> execution instructions (parse args -> onex run dispatch -> render results)
node       -> omnimarket/src/omnimarket/nodes/node_compliance_sweep/ (business logic)
contract   -> node_compliance_sweep/contract.yaml (inputs/outputs/topics)
```

This skill is a **thin wrapper** — it parses arguments, dispatches to the omnimarket
node via `onex run node_compliance_sweep`, and renders results. All scanning logic
lives in the node handler.

## See Also

- `contract-sweep` skill -- Contract drift detection (different concern)
- `contract-compliance-check` skill -- Pre-merge seam validation (per-ticket)
- `aislop-sweep` skill -- AI quality anti-patterns
- `arch-handler-contract-compliance` validator in `onex_change_control`
- OMN-6842 -- This skill's tracking ticket
- OMN-6843 -- Ticket creator extension
