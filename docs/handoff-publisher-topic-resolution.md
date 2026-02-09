# Handoff: Publisher Topic Resolution (OMN-1944 follow-up)

## Status
- Publisher rewired: DONE
- Topic format corrected: DONE
- Event registry gaps filled: DONE
- Cross-repo mismatch reconciliation: TODO

## What Was Done

### 1. Publisher Rewired to Local Registry
- `src/omniclaude/publisher/embedded_publisher.py` no longer imports `EventRegistry` from `omnibase_infra`
- Uses local `event_registry.py` for fan-out rules, validation, partition keys
- Uses local `_inject_metadata()` for correlation_id, causation_id, emitted_at, schema_version
- Fan-out support: one event type can publish to multiple topics with payload transforms (e.g., `prompt.submitted` -> intelligence topic + sanitized observability topic)

### 2. Topics Are Bare ONEX Suffixes
- Wire topic = TopicBase enum value directly (e.g., `onex.evt.omniclaude.session-started.v1`)
- NO environment prefix (`dev.`, `prod.`, etc.) -- realm-agnostic per OMN-1972 TopicResolver
- `build_topic(prefix, base)` in `topics.py` is NOT used by the publisher
- `build_full_topic(env, namespace, suffix)` in omnibase_infra is dead code with zero production callers

### 3. Six Missing Event Registrations Added
Added to `src/omniclaude/hooks/event_registry.py`:
- `context.utilization` -> `onex.evt.omniclaude.context-utilization.v1`
- `agent.match` -> `onex.evt.omniclaude.agent-match.v1`
- `latency.breakdown` -> `onex.evt.omniclaude.latency-breakdown.v1`
- `routing.decision` -> `onex.evt.omniclaude.routing-decision.v1`
- `notification.blocked` -> `onex.evt.omniclaude.notification-blocked.v1`
- `notification.completed` -> `onex.evt.omniclaude.notification-completed.v1`

Three new TopicBase entries added to `src/omniclaude/hooks/topics.py`:
- `ROUTING_DECISION`, `NOTIFICATION_BLOCKED`, `NOTIFICATION_COMPLETED`

### 4. Tests Updated
- `tests/publisher/test_embedded_publisher.py`: 4 tests updated to remove mocks of deleted `self._registry`

## Files Modified
| File | Change |
|------|--------|
| `src/omniclaude/hooks/topics.py` | +3 TopicBase entries |
| `src/omniclaude/hooks/event_registry.py` | +6 EventRegistrations (14 total) |
| `src/omniclaude/publisher/embedded_publisher.py` | Replaced infra EventRegistry with local registry + fan-out; bare suffix topics |
| `tests/publisher/test_embedded_publisher.py` | 4 tests updated |

## Architectural Principle Established

**The application repo (omniclaude4) is the sole source of truth for its event schemas.**

omnibase_infra should provide ONLY generic primitives:
- `EventBusKafka.publish(topic, key, value, headers)` -- publishes exactly what it's given
- `TopicResolver` -- pass-through validation (OMN-1972)
- Generic envelope/partitioning helpers
- Zero application-specific event catalogs

omnibase_infra4 currently violates this by having `EventRegistry._register_defaults()` with 12 hardcoded omniclaude event types. This should be removed from infra -- it belongs in the application repo.

## Remaining Mismatches (TODO)

### Mismatch 1: `session.outcome` topic (evt vs cmd)

| Source | Topic |
|--------|-------|
| omnibase_infra4 EventRegistry | `onex.evt.omniclaude.session-outcome.v1` |
| omniclaude4 TopicBase | `onex.cmd.omniintelligence.session-outcome.v1` |

**Root cause**: Different semantic intent.
- `evt` = observability/audit ("this happened")
- `cmd` = command ("do something with this") -- consumed by omniintelligence feedback loop

**Resolution options**:
1. **Fan-out** (recommended): Add both targets to `session.outcome` registration, similar to `prompt.submitted`. The `evt` target is for observability dashboards; the `cmd` target is for the intelligence feedback loop.
2. **Choose one**: If session outcome is only consumed by omniintelligence, `cmd` alone is correct. If dashboards also need it, add the `evt` target.

