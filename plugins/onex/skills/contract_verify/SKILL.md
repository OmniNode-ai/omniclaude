---
description: Runtime contract compliance verification — reads contract.yaml files and verifies the running system matches declarations
version: 1.0.0
mode: full
level: advanced
debug: false
category: verification
tags:
  - contracts
  - runtime
  - verification
  - compliance
---

# contract-verify skill

## Dispatch Requirement

When invoked, dispatch to a polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Contract verification run",
  prompt="Run the contract-verify skill. <full context>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

**Skill ID**: `onex:contract-verify`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-7040

---

## Purpose

Runtime contract compliance verification. Reads `contract.yaml` files from the
omnibase_infra verification subsystem and verifies that the running system matches
the declarations: registered handlers, subscribed topics, published events, and
cross-contract references.

---

## Usage

```
/contract-verify
```

Default mode: registration-only (fast, checks handler registration against contracts).

```
/contract-verify --all
```

Full mode: runs all 52 contract verification probes including subscription, publication,
handler signature, and cross-contract reference checks.

---

## Execution

### CLI Command

```bash
# Registration-only (default)
uv run python -m omnibase_infra.verification.cli --registration-only --json

# Full 52-contract verification
uv run python -m omnibase_infra.verification.cli --json

# With explicit output path
uv run python -m omnibase_infra.verification.cli --registration-only --json \
  --output-path "$ONEX_STATE_DIR/contract-verify/<run_id>/report.json"
```

### Output Path

Reports MUST be written to disk:

```
$ONEX_STATE_DIR/contract-verify/<run_id>/report.json
```

Where `<run_id>` is the current `ONEX_RUN_ID` or a timestamp-based fallback
(`contract-verify-<YYYYMMDD-HHMMSS>`).

### Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | PASS | All checks passed |
| 1 | FAIL | One or more checks failed — route to failure-to-ticket |
| 2 | QUARANTINE | Checks could not run (infra down, missing contracts) — warn only |

---

## Result Handling

### On PASS (exit 0)

Print summary with check count:

```
CONTRACT_VERIFY: PASS (N checks passed)
```

No further action required. If this is the second consecutive PASS and there are
open failure tickets from prior runs, trigger sustained-pass auto-close (see
Failure-to-Ticket Routing below).

### On FAIL (exit 1)

Print failure summary:

```
CONTRACT_VERIFY: FAIL
  - <contract_name>: <check_type> FAIL — <reason>
  - <contract_name>: <check_type> FAIL — <reason>
```

Route to `auto_ticket_from_findings` with structured findings (see below).

### On QUARANTINE (exit 2)

Print quarantine warning:

```
CONTRACT_VERIFY: QUARANTINE — <reason>
```

Do NOT create tickets. Quarantine means the verification infrastructure itself
could not run (e.g., database unreachable, contract files missing). This is an
operational issue, not a contract compliance failure.

---

## Failure-to-Ticket Routing

When the CLI exits with code 1 (FAIL), invoke `auto_ticket_from_findings` with
structured findings extracted from the JSON report.

### Finding Structure

Each failing check produces a finding:

```json
{
  "source": "contract-verify",
  "contract_name": "<contract_name>",
  "check_type": "<check_type>",
  "severity": "major",
  "title": "[contract-verify] <contract_name>: <check_type> FAIL",
  "description": "<detailed failure reason from CLI output>",
  "dedup_key": "<contract_name>:<check_type>"
}
```

### Deduplication

The `dedup_key` is `contract_name + ":" + check_type`. This ensures:
- Repeated failures for the same check do not create duplicate tickets
- Different check types on the same contract create separate tickets
- The dedup key is stable across runs

### Ticket Format

- **Title**: `[contract-verify] <contract_name>: <check_type> FAIL`
- **Labels**: `contract-verify`, `automated`
- **Priority**: Major (unless the check is marked as `warning` severity in the report)
- **Body**: Include the full check output, the contract file path, and the CLI
  command to reproduce

### Sustained PASS Auto-Close

When the verification produces PASS for 2 consecutive runs:
- Query open tickets with label `contract-verify` matching the now-passing checks
- Auto-close with comment: `Sustained PASS across 2 consecutive runs. Auto-closing.`
- The run history is tracked via the report files in `$ONEX_STATE_DIR/contract-verify/`

### QUARANTINE Does NOT Create Tickets

Quarantine results (exit 2) never trigger ticket creation. Quarantine indicates
infrastructure issues (database down, missing files), not contract violations.
These are operational alerts, not compliance failures.

---

## Architecture

```
SKILL.md           -> descriptive documentation (this file)
CLI                -> omnibase_infra.verification.cli (execution engine)
Report             -> $ONEX_STATE_DIR/contract-verify/<run_id>/report.json
Ticket routing     -> auto_ticket_from_findings skill (on FAIL only)
```

The skill is invoked:
1. Manually via `/contract-verify`
2. Automatically via cron-closeout phase B6_contract_verify
3. As part of integration-sweep post-merge verification

---

## See Also

- `omnibase_infra.verification` module — the verification engine
- `auto_ticket_from_findings` skill — ticket creation from structured findings
- `cron-closeout.sh` phase B6 — automated invocation
- `integration_sweep` skill — broader post-merge verification
