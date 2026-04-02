---
description: Validate end-to-end Kafka-to-DB-projection data flow for all golden chains
mode: full
level: advanced
debug: false
---

# golden-chain-sweep

## Dispatch Surface

**Target**: Direct invocation or Agent Teams

## Purpose

Executes a golden chain validation sweep that verifies events flow end-to-end
from Kafka through omnidash ReadModelConsumer projections into the
`omnidash_analytics` database with correct field values. Extends the existing
`golden_path_validate` skill (which tests Kafka-to-Kafka) to cover
Kafka-to-DB-projection.

## What It Validates

5 chains, each verifying one topic -> table projection:

| Chain | Head Topic | Tail Table |
|-------|-----------|------------|
| registration | `onex.evt.omniclaude.routing-decision.v1` | `agent_routing_decisions` |
| pattern_learning | `onex.evt.omniintelligence.pattern-stored.v1` | `pattern_learning_artifacts` |
| delegation | `onex.evt.omniclaude.task-delegated.v1` | `delegation_events` |
| routing | `onex.evt.omniclaude.llm-routing-decision.v1` | `llm_routing_decisions` |
| evaluation | `onex.evt.omniintelligence.run-evaluated.v1` | `session_outcomes` |

## How To Run

### Prerequisites

1. Local Kafka/Redpanda running (`infra-up` or Docker)
2. omnidash running (`cd omnidash && npm run dev:local`)
3. `KAFKA_BOOTSTRAP_SERVERS=localhost:19092`
4. `OMNIDASH_ANALYTICS_DB_URL` set to local omnidash_analytics

### Invocation

```
/golden_chain_sweep
```

With chain filter:
```
/golden_chain_sweep --chains registration,routing
```

## Execution Steps

1. **Build payloads**: The payload compute node generates synthetic events with
   `golden-chain-{name}-{uuid}` correlation IDs for all (or filtered) chains.

2. **Publish and poll** (parallel): For each chain, publish the synthetic event
   to the head topic via aiokafka, then poll the tail table in
   `omnidash_analytics` for a row matching the correlation_id. Timeout: 15s
   per chain.

3. **Assert**: Run field-level assertions against the projected row (e.g.,
   `selected_agent` is not null, `correlation_id` matches).

4. **Cleanup**: DELETE synthetic rows from projection tables after validation.

5. **Reduce**: Aggregate per-chain results into a sweep summary with overall
   status (pass/partial/fail).

6. **Persist**: INSERT results into `golden_chain_sweep_results` table for
   historical trend analysis.

7. **Evidence**: Write evidence artifact to
   `$ONEX_STATE_DIR/golden-chain-sweep/{date}/{sweep_id}/sweep_results.json`.

## Output

Displays a summary table:

```
Golden Chain Sweep: PASS (5/5 chains passed)

| Chain            | Status  | Publish (ms) | Projection (ms) |
|------------------|---------|--------------|------------------|
| registration     | pass    |         12.3 |            234.5 |
| pattern_learning | pass    |         11.1 |            345.6 |
| delegation       | pass    |         10.5 |            456.7 |
| routing          | pass    |         11.8 |            234.1 |
| evaluation       | pass    |         12.0 |            345.2 |

Sweep ID: a1b2c3d4-...
Evidence: .onex_state/golden-chain-sweep/2026-04-02/a1b2c3d4-.../sweep_results.json
```

## Failure Modes

| Failure | Behavior |
|---------|----------|
| Kafka unavailable | Chain shows `error` with publish failure |
| omnidash not running (consumer down) | Chain shows `timeout` (no projected row appears) |
| DB unreachable | Chain shows `error` with DB connection failure |
| Assertion mismatch | Chain shows `fail` with per-field assertion details |
| Cleanup fails | Warning logged, does not affect chain status |

## Python API

```python
from omniclaude.nodes.node_golden_chain_sweep_orchestrator import (
    ModelSweepRequest,
    run_sweep,
)

request = ModelSweepRequest(chain_filter=["registration"])
summary = await run_sweep(
    request,
    bootstrap_servers="localhost:19092",
    db_dsn="postgresql://...",
)
print(summary.overall_status)  # pass | partial | fail
```

## Historical Data

Sweep results are stored in `golden_chain_sweep_results` for trend analysis.
Query via the omnidash API:

```
GET /api/intelligence/golden-chain/history?days=7
```
