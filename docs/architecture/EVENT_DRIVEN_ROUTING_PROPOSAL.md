> ⚠️ **SUPERSEDED**: This was a pre-implementation proposal. The routing migration described here is complete. Current architecture is documented in `CLAUDE.md` and `docs/architecture/AGENT_ROUTING_ARCHITECTURE.md`. Kept because it is referenced by `plugins/onex/skills/routing/request-agent-routing/SKILL.md`.

---

# Event-Driven Agent Routing Architecture Proposal

**Status**: PROPOSAL (NOT YET IMPLEMENTED)
**Created**: 2025-10-30
**Last Updated**: 2025-10-30
**Author**: Polymorphic Agent (Architecture Review)
**Priority**: HIGH - Addresses critical architectural inconsistency

---

## 🔄 Current Implementation Status

**As of 2025-10-30**:

| Component | Status | Notes |
|-----------|--------|-------|
| **Database Event-Driven** | ✅ COMPLETE | DatabaseEventClient + adapter working |
| **Agent Routing Event-Driven** | ❌ NOT STARTED | Still using synchronous Python exec |
| **Container Registry** | ✅ COMPLETE | Container-based solution (no BaseOnexRegistry) |
| **Kafka Infrastructure** | ✅ OPERATIONAL | <kafka-bootstrap-servers>:9092 |
| **PostgreSQL** | ✅ OPERATIONAL | <postgres-host>:5436 |

**Key Achievement**: The database adapter event-driven implementation has been completed and validated, proving the viability of this architectural pattern.

**This Proposal**: Extends the proven event-driven pattern to agent routing, creating a unified event bus architecture.

---

## Executive Summary

**Problem**: Agent routing uses synchronous Python execution while manifest injection uses event-driven Kafka architecture. This inconsistency creates scalability, observability, and performance issues.

**Solution**: Migrate agent routing to event-driven architecture using Kafka, following the same patterns as manifest injection.

**Impact**:
- 🏗️ **Unified Architecture**: All intelligence operations via Kafka events
- 🚀 **Better Performance**: 30-50ms Python startup overhead eliminated
- 📊 **Improved Observability**: Complete routing traceability via event bus
- 🔄 **Event Replay**: Debug routing decisions by replaying events
- 📈 **Scalability**: Horizontal scaling, connection pooling, service-level caching

---

## Table of Contents

