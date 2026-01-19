# Agent Routing Architecture - Visual Comparison

This document provides visual comparisons between the current synchronous routing architecture and the proposed event-driven architecture.

---

## High-Level Architecture Comparison

### Current Architecture (Synchronous)

```
┌─────────────────────────────────────────────────────────────────┐
│                    INCONSISTENT ARCHITECTURE                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Agent Spawn                                                     │
│    │                                                             │
│    ├─► ROUTING (SYNCHRONOUS) ❌                                 │
│    │   │                                                         │
│    │   ├─► Spawn Python process (30-50ms)                       │
│    │   ├─► Load agent_router.py                                 │
│    │   ├─► Load YAML registry                                   │
│    │   ├─► Build indexes (TriggerMatcher, etc.)                 │
│    │   ├─► Execute router.route()                               │
│    │   ├─► Return recommendations                               │
│    │   └─► Exit (cache lost!)                                   │
│    │                                                             │
│    └─► MANIFEST INJECTION (EVENT-DRIVEN) ✅                     │
│        │                                                         │
│        ├─► Publish: intelligence.code-analysis-requested.v1     │
│        ├─► Kafka Event Bus                                      │
│        ├─► archon-intelligence-adapter (service)                │
│        ├─► Query: Qdrant, Memgraph, PostgreSQL                  │
│        ├─► Publish: intelligence.code-analysis-completed.v1     │
│        └─► Receive: Manifest intelligence                       │
│                                                                  │
│  Problem: Two different patterns for similar operations!        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Proposed Architecture (Event-Driven)

```
┌─────────────────────────────────────────────────────────────────┐
│                   UNIFIED EVENT BUS ARCHITECTURE                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Agent Spawn                                                     │
│    │                                                             │
│    ├─► ROUTING (EVENT-DRIVEN) ✅                                │
│    │   │                                                         │
│    │   ├─► Publish: agent.routing.requested.v1                  │
│    │   ├─► Kafka Event Bus                                      │
│    │   ├─► agent-router-service (NEW)                           │
│    │   │   - AgentRouter (warm, cached)                         │
│    │   │   - Service-level cache (persistent)                   │
│    │   │   - Circuit breaker + metrics                          │
│    │   ├─► Publish: agent.routing.completed.v1                  │
│    │   └─► Receive: Routing recommendations                     │
│    │                                                             │
│    └─► MANIFEST INJECTION (EVENT-DRIVEN) ✅                     │
│        │                                                         │
│        ├─► Publish: intelligence.code-analysis-requested.v1     │
│        ├─► Kafka Event Bus                                      │
│        ├─► archon-intelligence-adapter (service)                │
│        ├─► Query: Qdrant, Memgraph, PostgreSQL                  │
│        ├─► Publish: intelligence.code-analysis-completed.v1     │
│        └─► Receive: Manifest intelligence                       │
│                                                                  │
│  Benefit: Unified pattern for all intelligence operations!      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Request Flow Comparison

### Current Flow (Synchronous)

```
┌──────────────┐
│ Agent Needs  │
│ Routing      │
└──────┬───────┘
       │
       ▼
┌────────────────────────────────────────────┐
│ Inline Python Execution                    │
│                                            │
│ python3 << 'EOF'                           │
│ from agent_router import AgentRouter       │
│ router = AgentRouter()                     │
│ recommendations = router.route(...)        │
│ EOF                                        │
│                                            │
│ ⏱️  Python startup: 30-50ms                │
│ ⏱️  Module imports: 10-20ms                │
│ ⏱️  YAML parsing: 5-10ms                   │
│ ⏱️  Index building: 10-20ms                │
│ ⏱️  Routing logic: 20-30ms                 │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━                 │
│ ⏱️  TOTAL: 75-130ms                        │
└────────────┬───────────────────────────────┘
             │
             ▼
      ┌──────────────┐
      │ Cache Lost ❌ │
      │ (process exit)│
      └──────────────┘
```

### Proposed Flow (Event-Driven)

