# OmniClaude Event Contract Validation Plan

**Status**: Draft v1
**Created**: 2026-02-05
**Goal**: Ensure OmniClaude's produced events match OmniIntelligence's consumer expectations with end-to-end validation

---

## Context

OmniClaude is a **producer adapter** running inside Claude Code's execution context. It is NOT a service.

**OmniClaude's job**:
- Marshal event payloads
- Choose correct topic and schema version
- Emit via EmitClient/EmitDaemon
- Handle failure policy (best effort, bounded buffer)

**OmniClaude does NOT**:
- Run RuntimeHostProcess
- Consume events
- Project state
- Provide introspection endpoints

The consumer runtime is OmniIntelligence's responsibility.

---

## 1. Schema Contract Verification

### 1.1 Producer → Consumer Schema Alignment

| OmniClaude Produces | Topic | OmniIntelligence Consumes |
|---------------------|-------|---------------------------|
| `ModelHookPromptSubmittedPayload` | `onex.cmd.omniintelligence.claude-hook-event.v1` | `NodeClaudeHookEventEffect` |
| `ModelHookSessionOutcomePayload` | `onex.cmd.omniintelligence.session-outcome.v1` | `NodePatternFeedbackEffect` |
| `ModelHookToolExecutedPayload` | `onex.cmd.omniintelligence.tool-content.v1` | (TBD consumer) |

### 1.2 Verification Checklist

**P1.1**: Compare `ModelHookPromptSubmittedPayload` (omniclaude) vs expected input schema of `NodeClaudeHookEventEffect` (omniintelligence)

- [ ] Field names match exactly
- [ ] Field types match (including Optional vs required)
- [ ] Enum values match (if any)
- [ ] Nested model schemas align
- [ ] Timestamp format consistent (ISO-8601, timezone-aware)
- [ ] UUID format consistent (string vs UUID type)

**P1.2**: Compare `ModelHookSessionOutcomePayload` vs `NodePatternFeedbackEffect` input

- [ ] Same field alignment checks as above

**P1.3**: Add schema version to payloads

Producer side (omniclaude):
```python
class ModelHookPromptSubmittedPayload(BaseModel):
    schema_version: str = "1.0.0"  # Add if missing
    # ... existing fields
```

Consumer side (omniintelligence):
```python
def handle_claude_hook_event(payload: dict) -> None:
    schema_version = payload.get("schema_version", "unknown")
    if schema_version != EXPECTED_SCHEMA_VERSION:
        logger.warning(f"Schema mismatch: got {schema_version}, expected {EXPECTED_SCHEMA_VERSION}")
```

### 1.3 Schema Hash Logging

Add to producer emit path:
```python
import hashlib
import json

def compute_schema_hash(model_class: type[BaseModel]) -> str:
    schema_json = json.dumps(model_class.model_json_schema(), sort_keys=True)
    return hashlib.sha256(schema_json.encode()).hexdigest()[:12]

# Log on emit
logger.debug(f"Emitting {topic} with schema hash {compute_schema_hash(PayloadModel)}")
```

---

## 2. End-to-End Integration Test Harness

### 2.1 Test Producer CLI

Create a minimal CLI that emits a test event identical to real hook output:

**Location**: `tests/integration/e2e/test_producer_cli.py`

```python
"""
Test producer that emits a real OmniClaude event to Kafka.

Usage:
    python -m tests.integration.e2e.test_producer_cli emit-prompt
    python -m tests.integration.e2e.test_producer_cli emit-outcome
"""
import asyncio
from uuid import uuid4
from datetime import datetime, timezone

from omnibase_infra.event_bus.event_bus_kafka import EventBusKafka
from omniclaude.hooks.schemas import ModelHookPromptSubmittedPayload

async def emit_test_prompt_event():
    bus = EventBusKafka.default()
    await bus.start()

    payload = ModelHookPromptSubmittedPayload(
        session_id=str(uuid4()),
        prompt_preview="Test prompt for e2e validation",
        prompt_length=35,
        working_directory="/test/path",
        correlation_id=uuid4(),
        emitted_at=datetime.now(timezone.utc),
    )

    topic = "dev.onex.cmd.omniintelligence.claude-hook-event.v1"
    await bus.publish(topic, key=payload.session_id.encode(), value=payload.model_dump_json().encode())

    print(f"Emitted test event to {topic}")
    print(f"  correlation_id: {payload.correlation_id}")
    print(f"  session_id: {payload.session_id}")

    await bus.close()

if __name__ == "__main__":
    asyncio.run(emit_test_prompt_event())
```

### 2.2 Consumer Verification Test

**Location**: `tests/integration/e2e/test_consumer_receives.py`

