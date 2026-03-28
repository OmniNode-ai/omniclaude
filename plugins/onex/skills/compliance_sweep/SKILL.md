---
description: Handler contract compliance sweep — scans all repos for imperative handlers that bypass the ONEX contract system, reports violations, and optionally creates Linear tickets for remediation
version: 1.0.0
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

Handler contract compliance sweep. Wraps the `arch-handler-contract-compliance`
scanner from `onex_change_control` to audit all handlers across all repos for
imperative patterns that bypass the ONEX contract system.

**Announce at start:** "I'm using the compliance-sweep skill."

## What This Detects

The scanner performs 4 checks per handler:

| Check | Violation Type | What It Finds |
|-------|---------------|---------------|
| Topic compliance | `HARDCODED_TOPIC`, `UNDECLARED_PUBLISH`, `UNDECLARED_SUBSCRIBE` | Topic string literals in handler code not declared in contract.yaml |
| Transport compliance | `UNDECLARED_TRANSPORT`, `DIRECT_DB_ACCESS` | Handler imports transport libraries (psycopg, httpx, etc.) not declared in contract |
| Handler routing | `MISSING_HANDLER_ROUTING`, `UNREGISTERED_HANDLER` | Handler files not registered in contract.yaml `handler_routing` |
| Logic-in-node | `LOGIC_IN_NODE` | Business logic in node.py instead of handlers |

Detection uses AST-based analysis (not regex) to avoid false positives from comments
and docstrings.

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

- **Scanner**: `onex_change_control.scanners.handler_contract_compliance` -- AST-based
  cross-reference analysis per handler
- **Validator**: `onex_change_control.validators.arch_handler_contract_compliance` -- CLI
  entry point with `--repo-root`, `--allowlist-path`, `--generate-allowlist`, `--json`
- **Models**: `ModelHandlerComplianceResult`, `ModelComplianceSweepReport` -- structured
  output compatible with omnidash consumption
- **Enums**: `EnumComplianceVerdict`, `EnumComplianceViolation` -- classification types

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
prompt.md  -> execution instructions for the agent
```

## See Also

- `contract-sweep` skill -- Contract drift detection (different concern)
- `contract-compliance-check` skill -- Pre-merge seam validation (per-ticket)
- `aislop-sweep` skill -- AI quality anti-patterns
- `arch-handler-contract-compliance` validator in `onex_change_control`
- OMN-6842 -- This skill's tracking ticket
- OMN-6843 -- Ticket creator extension
