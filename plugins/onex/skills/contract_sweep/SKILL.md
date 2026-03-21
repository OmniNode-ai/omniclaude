---
description: Automated contract health audit — scans all repos for deficient ONEX contracts, validates required fields, detects duplicates and orphans
version: 1.0.0
mode: full
level: advanced
debug: false
category: verification
tags:
  - contracts
  - health-check
  - cross-repo
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
    description: "Min severity for tickets: CRITICAL | ERROR | WARNING (default: ERROR)"
    required: false
---

# contract_sweep

Automated ONEX contract health audit. Scans bare clones in `omni_home` for deficient, duplicate, orphaned, or misclassified contracts. Produces a structured YAML report and optionally creates Linear tickets for findings above threshold.

## Usage

```
/contract-sweep --dry-run
/contract-sweep --repos omnibase_infra,omnibase_core
/contract-sweep --severity-threshold WARNING
```

## Contract Class Doctrine

The sweep classifies every contract into exactly one of three classes:

| Class | Required Fields | Forbidden Fields | Detection Rule |
|-------|----------------|------------------|----------------|
| **Node contract** | `name`, `contract_version`, `description`, `node_type`, `node_version`, `input_model`, `output_model` | `handler_id`, `descriptor` | Has top-level `node_type` |
| **Handler contract** | `name`, `contract_version`, `description`, `handler_id`, `descriptor` (with `purity`, `timeout_ms`) | Top-level `node_type`, `node_version` | Has top-level `handler_id` |
| **Package-level architecture contract** | `name`, `contract_version`, `description` | None forbidden, but node/handler fields optional | Explicitly marked with `# Package-level architecture contract` comment AND located at repo/package root |

A contract that has BOTH `node_type` and `handler_id` at top level is a hybrid violation (ERROR).

## Checks Performed

### Phase A: Contract class and loader truth (highest impact)

1. **Contract class identification** -- Detect whether each contract is node, handler, or package-level based on field presence. Flag hybrids (both `node_type` and `handler_id` at top level) as ERROR.

2. **No ambiguous loader directories** -- Directories containing multiple contract-candidate files (`contract.yaml` + `handler_contract.yaml` etc.) that would cause loader ambiguity (ERROR).

3. **No superseded scaffolds** -- Stub contracts that are superseded by a richer canonical contract elsewhere in the repo (ERROR).

### Phase B: Class-specific field validation

4. **Required fields present** -- `name`, `contract_version`, `description` (CRITICAL if missing).

5. **Node-specific fields** -- `node_type`, `node_version`, `input_model`, `output_model` present (ERROR if missing on COMPUTE/EFFECT/ORCHESTRATOR).

6. **Handler-specific fields** -- `handler_id` at top level (not buried in metadata), `descriptor` with `purity` and `timeout_ms` (ERROR if missing).

7. **No node-only fields on handlers** -- Handler contracts must NOT carry top-level `node_type` or `node_version` (ERROR if present).

### Phase C: Cross-contract and location

8. **No duplicate contracts** -- Same `handler_id` at multiple paths (ERROR).

9. **No orphaned contracts** -- YAML exists but no corresponding Python handler/node file (WARNING).

10. **Package contract location** -- Must be at repo root or `src/<package>/contract.yaml`; must carry explicit `# Package-level architecture contract` marker (WARNING if unmarked).

## Severity Classification

| Severity | Criteria | Action |
|----------|----------|--------|
| **CRITICAL** | Missing name/contract_version/description (contract is unidentifiable) | Always create ticket |
| **ERROR** | Missing input_model, hybrid style, no descriptor on handler, duplicate contracts, ambiguous loader directories, superseded scaffolds with runtime references | Create ticket above threshold |
| **WARNING** | Missing node_version, orphaned contracts with no runtime impact, unmarked package-level contracts | Create ticket if threshold is WARNING |
| **INFO** | Test/fixture/example contracts with explicit minimality comments | Never create ticket |

### Severity escalation rule

Orphaned or duplicate contracts that can affect runtime resolution or loader ambiguity escalate above WARNING to ERROR, even if the contract is otherwise structurally valid.

## Exception Policy

Directory alone never grants exemption. Path-based downgrade applies only after explanatory-comment qualification. Files in `tests/`, `fixtures/`, or `examples/` without the required comment are validated at normal severity. The explanatory comment is part of the validation surface, not optional documentation.

## Output

Structured YAML report written to `$ONEX_STATE_DIR/contract-sweep/<run-id>/report.yaml`.

Summary table printed to stdout with per-repo counts by severity.

## Integration

This skill is designed to integrate with:

- **close-day**: Run as part of end-of-day verification
- **integration-sweep**: Complementary check (integration-sweep validates DoD evidence; contract-sweep validates contract structure)

## Repo List

Hardcoded scan targets (8 repos):

```
omnibase_core, omnibase_infra, omniclaude, omniintelligence,
omnimemory, omninode_infra, omnibase_spi, onex_change_control
```