```python
"""
Verify OmniIntelligence consumes and processes the test event.

Prerequisites:
- OmniIntelligence runtime is running
- Kafka is available
- PostgreSQL is available (for side-effect verification)

Usage:
    pytest tests/integration/e2e/test_consumer_receives.py -v
"""
import pytest
import asyncio
from uuid import UUID

@pytest.mark.integration
@pytest.mark.e2e
async def test_prompt_event_consumed_and_processed(
    kafka_bus,
    postgres_connection,
    test_correlation_id: UUID,
):
    """
    1. Emit test event with known correlation_id
    2. Wait for processing evidence:
       - Database row created
       - OR follow-up event emitted
       - OR metrics incremented
    3. Assert expected side effects
    """
    # Emit test event
    await emit_test_prompt_event(correlation_id=test_correlation_id)

    # Wait for processing (with timeout)
    async def check_processing_complete():
        # Option A: Check database for pattern extraction result
        result = await postgres_connection.fetchrow(
            "SELECT * FROM processing_log WHERE correlation_id = $1",
            str(test_correlation_id),
        )
        return result is not None

    # Poll with timeout
    for _ in range(30):  # 30 seconds max
        if await check_processing_complete():
            break
        await asyncio.sleep(1)
    else:
        pytest.fail(f"Event with correlation_id {test_correlation_id} was not processed within timeout")

    # Assert side effects
    # (specific assertions depend on what NodeClaudeHookEventEffect does)
```

### 2.3 Test Execution Flow

```
┌─────────────────┐     ┌─────────────┐     ┌─────────────────┐     ┌──────────────┐
│  Test Producer  │────▶│   Kafka     │────▶│ OmniIntelligence│────▶│  PostgreSQL  │
│  (test CLI)     │     │   Topic     │     │    Runtime      │     │  (side effect)│
└─────────────────┘     └─────────────┘     └─────────────────┘     └──────────────┘
                                                    │
                                                    ▼
                                            ┌──────────────┐
                                            │  Test Assert │
                                            │  (verify DB) │
                                            └──────────────┘
```

---

## 3. Optional: Producer Presence Event

If the platform needs to know OmniClaude is active:

### 3.1 Presence Event Schema

```python
class ModelProducerPresenceEvent(BaseModel):
    """Emitted once on first hook execution or session start."""

    producer_id: str = "omniclaude"
    producer_version: str
    plugin_root: str  # ${CLAUDE_PLUGIN_ROOT}
    capabilities: list[str]  # ["prompt-submitted", "tool-executed", "session-outcome"]
    publish_topics: list[str]
    emitted_at: datetime

    model_config = ConfigDict(frozen=True)
```

### 3.2 Emission Trigger

Emit on first SessionStart hook execution per process:

```python
# In session-start handler
_presence_emitted = False

async def emit_presence_if_first_run():
    global _presence_emitted
    if _presence_emitted:
        return

    await emit_producer_presence()
    _presence_emitted = True
```

### 3.3 Topic

```
onex.evt.platform.producer-presence.v1
```

**Priority**: P3 (optional - only if dashboard needs it)

---

## 4. Tasks

### Phase 1: Schema Verification (P1)

| ID | Task | Effort |
|----|------|--------|
| P1.1 | Compare `ModelHookPromptSubmittedPayload` vs `NodeClaudeHookEventEffect` input schema | M |
| P1.2 | Compare `ModelHookSessionOutcomePayload` vs `NodePatternFeedbackEffect` input schema | S |
| P1.3 | Add `schema_version` field to all emitted payloads | S |
| P1.4 | Add schema hash logging to emit path | S |
| P1.5 | Document schema alignment in shared contract doc | M |

### Phase 2: E2E Test Harness (P2)

| ID | Task | Effort |
|----|------|--------|
| P2.1 | Create test producer CLI | M |
| P2.2 | Create consumer verification test | M |
| P2.3 | Add test fixtures matching real payloads | S |
| P2.4 | Add CI job for e2e test (requires infra) | L |
| P2.5 | Document test execution prerequisites | S |

### Phase 3: Producer Presence (P3 - Optional)

| ID | Task | Effort |
|----|------|--------|
| P3.1 | Define `ModelProducerPresenceEvent` schema | S |
| P3.2 | Emit presence on first SessionStart | S |
| P3.3 | Document presence event in platform docs | S |

---

## 5. Exit Criteria

**Phase 1 Complete When**:
- [ ] All schema fields verified to match between producer and consumer
- [ ] `schema_version` present in all payloads
- [ ] Schema hash logged on emit

**Phase 2 Complete When**:
- [ ] Test producer CLI can emit to Kafka
- [ ] Consumer test can verify processing occurred
- [ ] E2E test passes in CI (when infra available)

**Phase 3 Complete When** (if implemented):
- [ ] Presence event emitted on first session
- [ ] Platform can display active producers

---

## Related Documentation

- [INTELLIGENCE_INFRA_INTEGRATION_PLAN.md](/Volumes/PRO-G40/Code/omniintelligence2/docs/planning/INTELLIGENCE_INFRA_INTEGRATION_PLAN.md) - Consumer runtime wiring (the blocking work)
- [CLAUDE.md](../../CLAUDE.md) - OmniClaude architecture and hook invariants
- [topics.py](../../src/omniclaude/hooks/topics.py) - Topic definitions
- [schemas.py](../../src/omniclaude/hooks/schemas.py) - Event schema definitions
