# ADR-001: Event Fan-Out Strategy and App-Owned Event Catalogs

## Document Metadata

| Field | Value |
|-------|-------|
| **Document Type** | Architecture Decision Record (ADR) |
| **Document Number** | ADR-001 |
| **Status** | IMPLEMENTED |
| **Created** | 2026-02-09 |
| **Last Updated** | 2026-02-09 |
| **Author** | Jonah |
| **Related Issues** | [OMN-1944](https://linear.app/omninode/issue/OMN-1944), [OMN-1972](https://linear.app/omninode/issue/OMN-1972), [OMN-1735](https://linear.app/omninode/issue/OMN-1735), [OMN-1892](https://linear.app/omninode/issue/OMN-1892) |
| **Implementation PRs** | omnibase_infra #275 (remove defaults), omniclaude4 branch `jonah/omn-1892-add-feedback-loop-with-guardrails` |
| **Related ADR** | omnibase_core [ADR-005](https://github.com/OmniNode-ai/omnibase_core/blob/main/docs/decisions/ADR-005-core-infra-dependency-boundary.md) - Core-Infra Dependency Boundary |

---

## Document Purpose

This Architecture Decision Record documents two interrelated decisions about the omniclaude event pipeline:

1. **App-owned event catalogs**: The application repository is the sole source of truth for its event schemas. Infrastructure provides generic publish primitives, not application-specific event definitions.
2. **Fan-out at daemon level**: A single semantic event can publish to multiple Kafka topics with per-target payload transformations, enabling clean separation of intelligence (CMD) and observability (EVT) concerns.

**Why this document exists**:
- To establish the invariant that infra must not ship app-specific event definitions
- To document the fan-out pattern and when to apply it (CMD vs EVT semantics)
- To record the removal of legacy topic names and the migration path
- To prevent regression back to "infra knows app stuff"

**When to reference this document**:
- When adding a new event type to the registry
- When deciding whether an event needs fan-out (CMD + EVT)
- When modifying the publisher's topic resolution logic
- When evaluating whether infra should contain application-specific code

---

## Document Status and Maintenance

**Current Status**: IMPLEMENTED - Publisher rewired, fan-out active, infra defaults removed

**Maintenance Model**: This is a **policy document** establishing architectural invariants. Updates should occur when:
- New fan-out events are added (update the fan-out table)
- The CMD/EVT topic semantics evolve
- New application repos need their own event catalogs

**Supersession**: This document is NOT superseded. The app-owned catalog and fan-out principles are foundational.

---

## Target Audience

| Audience | Use Case |
|----------|----------|
| **Hook Developers** | Adding new event types or modifying existing emit behavior |
| **Consumer Developers** | Understanding which topics to subscribe to and what payload shape to expect |
| **Infra Developers** | Knowing what NOT to add to omnibase_infra's EventRegistry |
| **Dashboard/Observability Engineers** | Knowing which EVT topics carry sanitized data |
| **Code Reviewers** | Evaluating PRs that touch event routing or topic definitions |

---

## Executive Summary

The omniclaude event pipeline was coupled to `omnibase_infra`'s `EventRegistry`, which hardcoded 12 application-specific event definitions. This created version drift, prevented fan-out, and violated the principle that infrastructure should be generic.

**Decision**: The application repository (`omniclaude4`) owns its event catalog via a local `EVENT_REGISTRY` dict. The emit daemon uses fan-out rules to publish a single event to multiple topics with per-target transforms. Infrastructure provides only `EventBusKafka.publish()` — the generic publish primitive.

Two events now fan-out to both CMD and EVT topics:
- `prompt.submitted` → intelligence (full prompt) + observability (sanitized 100-char preview)
- `session.outcome` → intelligence (feedback loop) + observability (dashboards/monitoring)

Legacy topic `agent-routing-decisions` was removed in favor of `onex.evt.omniclaude.routing-decision.v1`.

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Background](#background)
3. [Decision](#decision)
4. [Implementation](#implementation)
5. [Trade-offs](#trade-offs)
6. [References](#references)

---

## Problem Statement

Before this change, the omniclaude event pipeline had three structural problems:

### 1. Infra shipped app-specific event definitions

`omnibase_infra`'s `EventRegistry._register_defaults()` hardcoded 12 omniclaude-specific event types. This meant:
- Infra knew about omniclaude semantics it had no business knowing
- Adding a new event type required touching infra (wrong repo)
- The installed infra package, infra source, and local registry all had different event counts (4, 12, 17)

### 2. No fan-out support

Infra's `EventRegistry` mapped one event type → one topic. `prompt.submitted` needed to publish to *two* topics with different payloads:
- Full prompt to intelligence (CMD topic, restricted access)
- Sanitized 100-char preview to observability (EVT topic, broad access)

This was impossible without forking the registry.

### 3. Mixed CMD/EVT semantics

`session.outcome` was routed only to `onex.cmd.omniintelligence.session-outcome.v1`. Dashboards and monitoring had no visibility into session outcomes — they'd need to reverse-engineer intelligence-side artifacts. The event is simultaneously an intelligence input *and* an observability fact; the single-topic design forced a false choice.

**Questions resolved**:
- Should infra contain application-specific event definitions? **No.**
- Should the daemon support publishing one event to multiple topics? **Yes.**
- Should `session.outcome` be available to both intelligence and observability? **Yes.**

---

## Background

### ONEX Topic Naming Convention

```
onex.{kind}.{producer}.{event-name}.v{n}
```

| Kind | Semantics | Access |
|------|-----------|--------|
| `cmd` | "Do something with this" — intended for a specific downstream system | Restricted |
| `evt` | "This happened" — facts about what happened, safe to observe broadly | Broad |

Topics are **realm-agnostic** (OMN-1972). No environment prefix (`dev.`, `prod.`). The `TopicBase` StrEnum value IS the wire topic.

### Fan-Out Architecture

```
Hook Script
    |
    | emit_daemon_send(event_type="prompt.submitted", payload={...})
    v
Emit Daemon
    |
    | EVENT_REGISTRY lookup -> EventRegistration with [FanOutRule, FanOutRule]
    |
    +----> FanOutRule 1: CMD topic (passthrough)       -> intelligence consumers
    +----> FanOutRule 2: EVT topic (transform applied)  -> dashboards, monitoring
```

Each `FanOutRule` specifies:
- `topic_base: TopicBase` — target topic (bare ONEX suffix = wire topic)
- `transform: PayloadTransform | None` — optional callable applied before publishing
- `description: str` — human-readable purpose

### Prior State

| Component | Event Count | Fan-Out | Source of Truth |
|-----------|-------------|---------|-----------------|
| Infra `EventRegistry` (installed) | 4 | No | Stale |
| Infra `EventRegistry` (source) | 12 | No | Conflicting |
| omniclaude4 local `EVENT_REGISTRY` | 14 | Yes | Canonical |

---

## Decision

### 1. App owns its event catalog

The application repository is the **sole source of truth** for its event schemas.

**omniclaude4 provides** (in `src/omniclaude/hooks/event_registry.py`):
- `EVENT_REGISTRY` — static dict mapping `event_type` → `EventRegistration`
- Fan-out rules with per-target transforms
- Partition key configuration
- Required field validation
- Metadata injection (`_inject_metadata()` in the publisher)

**omnibase_infra provides** (generic primitives only):
- `EventBusKafka.publish(topic, key, value, headers)` — publishes exactly what it receives
- `TopicResolver` — pass-through validation (OMN-1972)
- No application-specific event catalogs
- No `_register_defaults()`

**Invariant**: If you `grep` infra for "omniclaude", you should find zero event definitions.

### 2. Fan-out at daemon level

One semantic event can publish to multiple Kafka topics with different payload transformations.

**Current fan-out events**:

| Event Type | CMD Target | EVT Target | EVT Transform |
|------------|-----------|------------|---------------|
| `prompt.submitted` | `onex.cmd.omniintelligence.claude-hook-event.v1` | `onex.evt.omniclaude.prompt-submitted.v1` | `transform_for_observability` (redacts secrets, truncates to 100 chars) |
| `session.outcome` | `onex.cmd.omniintelligence.session-outcome.v1` | `onex.evt.omniclaude.session-outcome.v1` | Passthrough (no sensitive content) |

All other event types (12 of 14) are single-target with passthrough.

**When to add fan-out**: An event needs fan-out when it is simultaneously:
- An input to a specific downstream system (CMD) — e.g., intelligence feedback loop
- A fact that dashboards/monitoring should observe (EVT) — e.g., session outcomes

If an event is only observed (not acted upon), a single EVT target suffices. If it's only a command (not worth observing), a single CMD target suffices.

### 3. CMD vs EVT topic naming

| Kind | Topic Format | Semantics |
|------|-------------|-----------|
| **CMD** | `onex.cmd.{consumer}.{event}.v{n}` | Named by consumer. "Do something with this." Restricted access. |
| **EVT** | `onex.evt.{producer}.{event}.v{n}` | Named by producer. "This happened." Broad access. |

The same `event_type` can legitimately map to both CMD and EVT via fan-out. This is not duplication — each target serves a different contract with different access semantics.

### 4. Legacy topic removal

`ROUTING_DECISIONS = "agent-routing-decisions"` removed from `TopicBase`. The ONEX-canonical replacement `ROUTING_DECISION = "onex.evt.omniclaude.routing-decision.v1"` is the sole target for `routing.decision` events.

**Resolved**: `consumers/agent_actions_consumer.py` has been migrated to subscribe to `"onex.evt.omniclaude.routing-decision.v1"` in the same PR.

---

## Implementation

### Files Modified

| File | Change |
|------|--------|
| `src/omniclaude/hooks/topics.py` | +3 TopicBase entries (`ROUTING_DECISION`, `NOTIFICATION_BLOCKED`, `NOTIFICATION_COMPLETED`), renamed `SESSION_OUTCOME` → `SESSION_OUTCOME_CMD` + `SESSION_OUTCOME_EVT`, removed `ROUTING_DECISIONS` |
| `src/omniclaude/hooks/event_registry.py` | +6 EventRegistrations (14 total), `session.outcome` upgraded to dual fan-out |
| `src/omniclaude/publisher/embedded_publisher.py` | Replaced infra `EventRegistry` with local registry imports, added `_inject_metadata()`, fan-out loop in `_handle_emit()` |
| `plugins/onex/hooks/lib/hook_event_adapter.py` | `TopicBase.ROUTING_DECISIONS` → `TopicBase.ROUTING_DECISION` |
| `tests/publisher/test_embedded_publisher.py` | Removed all `patch.object(publisher._registry, ...)` mocks |
| `tests/hooks/test_topics.py` | Removed `ROUTING_DECISIONS` assertions |
| `tests/hooks/test_event_registry.py` | +4 tests for session.outcome fan-out and routing.decision topic |
| `tests/hooks/test_emit_client_wrapper.py` | Updated docstring referencing legacy topic |

### Infra Changes (PR #275)

| File | Change |
|------|--------|
| `omnibase_infra4/.../event_registry.py` | Deleted `_register_defaults()` method entirely |
| `omnibase_infra4/.../test_event_registry.py` | Removed 60+ tests asserting 12 default registrations |

### Verification

```bash
# All 14 event types registered with correct fan-out
.venv/bin/python3 -c "
from omniclaude.hooks.event_registry import EVENT_REGISTRY
for et in sorted(EVENT_REGISTRY.keys()):
    reg = EVENT_REGISTRY[et]
    targets = [str(r.topic_base) for r in reg.fan_out]
    print(f'  {et:25s} -> {targets}')
print(f'Total: {len(EVENT_REGISTRY)} event types')
"

# No infra EventRegistry import in publisher
grep -c 'from omnibase_infra.*event_registry' src/omniclaude/publisher/embedded_publisher.py
# Expected: 0

# Tests pass
.venv/bin/pytest tests/hooks/test_event_registry.py tests/hooks/test_topics.py tests/publisher/test_embedded_publisher.py -v
```

---

## Trade-offs

### Accepted Trade-offs

1. **Breaking change for other working copies**
   - **Impact**: `omniclaude2` and `omniclaude3` still import `EventRegistry` from infra. They will fail when they pull updated infra (PR #275).
   - **Rationale**: Each working copy is on a separate ticket. They adopt the infra change when they're ready.
   - **Mitigation**: The fix is straightforward — switch to local registry, same as omniclaude4.

2. **Consumer migration** *(resolved)*
   - **Impact**: `consumers/agent_actions_consumer.py` migrated to `"onex.evt.omniclaude.routing-decision.v1"` in the same PR.
   - **Rationale**: Dual-publishing to legacy topics adds complexity for limited benefit.
   - **Mitigation**: Complete — consumer and skills updated to ONEX topic.

3. **Static registry (no dynamic registration)**
   - **Impact**: Adding event types requires code changes, not runtime configuration.
   - **Rationale**: The event catalog is known at code time. Dynamic registration adds complexity for a problem that doesn't exist.
   - **Mitigation**: The static dict is trivial to extend.

### Benefits Realized

1. **Single source of truth**: 14 event types defined once, in one file, in the app repo
2. **No version drift**: No infra package to go stale
3. **Fan-out support**: One event, multiple delivery targets with per-target transforms
4. **Privacy by design**: EVT topics get sanitized previews; CMD topics get full payloads
5. **Clean topic semantics**: CMD for commands, EVT for facts — not conflated
6. **Stronger test coverage**: Tests exercise the real registry instead of mocking infra's

---

## Alternatives Considered

### A. Keep event definitions in infra with register_batch

Apps would call `registry.register_batch(defs)` at startup. **Rejected** because:
- Still couples the registry mechanism to infra's class design
- omniclaude4 needs richer semantics (fan-out, transforms) that infra doesn't support
- Adds a runtime registration step for something that's static

### B. Dual-publish to legacy + ONEX topics during migration

Temporarily publish `routing.decision` to both `agent-routing-decisions` and `onex.evt.omniclaude.routing-decision.v1`. **Rejected** because:
- Adds complexity for a topic with limited active consumers
- Consumers should migrate, not be accommodated indefinitely
- Legacy topic name violates ONEX naming convention

### C. Add fan-out to infra's EventRegistry

Extend infra with `FanOutRule` support. **Rejected** because:
- Fan-out is an application concern, not an infrastructure primitive
- Only omniclaude needs it today
- Infra should stay generic — "publish to topic X" is the right abstraction level

---

## References

### Related Documentation

- **[ADR-005 (omnibase_core)](https://github.com/OmniNode-ai/omnibase_core/blob/main/docs/decisions/ADR-005-core-infra-dependency-boundary.md)**: Core-Infra Dependency Boundary — establishes the principle that core/infra provides abstractions, not application content
- **[Handoff Doc](../handoff-publisher-topic-resolution.md)**: Detailed handoff notes from the publisher rewiring work

### Related Code

- **Event Registry**: `src/omniclaude/hooks/event_registry.py` — 14 event types with fan-out rules
- **Topic Definitions**: `src/omniclaude/hooks/topics.py` — `TopicBase` StrEnum
- **Publisher**: `src/omniclaude/publisher/embedded_publisher.py` — fan-out loop in `_handle_emit()`
- **Infra PR**: omnibase_infra #275 — removed `_register_defaults()` from `EventRegistry`

### Related Issues

- **OMN-1944**: Port emit daemon from omnibase_infra to omniclaude
- **OMN-1972**: TopicResolver — realm-agnostic topics
- **OMN-1735**: Session outcome feedback loop
- **OMN-1892**: Routing feedback events with guardrails

---

## Revision History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-02-09 | 1.0 | Jonah | Initial ADR: app-owned catalogs, fan-out strategy, legacy topic removal |