1. [Current Architecture Analysis](#current-architecture-analysis)
2. [Issues with Current Approach](#issues-with-current-approach)
3. [Event-Driven Solution Design](#event-driven-solution-design)
4. [Implementation Plan](#implementation-plan)
5. [Benefits Analysis](#benefits-analysis)
6. [Migration Strategy](#migration-strategy)
7. [Performance Comparison](#performance-comparison)

---

## Current Architecture Analysis

### Manifest Injection (Event-Driven) ✅

**Implementation**: `agents/lib/manifest_injector.py` + `intelligence_event_client.py`

**Architecture**:
```
Agent Spawn
  ↓
ManifestInjector.generate_dynamic_manifest_async()
  ↓
IntelligenceEventClient.start()
  ↓ (publish to Kafka)
Topic: dev.archon-intelligence.intelligence.code-analysis-requested.v1
  ↓ (consumed by)
archon-intelligence-adapter service
  ↓ (queries)
Qdrant + Memgraph + PostgreSQL
  ↓ (publish to Kafka)
Topic: dev.archon-intelligence.intelligence.code-analysis-completed.v1
  ↓ (consumed by)
IntelligenceEventClient receives response
  ↓
Formatted manifest injected into agent prompt
```

**Key Features**:
- ✅ Async request-response pattern with correlation tracking
- ✅ Timeout handling with graceful fallback
- ✅ Context manager support (`async with`)
- ✅ Complete observability via Kafka events
- ✅ Event replay capability
- ✅ Service stays warm, connection pooling
- ✅ ~2000ms total (parallel queries)

**Code Example**:
```python
async with ManifestInjector() as injector:
    manifest = await injector.generate_dynamic_manifest_async(correlation_id)
    formatted = injector.format_for_prompt()
```

---

### Agent Routing (Synchronous) ❌

**Implementation**: Direct Python script execution

**Architecture**:
```
Agent needs routing decision
  ↓
Spawn Python process (30-50ms startup overhead)
  ↓
Load agent_router.py module
  ↓
Initialize AgentRouter class
  ↓
Load YAML registry from disk
  ↓
Build TriggerMatcher, ConfidenceScorer, CapabilityIndex
  ↓
Execute router.route(user_request)
  ↓
Return recommendations synchronously
  ↓
Python process exits (cache lost)
```

**Code Example** (from polymorphic agent instructions):
```python
cd /Volumes/PRO-G40/Code/omniclaude/agents && python3 << 'EOF'
import sys
sys.path.insert(0, '/Volumes/PRO-G40/Code/omniclaude/agents/lib')
from agent_router import AgentRouter

router = AgentRouter()
recommendations = router.route(user_request, max_recommendations=3)

selected_agent = recommendations[0].agent_name
confidence = recommendations[0].confidence.total
reason = recommendations[0].reason

print(f"✅ Selected Agent: {selected_agent}")
print(f"   Confidence: {confidence:.2%}")
print(f"   Reason: {reason}")
EOF
```

**Key Issues**:
- ❌ Python process startup overhead (30-50ms minimum)
- ❌ YAML registry reloaded every time
- ❌ Indexes rebuilt every time (TriggerMatcher, CapabilityIndex)
- ❌ ResultCache lost between executions (in-memory only)
- ❌ No correlation with manifest injection events
- ❌ Harder to trace across distributed agents
- ❌ No event replay capability
- ❌ No service-level features (circuit breaker, quorum, A/B testing)

---

## Issues with Current Approach

### 1. Architectural Inconsistency

**Problem**: Two different patterns for intelligence operations

| Operation | Pattern | Technology | Performance |
|-----------|---------|------------|-------------|
| Manifest Injection | Event-driven | Kafka + async | ~2000ms (parallel) |
| Agent Routing | Synchronous | Python exec | ~50-80ms (blocking) |

**Impact**:
- Developers must learn two different patterns
- Different error handling strategies
- Different observability approaches
- No unified correlation tracking

---

### 2. Scalability Problems

**Python Process Overhead**:
```
Single Routing Request:
- Python interpreter startup: 30-50ms
- Module imports: 10-20ms
- YAML parsing: 5-10ms
- Index building: 10-20ms
- Actual routing: 20-30ms
---------------------------------
Total: 75-130ms (startup overhead: 55-100ms)
```

**Multi-Agent Scenario**:
```
3 agents need routing decisions:
- Sequential: 75ms × 3 = 225ms
- Parallel: Still 75ms per agent (no shared cache)
- Memory: 3 Python processes × ~50MB = ~150MB
```

**Event-Driven Service**:
```
3 agents need routing decisions:
- Service warm startup: 0ms (already running)
- Cache hits: <5ms per request
- Memory: Single service process (~50MB shared)
- Network overhead: ~10ms per request
---------------------------------
Total: ~15ms per agent (15× faster!)
```

---

### 3. Observability Gaps

**Current State** (Synchronous Routing):
- ❌ Routing decisions happen inline in agent process
- ❌ No correlation with manifest injection events
- ❌ Logging scattered across agent processes
- ❌ No centralized routing metrics
- ❌ Hard to debug routing failures across distributed agents

**Event-Driven State** (Proposed):
- ✅ All routing decisions flow through Kafka
- ✅ Correlation ID links routing → manifest → execution
- ✅ Centralized logging in routing service
- ✅ Routing metrics aggregated in PostgreSQL
- ✅ Complete trace from user prompt to agent selection

**Database Traceability**:

Current:
```sql
-- Only routing decisions logged to database AFTER routing completes
SELECT * FROM agent_routing_decisions WHERE correlation_id = '...';
-- No live routing request tracking
```

Proposed:
```sql
-- Complete lifecycle: request → processing → decision
SELECT * FROM agent_routing_requests WHERE correlation_id = '...';
-- Shows: request_time, processing_time, decision_time, cache_hit
```

---

### 4. Performance Issues

**Routing Cache Ineffectiveness**:

Current (In-Memory Per-Process):
```python
# agents/lib/result_cache.py
class ResultCache:
    def __init__(self, default_ttl_seconds=3600):
        self._cache: Dict[str, CacheEntry] = {}  # Lost when process exits!
```

**Problem**:
- Cache hit rate: ~0% (cache lost between requests)
- Every routing request is a cache miss
- No benefit from caching logic

Proposed (Service-Level Persistent):
```python
# Cache survives across requests
# Target hit rate: >60%
# Cache misses only on first request or after TTL
```

**Performance Breakdown**:

| Component | Current (Python Exec) | Proposed (Event Service) |
|-----------|----------------------|--------------------------|
| Python startup | 30-50ms | 0ms (service running) |
| Module imports | 10-20ms | 0ms (already imported) |
| YAML parsing | 5-10ms | 0ms (registry cached) |
| Index building | 10-20ms | 0ms (indexes pre-built) |
| Network overhead | 0ms | 10-15ms (Kafka) |
| Actual routing | 20-30ms | 20-30ms (same) |
| **Total** | **75-130ms** | **30-45ms** (cache miss) |
| **Total** | **75-130ms** | **<10ms** (cache hit) |

---

### 5. Flexibility Limitations

**Current Limitations**:

1. **No A/B Testing**:
   - Can't test new routing strategies without code changes
   - No gradual rollout capability
   - Hard to compare routing accuracy between strategies

2. **No Routing Quorum**:
   - Single routing strategy decides (no consensus)
   - No fallback if primary strategy fails
   - Can't combine multiple strategies for confidence

3. **No Hot Reload**:
   - Registry changes require agent restarts
   - Can't update agent definitions without downtime
   - No gradual rollout of new agent capabilities

4. **No Circuit Breaker**:
   - No detection of routing service failures
   - No automatic fallback to backup routing
   - No health monitoring

**Event-Driven Enables**:

1. **A/B Testing**:
   ```python
   # Route 10% of requests to new strategy
   if random.random() < 0.1:
       routing_strategy = "experimental_semantic_matching"
   else:
       routing_strategy = "enhanced_fuzzy_matching"
   ```

2. **Routing Quorum**:
   ```python
   # Get recommendations from multiple strategies
   strategies = ["fuzzy", "semantic", "capability"]
   results = await asyncio.gather(*[
       strategy.route(user_request) for strategy in strategies
   ])
   # Vote on consensus
   selected_agent = vote(results, threshold=0.7)
   ```

3. **Hot Reload**:
   ```python
   # Service watches for registry changes
   async def watch_registry_changes():
       async for event in registry_watcher:
           await router.reload_registry()
           logger.info("Registry hot-reloaded")
   ```

4. **Circuit Breaker**:
   ```python
   # Detect routing service failures
   if routing_service_failures > threshold:
       logger.warning("Routing service circuit open - using fallback")
       return local_routing_fallback(user_request)
   ```

---

## Event-Driven Solution Design

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     UNIFIED EVENT BUS ARCHITECTURE              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Agent Hook/Spawn                                               │
│    │                                                            │
│    ├─► Publish: agent.routing.requested.v1                     │
│    │   (correlation_id, user_request, context)                 │
│    │                                                            │
│    ├─► Publish: intelligence.code-analysis-requested.v1        │
│    │   (correlation_id, operation_type, options)               │
│    │                                                            │
│    ▼                                                            │
│  Kafka Event Bus (<kafka-bootstrap-servers>:9092)                         │
│    │                                                            │
│    ├─► agent-router-service (NEW)                              │
│    │   - Consumes: agent.routing.requested.v1                  │
│    │   - AgentRouter (warm, cached)                            │
│    │   - Publishes: agent.routing.completed.v1                 │
│    │                                                            │
│    ├─► archon-intelligence-adapter (EXISTING)                  │
│    │   - Consumes: intelligence.code-analysis-requested.v1     │
│    │   - Queries: Qdrant, Memgraph, PostgreSQL                 │
│    │   - Publishes: intelligence.code-analysis-completed.v1    │
│    │                                                            │
│    ▼                                                            │
│  Agent Receives:                                                │
│    - Routing decision (selected_agent, confidence, reason)      │
│    - Manifest intelligence (patterns, debug intel, schemas)     │
│    │                                                            │
│    ▼                                                            │
│  Agent Executes as Selected Agent                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### Event Schema Design

**Request Event** (`agent.routing.requested.v1`):
```json
{
  "event_id": "uuid",
  "event_type": "AGENT_ROUTING_REQUESTED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T14:30:00Z",
  "service": "polymorphic-agent",
  "payload": {
    "user_request": "optimize my database queries",
    "context": {
      "domain": "database_optimization",
      "previous_agent": "agent-api-architect",
      "current_file": "api/database.py"
    },
    "options": {
      "max_recommendations": 3,
      "min_confidence": 0.6,
      "routing_strategy": "enhanced_fuzzy_matching"
    }
  }
}
```

**Response Event** (`agent.routing.completed.v1`):
```json
{
  "event_id": "uuid",
  "event_type": "AGENT_ROUTING_COMPLETED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T14:30:00.045Z",
  "service": "agent-router-service",
  "payload": {
    "recommendations": [
      {
        "agent_name": "agent-performance",
        "agent_title": "Performance Optimization Specialist",
        "confidence": {
          "total": 0.92,
          "trigger_score": 0.95,
          "context_score": 0.90,
          "capability_score": 0.88,
          "historical_score": 0.95,
          "explanation": "High confidence match on 'optimize' and 'database' triggers"
        },
        "reason": "Strong trigger match with 'optimize' keyword and database context",
        "definition_path": "/Users/jonah/.claude/agent-definitions/agent-performance.yaml"
      }
    ],
    "routing_metadata": {
      "routing_time_ms": 45,
      "cache_hit": false,
      "candidates_evaluated": 5,
      "routing_strategy": "enhanced_fuzzy_matching"
    }
  }
}
```

**Error Event** (`agent.routing.failed.v1`):
```json
{
  "event_id": "uuid",
  "event_type": "AGENT_ROUTING_FAILED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T14:30:00.100Z",
  "service": "agent-router-service",
  "payload": {
    "error_code": "REGISTRY_LOAD_FAILED",
    "error_message": "Failed to load agent registry: file not found",
    "fallback_recommendation": {
      "agent_name": "polymorphic-agent",
      "reason": "Fallback to polymorphic agent due to routing failure"
    }
  }
}
```

---

### Service Implementation

**agent-router-service** (New Service):

**Location**: `agents/services/agent-router-service/`

**Reference Implementation**: The database adapter (`omninode_bridge/src/omninode_bridge/nodes/effects/database_adapter/`) provides a proven pattern for this service. Key learnings:
- ✅ Request-response pattern via Kafka works well
- ✅ Container-based registry (no BaseOnexRegistry dependency needed)
- ✅ Correlation tracking enables complete traceability
- ✅ Graceful degradation with timeout handling
- ✅ Health checks and observability patterns established

**Structure**:
```
agents/services/agent-router-service/
├── main.py                    # Service entry point
├── router_event_handler.py    # Kafka consumer/producer
├── router_service.py          # Business logic wrapper
├── config.py                  # Service configuration
├── health_check.py            # Health endpoint
├── metrics.py                 # Prometheus metrics
├── Dockerfile                 # Container definition
└── docker-compose.yml         # Service deployment
```

**Key Components**:

1. **RouterEventHandler** (Kafka Integration):
```python
class RouterEventHandler:
    """
    Handles routing request/response events via Kafka.

    Similar to IntelligenceEventClient but for routing operations.
    """

    async def start(self):
        """Start producer and consumer."""
        self.producer = AIOKafkaProducer(...)
        self.consumer = AIOKafkaConsumer(
            "agent.routing.requested.v1",
            ...
        )
        await self.producer.start()
        await self.consumer.start()
        asyncio.create_task(self._consume_requests())

    async def _consume_requests(self):
        """Consume routing requests and publish responses."""
        async for msg in self.consumer:
            request = msg.value
            correlation_id = request["correlation_id"]

            try:
                # Use existing AgentRouter (stays warm!)
                recommendations = self.router.route(
                    user_request=request["payload"]["user_request"],
                    context=request["payload"].get("context"),
                    max_recommendations=request["payload"]["options"]["max_recommendations"]
                )

                # Publish success response
                await self._publish_routing_completed(
                    correlation_id=correlation_id,
                    recommendations=recommendations
                )

            except Exception as e:
                # Publish error response
                await self._publish_routing_failed(
                    correlation_id=correlation_id,
                    error=e
                )
```

2. **RouterService** (Business Logic):
```python
class RouterService:
    """
    Wraps AgentRouter with service-level features.

    Adds:
    - Persistent caching across requests
    - Metrics collection
    - Circuit breaker for fallback
    - Registry hot reload
    """

    def __init__(self):
        self.router = AgentRouter()
        self.cache_stats = CacheStats()
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            timeout_seconds=60
        )

    async def route(self, user_request: str, context: Dict, options: Dict):
        """
        Route request with service-level enhancements.
        """
        # Check circuit breaker
        if self.circuit_breaker.is_open:
            return self._fallback_routing(user_request)

        try:
            # Use existing AgentRouter
            recommendations = self.router.route(
                user_request=user_request,
                context=context,
                max_recommendations=options.get("max_recommendations", 5)
            )

            # Record success
            self.circuit_breaker.record_success()
            self.cache_stats.record_hit() if cache_hit else self.cache_stats.record_miss()

            return recommendations

        except Exception as e:
            # Record failure
            self.circuit_breaker.record_failure()
            logger.error(f"Routing failed: {e}")
            return self._fallback_routing(user_request)

    async def hot_reload_registry(self):
        """Reload registry without service restart."""
        await self.router.reload_registry()
        logger.info("Registry hot-reloaded")
```

---

### Client Integration

**RoutingEventClient** (New Client):

**Location**: `agents/lib/routing_event_client.py`

**Interface**:
```python
class RoutingEventClient:
    """
    Kafka client for agent routing requests.

    Mirrors IntelligenceEventClient API for consistency.
    """

    TOPIC_REQUEST = "agent.routing.requested.v1"
    TOPIC_COMPLETED = "agent.routing.completed.v1"
    TOPIC_FAILED = "agent.routing.failed.v1"

    async def request_routing(
        self,
        user_request: str,
        context: Optional[Dict] = None,
        max_recommendations: int = 5,
        timeout_ms: int = 5000
    ) -> List[AgentRecommendation]:
        """
        Request agent routing via events.

        Args:
            user_request: User's input text
            context: Optional execution context
            max_recommendations: Maximum recommendations
            timeout_ms: Response timeout

        Returns:
            List of agent recommendations

        Raises:
            TimeoutError: If no response within timeout
            KafkaError: If Kafka communication fails
        """
        correlation_id = str(uuid4())

        # Build request payload
        request_payload = {
            "event_id": str(uuid4()),
            "event_type": "AGENT_ROUTING_REQUESTED",
            "correlation_id": correlation_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "polymorphic-agent",
            "payload": {
                "user_request": user_request,
                "context": context or {},
                "options": {
                    "max_recommendations": max_recommendations,
                    "min_confidence": 0.6,
                    "routing_strategy": "enhanced_fuzzy_matching"
                }
            }
        }

        # Publish and wait for response
        result = await self._publish_and_wait(
            correlation_id=correlation_id,
            payload=request_payload,
            timeout_ms=timeout_ms
        )

        # Parse recommendations
        return [
            AgentRecommendation(**rec)
            for rec in result["recommendations"]
        ]
```

**Usage in Polymorphic Agent**:
```python
from routing_event_client import RoutingEventClient

async with RoutingEventClient() as client:
    recommendations = await client.request_routing(
        user_request="optimize my database queries",
        max_recommendations=3
    )

    selected_agent = recommendations[0].agent_name
    confidence = recommendations[0].confidence.total
    reason = recommendations[0].reason
```

---

## Implementation Plan

### Phase 1: Event-Driven Routing Service (Week 1-2)

**Status**: ⏳ NOT STARTED

**Goal**: Create `agent-router-service` that consumes routing requests

**Tasks**:

1. ⬜ Create service structure
   ```bash
   mkdir -p agents/services/agent-router-service
   ```

2. ⬜ Implement RouterEventHandler
   - Kafka consumer for `agent.routing.requested.v1`
   - Kafka producer for `agent.routing.completed.v1`, `agent.routing.failed.v1`
   - Request-response pattern with correlation tracking

3. ⬜ Implement RouterService wrapper
   - Use existing `AgentRouter` class (no rewrite needed!)
   - Add circuit breaker for fallback
   - Add metrics collection
   - Add registry hot reload

4. ⬜ Create Dockerfile and docker-compose.yml
   ```yaml
   services:
     agent-router-service:
       build: agents/services/agent-router-service
       ports:
         - "8055:8055"  # Health check endpoint
       environment:
         - KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092
         - REGISTRY_PATH=/Users/jonah/.claude/agent-definitions/agent-registry.yaml
       volumes:
         - ~/.claude/agent-definitions:/agent-definitions:ro
   ```

5. ⬜ Add health check endpoint
   ```python
   @app.get("/health")
   async def health():
       return {
           "status": "healthy",
           "router_loaded": router is not None,
           "cache_hit_rate": router.get_cache_stats()["cache_hit_rate"],
           "uptime_seconds": time.time() - start_time
       }
   ```

**Validation Criteria**:
- ⬜ Service starts and connects to Kafka
- ⬜ Service consumes routing requests
- ⬜ Service publishes routing responses
- ⬜ Health check returns 200 OK
- ⬜ Metrics endpoint shows routing stats

---

### Phase 2: Client Integration (Week 2-3)

**Status**: ⏳ NOT STARTED

**Goal**: Create `RoutingEventClient` for agent hooks

**Tasks**:

1. ⬜ Create `agents/lib/routing_event_client.py`
   - Mirror `IntelligenceEventClient` API (proven pattern from database adapter)
   - Same request-response pattern
   - Same timeout handling

2. ⬜ Add backward compatibility wrapper
   ```python
   # agents/lib/agent_router.py

   def route_via_events(
       user_request: str,
       context: Optional[Dict] = None,
       max_recommendations: int = 5,
       timeout_ms: int = 5000
   ) -> List[AgentRecommendation]:
       """
       Route request via events (async wrapper for backward compatibility).
       """
       import asyncio

       async def _route():
           async with RoutingEventClient() as client:
               return await client.request_routing(
                   user_request=user_request,
                   context=context,
                   max_recommendations=max_recommendations,
                   timeout_ms=timeout_ms
               )

       return asyncio.run(_route())
   ```

3. ⬜ Update polymorphic agent instructions
   ```python
   # OLD (synchronous Python exec)
   cd agents && python3 << 'EOF'
   from agent_router import AgentRouter
   router = AgentRouter()
   recommendations = router.route(user_request)
   EOF

   # NEW (event-driven)
   from agents.lib.routing_event_client import RoutingEventClient

   async with RoutingEventClient() as client:
       recommendations = await client.request_routing(user_request)
   ```

4. ⬜ Add fallback mechanism
   ```python
   try:
       # Try event-driven routing first
       recommendations = await client.request_routing(...)
   except (TimeoutError, KafkaError) as e:
       logger.warning(f"Event routing failed: {e}, using local fallback")
       # Fallback to local routing
       router = AgentRouter()
       recommendations = router.route(...)
   ```

**Validation Criteria**:
- ⬜ Event routing works end-to-end
- ⬜ Fallback works when service unavailable
- ⬜ Performance meets targets (<50ms routing time)
- ⬜ All correlation IDs tracked correctly

---

### Phase 3: Parallel Running & A/B Testing (Week 3-4)

**Status**: ⏳ NOT STARTED

**Goal**: Run both approaches in parallel, compare results

**Tasks**:

1. ⬜ Implement parallel execution
   ```python
   # Run both routing approaches in parallel
   event_task = client.request_routing(user_request)
   local_task = asyncio.to_thread(AgentRouter().route, user_request)

   event_result, local_result = await asyncio.gather(
       event_task, local_task, return_exceptions=True
   )

   # Compare results
   if event_result != local_result:
       logger.warning(f"Routing mismatch: event={event_result}, local={local_result}")
   ```

2. ⬜ Add comparison metrics
   ```sql
   CREATE TABLE routing_comparison_metrics (
       id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       correlation_id UUID NOT NULL,
       event_agent TEXT,
       local_agent TEXT,
       match BOOLEAN,
       event_confidence NUMERIC(5,4),
       local_confidence NUMERIC(5,4),
       event_time_ms INTEGER,
       local_time_ms INTEGER,
       created_at TIMESTAMPTZ DEFAULT NOW()
   );
   ```

3. ⬜ Generate comparison report
   ```python
   # Compare routing accuracy
   SELECT
       COUNT(*) as total_comparisons,
       SUM(CASE WHEN match THEN 1 ELSE 0 END) as matches,
       (SUM(CASE WHEN match THEN 1 ELSE 0 END)::FLOAT / COUNT(*)) * 100 as match_rate,
       AVG(event_time_ms) as avg_event_time,
       AVG(local_time_ms) as avg_local_time
   FROM routing_comparison_metrics
   WHERE created_at > NOW() - INTERVAL '24 hours';
   ```

4. ⬜ Gradual rollout
   ```python
   # Route 10% to event service, 90% to local
   if random.random() < 0.1:
       recommendations = await client.request_routing(...)
   else:
       recommendations = AgentRouter().route(...)
   ```

**Validation Criteria**:
- ⬜ Match rate >95% (event vs local routing)
- ⬜ Event routing faster than local (after warmup)
- ⬜ No regressions in routing quality
- ⬜ Gradual rollout works correctly

---

### Phase 4: Deprecate Synchronous API (Week 4-5)

**Status**: ⏳ NOT STARTED

**Goal**: Migrate all usage to event-driven routing

**Tasks**:

1. ⬜ Audit all AgentRouter usage
   ```bash
   grep -r "AgentRouter()" --include="*.py"
   ```

2. ⬜ Update all call sites to use event routing
   - Polymorphic agent instructions
   - Hook scripts
   - Test files

3. ⬜ Add deprecation warnings
   ```python
   # agents/lib/agent_router.py

   class AgentRouter:
       def __init__(self, *args, **kwargs):
           warnings.warn(
               "Direct AgentRouter usage is deprecated. "
               "Use RoutingEventClient for event-driven routing.",
               DeprecationWarning,
               stacklevel=2
           )
   ```

4. ⬜ Remove synchronous routing from polymorphic agent
   - Keep as fallback only
   - Primary path: event-driven

**Validation Criteria**:
- ⬜ All production usage migrated
- ⬜ Tests still pass
- ⬜ Deprecation warnings logged
- ⬜ Documentation updated

---

### Phase 5: Advanced Features (Week 5-6)

**Status**: ⏳ NOT STARTED

**Goal**: Add routing quorum, A/B testing, hot reload

**Tasks**:

1. ⬜ Implement routing quorum
   ```python
   # Get recommendations from multiple strategies
   strategies = ["fuzzy", "semantic", "capability"]
   results = await asyncio.gather(*[
       strategy_router.route(user_request) for strategy_router in routers
   ])

   # Vote on consensus
   votes = defaultdict(int)
   for result in results:
       votes[result[0].agent_name] += result[0].confidence.total

   # Select agent with highest total vote
   selected_agent = max(votes, key=votes.get)
   ```

2. ⬜ Implement A/B testing framework
   ```python
   # Route based on experiment assignment
   experiment_group = hash(correlation_id) % 100

   if experiment_group < 10:  # 10% experimental
       routing_strategy = "experimental_semantic_matching"
   else:  # 90% control
       routing_strategy = "enhanced_fuzzy_matching"
   ```

3. ⬜ Implement registry hot reload
   ```python
   # Watch for registry file changes
   async def watch_registry():
       last_mtime = os.path.getmtime(registry_path)
       while True:
           await asyncio.sleep(10)
           current_mtime = os.path.getmtime(registry_path)
           if current_mtime > last_mtime:
               logger.info("Registry file changed, reloading...")
               await router.reload_registry()
               last_mtime = current_mtime
   ```

**Validation Criteria**:
- ⬜ Routing quorum improves accuracy
- ⬜ A/B testing tracks experiment results
- ⬜ Hot reload works without service restart

---

## Benefits Analysis

### Performance Comparison

| Metric | Current (Python Exec) | Proposed (Event Service) | Improvement |
|--------|----------------------|--------------------------|-------------|
| **Cold Start** | 75-130ms | 30-45ms | **2-3× faster** |
| **Warm Start** | 75-130ms (no warmth) | <10ms (cache hit) | **7-13× faster** |
| **Multi-Agent (3)** | 225ms sequential | 30ms parallel | **7.5× faster** |
| **Memory Overhead** | 150MB (3 processes) | 50MB (1 service) | **3× less** |
| **Cache Hit Rate** | ~0% (lost) | >60% (persistent) | **∞ improvement** |
| **Network Overhead** | 0ms | 10-15ms | +10-15ms |
| **Total (cache miss)** | 75-130ms | 40-60ms | **2× faster** |
| **Total (cache hit)** | 75-130ms | <10ms | **7-13× faster** |

**Real-World Scenario**:
```
10 agents spawn over 1 hour:
- Current: 10 × 100ms = 1000ms routing overhead
- Proposed: 1 × 45ms + 9 × 5ms (cache hits) = 90ms routing overhead
- Savings: 910ms (10× faster)
```

---

### Scalability Comparison

**Horizontal Scaling**:

Current (Python Exec):
- ❌ Can't scale routing separately from agents
- ❌ Each agent spawns own Python process
- ❌ No connection pooling
- ❌ No load balancing

Proposed (Event Service):
- ✅ Scale routing service independently
- ✅ Multiple routing service instances
- ✅ Connection pooling via Kafka consumer groups
- ✅ Load balancing via Kafka partitions

**Example**:
```yaml
# Scale to 3 routing service instances
docker-compose scale agent-router-service=3

# Kafka automatically balances requests across instances
# Each instance shares the work via consumer group
```

---

### Observability Comparison

**Traceability**:

Current:
```
User Request
  ↓
??? (routing happens inline, not logged)
  ↓
Selected Agent
  ↓
Agent Execution
```

Proposed:
```
User Request (correlation_id: abc123)
  ↓
agent.routing.requested.v1 (correlation_id: abc123)
  ↓
agent-router-service processes
  ↓
agent.routing.completed.v1 (correlation_id: abc123)
  ↓
Selected Agent (correlation_id: abc123)
  ↓
intelligence.code-analysis-requested.v1 (correlation_id: abc123)
  ↓
Manifest Injection (correlation_id: abc123)
  ↓
Agent Execution (correlation_id: abc123)
```

**Database Queries**:

Current:
```sql
-- Only see routing decision after it's done
SELECT * FROM agent_routing_decisions
WHERE correlation_id = 'abc123';
```

Proposed:
```sql
-- See complete lifecycle
SELECT
    rr.created_at as request_time,
    rd.created_at as decision_time,
    ami.created_at as manifest_time,
    ael.created_at as execution_time,
    rd.selected_agent,
    rd.confidence_score,
    ami.patterns_count,
    ael.status
FROM agent_routing_requests rr
LEFT JOIN agent_routing_decisions rd ON rd.correlation_id = rr.correlation_id
LEFT JOIN agent_manifest_injections ami ON ami.correlation_id = rr.correlation_id
LEFT JOIN agent_execution_logs ael ON ael.correlation_id = rr.correlation_id
WHERE rr.correlation_id = 'abc123';
```

---

### Feature Comparison

| Feature | Current | Proposed | Notes |
|---------|---------|----------|-------|
| **Routing Speed** | 75-130ms | 5-45ms | Event service faster after warmup |
| **Cache Persistence** | ❌ Lost | ✅ Persistent | Service-level cache survives |
| **Event Replay** | ❌ No | ✅ Yes | Replay routing decisions for debugging |
| **Circuit Breaker** | ❌ No | ✅ Yes | Fallback when service down |
| **A/B Testing** | ❌ No | ✅ Yes | Test new routing strategies |
| **Routing Quorum** | ❌ No | ✅ Yes | Consensus across strategies |
| **Hot Reload** | ❌ No | ✅ Yes | Update registry without restart |
| **Metrics** | ⚠️ Limited | ✅ Full | Centralized Prometheus metrics |
| **Correlation Tracking** | ⚠️ Partial | ✅ Complete | End-to-end correlation IDs |
| **Scalability** | ❌ Process-per-agent | ✅ Horizontal | Scale routing independently |

---

## Migration Strategy

### Backward Compatibility

**Principle**: Support both approaches during transition

**Implementation**:
```python
# agents/lib/agent_router.py

def route(
    user_request: str,
    context: Optional[Dict] = None,
    use_events: bool = True,  # Default to event-driven
    fallback_on_error: bool = True,
    **kwargs
) -> List[AgentRecommendation]:
    """
    Route request with automatic fallback.

    Args:
        user_request: User's input text
        context: Optional execution context
        use_events: Use event-driven routing (default: True)
        fallback_on_error: Fallback to local routing on failure
        **kwargs: Additional routing options

    Returns:
        List of agent recommendations
    """
    if use_events:
        try:
            # Try event-driven routing first
            return route_via_events(
                user_request=user_request,
                context=context,
                **kwargs
            )
        except (TimeoutError, KafkaError) as e:
            if fallback_on_error:
                logger.warning(f"Event routing failed: {e}, using local fallback")
                # Fall through to local routing
            else:
                raise

    # Local routing (fallback or explicitly requested)
    router = AgentRouter()
    return router.route(
        user_request=user_request,
        context=context,
        **kwargs
    )
```

---

### Rollout Plan

**Week 1-2**: Phase 1 (Service Development)
- ⬜ Build agent-router-service
- ⬜ Deploy to test environment
- ⬜ Validate basic functionality
- **Status**: ⏳ NOT STARTED

**Week 2-3**: Phase 2 (Client Integration)
- ⬜ Create RoutingEventClient
- ⬜ Add to polymorphic agent (with feature flag)
- ⬜ Validate end-to-end flow
- **Status**: ⏳ NOT STARTED

**Week 3-4**: Phase 3 (Parallel Running)
- ⬜ 10% traffic to event service
- ⬜ Compare results (match rate >95%)
- ⬜ 50% traffic to event service
- ⬜ Monitor performance
- **Status**: ⏳ NOT STARTED

**Week 4-5**: Phase 4 (Full Migration)
- ⬜ 100% traffic to event service
- ⬜ Keep local routing as fallback only
- ⬜ Update documentation
- **Status**: ⏳ NOT STARTED

**Week 5-6**: Phase 5 (Advanced Features)
- ⬜ Add routing quorum
- ⬜ Add A/B testing framework
- ⬜ Add hot reload capability
- **Status**: ⏳ NOT STARTED

---

### Rollback Plan

**If event routing has issues**:

1. **Immediate Rollback** (< 5 minutes):
   ```python
   # Set feature flag to disable event routing
   export USE_EVENT_ROUTING=false

   # All routing falls back to local immediately
   ```

2. **Service Restart** (< 1 minute):
   ```bash
   docker-compose restart agent-router-service
   ```

3. **Full Rollback** (< 30 minutes):
   ```bash
   # Revert polymorphic agent instructions
   git revert <commit>

   # Remove event routing flag
   export USE_EVENT_ROUTING=false
   ```

**Monitoring**:
- Track event routing success rate
- Alert if success rate < 90%
- Auto-fallback if service unhealthy

---

## Conclusion

**Current State** (Agent Routing):
- ❌ Routing uses synchronous Python execution
- ❌ No caching persistence across requests
- ❌ No event-driven observability
- ❌ Limited scalability

**Proposed State** (Agent Routing):
- ✅ Routing uses event-driven Kafka architecture
- ✅ Service-level caching (>60% hit rate)
- ✅ Complete event bus observability
- ✅ Horizontal scalability

**Validation** (Database Event-Driven):
- ✅ **Database adapter event-driven implementation complete** (2025-10-30)
- ✅ **Container-based registry solution working**
- ✅ **Request-response pattern proven**
- ✅ **Kafka infrastructure operational**
- ✅ **Pattern validated and ready to extend to routing**

**Impact**:
- 🚀 **2-13× faster routing** (depending on cache)
- 📊 **Complete traceability** via correlation IDs
- 🔄 **Event replay** for debugging
- 📈 **Horizontal scaling** for high load
- 🎯 **Advanced features** (quorum, A/B testing, hot reload)
- 🏗️ **Unified architecture** (all intelligence operations via Kafka)

**Recommendation**: **APPROVE** and proceed with implementation.

This proposal addresses a critical architectural inconsistency and brings routing in line with the proven event-driven intelligence architecture. The migration path is low-risk with backward compatibility and multiple validation phases. **The database adapter implementation has validated this approach and provides a proven reference implementation.**

---

## Related Documentation

**Architecture Comparisons**:
- [Agent Traceability](../observability/AGENT_TRACEABILITY.md) - Observability architecture (deprecated)

**Next Steps**:
1. ✅ Review database adapter implementation for patterns
2. ⬜ Review and approve routing proposal
3. ⬜ Create implementation tasks
4. ⬜ Allocate development resources
5. ⬜ Begin Phase 1 (service development)

**Questions or Concerns?**:
- Contact: Polymorphic Agent
- Reference: This document
- Related: `docs/observability/AGENT_TRACEABILITY.md`
