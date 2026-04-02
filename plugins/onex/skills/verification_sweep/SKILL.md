---
description: Post-orchestration verification sweep — runs after epic-team or ticket-pipeline completes to verify dashboard endpoints return HTTP 200 with real data, database tables contain expected rows, and dod_evidence rendered_output items have passing receipts. Non-blocking (flags only, does not halt orchestration).
version: 1.0.0
mode: full
level: advanced
debug: false
category: verification
tags:
  - verification
  - post-orchestration
  - dashboard
  - database
  - dod
  - sweep
  - non-blocking
author: OmniClaude Team
composable: true
args:
  - name: --ticket
    description: "Single ticket ID to verify (e.g., OMN-5400)"
    required: false
  - name: --tickets
    description: "Comma-separated ticket IDs to verify (e.g., OMN-5400,OMN-5401)"
    required: false
  - name: --epic
    description: "Epic ID — discover and verify all child tickets (e.g., OMN-2000)"
    required: false
  - name: --dry-run
    description: "Print verification results without writing receipts or creating Linear comments"
    required: false
  - name: --skip-dashboard
    description: "Skip Phase 1 dashboard endpoint checks"
    required: false
  - name: --skip-database
    description: "Skip Phase 2 database table checks"
    required: false
  - name: --skip-dod
    description: "Skip Phase 3 DoD evidence checks"
    required: false
inputs:
  - name: tickets
    description: "list[str] — ticket IDs to verify; empty = discover from --epic"
outputs:
  - name: receipt_path
    description: "Absolute path to the written verification receipt YAML (empty if --dry-run)"
  - name: status
    description: "pass | fail | partial | skip"
---

# Verification Sweep

**Skill ID**: `onex:verification_sweep`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-7254

---

## Purpose

Post-orchestration verification sweep that runs as the final step after `epic-team` or
`ticket-pipeline` completes. It verifies that the work actually produced visible, correct
results — not just that PRs merged and tests passed.

Three verification phases:

1. **Dashboard endpoints** — HTTP GET against endpoints referenced by the work; assert
   HTTP 200 with non-null, non-default response data
2. **Database tables** — query tables touched by the work; assert rows exist matching
   expected schemas
3. **DoD evidence** — check `dod_evidence` items of type `rendered_output` have passing
   receipts

This skill is **non-blocking**: failures produce receipts and optional Linear comments
but do not halt orchestration. The orchestrator reads the receipt and decides whether
to proceed.

---

## Usage

```
/verification-sweep --ticket OMN-5400
/verification-sweep --tickets OMN-5400,OMN-5401
/verification-sweep --epic OMN-2000
/verification-sweep --dry-run --epic OMN-2000
/verification-sweep --ticket OMN-5400 --skip-dashboard
```

---

## Announce

"I'm using the verification-sweep skill to verify post-orchestration results for {tickets}."

---

## Phase 1 — Dashboard Endpoint Verification

For each ticket, extract dashboard endpoints from:
1. The ticket's `ModelTicketContract.dod_evidence` entries where `surface == "DASHBOARD"` or
   `type == "rendered_output"`
2. The ticket description (scan for `localhost:3000` or route references)
3. Known endpoint mappings from `omnidash/topics.yaml` for topics touched by the ticket

For each endpoint:

```bash
# HTTP check — expect 200 with non-empty body
curl -s -o /tmp/verify_response.json -w "%{http_code}" http://localhost:3000{route}

# Verify response is not null/empty/default
# Check: HTTP status == 200
# Check: response body is not empty, not "null", not "{}", not "[]"
# Check: if JSON, contains at least one non-null data field
```

Classify each endpoint:
- `PASS`: HTTP 200, response contains real data
- `FAIL_HTTP`: non-200 status code
- `FAIL_EMPTY`: HTTP 200 but response is null/empty/default
- `FAIL_DEFAULT`: HTTP 200 but data matches known default/placeholder patterns
- `SKIP`: endpoint not reachable (service not running) — non-blocking

---

## Phase 2 — Database Table Verification

For each ticket, extract database tables from:
1. The ticket's `ModelTicketContract.interfaces_touched` where surface is `DB`
2. Migration files referenced in the PR diff
3. Projection handlers mapped from `omnidash/topics.yaml`

For each table:

```bash
source ~/.omnibase/.env

# Check table exists and has rows
psql -h localhost -p 5436 -U postgres -d omnidash_analytics \
  -c "SELECT count(*) as row_count FROM {table_name};" 2>/dev/null

# Check schema matches expected columns (if contract specifies them)
psql -h localhost -p 5436 -U postgres -d omnidash_analytics \
  -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table_name}';" 2>/dev/null
```

Classify each table:
- `PASS`: table exists, has rows, schema matches expectations
- `FAIL_MISSING`: table does not exist
- `FAIL_EMPTY`: table exists but has 0 rows (when rows are expected)
- `FAIL_SCHEMA`: table exists but columns don't match expected schema
- `SKIP`: database not reachable — non-blocking

---

## Phase 3 — DoD Evidence Verification

For each ticket, fetch the `ModelTicketContract` from the Linear ticket description and
check `dod_evidence` items:

1. Items with `type: rendered_output`:
   - Must have a corresponding receipt in `.onex_state/verification-receipts/`
   - Receipt must show `status: pass`
   - If no receipt exists: `FAIL_NO_RECEIPT`

2. Items with `type: integration_test`:
   - Check CI status on the merged PR — all required checks must be green
   - If PR not merged: `SKIP`

