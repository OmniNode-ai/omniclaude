# Platform Readiness Gate

You are executing the platform readiness gate skill. This dispatches to the
`node_platform_readiness` node in omnimarket for aggregated verification across
7 dimensions into a tri-state (PASS/WARN/FAIL) readiness report.

## Argument Parsing

```
/platform_readiness [--json] [--dimension <dimension_name>]
```

Extract from `$ARGUMENTS`:
- `--json` -- Output raw JSON instead of markdown table
- `--dimension <name>` -- Check a single dimension only

## Announce

"I'm running the platform readiness gate to assess overall system health across 7 verification dimensions."

---

## Execution: Dispatch to node_platform_readiness

Build the `onex run` command from parsed arguments and dispatch to the omnimarket node.
The node handles all 7 verification checks internally (contract completeness, golden
chain health, data flow health, runtime wiring, dashboard data, cost measurement, CI health),
applies freshness overrides, and computes the overall status.

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok

# Build argument list from parsed flags
ARGS=""
if [ "$JSON_OUTPUT" = "true" ]; then
  ARGS="$ARGS --json"
fi
if [ -n "$SINGLE_DIMENSION" ]; then
  ARGS="$ARGS --dimension $SINGLE_DIMENSION"
fi

uv run onex run node_platform_readiness -- $ARGS
```

Capture the JSON output from stdout. The node produces a structured report with
per-dimension status, freshness, details, blockers, and degraded items.

---

## Post-dispatch: Render results

If `--json` flag was set, output the raw JSON from the node.

Otherwise, parse the node output and render the markdown report:

```markdown
# Platform Readiness Report -- {date}

## Overall: {PASS|WARN|FAIL}

| Dimension | Status | Freshness | Details |
|-----------|--------|-----------|---------|
| Contract completeness | {status} | {freshness} | {details} |
| Golden chain health | {status} | {freshness} | {details} |
| Data flow health | {status} | {freshness} | {details} |
| Runtime wiring | {status} | {freshness} | {details} |
| Dashboard data | {status} | {freshness} | {details} |
| Cost measurement | {status} | {freshness} | {details} |
| CI health | {status} | {freshness} | {details} |

## Blockers
{list of FAIL dimensions with details, or "None"}

## Degraded
{list of WARN dimensions with details, or "None"}

## Readiness Decision
{overall status with specific actionable items}
```

---

## Error Handling

- If `onex run` fails: report the error and exit
- If a dimension check fails within the node: it reports FAIL for that dimension with reason
- Never return fake/optimistic results -- when in doubt, WARN or FAIL
