---
description: Evaluate architectural invariant contracts across repos — convert CLAUDE.md/doctrine principles into typed YAML invariant contracts and report violations across STATIC_ARCHITECTURE, CI_GATE, PRE_TOOL_USE, RUNTIME_VALIDATION, and CONTRACT_VALIDATION surfaces.
version: 1.0.0
mode: full
level: advanced
debug: false
category: governance
tags:
  - architecture
  - invariants
  - enforcement
  - governance
  - org-wide
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated repo names to scan (default: all repos under OMNI_HOME)"
    required: false
  - name: --invariants
    description: "Comma-separated principle codes to evaluate: ARCH-001,ARCH-002,ARCH-003,ARCH-004,ARCH-005 (default: all)"
    required: false
  - name: --dry-run
    description: Scan and report only — no tickets, no events
    required: false
  - name: --severity-threshold
    description: "Minimum severity to report: DEBUG|INFO|WARNING|ERROR|CRITICAL (default: WARNING)"
    required: false
inputs:
  - name: repos
    description: "list[str] — repos to scan; empty = all repos under ONEX_WORKTREES_ROOT"
outputs:
  - name: skill_result
    description: "ArchInvariantLoopResult JSON; violations and summary delivered in result field"
---

# Architectural Invariant Loop

**Announce at start:** "I'm using the architectural-invariant-loop skill."

## Usage

```
/architectural_invariant_loop                              # All repos, all invariants
/architectural_invariant_loop --dry-run                   # Report only
/architectural_invariant_loop --repos omniclaude,omnibase_core
/architectural_invariant_loop --invariants ARCH-001,ARCH-003
/architectural_invariant_loop --severity-threshold ERROR  # Only ERROR+ findings
```

## Execution

### Step 1 — Parse arguments

- `--repos` → comma-separated repo names (default: all repos under `$ONEX_WORKTREES_ROOT`)
- `--invariants` → comma-separated principle codes (default: all 5 seed invariants)
- `--dry-run` → pass through to node
- `--severity-threshold` → pass through to node (default: WARNING)

Resolve each repo name to an absolute path under `$ONEX_WORKTREES_ROOT/<repo>`.

### Step 2 — Run node

Dispatch to the omnimarket node via local RuntimeLocal. This is a dispatch-only
shim — no inline scanning, no subprocess grep, no fallback logic.

```bash
uv run onex node node_architectural_invariant_loop -- \
  --target-dirs "<comma-list of absolute paths>" \
  --invariant-ids "<comma-list or omit for all>" \
  --severity-threshold WARNING \
  [--dry-run]
```

On non-zero exit, surface the `SkillRoutingError` JSON envelope directly. Do not
produce prose on error. Exit 0 = clean or informational findings; exit 1 = violations
at or above threshold.

### Step 3 — Render report

From the JSON output display:
- Header: repos scanned, invariants evaluated, total violations
- Summary table: by severity (CRITICAL → ERROR → WARNING → INFO)
- Secondary table: by violation category
- Findings grouped by principle code (ARCH-001 through ARCH-005):
  - Each finding: repo, path:line, severity, message, enforcement_surface

### Step 4 — Write skill result

Write to `$ONEX_STATE_DIR/skill-results/<run_id>/architectural-invariant-loop.json`:

```json
{
  "skill": "architectural-invariant-loop",
  "status": "clean | violations | error",
  "repos_scanned": 0,
  "invariants_evaluated": 5,
  "total_violations": 0,
  "by_severity": {},
  "by_category": {},
  "by_principle": {}
}
```

## Invariant Catalogue

| Code | Name | Category | Severity |
|------|------|----------|----------|
| ARCH-001 | no_hardcoded_persistence_in_runners | runtime_topology | ERROR |
| ARCH-002 | no_silent_fallback | static_architecture | WARNING |
| ARCH-003 | contract_driven_routing_only | contract_violation | ERROR |
| ARCH-004 | event_bus_di_projections | runtime_topology | ERROR |
| ARCH-005 | no_hardcoded_absolute_paths | static_architecture | ERROR |

## Enforcement Surface Doctrine

PreToolUse hooks are **developer ergonomics only** — they are NOT authoritative.
CI gates and runtime validators are the authoritative enforcement surfaces.
A violation that passes a PreToolUse hook but is caught by CI is still a violation.

## Architecture

```
SKILL.md  → thin shell: parse args → node dispatch → render results
node      → onex node node_architectural_invariant_loop
contract  → node_architectural_invariant_loop/contract.yaml
invariants → node_architectural_invariant_loop/invariants/ARCH-*.yaml
```

All scanning logic lives in the node handler. This skill does no scanning.
