# dod-sweep

**Skill ID**: `onex:dod-sweep`
**Version**: 1.0.0
**Owner**: omniclaude

## Purpose

Run a batch DoD compliance sweep across recently completed Linear tickets.
Returns structured `ModelDodSweepResult` JSON and emits a `dod.sweep.completed`
Kafka event for omnidash visibility.

This is a **thin shell** that delegates to the `check_dod_compliance.py --json`
handler in `onex_change_control`.

## Arguments

| Arg | Default | Description |
|-----|---------|-------------|
| `--since-days` | 7 | Look-back window |
| `--contracts-dir` | `$ONEX_CC_REPO_PATH/drift` | Contracts directory |
| `--dry-run` | false | Skip event emission |

## Execution

### Step 1: Resolve paths <!-- ai-slop-ok: skill-step-heading -->

```bash
ONEX_CC_REPO_PATH="${ONEX_CC_REPO_PATH:-$HOME/onex_change_control}"  # local-path-ok
CONTRACTS_DIR="${CONTRACTS_DIR:-$ONEX_CC_REPO_PATH/drift}"
SINCE_DAYS="${SINCE_DAYS:-7}"
```

### Step 2: Run DoD sweep handler <!-- ai-slop-ok: skill-step-heading -->

**Critical: In JSON mode, do NOT merge stderr into stdout and do NOT truncate stdout with `head`.** The `--json` contract guarantees stdout is clean parseable JSON; stderr carries diagnostics separately. Truncating JSON with `head` breaks parsing.

```bash
cd "$ONEX_CC_REPO_PATH"
SWEEP_OUTPUT=$(uv run python -m onex_change_control.scripts.check_dod_compliance \
  --contracts-dir "$CONTRACTS_DIR" \
  --since-days "$SINCE_DAYS" \
  --json 2>/dev/null)
SWEEP_EXIT=$?
```

If `$SWEEP_EXIT` is nonzero AND `$SWEEP_OUTPUT` is empty or non-JSON, report the error:
```bash
# Diagnostics on failure -- check stderr separately
uv run python -m onex_change_control.scripts.check_dod_compliance \
  --contracts-dir "$CONTRACTS_DIR" \
  --since-days "$SINCE_DAYS" \
  --json 1>/dev/null 2>&1 | head -50
```

Parse `$SWEEP_OUTPUT` as JSON. The `overall_status` field in the JSON payload is the authoritative result -- not the exit code.

### Step 3: Evaluate result <!-- ai-slop-ok: skill-step-heading -->

Read the `overall_status` field from the JSON:
- `PASS`: All non-exempted tickets passed all checks.
- `FAIL`: At least one ticket has a failing check. Print the failing tickets.
- `UNKNOWN`: Exemptions or inconclusive results. Print summary.

### Step 4: Emit event (unless --dry-run) <!-- ai-slop-ok: skill-step-heading -->

If not `--dry-run`, emit the `dod.sweep.completed` event using the emit CLI wrapper:

```bash
cd "$OMNICLAUDE_PROJECT_ROOT"
uv run python plugins/onex/hooks/lib/emit_client_wrapper.py emit \
  --event-type dod.sweep.completed \
  --payload "{\"run_id\": \"$RUN_ID\", \"overall_status\": \"$STATUS\", \"total_tickets\": $TOTAL, \"passed\": $PASSED, \"failed\": $FAILED, \"exempted\": $EXEMPTED, \"lookback_days\": $SINCE_DAYS}" 2>/dev/null || true
```

**Note**: The `|| true` ensures emission failure never blocks the skill (fire-and-forget).

### Step 5: Report <!-- ai-slop-ok: skill-step-heading -->

Print a summary table:
```
DoD Sweep Complete: {overall_status}
  Total: {total_tickets} | Passed: {passed} | Failed: {failed} | Exempt: {exempted}
  Look-back: {since_days} days | Run ID: {run_id}
```

Return the `overall_status` for upstream consumption (autopilot halt logic).
