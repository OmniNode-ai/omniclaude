---
description: End-to-end data flow verification — for each Kafka topic in omnidash topics.yaml, verify producer emits, consumer receives (0 lag), DB table has rows, dashboard page shows data. Auto-creates Linear tickets for broken flows.
mode: full
version: 2.0.0
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
    description: "Check a single topic only"
    required: false
  - name: --skip-playwright
    description: "Skip Phase 4 dashboard page verification"
    required: false
  - name: --flows
    description: "JSON array of pre-collected flow objects (topic, handler_name, table_name, producer_status, ...)"
    required: false
---

# Data Flow Sweep

**Announce at start:** "I'm using the data-flow-sweep skill to verify end-to-end data flow for all omnidash projections."

## Usage

```
/data-flow-sweep
/data-flow-sweep --dry-run
/data-flow-sweep --topic onex.evt.omniclaude.routing-decision.v1
/data-flow-sweep --skip-playwright
```

## Execution

### Step 1 — Parse arguments

- `--dry-run` → report only, no ticket creation
- `--topic` → filter to single topic
- `--skip-playwright` → skip Phase 4 dashboard verification
- `--flows` → JSON array of pre-collected flow metadata (skips live Kafka/DB checks)

### Step 2 — Collect flow metadata (unless `--flows` provided)

For each topic in `omnidash/topics.yaml`:
1. Check topic existence and offset via `rpk topic describe`
2. Check consumer group lag via `rpk group describe omnidash-read-model-v2`
3. Check DB table row count and latest timestamp via `psql`
4. Verify field mapping: consume 1 message, compare fields against projection handler and DB schema

Classify each flow: `FLOWING` | `STALE` | `LAGGING` | `EMPTY_TABLE` | `MISSING_TABLE` | `PRODUCER_DOWN`

### Step 3 — Run node

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_data_flow_sweep \
  [--flows '<json-array>'] \
  [--topic <topic>] \
  [--dry-run]
```

Capture stdout (JSON: `DataFlowSweepResult`). Exit 0 = healthy, exit 1 = issues found.

### Step 4 — Dashboard verification (unless `--skip-playwright`)

For each `FLOWING` table, use Playwright MCP to navigate to the dashboard route and verify
data renders (not "No data", no JS errors).

### Step 5 — Report + ticket creation

Display summary table with per-flow status. For each broken flow (not `FLOWING`+`VISIBLE`),
create a Linear ticket (unless `--dry-run`):

```
Title: fix(data-flow): {topic} — {failure_classification}
Labels: data-flow, sweep
Project: Active Sprint
```

## Critical Chains (always checked)

1. `onex.evt.platform.node-introspection.v1` → `node_service_registry`
2. `onex.evt.omniintelligence.pattern-learned.v1` → `pattern_learning_artifacts`
3. `onex.evt.omniclaude.routing-decision.v1` → `agent_routing_decisions`

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_data_flow_sweep/ (flow verification logic)
contract   -> node_data_flow_sweep/contract.yaml
```