```
┌──────────────┐
│ Agent Needs  │
│ Routing      │
└──────┬───────┘
       │
       ▼
┌────────────────────────────────────────────┐
│ RoutingEventClient                         │
│                                            │
│ async with RoutingEventClient() as client: │
│     recommendations = await                │
│         client.request_routing(...)        │
│                                            │
│ ⏱️  Publish to Kafka: 5ms                  │
└────────────┬───────────────────────────────┘
             │
             ▼
      ┌─────────────────────────────────────┐
      │ agent-router-service (WARM SERVICE) │
      │                                     │
      │ - AgentRouter already loaded ✅     │
      │ - Registry already parsed ✅        │
      │ - Indexes already built ✅          │
      │ - Cache persists ✅                 │
      │                                     │
      │ ⏱️  Cache check: 2ms                │
      │ ⏱️  Cache hit: <5ms total           │
      │ ⏱️  Cache miss: 20-30ms routing     │
      └─────────────┬───────────────────────┘
                    │
                    ▼
             ┌────────────────┐
             │ Publish result │
             │ to Kafka       │
             │ ⏱️  5ms         │
             └────────┬───────┘
                      │
                      ▼
               ┌──────────────┐
               │ Client       │
               │ receives     │
               │ response     │
               └──────┬───────┘
                      │
                      ▼
      ┌───────────────────────────────┐
      │ TOTAL TIME:                   │
      │ - Cache hit: <10ms ✅         │
      │ - Cache miss: 40-60ms ✅      │
      │ - Cache persists ✅           │
      └───────────────────────────────┘
```

---

## Performance Comparison (Timeline)

### Single Request Performance

```
Current (Synchronous):
|████████████████████████████████████████| 100ms
└─ Python startup ─┬─ Routing ─┘
                   (no cache)

Proposed (Cache Miss):
|████████████████████| 40ms
└─ Kafka ─┬─ Routing ─┬─ Kafka ─┘
         (service warm)

Proposed (Cache Hit):
|█████| 5ms
└─ Kafka ─┬─ Cache ─┘
```

### Multi-Agent Performance (3 agents)

```
Current (Sequential):
Agent 1: |████████████████████████████████████████| 100ms
Agent 2:                                          |████████████████████████████████████████| 100ms
Agent 3:                                                                                   |████████████████████████████████████████| 100ms
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOTAL: 300ms

Proposed (Parallel):
Agent 1: |█████████████████████| 40ms (miss)
Agent 2: |█████| 5ms (hit)
Agent 3: |█████| 5ms (hit)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOTAL: 40ms (7.5× faster!)
```

---

## Observability Comparison

### Current (Limited Observability)

```
┌─────────────────────────────────────────────────────────────┐
│ User Request                                                │
│   ↓                                                         │
│ ??? (routing happens inline, not logged to event bus)      │
│   ↓                                                         │
│ Selected Agent                                              │
│   ↓                                                         │
│ intelligence.code-analysis-requested.v1 (manifest)          │
│   ↓                                                         │
│ Agent Execution                                             │
│                                                             │
│ Gap: No event bus visibility into routing decisions!       │
└─────────────────────────────────────────────────────────────┘

Database View:
┌────────────────────────────────────┐
│ agent_routing_decisions            │
│ - correlation_id                   │
│ - selected_agent                   │
│ - confidence_score                 │
│ - created_at                       │
│                                    │
│ Problem: Only see AFTER routing    │
│          No request tracking       │
│          No live status            │
└────────────────────────────────────┘
```

### Proposed (Complete Observability)

```
┌─────────────────────────────────────────────────────────────┐
│ User Request (correlation_id: abc123)                       │
│   ↓                                                         │
│ agent.routing.requested.v1 (correlation_id: abc123) ✅      │
│   ↓                                                         │
│ agent-router-service processes ✅                           │
│   ↓                                                         │
│ agent.routing.completed.v1 (correlation_id: abc123) ✅      │
│   ↓                                                         │
│ Selected Agent (correlation_id: abc123)                     │
│   ↓                                                         │
│ intelligence.code-analysis-requested.v1 (abc123) ✅         │
│   ↓                                                         │
│ Agent Execution (correlation_id: abc123)                    │
│                                                             │
│ Benefit: Complete event bus traceability!                  │
└─────────────────────────────────────────────────────────────┘

Database View:
┌──────────────────────────────────────────────────────────┐
│ Complete Lifecycle Tracking                              │
│                                                          │
│ agent_routing_requests:                                  │
│   - correlation_id: abc123                               │
│   - user_request: "optimize database"                    │
│   - status: completed                                    │
│   - created_at: 14:30:00                                 │
│                                                          │
│ agent_routing_decisions:                                 │
│   - correlation_id: abc123                               │
│   - selected_agent: agent-performance                    │
│   - confidence: 0.92                                     │
│   - created_at: 14:30:00.045                            │
│                                                          │
│ agent_manifest_injections:                               │
│   - correlation_id: abc123                               │
│   - patterns_count: 120                                  │
│   - created_at: 14:30:00.090                            │
│                                                          │
│ agent_execution_logs:                                    │
│   - correlation_id: abc123                               │
│   - status: success                                      │
│   - created_at: 14:30:05.000                            │
│                                                          │
│ Benefit: End-to-end correlation tracking!                │
└──────────────────────────────────────────────────────────┘
```

