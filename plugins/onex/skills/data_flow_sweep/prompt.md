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

## Phase 1 — Topic Discovery

Read `omnidash/topics.yaml` to extract all `read_model_topics` entries.

```bash
OMNIDASH_PATH="${OMNIDASH_PATH:-}"
for candidate in \
  "/Volumes/PRO-G40/Code/omni_home/omnidash" \
  "${OMNI_HOME:-}/omnidash"; do
  if [ -f "$candidate/topics.yaml" ]; then
    OMNIDASH_PATH="$candidate"
    break
  fi
done
```

For each topic entry, build a manifest:
1. Parse `topics.yaml` — extract each topic name and its handler name
2. Map each handler to its projection file in `omnidash/server/projections/`
3. Map each projection to its target DB table(s) by reading `omnidash/shared/intelligence-schema.ts`
4. Determine the dashboard route that renders data from each table

If `--topic` is specified, filter the manifest to only that topic.

**Output**: Topic manifest table:

| Topic | Handler | Projection File | DB Table(s) | Dashboard Route |
|-------|---------|-----------------|-------------|-----------------|

---

## Phase 2 — Producer Verification

For each topic in the manifest, verify the producer is actively emitting:

```bash
KAFKA_BROKERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:19092}"

# Check if topic exists and has messages
docker exec omnibase-infra-redpanda rpk topic describe "$TOPIC" 2>&1

# If docker is not available, try kcat directly
kcat -L -b "$KAFKA_BROKERS" -t "$TOPIC" 2>&1 | head -5

# Check latest offset
kcat -C -b "$KAFKA_BROKERS" -t "$TOPIC" -o end -c 1 -e 2>&1 | head -3
```

Classify each topic:
- `ACTIVE`: topic exists, has recent messages (offset > 0)
- `EMPTY`: topic exists but 0 messages
- `MISSING`: topic does not exist in broker metadata

---

## Phase 3 — Consumer + DB Verification

For each topic with `ACTIVE` producer status:

```bash
INFRA_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5436}"

# Check consumer group lag
docker exec omnibase-infra-redpanda rpk group describe omnidash-read-model-v2 2>&1

# Check DB table row count
psql -h "$INFRA_HOST" -p "$POSTGRES_PORT" -U postgres -d omnidash_analytics \
  -tAc "SELECT count(*) FROM $TABLE_NAME;"

# Check latest row timestamp
psql -h "$INFRA_HOST" -p "$POSTGRES_PORT" -U postgres -d omnidash_analytics \
  -tAc "SELECT max(created_at) FROM $TABLE_NAME;"
```

Classify each flow:
- `FLOWING`: lag=0, table has recent rows (within 24h)
- `STALE`: lag=0 but table data older than 24h
- `LAGGING`: consumer lag > 0
- `EMPTY_TABLE`: messages in topic but 0 rows in DB
- `MISSING_TABLE`: table does not exist

---

## Phase 3b — Field Mapping Verification

For each topic-to-projection-to-DB chain, verify field alignment:

1. **Consume 1 message** from the topic:
```bash
kcat -C -b "$KAFKA_BROKERS" -t "$TOPIC" -o end -c 1 -e 2>&1
```

2. **Parse the JSON payload** — extract top-level field names

3. **Read the projection handler source** — extract field names it reads from `data.*`:
```bash
grep -oP 'data\.\K\w+' "$PROJECTION_FILE" | sort -u
```

4. **Read the DB table schema** — extract column names:
```sql
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = '$TABLE_NAME';
```

5. **Assert**: every field the projection reads from the message exists in the message
6. **Assert**: every column the projection writes to exists in the DB table

### Critical Chains to Verify (Minimum)

These three chains must always be checked regardless of filter:
1. `onex.evt.platform.node-introspection.v1` -> `platform-projections.ts:projectNodeIntrospection` -> `node_service_registry`
2. `onex.evt.omniintelligence.pattern-learned.v1` -> `omniintelligence-projections.ts:projectPatternLearned` -> `pattern_learning_artifacts`
3. `onex.evt.omniclaude.routing-decision.v1` -> `omniclaude-projections.ts:projectRoutingDecision` -> `agent_routing_decisions`

---

## Phase 4 — Dashboard Page Verification (Optional)

**Skip this phase if `--skip-playwright` is set.**

For each table with `FLOWING` status, navigate to the associated dashboard route using Playwright MCP.

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

## Phase 5 — Report + Ticket Creation

### Summary Table

```
Data Flow Sweep: {OVERALL_STATUS}

| Topic | Producer | Consumer | DB | Dashboard | Status |
|-------|----------|----------|----|-----------|--------|
| onex.evt.omniclaude.routing-decision.v1 | ACTIVE | FLOWING | 1234 rows | VISIBLE | OK |
| onex.evt.omniintelligence.pattern-stored.v1 | ACTIVE | STALE | 56 rows | EMPTY_PAGE | WARN |
```

### Ticket Creation

For each broken flow (anything not FLOWING+VISIBLE), auto-create a Linear ticket:

**Only if `--dry-run` is NOT set:**

```
Title: fix(data-flow): {topic} — {failure_classification}
Project: Active Sprint
Labels: data-flow, sweep
Description:
  - Topic: {topic}
  - Handler: {handler}
  - Projection: {projection_file}
  - DB table: {table}
  - Dashboard route: {route}
  - Failure point: {classification}
  - Evidence: {rpk output / psql output / screenshot}
```

When `--dry-run` is set:
- Print what tickets WOULD be created
- Do not create any tickets
- Do not modify any state

---

## Dispatch Rules

- ALL work dispatched through `onex:polymorphic-agent`
- NEVER edit files directly from orchestrator context
- `--dry-run` produces zero side effects (no tickets, no PRs)

## Integration Points

- **autopilot**: invoked as optional data verification step in close-out mode
- **dashboard-sweep**: complementary — dashboard-sweep checks UI; data-flow-sweep checks pipeline
- **integration-sweep**: complementary — integration-sweep checks contracts; data-flow-sweep checks live data