**Action**: Decide which consumers need session.outcome data, then update the fan-out rules in `event_registry.py` accordingly.

### Mismatch 2: `routing.decision` topic (legacy vs ONEX)

| Source | Topic |
|--------|-------|
| omnibase_infra4 EventRegistry | `agent-routing-decisions` (legacy, non-ONEX format) |
| omniclaude4 local event_registry | `onex.evt.omniclaude.routing-decision.v1` (ONEX format) |

**Root cause**: Infra still has the legacy topic name from before the ONEX migration. omniclaude4 uses the correct ONEX-canonical name.

**Resolution**:
- omniclaude4 is correct. `onex.evt.omniclaude.routing-decision.v1` follows the canonical ONEX naming.
- If any consumers still subscribe to `agent-routing-decisions`, add temporary fan-out to both topics during migration, then remove the legacy target.
- The legacy name in infra4's EventRegistry should be removed when infra is cleaned of app-specific catalogs.

### Mismatch 3: omnibase_infra4 has app-specific event catalogs (architectural violation)

**File**: `omnibase_infra4/src/omnibase_infra/runtime/emit_daemon/event_registry.py` lines 193-272

The `_register_defaults()` method hardcodes 12 omniclaude-specific event types. This creates:
- Version drift (installed infra shows 4 events, infra4 source shows 12, omniclaude4 local has 14)
- False source-of-truth confusion
- Coupling between platform infra and application semantics

**Resolution**: Remove `_register_defaults()` from infra's EventRegistry. Make EventRegistry a generic class that apps populate. The omniclaude event catalog lives only in `omniclaude4/src/omniclaude/hooks/event_registry.py`.

## How to Verify Current State

### All 14 event types registered
```bash
cd /Volumes/PRO-G40/Code/omniclaude4
.venv/bin/python3 -c "
from omniclaude.hooks.event_registry import EVENT_REGISTRY
for et in sorted(EVENT_REGISTRY.keys()):
    reg = EVENT_REGISTRY[et]
    targets = [str(r.topic_base) for r in reg.fan_out]
    print(f'  {et:25s} -> {targets}')
print(f'Total: {len(EVENT_REGISTRY)} event types')
"
```

### Publisher uses bare suffixes (no prefix)
```bash
.venv/bin/python3 -c "
from omniclaude.hooks.event_registry import get_registration
reg = get_registration('session.started')
topic = str(reg.fan_out[0].topic_base)
assert not any(topic.startswith(p) for p in ['dev.', 'prod.', 'staging.']), f'Prefixed: {topic}'
print(f'Wire topic: {topic}')
"
```

### No infra EventRegistry import in publisher
```bash
grep -c 'from omnibase_infra.*event_registry' src/omniclaude/publisher/embedded_publisher.py
# Should print: 0
```

### Tests pass
```bash
.venv/bin/pytest tests/ -v -k "event_registry or publisher or topic" --tb=short
```

## Related Tickets
- OMN-1944: Port emit daemon from omnibase_infra to omniclaude (DONE)
- OMN-1972: TopicResolver -- realm-agnostic topics (DONE in infra)
- OMN-1892: Routing feedback events (DONE -- routing.feedback, routing.skipped added)
- OMN-1889: Injection metrics events (DONE -- context.utilization, agent.match, latency.breakdown)
- OMN-1831: Notification events (DONE -- notification.blocked, notification.completed)

## Decision Log
| Decision | Rationale |
|----------|-----------|
| Bare ONEX suffixes (no env prefix) | OMN-1972 established realm-agnostic topics; `build_full_topic` is dead code |
| Local event_registry owns fan-out | Infra doesn't support fan-out; prompt.submitted needs 2 targets |
| Local `_inject_metadata` helper | Same fields as infra's version; avoids importing infra's EventRegistry |
| App repo = source of truth for event schemas | Infra should be generic; app-specific catalogs cause version drift |
