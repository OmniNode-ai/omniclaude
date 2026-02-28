# golden-path-validate

**Ticket:** OMN-2976
**Repo:** omniclaude

## Purpose

Executes a golden path event chain test using real Kafka/Redpanda. Given a
`golden_path` declaration, the skill:

1. Warm-subscribes to the output topic (before producing — avoids the race where
   the event arrives before the consumer is ready)
2. Emits a fixture to the input topic with an injected `correlation_id`
3. Polls the output topic for a matching event (filtered by `correlation_id`)
4. Validates field assertions against the matched event payload
5. Optionally validates the event against a Pydantic schema (`schema_name`)
6. Writes an unsigned evidence artifact to disk

## Entrypoint

```bash
plugins/onex/skills/golden-path-validate/run-golden-path <decl-json-or-file>
```

## Declaration Format

```json
{
    "node_id": "node_my_compute",
    "ticket_id": "OMN-2976",
    "input": {
        "topic": "onex.cmd.my_node.v1",
        "fixture": {"event_type": "process", "payload": {"key": "value"}}
    },
    "output": {
        "topic": "onex.evt.my_node.v1"
    },
    "timeout_ms": 10000,
    "assertions": [
        {"field": "status", "op": "eq", "expected": "ok"},
        {"field": "latency_ms", "op": "lte", "expected": 1000}
    ],
    "schema_name": "omnibase_core.models.model_my_event.ModelMyEvent"
}
```

### Assertion Operators

| Operator | Semantics |
|----------|-----------|
| `eq` | actual == expected |
| `neq` | actual != expected |
| `gte` | actual >= expected |
| `lte` | actual <= expected |
| `in` | actual in expected (expected is a list) |
| `contains` | expected in actual (actual is a list or string) |

### schema_name handling

| Condition | `schema_validation_status` |
|-----------|---------------------------|
| `schema_name` absent | `not_declared` |
| Present but not importable | `skipped` (WARN logged) |
| Present, importable, event valid | `pass` |
| Present, importable, event invalid | `fail` |

## Evidence Artifact

**Path:** `~/.claude/golden-path/{YYYY-MM-DD}/{run_id}/{node_id}.json`

The `YYYY-MM-DD` is extracted from `emitted_at` — used by `close-day` to detect
today's runs.

**Fields:**

| Field | Description |
|-------|-------------|
| `node_id` | Identifier for the node under test |
| `ticket_id` | Linear ticket ID |
| `run_id` | Unique run identifier (uuid4-based) |
| `emitted_at` | ISO-8601 timestamp when fixture was emitted |
| `status` | Overall result: `pass` \| `fail` \| `timeout` |
| `input_topic` | Kafka topic the fixture was published to |
| `output_topic` | Kafka topic polled for the output event |
| `latency_ms` | Milliseconds between emit and matching event receipt; `-1` on timeout |
| `correlation_id` | UUID injected into fixture and used to filter output events |
| `consumer_group_id` | Kafka consumer group used during this run |
| `schema_validation_status` | `pass` \| `fail` \| `skipped` \| `not_declared` |
| `assertions` | Per-assertion results: `field`, `op`, `expected`, `actual`, `passed` |
| `raw_output_preview` | First 500 chars of the raw output event JSON; empty on timeout |
| `kafka_offset` | Partition offset of the matching output event; `-1` on timeout |
| `kafka_timestamp_ms` | Broker-assigned timestamp of the output event; `-1` on timeout |

## Kafka Configuration

| Context | `KAFKA_BOOTSTRAP_SERVERS` |
|---------|--------------------------|
| Host scripts | `192.168.86.200:29092` <!-- onex-allow-internal-ip --> |
| Docker services | `omnibase-infra-redpanda:9092` |

The runner reads `KAFKA_BOOTSTRAP_SERVERS` from the environment, defaulting to
`192.168.86.200:29092`. <!-- onex-allow-internal-ip -->

## Python API

```python
from plugins.onex.skills.golden_path_validate.golden_path_runner import GoldenPathRunner

runner = GoldenPathRunner(
    bootstrap_servers="192.168.86.200:29092",  # onex-allow-internal-ip
    artifact_base_dir="/custom/artifacts",
)
artifact = await runner.run(decl)
print(artifact.status)  # pass | fail | timeout
```

## Running Unit Tests

```bash
cd /path/to/omniclaude
uv run pytest tests/unit/skills/test_golden_path_validate.py -v -m unit
```
