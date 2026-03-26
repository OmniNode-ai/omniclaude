# dod-sweep

**Skill ID**: `onex:dod-sweep`
**Version**: 1.1.0
**Owner**: omniclaude
**Ticket**: OMN-6728

## Purpose

Run a batch DoD compliance sweep across recently completed Linear tickets.
Returns structured `ModelDodSweepResult` JSON and emits a `dod.sweep.completed`
Kafka event for omnidash visibility.

When invoked with `--per-ticket-verify`, runs `dod-verify` individually against
each discovered ticket for granular evidence receipts. When invoked with
`--since-last-cycle`, uses the last autopilot cycle timestamp as the look-back
boundary instead of a fixed `--since-days` window.

This is the standard Step B1 (formerly Step 1.5) in the close-out autopilot
pipeline, positioned between merge-sweep (A1) and integration-sweep (B5).

## Arguments

| Arg | Default | Description |
|-----|---------|-------------|
| `--since-days` | 7 | Look-back window |
| `--since-last-cycle` | false | Use last autopilot cycle timestamp as look-back boundary |
| `--per-ticket-verify` | false | Run dod-verify individually per ticket |
| `--contracts-dir` | `$ONEX_CC_REPO_PATH/drift` | Contracts directory |
| `--dry-run` | false | Skip event emission |

## Execution

### Step 1: Resolve paths and look-back window <!-- ai-slop-ok: skill-step-heading -->

```bash
ONEX_CC_REPO_PATH="${ONEX_CC_REPO_PATH:-$HOME/onex_change_control}"  # local-path-ok
CONTRACTS_DIR="${CONTRACTS_DIR:-$ONEX_CC_REPO_PATH/drift}"
SINCE_DAYS="${SINCE_DAYS:-7}"
```

**If `--since-last-cycle` is set:**

Read the last cycle timestamp from `$ONEX_STATE_DIR/state/autopilot/cycle-state.yaml`:

```python
import yaml
from datetime import datetime, UTC, timedelta
from pathlib import Path

cycle_state_path = Path(os.environ.get("ONEX_STATE_DIR", "")) / "state/autopilot/cycle-state.yaml"

if cycle_state_path.exists():
    with open(cycle_state_path) as f:
        cycle_state = yaml.safe_load(f)
    last_cycle_ts = cycle_state.get("last_cycle_id")  # ISO timestamp
    if last_cycle_ts:
        last_cycle_dt = datetime.fromisoformat(last_cycle_ts)
        days_since = (datetime.now(tz=UTC) - last_cycle_dt).days
        SINCE_DAYS = max(days_since, 1)  # at least 1 day
    else:
        # No prior cycle, fall back to default
        SINCE_DAYS = 7
else:
    # No cycle state file, fall back to default
    SINCE_DAYS = 7
```

Print: `DoD sweep look-back: {SINCE_DAYS} days (since-last-cycle: {last_cycle_ts or 'none'})`

### Step 2: Discover completed tickets <!-- ai-slop-ok: skill-step-heading -->

Query Linear for tickets completed within the look-back window:

```python
# Use mcp__linear-server__list_issues to find completed tickets
# Filter by completedAt within the look-back window
issues = mcp__linear-server__list_issues(
    team="Omninode",
    state="Done",
    # Filter by completedAt >= (now - SINCE_DAYS)
)
```

Filter results to only include tickets where `completedAt` is within the look-back window.

If no tickets found: report "No tickets completed in look-back window" and return
`overall_status=PASS` (nothing to check).

### Step 3: Run DoD checks <!-- ai-slop-ok: skill-step-heading -->

**If `--per-ticket-verify` is set (or invoked from autopilot):**

For each discovered ticket, run individual dod-verify:

```python
from pathlib import Path

results = []
for ticket in completed_tickets:
    ticket_id = ticket["identifier"]  # e.g., "OMN-1234"

    # Check if contract exists
    contract_path = Path(ONEX_CC_REPO_PATH) / "contracts" / f"{ticket_id}.yaml"
    if not contract_path.exists():
        results.append({
            "ticket_id": ticket_id,
            "status": "UNKNOWN",
            "reason": "No contract file found",
        })
        continue

    # Load contract and check for dod_evidence
    with open(contract_path) as f:
        contract = yaml.safe_load(f)

    dod_evidence = contract.get("dod_evidence", [])
    if not dod_evidence:
        results.append({
            "ticket_id": ticket_id,
            "status": "PASS",
            "reason": "No DoD evidence items defined (exempt)",
        })
        continue

    # Run evidence checks via the shared runner
    from dod_evidence_runner import run_dod_evidence, write_evidence_receipt

    run_result = run_dod_evidence(dod_evidence)
    receipt_path = write_evidence_receipt(ticket_id, str(contract_path), run_result)

    status = "PASS" if run_result.failed == 0 else "FAIL"
    results.append({
        "ticket_id": ticket_id,
        "status": status,
        "verified": run_result.verified,
        "failed": run_result.failed,
        "skipped": run_result.skipped,
        "receipt_path": str(receipt_path),
    })
```

