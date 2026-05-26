---
description: End-to-end data flow verification — dispatches to node_data_flow_sweep which handles all metadata collection (rpk/psql probes) and flow classification internally.
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
    description: "Skip Phase 3 dashboard page verification"
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

### Phase 1 — Parse arguments

- `--dry-run` → report only, no ticket creation; zero side effects
- `--topic` → filter to single topic
- `--skip-playwright` → skip Phase 3 dashboard verification

### Phase 2 — Dispatch to node

```bash
onex node node_data_flow_sweep -- \
  --collect \
  [--topic <topic>] \
  [--dry-run]
```

The node handles all metadata collection internally:
- Producer status via `rpk topic describe`
- Consumer group lag via `rpk group describe`
- DB table row counts and recency via `psql`
- Flow classification: `FLOWING` | `STALE` | `LAGGING` | `EMPTY_TABLE` | `MISSING_TABLE` | `PRODUCER_DOWN` | `TOPIC_STALE`

Capture stdout (JSON: `DataFlowSweepResult`). Exit 0 = healthy, exit 1 = issues found.

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose.

### Phase 3 — Dashboard verification (unless `--skip-playwright`)

For each `FLOWING` table in the result, use Playwright MCP to navigate to the dashboard route and verify data renders (not "No data", no JS errors).

### Phase 4 — Report + ticket creation (no tickets if `--dry-run`)

Display health matrix from the node result:

| Topic | Producer | Consumer | DB Table | Dashboard | Status |
|-------|----------|----------|----------|-----------|--------|
| ...   | ACTIVE   | 0 lag    | rows     | visible   | FLOWING |

For each broken flow, create a Linear ticket:

```
Title: fix(data-flow): {topic} — {failure_classification}
Labels: data-flow, sweep
Project: Active Sprint
```

## Dispatch Rules

This skill is invoked autonomously by:
- `autopilot` (daily sweep)
- `dashboard-sweep` (after deploy)
- `integration-sweep` (post-merge verification)

Use `general-purpose` routing for parallel topic checks.

## Critical Chains (always checked)

1. `onex.evt.platform.node-introspection.v1` → `node_service_registry`
2. `onex.evt.omniintelligence.pattern-learned.v1` → `pattern_learning_artifacts`
3. `onex.evt.omniclaude.routing-decision.v1` → `agent_routing_decisions`

## Architecture

```
SKILL.md   -> thin dispatch shim (this file)
node       -> omnimarket/src/omnimarket/nodes/node_data_flow_sweep/ (collection + classification)
contract   -> node_data_flow_sweep/contract.yaml
collector  -> node_data_flow_sweep/collector.py (rpk/psql probes — inside the node)
```

**Routing contract:** dispatch must use `onex node <node_name> -- --collect` (not `onex run`).
Non-zero exit emits a `SkillRoutingError` JSON envelope — callers must surface it verbatim, never paraphrase.

## Migration note (v1 to v2)

v1 ran `rpk`/`psql` probes inline in the skill before dispatching pre-collected data via `--flows`.
v2 dispatches with `--collect` — the node runs the probes internally.
The `--flows` flag on the node CLI remains available for testing with pre-collected data.
