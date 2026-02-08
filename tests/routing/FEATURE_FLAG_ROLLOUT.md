# Feature Flag Rollout Plan: USE_ONEX_ROUTING_NODES

**Ticket**: OMN-1928 (P5 Validation)
**Parent**: OMN-1922 (Extract Agent Routing to ONEX Nodes)
**Date**: 2026-02-07

---

## Overview

The `USE_ONEX_ROUTING_NODES` feature flag gates the transition from the
legacy `AgentRouter` routing path to the ONEX node-based routing path
(`HandlerRoutingDefault` + `HandlerRoutingEmitter` + `HandlerHistoryPostgres`).

This document describes the rollout strategy, validation gates, and
rollback procedure.

---

## Current State

| Component | Status |
|-----------|--------|
| P0: Golden Corpus + Regression Harness | Complete (OMN-1923) |
| P1: Strongly-Typed Routing Models | Complete (OMN-1924) |
| P2+P3: ONEX Node Extraction | Complete (OMN-1926) |
| P4: Wrapper Update | Complete (OMN-1927) |
| P5: Validation (this ticket) | In Progress (OMN-1928) |

---

## Rollout Phases

### Phase 1: Developer Testing (Current)

**Who**: Individual developers
**How**: `export USE_ONEX_ROUTING_NODES=true` in local `.env`
**Duration**: 1-2 weeks
**Validation**:
- All P5 tests pass (golden corpus, performance, integration)
- Manual spot-checking of routing decisions in `~/.claude/hooks.log`
- No regressions in daily development workflow

**Rollback**: Remove or set `USE_ONEX_ROUTING_NODES=false` in `.env`

### Phase 2: CI Enablement

**Who**: All contributors via CI
**How**: Add `USE_ONEX_ROUTING_NODES=true` to GitHub Actions env
**Duration**: 1 sprint
**Validation**:
- CI pipeline passes with flag enabled (golden corpus + integration tests)
- No test regressions in CI or local runs
- Performance benchmarks are **local-only** (`pytest.mark.skipif(CI)`) — run manually before advancing to Phase 3
- CI does NOT validate latency budgets; this is explicitly deferred to local dev verification

**Rollback**: Remove env var from CI configuration

### Phase 3: Default Enablement

**Who**: All users
**How**: Change default from `false` to `true` in `route_via_events_wrapper.py`
**Duration**: 1 sprint (monitoring)
**Validation**:
- Routing decision metrics stable (via Kafka observability)
- No increase in fallback rate
- No latency regression in production hooks

**Rollback**: Revert default back to `false`

### Phase 4: Legacy Path Removal

**Who**: Codebase cleanup
**How**: Remove legacy `AgentRouter.route()` direct-call path from wrapper
**When**: After Phase 3 runs stable for 2+ weeks
**Validation**:
- All tests pass without legacy path
- Golden corpus still passes through ONEX path only

**Rollback**: This is a one-way door. If issues are found, revert the
commit that removed the legacy path.

---

## Validation Gates (P5 Required)

Each gate MUST pass before advancing to the next rollout phase.

### Gate 1: Legacy Regression Harness

- **Requirement**: 100% match within tolerance for all 104 corpus entries
- **Test**: `tests/routing/test_regression_harness.py`
- **Tolerance**: confidence +/-0.05, selected_agent exact, routing_policy exact
- **Note**: This gate validates the legacy `AgentRouter` path against the golden corpus. The ONEX path cross-validation is Gate 4.

### Gate 2: Performance Budget

- **Requirement**: p95 <100ms, p50 <50ms (cold cache)
- **Test**: `tests/routing/test_performance_validation.py`
- **Environment**: Standard dev machine

### Gate 3: Integration Tests

- **Requirement**: All integration tests pass with mocked Kafka
- **Test**: `tests/integration/test_onex_kafka_integration.py`
- **Tech debt**: Real Kafka validation deferred (see below)

### Gate 4: ONEX Cross-Validation

- **Requirement**: ONEX and legacy paths agree on >=80% of agent selections (`_MIN_AGREEMENT_RATIO`) and >=90% of routing policies
- **Tests**:
  - `test_onex_golden_corpus.py::TestOnexLegacyCrossValidation::test_agreement_above_minimum_threshold` (agent agreement)
  - `test_onex_golden_corpus.py::TestOnexLegacyCrossValidation::test_policy_agreement_is_high` (policy agreement)
  - `test_onex_golden_corpus.py::TestOnexBehavioralInvariants::test_explicit_agent_requests_always_match` (explicit-request invariant)
- **Note**: Divergences expected due to ONEX TriggerMatcher enhancements (tiered fuzzy thresholds, HIGH_CONFIDENCE_TRIGGERS)

---

## Tech Debt

### Mocked Kafka (Known Limitation)

**Current state**: All Kafka interactions in P5 tests are mocked. The
emit daemon is replaced with a test double that captures payloads.

**What is NOT tested**:
- Event serialization to Kafka wire format
- Topic partitioning and consumer group coordination
- End-to-end event delivery (hook -> daemon -> Kafka -> consumer)
- Event schema validation against Redpanda Schema Registry

**Required before production**:
1. Gate real-bus integration tests behind `KAFKA_INTEGRATION_TESTS=real`
2. Consume from `onex.evt.omniclaude.routing-decision.v1` and validate
   event envelope structure
3. Verify events arrive within 5-second SLA
4. Test with Kafka broker unavailable (verify graceful degradation)

### In-Memory History Store

**Current state**: `HandlerHistoryPostgres` uses an in-memory store
(dict-based) rather than actual PostgreSQL queries.

**Required before production**:
1. Implement real PostgreSQL queries for `query_routing_stats()`
2. Test with `POSTGRES_INTEGRATION_TESTS=1`
3. Verify stats caching TTL and invalidation

---

## Monitoring

When the flag is enabled in Phase 2+, monitor:

1. **Routing latency**: `latency_ms` field in routing decision events
   - Alert if p95 > 100ms
   - Alert if p50 > 50ms

2. **Fallback rate**: Count of `routing_policy=fallback_default` vs total
   - Alert if fallback rate increases by >5% from baseline

3. **Error rate**: Count of ONEX path failures (logged as warnings)
   - Alert if error rate > 1% of routing decisions

4. **Emission success**: Count of successful vs failed emissions
   - Alert if emission failure rate > 10% (non-blocking but indicates infra issues)

---

## Configuration Reference

```bash
# Enable ONEX routing nodes (any truthy value)
USE_ONEX_ROUTING_NODES=true    # Recommended
USE_ONEX_ROUTING_NODES=1       # Also works
USE_ONEX_ROUTING_NODES=yes     # Also works

# Disable ONEX routing nodes (default)
USE_ONEX_ROUTING_NODES=false
USE_ONEX_ROUTING_NODES=0
# Or simply unset the variable
```
