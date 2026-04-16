# Golden Chain Sweep

You are executing the golden-chain-sweep skill. This validates end-to-end Kafka-to-DB-projection data flow for all golden chains.

## Argument Parsing

```
/golden_chain_sweep [--chains <chain1,chain2,...>] [--dry-run] [--timeout <seconds>]
```

```python
args = "$ARGUMENTS".split() if "$ARGUMENTS".strip() else []

chains_filter = None
dry_run = "--dry-run" in args
timeout_per_chain = 30  # seconds

if "--chains" in args:
    idx = args.index("--chains")
    if idx + 1 < len(args):
        chains_filter = [c.strip() for c in args[idx + 1].split(",")]

if "--timeout" in args:
    idx = args.index("--timeout")
    if idx + 1 < len(args):
        timeout_per_chain = int(args[idx + 1])
```

## Announce

"I'm using the golden-chain-sweep skill to validate end-to-end Kafka-to-DB-projection data flow."

---

## Chain Definitions

### Contract-Based Chains (Preferred Source)

First, attempt to load golden_path definitions from onex_change_control contracts:

```bash
ONEX_CC_PATH="${ONEX_CC_REPO_PATH:-}"
if [ -z "$ONEX_CC_PATH" ]; then
  for candidate in \
    "${ONEX_REGISTRY_ROOT:?ONEX_REGISTRY_ROOT required}/onex_change_control"; do
    if [ -d "$candidate/contracts" ]; then
      ONEX_CC_PATH="$candidate"
      break
    fi
  done
fi
```

Read all `contracts/*.yaml` files. For each contract with a non-null `golden_path`, extract:
- `input.topic` — the Kafka topic to publish the synthetic event to
- `input.fixture` — path to the JSON fixture file
- `output.topic` — the Kafka topic or DB table to verify against
- `output.schema_name` — optional Pydantic model for output validation

### Hardcoded Chains (Transitional Fallback)

If contract-based discovery yields fewer than 5 chains, fall back to these hardcoded definitions. These remain until contract-based chains prove stable across 3+ consecutive clean sweeps AND contract coverage reaches all 5 chains.

| Chain | Input Topic | Output DB Table |
|-------|-----------|------------|
| registration | `onex.evt.omniclaude.routing-decision.v1` | `agent_routing_decisions` |
| pattern_learning | `onex.evt.omniintelligence.pattern-stored.v1` | `pattern_learning_artifacts` |
| delegation | `onex.evt.omniclaude.task-delegated.v1` | `delegation_events` |
| routing | `onex.evt.omniclaude.llm-routing-decision.v1` | `llm_routing_decisions` |
| evaluation | `onex.evt.omniintelligence.run-evaluated.v1` | `session_outcomes` |

### Fallback Retirement Criteria

Hardcoded chain fallbacks can be removed when:
- Contract coverage includes all 5 chains with valid golden_path definitions
- Contract-based chains have produced 3+ consecutive clean sweep results
- No chain regressions observed for 7 days after switching to contract-only mode

---

## Execution Steps

### 1. Resolve Chain Definitions

Merge contract-based and hardcoded chains. Apply `--chains` filter if specified.

For each chain, determine:
- `chain_name`: human-readable identifier
- `head_topic`: Kafka topic to publish synthetic event to
- `tail_table`: DB table to poll for projected row
- `correlation_id_field`: field name for correlation (default: `correlation_id`)

### 2. Environment Validation

Verify required infrastructure is available:

```bash
# Check Kafka/Redpanda connectivity
KAFKA_BROKERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:19092}"
kcat -L -b "$KAFKA_BROKERS" -t __consumer_offsets 2>&1 | head -3

# Check PostgreSQL connectivity
INFRA_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5436}"
psql -h "$INFRA_HOST" -p "$POSTGRES_PORT" -U postgres -d omnidash_analytics -c "SELECT 1" 2>&1
```

If Kafka or PostgreSQL are unreachable:
- In `--dry-run` mode: report all chains as SKIP with reason "infrastructure unavailable"
- In normal mode: report chains as ERROR with connection failure details

### 3. Build Synthetic Payloads

For each chain, generate a synthetic event with a unique correlation ID:

```python
import uuid, json, datetime

sweep_id = str(uuid.uuid4())[:8]
correlation_id = f"golden-chain-{chain_name}-{sweep_id}"

# Build payload matching the expected event schema for the head topic
payload = {
    "correlation_id": correlation_id,
    "event_type": head_topic.split(".")[-2],  # e.g., "routing-decision"
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source": "golden-chain-sweep",
    "data": {}  # Chain-specific fields populated per chain definition
}
```

### 4. Validate Synthetic Fixtures

Before publishing, validate each synthetic fixture:
- Ensure required fields are present (correlation_id, event_type, timestamp)
- If contract specifies a schema_name and it's importable, validate against the Pydantic model
- If validation fails: log warning, mark chain as SKIP (not PASS), continue to next chain