---

## Scalability Comparison

### Current (No Horizontal Scaling)

```
┌──────────────────────────────────────────────────────┐
│ Multiple Agents Need Routing                         │
│                                                      │
│ Agent 1 ──► Python Process 1 (50MB) ──► Exit        │
│ Agent 2 ──► Python Process 2 (50MB) ──► Exit        │
│ Agent 3 ──► Python Process 3 (50MB) ──► Exit        │
│ Agent 4 ──► Python Process 4 (50MB) ──► Exit        │
│ Agent 5 ──► Python Process 5 (50MB) ──► Exit        │
│                                                      │
│ Total Memory: 250MB                                  │
│ Total Time: 5 × 100ms = 500ms                       │
│                                                      │
│ Problem:                                             │
│ - Can't scale routing separately from agents         │
│ - Each agent spawns own process                      │
│ - No connection pooling                              │
│ - No load balancing                                  │
└──────────────────────────────────────────────────────┘
```

### Proposed (Horizontal Scaling)

```
┌──────────────────────────────────────────────────────┐
│ Multiple Agents Need Routing                         │
│                                                      │
│ Agent 1 ──┐                                          │
│ Agent 2 ──┤                                          │
│ Agent 3 ──┼──► Kafka Event Bus                       │
│ Agent 4 ──┤    (load balanced)                       │
│ Agent 5 ──┘                                          │
│            │                                          │
│            ▼                                          │
│ ┌────────────────────────────────────────┐          │
│ │ agent-router-service (Instance 1)      │          │
│ │ - Consumer Group: routing-group        │          │
│ │ - Partitions: 0, 1                     │          │
│ │ - Memory: 50MB                         │          │
│ └────────────────────────────────────────┘          │
│                                                      │
│ ┌────────────────────────────────────────┐          │
│ │ agent-router-service (Instance 2)      │          │
│ │ - Consumer Group: routing-group        │          │
│ │ - Partitions: 2, 3                     │          │
│ │ - Memory: 50MB                         │          │
│ └────────────────────────────────────────┘          │
│                                                      │
│ ┌────────────────────────────────────────┐          │
│ │ agent-router-service (Instance 3)      │          │
│ │ - Consumer Group: routing-group        │          │
│ │ - Partitions: 4, 5                     │          │
│ │ - Memory: 50MB                         │          │
│ └────────────────────────────────────────┘          │
│                                                      │
│ Total Memory: 150MB (vs 250MB)                      │
│ Total Time: max(40ms, 5ms, 5ms, 5ms, 5ms) = 40ms   │
│ (parallel processing via Kafka partitions)          │
│                                                      │
│ Scaling Command:                                     │
│ $ docker-compose scale agent-router-service=3       │
│                                                      │
│ Benefits:                                            │
│ ✅ Scale routing independently                       │
│ ✅ Load balancing via Kafka                          │
│ ✅ Connection pooling                                │
│ ✅ Fault tolerance                                   │
└──────────────────────────────────────────────────────┘
```

---

## Feature Comparison

### Current Capabilities

```
┌─────────────────────────────────────────────┐
│ Current Routing Capabilities                │
├─────────────────────────────────────────────┤
│ ✅ Enhanced fuzzy matching                  │
│ ✅ Confidence scoring (4 components)        │
│ ✅ In-memory caching (lost on exit)         │
│ ✅ Trigger-based matching                   │
│ ❌ Service-level caching                    │
│ ❌ Event bus observability                  │
│ ❌ Circuit breaker                          │
│ ❌ A/B testing                              │
│ ❌ Routing quorum                           │
│ ❌ Hot reload                               │
│ ❌ Horizontal scaling                       │
│ ❌ Metrics aggregation                      │
└─────────────────────────────────────────────┘
```

