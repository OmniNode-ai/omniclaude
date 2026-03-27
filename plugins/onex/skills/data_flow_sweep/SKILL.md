---
description: End-to-end data flow verification — for each Kafka topic in omnidash topics.yaml, verify producer emits, consumer receives (0 lag), DB table has rows, dashboard page shows data. Auto-creates Linear tickets for broken flows.
mode: full
version: "1.0.0"
level: advanced
debug: false
category: verification
tags: [data-flow, kafka, projections, sweep, close-out]
author: omninode
composable: true
args:
  - name: --dry-run
    description: "Report findings without creating Linear tickets (default: false)"
    required: false
  - name: --topic
    description: "Check a single topic only (e.g., onex.evt.omniclaude.session-outcome.v1)"
    required: false
  - name: --skip-playwright
    description: "Skip Phase 4 dashboard page verification (faster, infra-only check)"
    required: false
---

# Data Flow Sweep

**Skill ID**: `onex:data-flow-sweep`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-6761
**Epic**: OMN-6760

---

## Dispatch Requirement

When invoked, your FIRST and ONLY action is to dispatch to a polymorphic-agent. Do NOT
read files, run bash, or take any other action before dispatching.

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Run data-flow-sweep",
  prompt="Run the data-flow-sweep skill. <full context and args>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

## Purpose

End-to-end data flow verification for omnidash projections. For each Kafka topic
subscribed by the omnidash read-model consumer, verify the complete pipeline:

```
Producer (omniclaude/omnibase_infra/omniintelligence)
  → Kafka topic (Redpanda)
    → Consumer (omnidash read-model-consumer)
      → DB table (omnidash_analytics)
        → Dashboard page (localhost:3000)
```

**Announce at start:** "I'm using the data-flow-sweep skill to verify end-to-end data flow for all omnidash projections."

## Usage

```
/data-flow-sweep
/data-flow-sweep --dry-run
/data-flow-sweep --topic onex.evt.omniclaude.session-outcome.v1
/data-flow-sweep --skip-playwright
```

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | false | Report only, no Linear tickets created |
| `--topic` | _(all)_ | Check a single topic instead of all |
| `--skip-playwright` | false | Skip Phase 4 dashboard page verification |

---

## Phase 1 — Topic Discovery

Read `omnidash/topics.yaml` to extract all `read_model_topics` entries.
For each entry, record: `{topic, handler_name}`.

Map each handler to its projection file in `omnidash/server/projections/`.
Map each projection to its target DB table(s) in `omnidash/shared/intelligence-schema.ts`.

Output: topic manifest with columns:

| Topic | Handler | Projection File | DB Table(s) | Dashboard Route |
|-------|---------|-----------------|-------------|-----------------|

If `--topic` is set, filter the manifest to that single topic.

---

## Phase 2 — Producer Verification

For each topic, check if the producer is actively emitting:

```bash
# Check if topic exists and has messages
docker exec omnibase-infra-redpanda rpk topic describe {topic}
# Check latest offset (non-zero = messages exist)
docker exec omnibase-infra-redpanda rpk topic consume {topic} --num 1 --offset end
```

Classify each topic:
- `ACTIVE`: topic exists, has recent messages (offset > 0)
- `EMPTY`: topic exists but 0 messages
- `MISSING`: topic does not exist in Redpanda

---

## Phase 3 — Consumer + DB Verification

For each topic with `ACTIVE` producer status:

```bash
# Check consumer group lag
docker exec omnibase-infra-redpanda rpk group describe omnidash-read-model-v2

# Check DB table row count
source ~/.omnibase/.env
psql -h localhost -p 5436 -U postgres -d omnidash_analytics \
  -c "SELECT count(*) FROM {table_name};"

# Check latest row timestamp
psql -h localhost -p 5436 -U postgres -d omnidash_analytics \
  -c "SELECT max(created_at) FROM {table_name};"
```

Classify each flow:
- `FLOWING`: lag=0, table has recent rows (within 24h)
- `STALE`: lag=0 but table data older than 24h
- `LAGGING`: consumer lag > 0
- `EMPTY_TABLE`: messages in topic but 0 rows in DB
- `MISSING_TABLE`: table does not exist

---

## Phase 4 — Dashboard Page Verification (optional)

Skip if `--skip-playwright` is set.

For each table with `FLOWING` status, navigate to the associated dashboard route
using Playwright MCP. Verify:
- Page loads without errors
- Non-zero data is visible (not "No data" or "0 results")
- No JS console errors

Classify:
- `VISIBLE`: data renders on dashboard
- `EMPTY_PAGE`: page loads but shows no data despite DB having rows
- `BROKEN_PAGE`: JS errors or HTTP failures

---

## Phase 5 — Report + Ticket Creation

Emit a summary table:

| Topic | Producer | Consumer | DB | Dashboard | Status |
|-------|----------|----------|----|-----------|--------|

For each broken flow (anything not FLOWING+VISIBLE), auto-create a Linear ticket
unless `--dry-run` is set:

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

---

## Dispatch Rules

```
RULE: ALL Task() calls MUST use subagent_type="onex:polymorphic-agent".
RULE: NEVER modify files directly from the orchestrator context.
RULE: --dry-run produces zero side effects: no tickets, no PRs, no file changes.
```

---

## Integration Points

- **autopilot**: invoked as optional data verification step in close-out mode
- **dashboard-sweep**: complementary — dashboard-sweep checks UI; data-flow-sweep checks pipeline
- **integration-sweep**: complementary — integration-sweep checks contracts; data-flow-sweep checks live data