### 5. Publish and Poll (Per Chain)

For each chain:

1. **Publish** the synthetic event to the head topic:
```bash
echo '$PAYLOAD_JSON' | kcat -P -b "$KAFKA_BROKERS" -t "$HEAD_TOPIC"
```

2. **Poll** the tail DB table for a matching row:
```bash
# Poll every 2 seconds up to timeout
for i in $(seq 1 $((timeout_per_chain / 2))); do
    RESULT=$(psql -h "$INFRA_HOST" -p "$POSTGRES_PORT" -U postgres -d omnidash_analytics \
        -tAc "SELECT count(*) FROM $TAIL_TABLE WHERE correlation_id = '$CORRELATION_ID'")
    if [ "$RESULT" -gt 0 ]; then
        echo "FOUND"
        break
    fi
    sleep 2
done
```

3. **Classify** the result:
- `PASS`: Row found in tail table within timeout
- `FAIL`: Row not found but publish succeeded (projection or consumer issue)
- `TIMEOUT`: Polling exceeded timeout_per_chain seconds
- `ERROR`: Publish failed or DB unreachable
- `SKIP`: Fixture validation failed or infrastructure unavailable

### 6. Field-Level Assertions (If Contract Provides Them)

If the contract's golden_path.output.assertions is non-empty, query the projected row and verify each assertion:

```sql
SELECT * FROM $TAIL_TABLE WHERE correlation_id = '$CORRELATION_ID' LIMIT 1;
```

For each assertion, evaluate:
- `eq`: field value equals expected
- `neq`: field value does not equal expected
- `contains`: field value contains expected substring

Failed assertions change chain status from PASS to FAIL.

### 7. Cleanup Synthetic Rows

```sql
DELETE FROM $TAIL_TABLE WHERE correlation_id LIKE 'golden-chain-%' AND correlation_id = '$CORRELATION_ID';
```

Cleanup failure is logged as a warning but does not affect chain status.

### 8. Persist Results

Write results to two locations:

1. **State directory**:
```bash
SWEEP_DIR="$ONEX_STATE_DIR/golden-chain-sweep/$(date -u +%Y-%m-%d)/$SWEEP_ID"
mkdir -p "$SWEEP_DIR"
```

Write `sweep_results.json`:
```json
{
    "sweep_id": "$SWEEP_ID",
    "timestamp": "2026-04-03T...",
    "overall_status": "pass|partial|fail",
    "chains": [
        {
            "name": "registration",
            "status": "pass",
            "publish_latency_ms": 12.3,
            "projection_latency_ms": 234.5,
            "assertions_passed": 2,
            "assertions_failed": 0
        }
    ]
}
```

2. **Database** (if available):
```sql
INSERT INTO golden_chain_sweep_results (sweep_id, chain_name, status, publish_latency_ms, projection_latency_ms, created_at)
VALUES ('$SWEEP_ID', '$CHAIN_NAME', '$STATUS', $PUBLISH_LATENCY_MS, $PROJECTION_LATENCY_MS, NOW());
```

---

## Output Format

Display a summary table:

```
Golden Chain Sweep: {OVERALL_STATUS} ({passed}/{total} chains passed)

| Chain            | Status  | Publish (ms) | Projection (ms) |
|------------------|---------|--------------|------------------|
| registration     | pass    |         12.3 |            234.5 |
| pattern_learning | pass    |         11.1 |            345.6 |
| delegation       | pass    |         10.5 |            456.7 |
| routing          | pass    |         11.8 |            234.1 |
| evaluation       | pass    |         12.0 |            345.2 |

Sweep ID: {sweep_id}
Evidence: .onex_state/golden-chain-sweep/{date}/{sweep_id}/sweep_results.json
```

Overall status:
- `PASS`: All chains passed
- `PARTIAL`: Some chains passed, some failed/skipped
- `FAIL`: No chains passed

---

## Failure Modes

| Failure | Behavior |
|---------|----------|
| Kafka unavailable | Chain shows `ERROR` with publish failure |
| omnidash consumer not running | Chain shows `TIMEOUT` (no projected row appears) |
| DB unreachable | Chain shows `ERROR` with DB connection failure |
| Assertion mismatch | Chain shows `FAIL` with per-field assertion details |
| Cleanup fails | Warning logged, does not affect chain status |
| Malformed contract chain metadata | Log warning, SKIP chain, report as SKIP not PASS |

---

## Dry-Run Behavior

When `--dry-run` is set:
- Resolve chain definitions and print the chain table
- Validate environment connectivity
- Do NOT publish synthetic events
- Do NOT poll database
- Report all chains as SKIP with reason "dry-run mode"
- Still write results to state directory (with dry_run: true marker)
