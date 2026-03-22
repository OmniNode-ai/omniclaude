---
description: Contract-driven post-merge integration verification — reads ModelTicketContract.dod_evidence for recently completed tickets, probes each integration surface (KAFKA, DB, CI, PLUGIN, GITHUB_CI, SCRIPT, CONTAINER_HEALTH, RUNTIME_HEALTH), and writes a ModelIntegrationRecord artifact to onex_change_control
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
author: OmniClaude Team
composable: true
args:
  - name: --date
    description: "ISO date to sweep (default: today). Filters tickets by updatedAt >= date."
    required: false
  - name: --tickets
    description: "Comma-separated ticket IDs to probe explicitly (skips Linear discovery)"
    required: false
  - name: --mode
    description: "Scope of surface probing: omniclaude-only | full-infra (default: omniclaude-only)"
    required: false
  - name: --dry-run
    description: "Print results table but do NOT write the ModelIntegrationRecord artifact"
    required: false
  - name: --output
    description: "Override artifact output path (default: $ONEX_CC_REPO_PATH/drift/integration/{date}.yaml)"
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

# integration-sweep

**Skill ID**: `onex:integration-sweep`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-5436
**Epic**: OMN-5431

---

## Purpose

Contract-driven post-merge verification. For each recently completed ticket:

1. Extract the `ModelTicketContract` embedded in the ticket description (YAML block)
2. Map `interfaces_touched` fields to `EnumIntegrationSurface` values
3. Execute the `dod_evidence[*].checks` for each surface
4. Assemble a `ModelIntegrationRecord` with per-surface `ModelIntegrationProbeResult` entries
5. Write the artifact to `$ONEX_CC_REPO_PATH/drift/integration/{date}.yaml`

The contract IS the guard rail. No contract → UNKNOWN/no_contract → halt.

---

## Usage

```
/integration-sweep
/integration-sweep --date 2026-03-18
/integration-sweep --tickets OMN-5400,OMN-5401
/integration-sweep --mode full-infra
/integration-sweep --dry-run
/integration-sweep --dry-run --tickets OMN-5436
```

---

## Integration Surfaces

| EnumIntegrationSurface | What is probed |
|------------------------|----------------|
| `KAFKA` | Topic constants match consumer subscribe strings; producer and consumer models are compatible |
| `DB` | Migration applied; ORM columns match DDL; no broken schema references |
| `CI` | Required workflow files exist; no disabled checks; status badges passing |
| `PLUGIN` | omniclaude plugin loads cleanly; skill files valid; no phantom callables |
| `GITHUB_CI` | Branch protection rules; required status checks registered; auto-merge eligibility |
| `SCRIPT` | Referenced scripts exist at declared paths; exit cleanly under `--dry-run` when applicable |
| `CONTAINER_HEALTH` | Docker container state — all expected containers running (unconditional, every invocation) |
| `RUNTIME_HEALTH` | HTTP health endpoints for runtime services (unconditional, every invocation) |

---

## Halt Policy

| Probe Status | Reason | Action |
|--------------|--------|--------|
| `FAIL` | any | Halt — do not write artifact |
| `UNKNOWN` | `NO_CONTRACT` | Halt — contract missing |
| `UNKNOWN` | `INCONCLUSIVE` | Halt — probe returned ambiguous result |
| `UNKNOWN` | `PROBE_UNAVAILABLE` | Continue with warning — tool not available |
| `UNKNOWN` | `NOT_APPLICABLE` | Continue — surface not touched by ticket |

---

## Output Artifact

Written to `$ONEX_CC_REPO_PATH/drift/integration/{date}.yaml`:

```yaml
# ModelIntegrationRecord
sweep_date: "2026-03-18"
tickets_swept: ["OMN-5400", "OMN-5401"]
surfaces_probed: ["KAFKA", "DB", "CI"]
results:
  - ticket_id: "OMN-5400"
    surface: KAFKA
    status: PASS
    reason: null
    evidence: "topic constant onex.evt.omniintelligence.pattern-detected.v1 matches consumer"
  - ticket_id: "OMN-5400"
    surface: DB
    status: PASS
    reason: null
    evidence: "migration 0042 applied; columns aligned"
  - ticket_id: "OMN-5401"
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

| Ticket   | Surface   | Probe              | Status  | Evidence                                      |
|----------|-----------|--------------------|---------|-----------------------------------------------|
| OMN-5400 | KAFKA     | topic_match        | PASS    | topic constant matches consumer               |
| OMN-5400 | DB        | migration_applied  | PASS    | migration 0042 applied; columns aligned       |
| OMN-5401 | CI        | workflow_exists    | UNKNOWN | PROBE_UNAVAILABLE — gh CLI not available      |

Summary: 2 PASS, 0 FAIL, 1 UNKNOWN (3 total)
Artifact: $ONEX_CC_REPO_PATH/drift/integration/2026-03-18.yaml
```

---

## Known Limitations

- **Linear list_issues truncation (OMN-5473)**: The Linear `list_issues` API truncates
  descriptions to ~500 characters. Discovery (Step 2) uses `list_issues` for ticket IDs
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
