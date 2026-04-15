---
description: Handler contract compliance sweep — scans all repos for imperative handlers that bypass the ONEX contract system, wire schema mismatches, and infrastructure coupling anti-patterns, reports violations, and optionally creates Linear tickets for remediation
version: 2.0.0
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
    description: "Comma-separated repo names (default: all Python repos with handler directories)"
    required: false
  - name: --dry-run
    description: "Scan and report only — no ticket creation"
    required: false
  - name: --create-tickets
    description: "Create Linear tickets for violations not already tracked"
    required: false
  - name: --max-tickets
    description: "Maximum tickets to create per run (default: 10)"
    required: false
  - name: --json
    description: "Output results as JSON instead of formatted table"
    required: false
inputs:
  - name: repos
    description: "list[str] — repos to scan; empty = all"
outputs:
  - name: skill_result
    description: "ModelComplianceSweepReport JSON with violations by type and severity"
---

# Compliance Sweep

**Announce at start:** "I'm using the compliance-sweep skill."

## Usage

```
/compliance-sweep                              # Full scan, report only
/compliance-sweep --dry-run                    # Explicit dry-run
/compliance-sweep --repos omnibase_infra       # Scan one repo
/compliance-sweep --create-tickets             # Scan + create Linear tickets
/compliance-sweep --create-tickets --max-tickets 5
/compliance-sweep --json                       # JSON output
```

## Default Repos

omnibase_core, omnibase_infra, omniclaude, omniintelligence, omnimemory, omnimarket,
omninode_infra, onex_change_control

## Execution

### Phase 1 — Parse arguments

- `--repos` → comma-separated list (default: all handler repos)
- `--dry-run` → pass through to node
- `--create-tickets` → enable ticket creation after scan
- `--max-tickets` → cap on tickets created (default: 10)
- `--json` → output as JSON

### Phase 2 — Dispatch to node

```bash
onex run-node node_compliance_sweep \
  --input '{"repos": "<comma-list>", "checks": "<comma-list>", "dry_run": false}' \
  --timeout 300
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose. Exit 0 = compliant, exit 1 = violations found.

### Phase 3 — Render report

Verdicts per handler: COMPLIANT, IMPERATIVE, HYBRID, ALLOWLISTED, MISSING_CONTRACT

Violation types detected:
- HARDCODED_TOPIC
- UNDECLARED_TRANSPORT
- MISSING_HANDLER_ROUTING
- LOGIC_IN_NODE
- DIRECT_DB_ACCESS

Each violation: repo, handler path, node name, violation type, severity, message

Output: `ModelComplianceSweepReport`
Report path convention: `docs/registry/compliance-scan-<date>.json`

### Phase 4 — Ticket creation (only if `--create-tickets` and not `--dry-run`)

Group violations by node directory (one ticket per node). For each node with
violations not already tracked in Linear, create via `mcp__linear-server__save_issue`.
Ticket creation is idempotent — search for existing open tickets before creating.

```
Title: fix(compliance): migrate <node_name> to declarative pattern [OMN-6843]
Project: Active Sprint
Label: contract-compliance
```

Limit to `--max-tickets` tickets per run (default: 10).

### Phase 5 — Write skill result

Write to `$ONEX_STATE_DIR/skill-results/<run_id>/compliance-sweep.json`:

```json
{
  "skill": "compliance-sweep",
  "status": "compliant | violations_found | error",
  "handlers_scanned": 0,
  "total_violations": 0,
  "by_type": {},
  "by_severity": {}
}
```

## Architecture

```
SKILL.md  → thin shell: parse args → node dispatch → render results
node      → omnimarket/src/omnimarket/nodes/node_compliance_sweep/
contract  → node_compliance_sweep/contract.yaml
```

All scanning logic lives in the node handler. This skill does no scanning.
