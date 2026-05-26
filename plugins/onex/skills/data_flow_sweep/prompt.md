# Data Flow Sweep

You are executing the data-flow-sweep skill. This verifies end-to-end data flow for all omnidash Kafka-to-DB-to-Dashboard projections.

## Argument Parsing

```
/data_flow_sweep [--dry-run] [--topic <topic_name>] [--skip-playwright]
```

```python
args = "$ARGUMENTS".split() if "$ARGUMENTS".strip() else []

dry_run = "--dry-run" in args
skip_playwright = "--skip-playwright" in args
single_topic = None

if "--topic" in args:
    idx = args.index("--topic")
    if idx + 1 < len(args):
        single_topic = args[idx + 1]
```

## Announce

"I'm using the data-flow-sweep skill to verify end-to-end data flow for all omnidash projections."

---

## Phase 1 — Dispatch to node

Run the node with `--collect` so it performs all rpk/psql metadata collection internally:

```bash
onex node node_data_flow_sweep -- \
  --collect \
  ${single_topic:+--topic "$single_topic"} \
  ${dry_run:+--dry-run}
```

Capture JSON stdout as `sweep_result`. Exit 0 = healthy, exit 1 = issues found.

On non-zero exit, surface the `SkillRoutingError` JSON envelope verbatim — do not produce prose.

The node collects and classifies each flow in one pass:
- Producer status (`ACTIVE` | `EMPTY` | `MISSING`) via `rpk topic describe`
- Consumer lag via `rpk group describe`
- DB table row count and recency via `psql`
- Flow status: `FLOWING` | `STALE` | `LAGGING` | `EMPTY_TABLE` | `MISSING_TABLE` | `PRODUCER_DOWN` | `TOPIC_STALE`

---

## Phase 2 — Dashboard Page Verification (Optional)

**Skip this phase if `--skip-playwright` is set.**

For each flow with `flow_status == "FLOWING"` in `sweep_result.flow_results`, navigate to
the associated `dashboard_route` using Playwright MCP.

```
Use mcp__playwright__browser_navigate to load http://localhost:3000{dashboard_route}
Use mcp__playwright__browser_snapshot to capture page state
Use mcp__playwright__browser_console_messages to check for JS errors
```

Verify:
- Page loads without errors (HTTP 200)
- Non-zero data is visible (not "No data" or "0 results")
- No JS console errors

Classify:
- `VISIBLE`: data renders on dashboard
- `EMPTY_PAGE`: page loads but shows no data despite DB having rows
- `BROKEN_PAGE`: JS errors or HTTP failures

---

## Phase 3 — Report + Ticket Creation

### Summary Table

```
Data Flow Sweep: {sweep_result.status}

| Topic | Producer | Consumer | DB | Dashboard | Status |
|-------|----------|----------|----|-----------|--------|
| onex.evt.omniclaude.routing-decision.v1 | ACTIVE | FLOWING | 1234 rows | VISIBLE | OK |
| onex.evt.omniintelligence.pattern-stored.v1 | ACTIVE | STALE | 56 rows | EMPTY_PAGE | WARN |
```

### Ticket Creation

For each broken flow (anything not `FLOWING`), auto-create a Linear ticket.

**Only if `--dry-run` is NOT set:**

```
Title: fix(data-flow): {topic} — {failure_classification}
Project: Active Sprint
Labels: data-flow, sweep
Description:
  - Topic: {topic}
  - Handler: {handler_name}
  - DB table: {table_name}
  - Dashboard route: {dashboard_route}
  - Failure point: {flow_status}
  - Evidence: {node JSON output excerpt}
```

When `--dry-run` is set:
- Print what tickets WOULD be created
- Do not create any tickets
- Do not modify any state

---

## Dispatch Rules

- ALL work dispatched through `general-purpose`
- NEVER edit files directly from orchestrator context
- `--dry-run` produces zero side effects (no tickets, no PRs)

## Integration Points

- **autopilot**: invoked as optional data verification step in close-out mode
- **dashboard-sweep**: complementary — dashboard-sweep checks UI; data-flow-sweep checks pipeline
- **integration-sweep**: complementary — integration-sweep checks contracts; data-flow-sweep checks live data
