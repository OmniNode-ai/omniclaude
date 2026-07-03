---
description: Contract-driven post-merge integration verification — dispatches to node_integration_sweep_orchestrator for execution
version: 1.0.0
mode: full
level: advanced
debug: false
category: verification
tags:
  - integration
  - contracts
  - dod
  - post-merge
  - verification
  - kafka
  - database
  - ci
  - autonomous
  - playwright
author: OmniClaude Team
composable: true
args:
  - name: --dry-run
    description: "Compute artifact path but do NOT write the ModelIntegrationRecord artifact"
    required: false
inputs:
  - name: tickets
    description: "list[str] — explicit ticket IDs; empty = discover from Linear"
outputs:
  - name: artifact_path
    description: "Absolute path to the written ModelIntegrationRecord YAML (empty if --dry-run)"
  - name: status
    description: "clean | fail | partial"
---

<!-- routing-enforced: dispatches to node_integration_sweep_orchestrator. -->

# integration-sweep

**Skill ID**: `onex:integration_sweep`
**Version**: 1.0.0
**Owner**: omniclaude

---

## Purpose

Contract-driven post-merge verification. For each recently completed ticket: <!-- skill-boundary-ok: ticket iteration is performed by node_integration_sweep_orchestrator handler, not the skill -->

1. Extract the `ModelTicketContract` embedded in the ticket description (YAML block)
2. Map `interfaces_touched` fields to `EnumIntegrationSurface` values
3. Execute the `dod_evidence[*].checks` for each surface
4. Assemble a `ModelIntegrationRecord` with per-surface `ModelIntegrationProbeResult` entries
5. Return the assembled integration record. Durable artifact persistence under
   `$ONEX_CC_REPO_PATH/drift/integration/` is pending backing node implementation
   and must not be claimed until it is in place.

The contract IS the guard rail. No contract → UNKNOWN/no_contract → halt.

---

## Usage

```
/integration-sweep
/integration-sweep --dry-run
```

---

## Integration Surfaces

The following surfaces are implemented in the node (`surface_probes.py`). All other surfaces listed in the enum are defined but not yet probed by the node implementation.

| EnumIntegrationSurface | What is probed |
|------------------------|----------------|
| `RUNTIME_HEALTH` | HTTP health endpoints for runtime services — unconditional, every invocation |
| `CONTAINER_HEALTH` | Docker container state via SSH — all expected containers running, unconditional, every invocation |
| `GITHUB_CI` | Recent GitHub Actions run results for the configured repo — pass/fail counts | <!-- skill-boundary-ok: repo iteration is performed by node_integration_sweep_orchestrator handler -->
| `runtime_sha_match` | Per-ticket SHA match from `dod_evidence` checks against the live runtime deployment |

---

## Halt Policy

| Probe Status | Reason | Action |
|--------------|--------|--------|
| `FAIL` | any | Halt — do not write artifact |
| `UNKNOWN` | `NO_CONTRACT` | Halt — contract missing |
| `UNKNOWN` | `INCONCLUSIVE` | Halt — probe returned ambiguous result |
| `UNKNOWN` | `PROBE_UNAVAILABLE` | Continue with warning — tool not available |
| `UNKNOWN` | `NOT_APPLICABLE` | Continue — surface not touched by ticket |
| `PASS_WITH_WARNINGS` | any | Continue — probe passed with non-blocking warnings (e.g., PLAYWRIGHT_BEHAVIORAL data-flow failure in local env) |

**Auto-generated contracts:**

Contracts produced by `generate_contract` / `enrich_contract` pipeline phases may contain:
- Evidence items with `source: "generated"` -- these are machine-produced and should be probed
  normally (not skipped)
- Evidence items with `status: "pending"` -- these have not been verified yet; probe them and
  update status based on the probe result

**Contract with empty dod_evidence[]:**
A contract that exists and validates against the schema but has empty `dod_evidence[]`
is treated as PASS for the CONTRACT surface (the contract exists) with a WARNING that
evidence is missing. This distinguishes "no contract" (HALT via `NO_CONTRACT`) from
"contract exists but unenriched" (CONTINUE with warning).

---

## Output Artifact

Written to `$ONEX_CC_REPO_PATH/drift/integration/{date}.yaml`:

```yaml
# ModelIntegrationRecord
sweep_date: "2026-03-18"
tickets_swept: ["TICKET-A", "TICKET-B"]
surfaces_probed: ["KAFKA", "DB", "CI"]
results:
  - ticket_id: "TICKET-A"
    surface: KAFKA
    status: PASS
    reason: null
    evidence: "topic constant onex.evt.omniintelligence.pattern-detected.v1 matches consumer"
  - ticket_id: "TICKET-A"
    surface: DB
    status: PASS
    reason: null
    evidence: "migration 0042 applied; columns aligned"
  - ticket_id: "TICKET-B"
    surface: CI
    status: UNKNOWN
    reason: PROBE_UNAVAILABLE
    evidence: "gh CLI not available in this environment"
overall_status: PASS   # PASS | FAIL | PARTIAL
artifact_written: true
```

If `--dry-run`: `artifact_written: false` and file is never created.

---

## Summary Output

```
INTEGRATION SWEEP — 2026-03-18
================================

| Ticket    | Surface   | Probe              | Status  | Evidence                                      |
|-----------|-----------|--------------------|---------|-----------------------------------------------|
| TICKET-A  | KAFKA     | topic_match        | PASS    | topic constant matches consumer               |
| TICKET-A  | DB        | migration_applied  | PASS    | migration 0042 applied; columns aligned       |
| TICKET-B  | CI        | workflow_exists    | UNKNOWN | PROBE_UNAVAILABLE — gh CLI not available      |

Summary: 2 PASS, 0 FAIL, 1 UNKNOWN (3 total)
Artifact: $ONEX_CC_REPO_PATH/drift/integration/2026-03-18.yaml
```

---

## Known Limitations

- **Linear list_issues truncation**: The Linear `list_issues` API truncates
  descriptions to ~500 characters. Discovery (Step 2) uses `list_issues` for ticket IDs <!-- skill-boundary-ok: issue listing is performed by node_integration_sweep_orchestrator handler -->
  only. Contract extraction (Step 3) MUST use `get_issue` per ticket to retrieve full
  descriptions. This adds ~1 API call per ticket but prevents contract parsing failures
  from truncated YAML blocks.

---

## Integration Points

- **close-day**: invokes integration-sweep as part of invariants-checked gate
- **ModelDayCloseInvariantsChecked**: `integration_sweep` field set from this skill's overall_status
- **ModelIntegrationRecord**: written to `onex_change_control/drift/integration/`
- **dod-verify**: runs individual ticket DoD checks; integration-sweep aggregates across tickets and surfaces
- **gap**: gap-detect reads the integration record to identify surface drift over time