### Proposed Capabilities

```
┌─────────────────────────────────────────────┐
│ Event-Driven Routing Capabilities           │
├─────────────────────────────────────────────┤
│ ✅ Enhanced fuzzy matching                  │
│ ✅ Confidence scoring (4 components)        │
│ ✅ Service-level caching (persistent)       │
│ ✅ Trigger-based matching                   │
│ ✅ Event bus observability                  │
│ ✅ Circuit breaker                          │
│ ✅ A/B testing framework                    │
│ ✅ Routing quorum (multiple strategies)     │
│ ✅ Hot reload (no restart)                  │
│ ✅ Horizontal scaling                       │
│ ✅ Centralized metrics                      │
│ ✅ Event replay                             │
│ ✅ Correlation tracking                     │
└─────────────────────────────────────────────┘
```

---

## Cost-Benefit Analysis

### Development Cost

```
┌──────────────────────────────────────────┐
│ Implementation Effort                    │
├──────────────────────────────────────────┤
│ Phase 1: Service Development   2 weeks  │
│ Phase 2: Client Integration    1 week   │
│ Phase 3: Parallel Testing      1 week   │
│ Phase 4: Migration             1 week   │
│ Phase 5: Advanced Features     1 week   │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│ TOTAL: ~6 weeks                          │
│                                          │
│ Risk Level: LOW                          │
│ - Proven pattern (manifest injection)   │
│ - Backward compatibility                │
│ - Gradual rollout                        │
│ - Automatic fallback                     │
└──────────────────────────────────────────┘
```

### Performance Benefit

```
┌──────────────────────────────────────────┐
│ Performance Improvement                  │
├──────────────────────────────────────────┤
│ Cold Start:  2× faster (130ms → 60ms)   │
│ Warm Start:  13× faster (130ms → 10ms)  │
│ Multi-Agent: 7.5× faster (300ms → 40ms) │
│ Memory:      3× less (150MB → 50MB)     │
│ Cache Hit:   ∞ improvement (0% → 60%)   │
│                                          │
│ Real-World Impact:                       │
│ 100 agents/day:                          │
│ - Current: 100 × 100ms = 10s total      │
│ - Proposed: 60ms + 99 × 5ms = 555ms     │
│ - Savings: 9.4 seconds/day              │
│                                          │
│ Annual Savings (1000 agents/day):        │
│ - Time saved: ~3 hours/day               │
│ - Compute cost: ~50% reduction           │
└──────────────────────────────────────────┘
```

### Observability Benefit

```
┌──────────────────────────────────────────┐
│ Observability Improvement                │
├──────────────────────────────────────────┤
│ Before: Limited visibility               │
│ - Routing happens inline                 │
│ - No event bus tracking                  │
│ - Scattered logs                         │
│                                          │
│ After: Complete visibility               │
│ - All routing via Kafka                  │
│ - Correlation ID tracking                │
│ - Centralized logs                       │
│ - Event replay capability                │
│                                          │
│ Impact:                                  │
│ - Debug time: 50% faster                 │
│ - Issue detection: Real-time             │
│ - Root cause analysis: Complete          │
└──────────────────────────────────────────┘
```

---

## Conclusion

**Current State**:
- ❌ Synchronous Python execution
- ❌ Architectural inconsistency with manifest injection
- ❌ No cache persistence
- ❌ Limited scalability

**Proposed State**:
- ✅ Event-driven via Kafka
- ✅ Unified architecture with manifest injection
- ✅ Service-level caching (>60% hit rate)
- ✅ Horizontal scalability

**Key Benefits**:
- 🚀 **2-13× faster** routing (depending on cache)
- 📊 **Complete observability** via event bus
- 🔄 **Event replay** for debugging
- 📈 **Horizontal scaling** for high load
- 🎯 **Advanced features** (quorum, A/B testing, hot reload)

**Recommendation**: **PROCEED** with implementation

---

**Next**: Read full proposal in `EVENT_DRIVEN_ROUTING_PROPOSAL.md`
