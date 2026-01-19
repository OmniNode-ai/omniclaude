# OmniClaude Event Alignment Plan

**Purpose**: Track alignment of omniclaude events with EVENT_BUS_INTEGRATION_GUIDE and MVP Event Catalog

**Date Created**: 2025-11-13
**Last Updated**: 2025-11-13
**Status**: Phase 0 Complete (18.5% overall)
**Owner**: OmniClaude Team

---

## Executive Summary

**Goal**: Align all omniclaude events with OmniNode event bus standards (EVENT_BUS_INTEGRATION_GUIDE + MVP_EVENT_CATALOG)

**Current State**:
- ✅ 5 tasks completed (Phase 0)
- 🔄 22 tasks remaining (Phases 1-5)
- 📊 18.5% complete

**Key Achievements Today**:
1. All existing routing, intelligence, and transformation events aligned with standards
2. Partition key policy module created with 5 event families
3. Event validation utilities created with 9 validation functions
4. Complete DLQ analysis across omninode_bridge and omniarchon

**Next Sprint Focus**:
- Expand agent events from 3 to 10 (MVP requirement)
- Add structured logging events (3 events)

---

## Reference Documents

| Document | Location | Purpose |
|----------|----------|---------|
| **EVENT_BUS_INTEGRATION_GUIDE** | `/Volumes/PRO-G40/Code/omninode/docs/EVENT_BUS_INTEGRATION_GUIDE.md` | Event standards, envelope structure, partition keys |
| **MVP_EVENT_CATALOG** | `/Volumes/PRO-G40/Code/omninode/docs/MVP_EVENT_CATALOG.md` | Complete catalog of 123 events (91 MVP + 32 planned) |
| **omninode_bridge DLQ** | `/Volumes/PRO-G40/Code/omninode_bridge/src/omninode_bridge/services/kafka_client.py` | Production DLQ with error taxonomy |
| **omniarchon DLQ** | `/Volumes/PRO-G40/Code/omniarchon/python/src/events/dlq/dlq_handler.py` | DLQ handler with reprocessing |

---

## Event Alignment Status

### Current OmniClaude Events

| Event | Status | Topic | Notes |
|-------|--------|-------|-------|
| **Agent Routing (Requested)** | ✅ Aligned | `omninode.agent.routing.requested.v1` | Complete envelope, partition key policy |
| **Agent Routing (Completed)** | ✅ Aligned | `omninode.agent.routing.completed.v1` | Complete envelope, partition key policy |
| **Agent Routing (Failed)** | ✅ Aligned | `omninode.agent.routing.failed.v1` | Complete envelope, partition key policy |
| **Intelligence Query (Requested)** | ✅ Aligned | `omninode.intelligence.code-analysis.requested.v1` | Complete envelope, Kafka headers |
| **Intelligence Query (Completed)** | ✅ Aligned | `omninode.intelligence.code-analysis.completed.v1` | Complete envelope, Kafka headers |
| **Intelligence Query (Failed)** | ✅ Aligned | `omninode.intelligence.code-analysis.failed.v1` | Complete envelope, Kafka headers |
| **Transformation (Started)** | ✅ Aligned | `omninode.agent.transformation.started.v1` | OnexEnvelopeV1, idempotency |
| **Transformation (Completed)** | ✅ Aligned | `omninode.agent.transformation.completed.v1` | OnexEnvelopeV1, idempotency |
| **Transformation (Failed)** | ✅ Aligned | `omninode.agent.transformation.failed.v1` | OnexEnvelopeV1, idempotency |

**Total**: 9 events aligned (100% of existing events)

### MVP Event Catalog Requirements

