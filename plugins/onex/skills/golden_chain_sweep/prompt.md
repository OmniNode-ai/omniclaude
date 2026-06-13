# Golden Chain Sweep

You are executing the golden-chain-sweep skill. This validates end-to-end Kafka-to-DB-projection data flow for all golden chains by validating pre-collected projected_rows against chain definitions.

## Argument Parsing

```
/golden_chain_sweep [--chains <chain1,chain2,...>] [--timeout-ms <ms>] [--projected-rows '<json>'] [--dry-run]
```

```python
args = "$ARGUMENTS".split() if "$ARGUMENTS".strip() else []

chains_filter = None
timeout_ms = 15000
projected_rows = {}
dry_run = "--dry-run" in args

if "--chains" in args:
    idx = args.index("--chains")
    if idx + 1 < len(args):
        chains_filter = [c.strip() for c in args[idx + 1].split(",")]

if "--timeout-ms" in args:
    idx = args.index("--timeout-ms")
    if idx + 1 < len(args):
        timeout_ms = int(args[idx + 1])

if "--projected-rows" in args:
    idx = args.index("--projected-rows")
    if idx + 1 < len(args):
        import json
        projected_rows = json.loads(args[idx + 1])
```

## Announce

"I'm using the golden-chain-sweep skill to validate golden chain projected_rows."

---

## Execution Steps

### 1. Run node

Dispatch to `node_golden_chain_sweep` with the resolved arguments:

```bash
onex node node_golden_chain_sweep -- \
  [--chains <comma-list>] \
  [--timeout-ms <ms>] \
  [--projected-rows '<json>'] \
  [--dry-run]
```

Capture stdout (JSON: `GoldenChainSweepResult`). Exit 0 = all chains pass, exit 1 = partial/fail.

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose.

### 2. Render report

From the JSON output display:

- Summary: overall status (pass/partial/fail/gated), chains total/passed/failed/gated
- Per-chain table: chain name, status, head_topic, tail_table, missing fields (if any)
- Failure details: missing fields, error descriptions

---

## Chain Definitions

| Chain | Head Topic | Tail Table |
|-------|-----------|------------|
| registration | `onex.evt.omniclaude.routing-decision.v1` | `agent_routing_decisions` |
| pattern_learning | `onex.evt.omniintelligence.pattern-stored.v1` | `pattern_learning_artifacts` |
| delegation | `onex.evt.omniclaude.task-delegated.v1` | `delegation_events` |
| routing | `onex.evt.omniclaude.llm-routing-decision.v1` | `llm_routing_decisions` |
| evaluation | `onex.evt.omniclaude.session-outcome.v1` | `session_outcomes` |

---

## Failure Modes

| Failure | Behavior |
|---------|----------|
| Missing projected_rows for a chain | Chain shows `TIMEOUT` or `GATED` (if idle_gate=true) |
| Assertion mismatch on expected fields | Chain shows `FAIL` with per-field details |
| Error in chain definition | Log warning, mark chain `ERROR` |