**If `--per-ticket-verify` is NOT set (batch mode):**

Delegate to the batch handler:

```bash
cd "$ONEX_CC_REPO_PATH"
SWEEP_OUTPUT=$(uv run python -m onex_change_control.scripts.check_dod_compliance \
  --contracts-dir "$CONTRACTS_DIR" \
  --since-days "$SINCE_DAYS" \
  --json 2>/dev/null)
SWEEP_EXIT=$?
```

**Critical: In JSON mode, do NOT merge stderr into stdout and do NOT truncate stdout with `head`.** The `--json` contract guarantees stdout is clean parseable JSON; stderr carries diagnostics separately. Truncating JSON with `head` breaks parsing.

If `$SWEEP_EXIT` is nonzero AND `$SWEEP_OUTPUT` is empty or non-JSON, report the error:
```bash
# Diagnostics on failure -- check stderr separately
uv run python -m onex_change_control.scripts.check_dod_compliance \
  --contracts-dir "$CONTRACTS_DIR" \
  --since-days "$SINCE_DAYS" \
  --json 1>/dev/null 2>&1 | head -50
```

Parse `$SWEEP_OUTPUT` as JSON. The `overall_status` field in the JSON payload is the authoritative result -- not the exit code.

### Step 4: Flag incomplete DoD evidence <!-- ai-slop-ok: skill-step-heading -->

For per-ticket-verify mode, aggregate results:

```python
total = len(results)
passed = sum(1 for r in results if r["status"] == "PASS")
failed = sum(1 for r in results if r["status"] == "FAIL")
unknown = sum(1 for r in results if r["status"] == "UNKNOWN")

if failed > 0:
    overall_status = "FAIL"
elif unknown > 0 and passed == 0:
    overall_status = "UNKNOWN"
else:
    overall_status = "PASS"
```

For batch mode, read the `overall_status` field from the JSON:
- `PASS`: All non-exempted tickets passed all checks.
- `FAIL`: At least one ticket has a failing check. Print the failing tickets.
- `UNKNOWN`: Exemptions or inconclusive results. Print summary.

### Step 5: Emit event (unless --dry-run) <!-- ai-slop-ok: skill-step-heading -->

If not `--dry-run`, emit the `dod.sweep.completed` event using the emit CLI wrapper:

```bash
cd "$OMNICLAUDE_PROJECT_ROOT"
uv run python plugins/onex/hooks/lib/emit_client_wrapper.py emit \
  --event-type dod.sweep.completed \
  --payload "{\"run_id\": \"$RUN_ID\", \"overall_status\": \"$STATUS\", \"total_tickets\": $TOTAL, \"passed\": $PASSED, \"failed\": $FAILED, \"exempted\": $EXEMPTED, \"lookback_days\": $SINCE_DAYS, \"per_ticket_verify\": $PER_TICKET}" 2>/dev/null || true
```

**Note**: The `|| true` ensures emission failure never blocks the skill (fire-and-forget).

### Step 6: Report <!-- ai-slop-ok: skill-step-heading -->

Print a summary table:

For per-ticket-verify mode:
```
DoD Sweep Complete: {overall_status}
  Mode: per-ticket-verify | Since: {since_description}
  Total: {total} | Passed: {passed} | Failed: {failed} | Unknown: {unknown}

Failing tickets:
  - {ticket_id}: {failed_checks} (receipt: {receipt_path})
  ...

Tickets with incomplete DoD evidence require remediation before release.
```

For batch mode:
```
DoD Sweep Complete: {overall_status}
  Total: {total_tickets} | Passed: {passed} | Failed: {failed} | Exempt: {exempted}
  Look-back: {since_days} days | Run ID: {run_id}
```

Return the `overall_status` for upstream consumption (autopilot halt logic).