| Domain | Required Events | Implemented | Gap | Priority |
|--------|----------------|-------------|-----|----------|
| **Agent** | 10 | 3 | 7 | 🔴 HIGH |
| **Intelligence** | 16 | 2 (partial) | 14 | 🟡 MEDIUM |
| **Logging** | 3 | 0 | 3 | 🟡 MEDIUM |
| **Code Generation** | 8 | 0 | 8 | 🟢 LOW (not omniclaude's role) |
| **Metadata** | 7 | 0 | 7 | 🟢 LOW (not omniclaude's role) |
| **PostgreSQL** | 11 | 0 | 11 | 🟢 LOW (not omniclaude's role) |
| **Consul** | 9 | 0 | 9 | 🟢 LOW (not omniclaude's role) |
| **Vault** | 15 | 0 | 15 | 🟢 LOW (not omniclaude's role) |

**Note**: Many domains (Code Generation, Metadata, Infrastructure Adapters) are not omniclaude's responsibility. Focus is on Agent, Intelligence, and Logging domains.

---

## ✅ Phase 0: COMPLETED (5 tasks)

**Status**: ✅ Complete (2025-11-13)

### Task 0.1: Align Routing Events ✅
- **Completed**: 2025-11-13
- **Files Modified**:
  - `agents/lib/routing_event_client.py`
  - `services/routing_adapter/schemas/model_routing_event_envelope.py`
  - `services/routing_adapter/schemas/topics.py`
  - `agents/services/agent_router_event_service.py`
- **Changes**:
  - Topics: `agent.routing.*` → `omninode.agent.routing.*.v1`
  - Envelope fields added: `tenant_id`, `namespace`, `causation_id`, `schema_ref`
  - Event types: `AGENT_ROUTING_REQUESTED` → `omninode.agent.routing.requested.v1`
  - Partition key: `correlation_id` (documented)
- **Tests**: Existing tests verified compatible

### Task 0.2: Align Intelligence Events ✅
- **Completed**: 2025-11-13
- **Files Modified**:
  - `agents/lib/intelligence_event_client.py`
- **Changes**:
  - Topics: `dev.archon-intelligence.*` → `omninode.intelligence.code-analysis.*.v1`
  - Complete envelope with all required fields
  - Kafka headers: `x-traceparent`, `x-correlation-id`, `x-causation-id`, `x-tenant`, `x-schema-hash`
  - Backward compatibility maintained
- **Tests**: 36 passed, 2 skipped
- **Documentation**: `docs/EVENT_BUS_ALIGNMENT_SUMMARY.md` created

### Task 0.3: Align Transformation Events ✅
- **Completed**: 2025-11-13
- **Files Modified**:
  - `agents/lib/transformation_event_publisher.py`
  - `agents/lib/agent_transformer.py`
- **Changes**:
  - Separate topics: `omninode.agent.transformation.{started|completed|failed}.v1`
  - OnexEnvelopeV1 wrapper with all required fields
  - Idempotency: unique `event_id`, deduplication key = `correlation_id + event_type`
  - Partition key: `correlation_id`
- **Tests**: Manual validation successful

### Task 0.4: Create Partition Key Policy Module ✅
- **Completed**: 2025-11-13
- **Files Created**:
  - `agents/lib/partition_key_policy.py` (439 lines)
  - `agents/tests/lib/test_partition_key_policy.py` (471 lines, 35 tests)
  - `agents/tests/lib/test_partition_key_policy_integration.py` (348 lines, 10 tests)
  - `agents/lib/partition_key_policy_example.py` (337 lines)
  - `agents/lib/README_PARTITION_KEY_POLICY.md` (562 lines)
  - `agents/lib/PARTITION_KEY_POLICY_SUMMARY.md` (300 lines)
- **Event Families**: 5 covered (agent.routing, agent.transformation, agent.actions, intelligence.query, quality.gate)
- **Tests**: 41 passed, 4 skipped (91% success)

### Task 0.5: Create Event Validation Utilities ✅
- **Completed**: 2025-11-13
- **Files Created**:
  - `agents/lib/event_validation.py` (564 lines)
  - `agents/lib/test_event_validation.py` (617 lines, 51 tests)
  - `agents/lib/EVENT_VALIDATION_USAGE.md` (443 lines)
- **Validation Functions**: 9 (envelope, naming, UUID, timestamp, schema_ref, partition key, batch, full event)
- **Tests**: 51 passed (100% success in 0.23s)

---

## 🔄 Phase 1: EXPAND AGENT EVENTS (7 tasks)

**Priority**: 🔴 HIGH
**Target**: Next Sprint
**Dependencies**: None

MVP Event Catalog requires **10 agent events**. We have **3**. Need **7 more**.

### Task 1.1: Add `omninode.agent.execution.started.v1` ⏳
- **Status**: Not Started
- **Purpose**: Track when agent execution begins
- **Location**: Create/update `agents/lib/agent_execution_publisher.py`
- **Partition Key**: `correlation_id`
- **Envelope Fields**: Standard (tenant_id, namespace, correlation_id, causation_id, schema_ref)
- **Payload Schema**:
  ```json
  {
    "agent_name": "string",
    "user_request": "string",
    "correlation_id": "uuid-v7",
    "session_id": "uuid-v7",
    "started_at": "RFC3339",
    "context": {}
  }
  ```
- **Integration Points**: Agent workflow coordinator, polymorphic agent launcher
- **Estimated Effort**: 2-3 hours

### Task 1.2: Add `omninode.agent.execution.completed.v1` ⏳
- **Status**: Not Started
- **Purpose**: Track when agent execution finishes successfully
- **Location**: Same as 1.1
- **Partition Key**: `correlation_id`
- **Payload Schema**:
  ```json
  {
    "agent_name": "string",
    "correlation_id": "uuid-v7",
    "duration_ms": "int",
    "quality_score": "float",
    "completed_at": "RFC3339",
    "output_summary": "string",
    "metrics": {}
  }
  ```
- **Integration Points**: Agent completion handlers
- **Estimated Effort**: 2-3 hours

### Task 1.3: Add `omninode.agent.execution.failed.v1` ⏳
- **Status**: Not Started
- **Purpose**: Track when agent execution fails
- **Location**: Same as 1.1
- **Partition Key**: `correlation_id`
- **Payload Schema**:
  ```json
  {
    "agent_name": "string",
    "correlation_id": "uuid-v7",
    "error_message": "string",
    "error_type": "string",
    "error_stack_trace": "string",
    "failed_at": "RFC3339",
    "partial_results": {}
  }
  ```
- **Integration Points**: Error handlers, exception catchers
- **Estimated Effort**: 2-3 hours

### Task 1.4: Add `omninode.agent.quality.gate.passed.v1` ⏳
- **Status**: Not Started
- **Purpose**: Track quality gate validation passes
- **Location**: Quality gate validation code
- **Partition Key**: `correlation_id`
- **Payload Schema**:
  ```json
  {
    "gate_name": "string",
    "correlation_id": "uuid-v7",
    "score": "float",
    "threshold": "float",
    "passed_at": "RFC3339",
    "metrics": {}
  }
  ```
- **Integration Points**: Quality gate validators
- **Estimated Effort**: 2 hours

### Task 1.5: Add `omninode.agent.quality.gate.failed.v1` ✅
- **Status**: Complete
- **Purpose**: Track quality gate validation failures
- **Location**: `agents/lib/quality_gate_publisher.py`
- **Partition Key**: `correlation_id`
- **Payload Schema**:
  ```json
  {
    "gate_name": "string",
    "correlation_id": "uuid-v7",
    "score": "float",
    "threshold": "float",
    "failed_at": "RFC3339",
    "failure_reasons": ["string"],
    "recommendations": ["string"]
  }
  ```
- **Integration Points**: `agents/lib/quality_validator.py`
- **Tests**: `agents/tests/test_quality_gate_publisher.py` (16 tests, all passing)
- **Estimated Effort**: 2 hours
- **Actual Effort**: 2 hours
- **Completed**: 2025-11-13

### Task 1.6: Add `omninode.agent.provider.selected.v1` ✅
- **Status**: ✅ Complete (2025-11-13)
- **Purpose**: Track AI provider selection decisions
- **Location**: Provider selection logic
- **Partition Key**: `correlation_id`
- **Payload Schema**:
  ```json
  {
    "provider_name": "string",
    "model_name": "string",
    "correlation_id": "uuid-v7",
    "selection_reason": "string",
    "selection_criteria": {},
    "selected_at": "RFC3339"
  }
  ```
- **Integration Points**: Provider toggle script, model selection logic
- **Estimated Effort**: 2 hours (Actual: 2 hours)
- **Deliverables**:
  - ✅ `agents/lib/provider_selection_publisher.py` - Event publisher with async/sync support
  - ✅ `scripts/publish_provider_selection.py` - CLI tool for shell integration
  - ✅ `agents/tests/test_provider_selection_publisher.py` - Comprehensive test suite (16 tests)
  - ✅ `docs/events/PROVIDER_SELECTION_INTEGRATION.md` - Integration guide
  - ✅ `agents/lib/partition_key_policy.py` - Added AGENT_PROVIDER event family
  - ✅ Linear ticket OMN-32 completed

### Task 1.7: Add `omninode.agent.confidence.scored.v1` ⏳
- **Status**: Not Started
- **Purpose**: Track routing confidence scoring
- **Location**: Agent router service
- **Partition Key**: `correlation_id`
- **Payload Schema**:
  ```json
  {
    "agent_name": "string",
    "confidence_score": "float",
    "routing_strategy": "string",
    "correlation_id": "uuid-v7",
    "scored_at": "RFC3339",
    "factors": {}
  }
  ```
- **Integration Points**: `agents/services/agent_router_event_service.py`
- **Estimated Effort**: 2 hours

**Phase 1 Total Estimated Effort**: 14-17 hours

---

## 📊 Phase 2: ADD LOGGING EVENTS (3 tasks)

**Priority**: 🟡 MEDIUM
**Target**: Sprint after Phase 1
**Dependencies**: None

### Task 2.1: Implement `omninode.logging.application.v1` ⏳
- **Status**: Not Started
- **Purpose**: Structured application logs for omnidash integration
- **Location**: Create `agents/lib/logging_event_publisher.py`
- **Partition Key**: `service_name`
- **Payload Schema**:
  ```json
  {
    "service_name": "omniclaude",
    "instance_id": "omniclaude-1",
    "level": "INFO|WARN|ERROR",
    "logger": "router.pipeline",
    "message": "agent execution completed",
    "code": "AGENT_EXECUTION_COMPLETED",
    "context": {}
  }
  ```
- **Integration Points**: Replace/augment file logging throughout codebase
- **Reference**: EVENT_BUS_INTEGRATION_GUIDE lines 729-791
- **Estimated Effort**: 4-6 hours

### Task 2.2: Implement `omninode.logging.audit.v1` ⏳
- **Status**: Not Started
- **Purpose**: Audit trail for compliance
- **Location**: Same as 2.1
- **Partition Key**: `tenant_id`
- **Payload Schema**:
  ```json
  {
    "tenant_id": "uuid",
    "action": "agent.execution",
    "actor": "user-id",
    "resource": "agent-name",
    "timestamp": "RFC3339",
    "outcome": "success|failure"
  }
  ```
- **Integration Points**: Agent lifecycle events
- **Estimated Effort**: 3-4 hours

### Task 2.3: Implement `omninode.logging.security.v1` ⏳
- **Status**: Not Started
- **Purpose**: Security audit events
- **Location**: Same as 2.1
- **Partition Key**: `tenant_id`
- **Payload Schema**:
  ```json
  {
    "tenant_id": "uuid",
    "event_type": "api_key_used|permission_check",
    "user_id": "string",
    "resource": "string",
    "decision": "allow|deny",
    "timestamp": "RFC3339"
  }
  ```
- **Integration Points**: API key usage, permission checks
- **Estimated Effort**: 3-4 hours

**Phase 2 Total Estimated Effort**: 10-14 hours

---

## 🔧 Phase 3: DLQ IMPLEMENTATION (5 tasks)

**Priority**: 🟡 MEDIUM (Required for Production)
**Target**: Production Prep Sprint
**Dependencies**: Phase 1 (agent events)

### DLQ Research Findings

**omninode_bridge DLQ**:
- Location: `/Volumes/PRO-G40/Code/omninode_bridge/src/omninode_bridge/services/kafka_client.py`
- Pattern: Producer-side with error taxonomy
- Error Classes: 6 (retryable transient, retryable dependency, non-retryable validation/policy/security/idempotency)
- Max Retries: 3 (configurable)
- Monitoring: Dedicated DLQ monitor service

**omniarchon DLQ**:
- Location: `/Volumes/PRO-G40/Code/omniarchon/python/src/events/dlq/dlq_handler.py`
- Pattern: Hybrid (producer + consumer + dedicated handler)
- Features: Auto-discovery, reprocessing, secret sanitization, circuit breaker
- Max Retries: 3 (configurable)
- Backoff: Exponential (1s → 2s → 4s → DLQ)

### Task 3.1: Implement Error Taxonomy ⏳
- **Status**: Not Started
- **Purpose**: Classify errors for intelligent retry behavior
- **Location**: Create `agents/lib/error_taxonomy.py`
- **Reference**: `/Volumes/PRO-G40/Code/omninode_bridge/src/omninode_bridge/services/error_taxonomy.py`
- **Error Classes**:
  1. RETRYABLE_TRANSIENT (6 retries, 100-5000ms backoff)
  2. RETRYABLE_DEPENDENCY (3 retries, 500-10000ms backoff)
  3. NON_RETRYABLE_VALIDATION (immediate DLQ)
  4. NON_RETRYABLE_POLICY (immediate DLQ)
  5. NON_RETRYABLE_SECURITY (immediate DLQ)
  6. NON_RETRYABLE_IDEMPOTENCY (skip silently)
- **Functions**:
  - `classify_kafka_error(exception) -> EnumKafkaErrorClass`
  - `get_retry_strategy(error_class) -> dict`
  - `get_dlq_metadata(error_class, exception) -> dict`
- **Estimated Effort**: 4-6 hours

### Task 3.2: Add DLQ Routing to Publishers ⏳
- **Status**: Not Started
- **Purpose**: Send failed events to DLQ after max retries
- **Location**: Update `agents/lib/routing_event_client.py`, `intelligence_event_client.py`, `transformation_event_publisher.py`
- **Changes**:
  - Add `_send_to_dlq()` method
  - Topic naming: `{original_topic}.dlq`
  - DLQ payload: original event + error metadata + retry count
  - Max retries: 3 (configurable via env var)
  - Exponential backoff with jitter
- **Reference**: omniarchon `events/publisher/event_publisher.py` lines 234-239
- **Estimated Effort**: 6-8 hours

### Task 3.3: Implement Secret Sanitization ⏳
- **Status**: Not Started
- **Purpose**: Prevent credential leaks in DLQ
- **Location**: Create `agents/lib/secret_sanitizer.py`
- **Reference**: omniarchon `events/publisher/event_publisher.py` lines 423-444
- **Features**:
  - Mask API keys (GEMINI_API_KEY, ZAI_API_KEY, OPENAI_API_KEY)
  - Mask passwords (POSTGRES_PASSWORD, etc.)
  - Mask tokens
  - Apply before DLQ publish
- **Estimated Effort**: 3-4 hours

### Task 3.4: Add DLQ Handler in Consumers ⏳
- **Status**: Not Started
- **Purpose**: Consumer-side DLQ for processing failures
- **Location**: Update `agents/lib/routing_event_client.py`, `intelligence_event_client.py` (response consumers)
- **Changes**:
  - Track retry count per message key
  - Send to DLQ after max retries
  - Non-retryable errors → immediate DLQ
- **Reference**: omniarchon `intelligence-consumer/src/error_handler.py`
- **Estimated Effort**: 4-6 hours

### Task 3.5: Create DLQ Monitoring Service (Optional) ⏳
- **Status**: Not Started
- **Purpose**: Monitor DLQ topics and alert on thresholds
- **Location**: Create `agents/services/dlq_monitor.py`
- **Features**:
  - Auto-discover `*.dlq` topics
  - Threshold-based alerting (default: 10 messages)
  - Alert cooldown (default: 15 minutes)
  - Reprocessing capability (optional)
  - Metrics tracking
- **Reference**:
  - omninode_bridge `monitoring/codegen_dlq_monitor.py`
  - omniarchon `events/dlq/dlq_handler.py`
- **Estimated Effort**: 6-8 hours

**Phase 3 Total Estimated Effort**: 23-32 hours

---

## 🎯 Phase 4: ENHANCED OBSERVABILITY (2 tasks)

**Priority**: 🟢 LOW (Post-MVP)
**Target**: Post-production
**Dependencies**: Phase 1, Phase 2

### Task 4.1: Integrate Action Logging with Events ⏳
- **Status**: Not Started
- **Purpose**: Correlate action logs with domain events
- **Location**: Update `agents/lib/action_logging.py`
- **Changes**:
  - Link action logs to agent execution events via correlation_id
  - Link action logs to routing events
  - Add event_id references to action log entries
- **Estimated Effort**: 3-4 hours

### Task 4.2: Publish Action Logs as Events ⏳
- **Status**: Not Started
- **Purpose**: Real-time observability via event stream
- **Location**: Update `agents/lib/action_logging.py`
- **Changes**:
  - Align with `omninode.logging.application.v1` instead of custom `agent-actions` topic
  - Use standard logging event envelope
  - Maintain backward compatibility
- **Estimated Effort**: 3-4 hours

**Phase 4 Total Estimated Effort**: 6-8 hours

---

## 📚 Phase 5: DOCUMENTATION & TESTING (5 tasks)

**Priority**: 🟢 ONGOING
**Target**: Throughout all phases
**Dependencies**: Phases 1-4

### Task 5.1: Document Event Architecture ⏳
- **Status**: Not Started
- **Purpose**: Architecture decision records
- **Location**: Create `docs/events/OMNICLAUDE_EVENT_ARCHITECTURE.md`
- **Contents**:
  - Event flow diagrams
  - Design patterns (request/response, lifecycle, status)
  - Integration points with omniarchon, omninode_bridge
  - Best practices
- **Estimated Effort**: 4-6 hours

### Task 5.2: Create Event Usage Guide ⏳
- **Status**: Not Started
- **Purpose**: Developer guide
- **Location**: Create `docs/events/EVENT_USAGE_GUIDE.md`
- **Contents**:
  - Code examples for publishing events
  - Code examples for consuming events
  - Testing strategies
  - Common patterns
- **Estimated Effort**: 3-4 hours

### Task 5.3: Update CLAUDE.md ⏳
- **Status**: Not Started
- **Purpose**: Reflect alignment completion
- **Location**: Update `/Volumes/PRO-G40/Code/omniclaude/CLAUDE.md`
- **Changes**:
  - Add event alignment status section
  - Document new utilities (partition key policy, event validation)
  - Update quick reference
- **Estimated Effort**: 1-2 hours

### Task 5.4: Add Integration Tests for Events ⏳
- **Status**: Not Started
- **Purpose**: End-to-end event flow testing
- **Location**: Create `agents/tests/integration/test_event_flows.py`
- **Test Coverage**:
  - Agent execution lifecycle (started → completed)
  - Agent execution lifecycle (started → failed)
  - Quality gate validation flows
  - Logging event flows
- **Estimated Effort**: 6-8 hours

### Task 5.5: Add DLQ Integration Tests ⏳
- **Status**: Not Started
- **Purpose**: Verify DLQ routing and reprocessing
- **Location**: Create `agents/tests/integration/test_dlq.py`
- **Test Coverage**:
  - Max retries exceeded → DLQ
  - Non-retryable errors → immediate DLQ
  - Secret sanitization in DLQ payloads
  - DLQ monitoring and alerting
- **Reference**: omninode_bridge `tests/integration/monitoring/test_codegen_dlq_monitor_integration.py`
- **Estimated Effort**: 6-8 hours

**Phase 5 Total Estimated Effort**: 20-28 hours

---

## Timeline & Milestones

### Sprint 1 (Current - Week of 2025-11-13)
- [x] Phase 0: Event alignment foundation (COMPLETE)
- [x] DLQ research across codebases (COMPLETE)
- [x] Planning document creation (COMPLETE)

### Sprint 2 (Week of 2025-11-18)
- [ ] Phase 1: Expand agent events (7 events)
  - Days 1-2: Execution events (started, completed, failed)
  - Days 3-4: Quality gate events (passed, failed)
  - Day 5: Provider and confidence events

**Deliverable**: 10 agent events (MVP requirement met)

### Sprint 3 (Week of 2025-11-25)
- [ ] Phase 2: Add logging events (3 events)
  - Days 1-2: Application logging implementation
  - Days 3-4: Audit and security logging
  - Day 5: Integration and testing

**Deliverable**: Structured logging for omnidash

### Sprint 4 (Week of 2025-12-02)
- [ ] Phase 3: DLQ implementation (5 tasks)
  - Days 1-2: Error taxonomy + secret sanitization
  - Days 3-4: DLQ routing in publishers and consumers
  - Day 5: DLQ monitoring service (optional)

**Deliverable**: Production-ready DLQ

### Sprint 5+ (Week of 2025-12-09+)
- [ ] Phase 4: Enhanced observability
- [ ] Phase 5: Documentation and testing
- [ ] Integration testing
- [ ] Production deployment preparation

---

## Success Metrics

### Phase Completion Metrics
- [ ] Phase 1: 10 agent events published and consumed successfully
- [ ] Phase 2: Logging events visible in omnidash
- [ ] Phase 3: DLQ handles failures with <0.1% data loss
- [ ] Phase 4: Action logs correlated with domain events
- [ ] Phase 5: 100% test coverage for event flows

### Quality Metrics
- [ ] Event naming: 100% compliance with EVENT_BUS_INTEGRATION_GUIDE
- [ ] Envelope structure: 100% compliance (all required fields)
- [ ] Partition keys: 100% policy compliance
- [ ] Test coverage: >90% for event publishing/consuming code
- [ ] Documentation: Complete usage guide with examples

### Performance Metrics
- [ ] Event publishing: <5ms overhead (non-blocking)
- [ ] DLQ routing: <10ms additional latency
- [ ] Event validation: <1ms per event
- [ ] Partition key lookup: <1ms per event

---

## Risk Assessment

### High Risk
1. **DLQ Implementation Complexity**
   - Mitigation: Reference omninode_bridge and omniarchon implementations
   - Estimated time buffer: +40% (built into estimates)

2. **Backward Compatibility**
   - Mitigation: Maintain dual-read period for topic migrations
   - Testing: Comprehensive backward compatibility tests

### Medium Risk
1. **Integration with Existing Systems**
   - Mitigation: Gradual rollout, feature flags
   - Testing: Integration tests with actual Kafka infrastructure

2. **Performance Impact**
   - Mitigation: Non-blocking async publishing, batching
   - Monitoring: Track event publishing latency

### Low Risk
1. **Documentation Drift**
   - Mitigation: Update docs as part of each PR
   - Review: Documentation review in PR checklist

---

## Dependencies

### External Dependencies
- ✅ Kafka/Redpanda infrastructure (192.168.86.200:9092)
- ✅ PostgreSQL (192.168.86.200:5436)
- ✅ EVENT_BUS_INTEGRATION_GUIDE (stable)
- ✅ MVP_EVENT_CATALOG (stable)

### Internal Dependencies
- ✅ Pydantic Settings framework (Phase 2 from previous work)
- ✅ Docker Compose consolidation (Phase 2 from previous work)
- Phase 1 → Phase 3 (DLQ needs agent events to test)
- Phase 2 → Phase 4 (observability needs logging events)

---

## Notes

### Design Decisions
1. **Topic Naming**: Use `omninode.*` prefix for consistency with platform
2. **Envelope Structure**: Use OnexEnvelopeV1 from omninode_bridge as standard
3. **Partition Keys**: Use `correlation_id` for all workflow-related events
4. **DLQ**: Hybrid approach (producer-side + consumer-side + monitoring)
5. **Secret Sanitization**: Apply before DLQ to prevent credential leaks

### Best Practices
1. Always include correlation_id for distributed tracing
2. Use causation_id to track event chains
3. Include schema_ref for validation
4. Publish events non-blocking (async, fire-and-forget with DLQ fallback)
5. Log all event publishing failures

### Future Enhancements (Post-MVP)
1. Schema registry integration
2. Event replay capability
3. Event versioning and migration strategy
4. Event-driven webhooks for external systems
5. GraphQL subscription layer over events

---

## Completion Checklist

### Phase 0 (COMPLETE)
- [x] Routing events aligned
- [x] Intelligence events aligned
- [x] Transformation events aligned
- [x] Partition key policy created
- [x] Event validation utilities created

### Phase 1 (IN PROGRESS)
- [ ] Agent execution started event
- [ ] Agent execution completed event
- [ ] Agent execution failed event
- [ ] Quality gate passed event
- [ ] Quality gate failed event
- [ ] Provider selected event
- [ ] Confidence scored event

### Phase 2 (PENDING)
- [ ] Application logging event
- [ ] Audit logging event
- [ ] Security logging event

### Phase 3 (PENDING)
- [ ] Error taxonomy
- [ ] DLQ routing (publishers)
- [ ] Secret sanitization
- [ ] DLQ handler (consumers)
- [ ] DLQ monitoring (optional)

### Phase 4 (PENDING)
- [ ] Action logging integration
- [ ] Action logs as events

### Phase 5 (PENDING)
- [ ] Event architecture doc
- [ ] Event usage guide
- [ ] CLAUDE.md update
- [ ] Integration tests
- [ ] DLQ tests

---

**Last Updated**: 2025-11-13
**Next Review**: 2025-11-18 (Sprint 2 kickoff)
**Owner**: OmniClaude Team
