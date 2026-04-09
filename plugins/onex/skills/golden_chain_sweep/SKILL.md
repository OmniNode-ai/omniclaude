---
description: Validate end-to-end Kafka-to-DB-projection data flow for all golden chains
mode: full
version: 2.0.0
level: advanced
debug: false
---

# golden-chain-sweep

**Announce at start:** "I'm using the golden-chain-sweep skill."

## Usage

```
/golden-chain-sweep                                 # Validate all 5 chains
/golden-chain-sweep --chains registration,routing   # Filter chains
/golden-chain-sweep --timeout-ms 30000              # Override timeout
```

## Execution

### Step 1 — Parse arguments

- `--chains` → comma-separated chain names (default: all 5)
- `--timeout-ms` → per-chain timeout (default: 15000)
- `--projected-rows` → JSON dict of pre-collected projection data

### Step 2 — Run node

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_golden_chain_sweep \
  [--chains <comma-list>] \
  [--timeout-ms <ms>] \
  [--projected-rows '<json>']
```

Capture stdout (JSON: `GoldenChainSweepResult`). Exit 0 = all chains pass, exit 1 = partial/fail.

### Step 3 — Render report

From the JSON output display:

- Summary: overall status (pass/partial/fail), chains total/passed/failed
- Per-chain table: chain name, status, publish latency (ms), projection latency (ms)
- Failure details: missing fields, timeout messages, error descriptions

### Step 4 — Failure handling

| Failure | Cause |
|---------|-------|
| `timeout` | omnidash consumer not running or DB unreachable |
| `fail` | Assertion mismatch on expected fields |
| `error` | Kafka unavailable or DB connection failure |

## Chains

| Chain | Head Topic | Tail Table |
|-------|-----------|------------|
| registration | `onex.evt.omniclaude.routing-decision.v1` | `agent_routing_decisions` |
| pattern_learning | `onex.evt.omniintelligence.pattern-stored.v1` | `pattern_learning_artifacts` |
| delegation | `onex.evt.omniclaude.task-delegated.v1` | `delegation_events` |
| routing | `onex.evt.omniclaude.llm-routing-decision.v1` | `llm_routing_decisions` |
| evaluation | `onex.evt.omniintelligence.run-evaluated.v1` | `session_outcomes` |

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_golden_chain_sweep/ (business logic)
contract   -> node_golden_chain_sweep/contract.yaml
```