3. Items with `type: playwright_behavioral`:
   - Check for Playwright test results in CI artifacts or local test runs
   - If no results found: `FAIL_NO_EVIDENCE`

Classify each evidence item:
- `PASS`: evidence exists and validates
- `FAIL_NO_RECEIPT`: rendered_output with no receipt
- `FAIL_NO_EVIDENCE`: evidence type with no supporting artifacts
- `FAIL_STALE`: receipt exists but is older than the most recent merge
- `SKIP`: evidence type not applicable or infrastructure unavailable

---

## Verification Receipt Schema

Written to `.onex_state/verification-receipts/{ticket-id}.yaml`:

```yaml
# Verification Receipt
ticket_id: "OMN-5400"
sweep_timestamp: "2026-04-02T10:30:00Z"
overall_status: pass  # pass | fail | partial
phases:
  dashboard:
    status: pass
    endpoints_checked: 2
    results:
      - endpoint: "/api/intelligence/patterns"
        status: pass
        http_code: 200
        evidence: "Response contains 15 pattern records"
      - endpoint: "/api/platform/registry"
        status: pass
        http_code: 200
        evidence: "Response contains 8 registered nodes"
  database:
    status: pass
    tables_checked: 1
    results:
      - table: "pattern_learning_artifacts"
        status: pass
        row_count: 42
        evidence: "42 rows, schema matches expected columns"
  dod_evidence:
    status: pass
    items_checked: 1
    results:
      - type: "rendered_output"
        status: pass
        evidence: "Receipt exists, status=pass, timestamp within 24h of merge"
idempotent: true  # Running again produces the same receipt if state unchanged
```

---

## Failure Receipt Schema

Written to `.onex_state/verification-failures/{ticket-id}.yaml` when `overall_status != pass`:

```yaml
ticket_id: "OMN-5400"
sweep_timestamp: "2026-04-02T10:30:00Z"
overall_status: fail
failure_summary: "Dashboard endpoint /api/platform/registry returned empty data"
phases:
  dashboard:
    status: fail
    endpoints_checked: 2
    results:
      - endpoint: "/api/intelligence/patterns"
        status: pass
        http_code: 200
        evidence: "Response contains 15 pattern records"
      - endpoint: "/api/platform/registry"
        status: fail_empty
        http_code: 200
        evidence: "Response body is '[]' — no registered nodes"
  database:
    status: pass
    tables_checked: 1
    results:
      - table: "pattern_learning_artifacts"
        status: pass
        row_count: 42
        evidence: "42 rows, schema matches expected columns"
  dod_evidence:
    status: skip
    items_checked: 0
    results: []
linear_comment_posted: true
```

---

## Linear Comment on Failure

When `overall_status` is `fail` and `--dry-run` is NOT set, post a Linear comment:

```
**Verification Sweep — FAIL**

Ticket: {ticket_id}
Sweep time: {timestamp}

**Failed checks:**
- Dashboard: `/api/platform/registry` returned empty data (HTTP 200, body `[]`)

**Passing checks:**
- Dashboard: `/api/intelligence/patterns` — 15 records
- Database: `pattern_learning_artifacts` — 42 rows

Receipt: `.onex_state/verification-failures/{ticket-id}.yaml`
```

---

## Non-Blocking Behavior

This skill is explicitly **non-blocking**:

- It writes receipts to `.onex_state/verification-receipts/` or `.onex_state/verification-failures/`
- It optionally posts Linear comments on failure
- It does NOT halt orchestration, block merges, or prevent epic completion
- The calling orchestrator (epic-team, ticket-pipeline) reads the receipt and decides
  how to handle failures

---

## Idempotency

Running the sweep twice on the same ticket with the same underlying state produces the
same receipt. The receipt file is overwritten (not appended). Receipt timestamps reflect
the most recent sweep run.

---

## Integration Points

- **epic-team**: dispatches verification-sweep after all waves complete, before DoD gate
- **ticket-pipeline**: dispatches verification-sweep after auto-merge, before marking Done
- **integration-sweep**: complementary — integration-sweep checks contracts and surfaces;
  verification-sweep checks live data and rendered output
- **data-flow-sweep**: complementary — data-flow-sweep checks full pipeline topology;
  verification-sweep checks per-ticket verification
- **dod-verify**: verification-sweep checks dod_evidence items; dod-verify runs the full
  DoD compliance check

---

## Dispatch Rules

- ALL work dispatched through Agent Teams or Headless
- NEVER edit files directly from orchestrator context
- `--dry-run` produces zero side effects (no receipts, no Linear comments)

---

## Summary Output

```
VERIFICATION SWEEP — {ticket_ids}
====================================

| Ticket   | Phase      | Check                      | Status     | Evidence                                |
|----------|------------|----------------------------|------------|-----------------------------------------|
| OMN-5400 | Dashboard  | /api/intelligence/patterns | PASS       | 15 pattern records                      |
| OMN-5400 | Dashboard  | /api/platform/registry     | FAIL_EMPTY | Response body is '[]'                   |
| OMN-5400 | Database   | pattern_learning_artifacts | PASS       | 42 rows, schema matches                 |
| OMN-5400 | DoD        | rendered_output            | PASS       | Receipt exists, status=pass             |

Summary: 3 PASS, 1 FAIL, 0 SKIP (4 total)
Overall: FAIL
Receipt: .onex_state/verification-failures/OMN-5400.yaml
```
