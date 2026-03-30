---
description: Scan all repos for handler contract compliance violations — cross-references handler source code against contract.yaml declarations to detect hardcoded topics, undeclared transports, unregistered handlers, and logic-in-node violations. Generates ModelComplianceSweepReport JSON and prints human-readable summary.
mode: full
version: "1.0.0"
level: advanced
debug: false
category: governance
tags: [compliance, contracts, handlers, declarative, scan]
author: omninode
composable: true
args:
  - name: --repos
    description: "Comma-separated list of repos to scan (default: all repos under omni_home with handlers)"
    required: false
  - name: --create-tickets
    description: "Create Linear tickets for non-allowlisted violations (max 10 per run)"
    required: false
  - name: --dry-run
    description: "Report findings without creating tickets or saving reports (default: false)"
    required: false
---

# Compliance Scan

**Skill ID**: `onex:compliance-scan`

## Purpose

Scan all ONEX repositories for handler contract compliance violations. This skill
cross-references handler Python source code against contract.yaml declarations to detect:

1. **Hardcoded topics** — topic string literals in handler code not declared in contract.yaml
2. **Undeclared transports** — handler imports/uses transports (DB, HTTP, Kafka) not declared in contract
3. **Unregistered handlers** — handler files in handlers/ not listed in contract.yaml handler_routing
4. **Logic in node.py** — business logic in node.py instead of handlers (should only have __init__)

The scan is **read-only** by default — it does not modify any code.

## Announce

"I'm using the compliance-scan skill to audit handler contract compliance across ONEX repos."

## Usage

/compliance-scan
/compliance-scan --repos omnibase_infra,omniintelligence
/compliance-scan --create-tickets
/compliance-scan --dry-run

## Phase 1 — Discover repos

Scan `omni_home/` for repositories containing `src/**/nodes/*/handlers/` directories.
Default repos: `omnibase_infra`, `omniintelligence`, `omnimemory`, `omnibase_core`.
If `--repos` is specified, scan only those repos.

## Phase 2 — Scan each repo

For each repo:
1. Find all `src/**/nodes/node_*/` directories that contain a `handlers/` subdirectory
2. For each node directory, use `onex_change_control.scanners.handler_contract_compliance.cross_reference()` to audit all handlers
3. Load the repo's allowlist from `arch-handler-contract-compliance-allowlist.yaml` (if it exists)
4. Collect all `ModelHandlerComplianceResult` objects

## Phase 3 — Aggregate results

Build a `ModelComplianceSweepReport` with:
- Total handler count, compliant/imperative/hybrid/allowlisted/missing-contract counts
- Compliant percentage
- Violation histogram (count per violation type)
- Per-repo breakdown (`ModelRepoComplianceBreakdown`)
- Full result details

## Phase 4 — Save and display

1. Save the report JSON to `docs/registry/compliance-scan-<YYYY-MM-DD>.json` in `omni_home`
2. Print human-readable summary:
   - Overall compliance ratio
   - Per-repo breakdown table
   - Top violation types
   - List of non-allowlisted violations (if any)

### Create tickets (if --create-tickets)

If `--create-tickets` is specified:
1. For each node directory with non-allowlisted violations, create a Linear ticket:
   - Title: "Fix contract compliance: <node_name> [VIOLATION_TYPES]"
   - Project: Active Sprint
   - Label: contract-compliance
   - Description: handler paths, specific violations, contract.yaml changes needed
2. Group violations by node directory (one ticket per node)
3. Update the repo's allowlist YAML with the new ticket ID
4. Maximum 10 tickets per run to prevent spam

## Output

The skill produces:
- A `ModelComplianceSweepReport` JSON file saved to `docs/registry/`
- Human-readable summary printed to stdout
- Linear tickets (if `--create-tickets` is used)

## Dependencies

- `onex_change_control` package (for scanner module and models)
- Linear API (for ticket creation, only with `--create-tickets`)
