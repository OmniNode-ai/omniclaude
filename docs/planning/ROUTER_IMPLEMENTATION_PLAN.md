# Universal Agent Router - Implementation Plan

**Status**: Blocked - Awaiting PR #22 merge
**Target Start Date**: TBD (after PR #22 resolution)
**Estimated Duration**: 4 weeks (20 working days)
**Team**: 1-2 developers
**Last Updated**: 2025-11-07

---

## Prerequisites (BLOCKING)

### Critical Blocker: PR #22

**PR Details**:
- **Number**: #22
- **Title**: "feat: Complete observability infrastructure with action logging and pattern cleanup"
- **Branch**: `fix/observability-data-flow-gaps`
- **Status**: OPEN, MERGEABLE (but checks failing)

**CI/CD Issues** (3 failing checks):
1. **Code Quality Checks** - FAIL (4m59s)
   - Likely: Linting issues, code formatting, complexity warnings

2. **Python Security Scan** - FAIL (4m10s)
   - Likely: Bandit security warnings, dependency vulnerabilities

3. **Run Tests** - FAIL (5m13s)
   - Likely: Unit test failures, integration test issues

**CodeRabbit Review Issues**:
- **9 actionable comments** (must address)
- **4 critical outside-diff comments** (high priority):
  1. `routing_event_client.py` - Cleanup logic in `stop()` method
  2. `omninode_template_engine.py` - Kafka URL normalization (2 locations)
  3. `agent_coder.py` - Model metadata mismatch

- **12 nitpick comments** (optional but recommended)

**Estimated Resolution Time**: 1-2 days
**Estimated Merge Date**: 2025-11-08 or 2025-11-09

### Infrastructure Verification

Before starting Phase 1, verify:

```bash
# 1. PostgreSQL connectivity
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"

# 2. Kafka/Redpanda health
docker exec omninode-bridge-redpanda rpk cluster health

# 3. vLLM endpoint
curl http://192.168.86.200:11434/v1/models

# 4. Valkey/Redis (will be added)
# redis-cli -h localhost -p 6379 PING

# 5. Agent registry exists
ls ~/.claude/agent-definitions/
```

**Expected Results**:
- ✅ PostgreSQL: Returns `1`
- ✅ Kafka: Shows healthy cluster
- ✅ vLLM: Returns model list (including Llama-3.1-8B-Instruct)
- ⏳ Valkey: Will be added in Phase 1
- ✅ Agent registry: Contains YAML files

---

## Phase 1: Foundation (Week 1)

**Duration**: 5 working days (Mon-Fri)
**Goal**: Core routing service with HTTP API, Valkey caching, and fuzzy fallback

### Day 1 (Monday): Service Scaffold

**Tasks**:

1. **Create directory structure**
   ```bash
   mkdir -p services/universal_router/
   mkdir -p services/universal_router/api/
   mkdir -p services/universal_router/core/
   mkdir -p services/universal_router/models/
   mkdir -p services/universal_router/tests/
   ```

2. **FastAPI application setup**
   - File: `services/universal_router/main.py`
   - Includes: CORS middleware, request logging, error handlers
   - Health endpoint: `GET /v1/health`

3. **Request/response models**
   - File: `services/universal_router/models/request.py`
   - Models: `UniversalRouteRequest`, `RouteOptions`, `RequestContext`
   - Validation: Pydantic validators for all fields

4. **Response models**
   - File: `services/universal_router/models/response.py`
   - Models: `RouteResponse`, `AgentRecommendation`, `PerformanceMetrics`

5. **Correlation ID generation**
   - File: `services/universal_router/core/correlation.py`
   - Function: `generate_correlation_id() -> str`
   - Middleware: Inject correlation ID into all requests

**Acceptance Criteria**:
- ✅ FastAPI app starts without errors
- ✅ Health endpoint returns 200 OK
- ✅ Request models validate correctly
- ✅ Correlation IDs generated for all requests
- ✅ Basic logging to stdout

**Testing**:
```bash
# Start service
cd services/universal_router && uvicorn main:app --reload

# Test health endpoint
curl http://localhost:8070/v1/health
# Expected: {"status": "healthy", "version": "1.0.0"}

# Test route endpoint (should fail - not implemented yet)
curl -X POST http://localhost:8070/v1/route \
  -H "Content-Type: application/json" \
  -d '{"request": "test"}'
# Expected: 501 Not Implemented
```

**Deliverables**:
- [ ] `services/universal_router/main.py` - FastAPI app
- [ ] `services/universal_router/api/routes.py` - Route endpoints
- [ ] `services/universal_router/models/request.py` - Request models
- [ ] `services/universal_router/models/response.py` - Response models
- [ ] `services/universal_router/core/correlation.py` - Correlation ID logic

---

### Day 2 (Tuesday): Valkey Integration

**Tasks**:

1. **Add Valkey to docker-compose**
   - File: `deployment/docker-compose.yml`
   - Service: `valkey`
   - Port: 6379
   - Volume: `valkey_data:/data`
   - Config: `maxmemory 512mb`, `maxmemory-policy allkeys-lru`

2. **Valkey client setup**
   - File: `services/universal_router/cache/client.py`
   - Library: `redis[hiredis]` (Valkey-compatible)
   - Features: Connection pooling, async support, retry logic

3. **Cache key generation**
   - File: `services/universal_router/cache/keys.py`
   - Function: `generate_cache_key(request: UniversalRouteRequest) -> str`
   - Format: `router:v1:{hash(request_text + context_fingerprint)}`
   - Hash: SHA256 truncated to 16 chars

4. **Cache operations**
   - File: `services/universal_router/cache/operations.py`
   - Functions: `cache_get()`, `cache_set()`, `cache_delete()`, `cache_exists()`
   - TTL: 3600 seconds (1 hour)

5. **Cache invalidation**
   - File: `services/universal_router/cache/invalidation.py`
   - Functions: `invalidate_all()`, `invalidate_pattern()`, `invalidate_agent()`

**Acceptance Criteria**:
- ✅ Valkey service starts in Docker Compose
- ✅ Cache client connects successfully
- ✅ Cache set/get operations work
- ✅ TTL expiry works (test with 10s TTL)
- ✅ Pattern-based invalidation works

**Testing**:
```bash
# Start Valkey
docker-compose up -d valkey

# Test connection
redis-cli -h localhost -p 6379 PING
# Expected: PONG

# Run cache tests
pytest services/universal_router/tests/test_cache.py -v

# Manual cache test
python3 -c "
from services.universal_router.cache.client import CacheClient
import asyncio

async def test():
    cache = CacheClient()
    await cache.set('test', 'value', ttl=10)
    result = await cache.get('test')
    print(f'Result: {result}')

asyncio.run(test())
"
```

**Deliverables**:
- [ ] Updated `deployment/docker-compose.yml` with Valkey service
- [ ] `services/universal_router/cache/client.py` - Cache client
- [ ] `services/universal_router/cache/keys.py` - Cache key generation
- [ ] `services/universal_router/cache/operations.py` - Cache operations
- [ ] `services/universal_router/tests/test_cache.py` - Cache unit tests

---

### Day 3 (Wednesday): Fuzzy Fallback

**Tasks**:

1. **Load agent registry**
   - File: `services/universal_router/registry/loader.py`
   - Function: `load_agent_registry() -> List[AgentDefinition]`
   - Location: `~/.claude/agent-definitions/*.yaml`
   - Caching: In-memory cache with file watcher for updates

2. **Agent registry models**
   - File: `services/universal_router/models/agent.py`
   - Model: `AgentDefinition` (from YAML structure)
   - Fields: `agent_name`, `capabilities`, `keywords`, `compatible_frameworks`

3. **Fuzzy matching implementation**
   - File: `services/universal_router/core/fuzzy_matcher.py`
   - Library: `rapidfuzz`
   - Algorithm: Token sort ratio + weighted scoring
   - Confidence: 0.0-1.0 (normalized)

4. **Fuzzy router**
   - File: `services/universal_router/routers/fuzzy_router.py`
   - Function: `route_with_fuzzy(request: UniversalRouteRequest) -> RouteResponse`
   - Logic: Match request against agent keywords/capabilities
   - Threshold: Min confidence 0.6

5. **Integration into main route**
   - File: `services/universal_router/api/routes.py`
   - Update: `/v1/route` endpoint to use fuzzy router
   - Flow: Cache miss → fuzzy router → cache result

**Acceptance Criteria**:
- ✅ Agent registry loads from YAML files
- ✅ Fuzzy matching returns confidence scores
- ✅ Top 3 agents returned for each request
- ✅ Confidence scores >0.6 for common requests
- ✅ Integration test: HTTP → cache miss → fuzzy → response

**Testing**:
```bash
# Run fuzzy matching tests
pytest services/universal_router/tests/test_fuzzy_matcher.py -v

# Integration test
curl -X POST http://localhost:8070/v1/route \
  -H "Content-Type: application/json" \
  -d '{
    "request": "Help me implement ONEX patterns",
    "options": {"max_recommendations": 3}
  }'

# Expected response:
# {
#   "correlation_id": "...",
#   "recommendations": [
#     {"agent_name": "agent-onex-architect", "confidence_score": 0.95, ...}
#   ],
#   "performance": {"total_latency_ms": 8, "tier_used": "fuzzy"}
# }
```

**Deliverables**:
- [ ] `services/universal_router/registry/loader.py` - Agent registry loader
- [ ] `services/universal_router/models/agent.py` - Agent models
- [ ] `services/universal_router/core/fuzzy_matcher.py` - Fuzzy matching
- [ ] `services/universal_router/routers/fuzzy_router.py` - Fuzzy router
- [ ] `services/universal_router/tests/test_fuzzy_matcher.py` - Fuzzy tests

---

### Day 4 (Thursday): Database Integration

**Tasks**:

1. **Create database table**
   - File: `migrations/XXX_create_universal_router_events.sql`
   - Table: `universal_router_events`
   - Columns: See architecture doc (correlation_id, request_text, agent_name, confidence_score, etc.)
   - Indexes: `correlation_id`, `agent_framework`, `routing_tier`, `created_at`

2. **SQLAlchemy models**
   - File: `services/universal_router/db/models.py`
   - Model: `UniversalRouterEvent`
   - Relationships: None (single table for now)

3. **Database client**
   - File: `services/universal_router/db/client.py`
   - Library: `asyncpg` (async PostgreSQL)
   - Features: Connection pooling, retry logic, non-blocking

4. **Event logging**
   - File: `services/universal_router/db/logger.py`
   - Function: `log_routing_event(request, response, performance) -> None`
   - Async: Non-blocking fire-and-forget
   - Error handling: Graceful degradation if DB unavailable

5. **Integration**
   - File: `services/universal_router/api/routes.py`
   - Update: Log all routing events to database
   - Performance: Logging should not block response

**Acceptance Criteria**:
- ✅ Database table created successfully
- ✅ SQLAlchemy model matches table schema
- ✅ Events logged to database
- ✅ Non-blocking (response time not affected)
- ✅ Graceful degradation if DB unavailable

**Testing**:
```bash
# Create table
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -f migrations/XXX_create_universal_router_events.sql

# Verify table
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "\d universal_router_events"

# Run database tests
pytest services/universal_router/tests/test_db.py -v

# Integration test: Verify events logged
curl -X POST http://localhost:8070/v1/route \
  -H "Content-Type: application/json" \
  -d '{"request": "test routing"}'

# Check database
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT * FROM universal_router_events ORDER BY created_at DESC LIMIT 1;"
```

**Deliverables**:
- [ ] `migrations/XXX_create_universal_router_events.sql` - SQL migration
- [ ] `services/universal_router/db/models.py` - SQLAlchemy models
- [ ] `services/universal_router/db/client.py` - Database client
- [ ] `services/universal_router/db/logger.py` - Event logger
- [ ] `services/universal_router/tests/test_db.py` - Database tests

---

### Day 5 (Friday): Testing & Refinement

**Tasks**:

1. **Unit test coverage**
   - Target: >80% code coverage
   - Files: All `services/universal_router/**/*.py` files
   - Tools: `pytest`, `pytest-cov`, `pytest-asyncio`

2. **Integration tests**
   - File: `services/universal_router/tests/test_integration.py`
   - Scenarios:
     - HTTP → cache hit → response
     - HTTP → cache miss → fuzzy → cache → response
     - HTTP → fuzzy low confidence → fallback (not implemented yet)
     - Concurrent requests (100 req/s)

3. **Load testing**
   - Tool: `locust` or `k6`
   - Target: 100 req/s sustained for 5 minutes
   - Metrics: P50/P95/P99 latency, error rate, throughput

4. **Performance profiling**
   - Tool: `py-spy` or `cProfile`
   - Identify: Bottlenecks in cache/fuzzy/database
   - Optimize: Hot paths

5. **Documentation**
   - File: `services/universal_router/README.md`
   - Content: Setup instructions, API examples, troubleshooting
   - OpenAPI: Auto-generated from FastAPI

**Acceptance Criteria**:
- ✅ >80% unit test coverage
- ✅ All integration tests pass
- ✅ Load test achieves 100 req/s
- ✅ P95 latency <10ms for cached requests
- ✅ P95 latency <15ms for fuzzy requests
- ✅ Documentation complete

**Testing**:
```bash
# Unit tests with coverage
pytest services/universal_router/tests/ --cov=services/universal_router --cov-report=html

# Integration tests
pytest services/universal_router/tests/test_integration.py -v

# Load test (using locust)
locust -f services/universal_router/tests/loadtest.py --host=http://localhost:8070

# Profile performance
py-spy record -o profile.svg -- python services/universal_router/main.py
```

**Deliverables**:
- [ ] `services/universal_router/tests/test_integration.py` - Integration tests
- [ ] `services/universal_router/tests/loadtest.py` - Load test script
- [ ] `services/universal_router/README.md` - Documentation
- [ ] Test coverage report (HTML)
- [ ] Performance profiling results

---

### Phase 1 Success Criteria

**Functional**:
- ✅ HTTP API responds to `/v1/route` requests
- ✅ Valkey caching works (cache hit/miss)
- ✅ Fuzzy fallback provides routing decisions
- ✅ Events logged to PostgreSQL
- ✅ Graceful error handling

**Performance**:
- ✅ P95 latency <10ms for cached requests
- ✅ P95 latency <15ms for fuzzy requests
- ✅ Throughput: 100+ req/s sustained
- ✅ Cache hit rate: 50%+ (with warming)

**Quality**:
- ✅ >80% unit test coverage
- ✅ All integration tests pass
- ✅ Load test passes (100 req/s for 5 min)
- ✅ Documentation complete

**Deliverables**:
- ✅ Working Universal Router service (HTTP API only)
- ✅ Valkey cache integration
- ✅ Fuzzy fallback routing
- ✅ Database event logging
- ✅ Comprehensive test suite
- ✅ Performance benchmarks

---

## Phase 2: GPU Acceleration (Week 2)

**Duration**: 5 working days (Mon-Fri)
**Goal**: vLLM integration with 4-tier fallback cascade

### Day 6 (Monday): vLLM Client

**Tasks**:

1. **vLLM client implementation**
   - File: `services/universal_router/clients/vllm_client.py`
   - Library: `openai` (vLLM OpenAI-compatible API)
   - Features: Connection pooling, timeouts, retries

2. **Health check**
   - Function: `check_vllm_health() -> bool`
   - Endpoint: `GET http://192.168.86.200:11434/v1/models`
   - Timeout: 5 seconds

3. **Connection pooling**
   - Library: `aiohttp` for async HTTP
   - Pool size: 20 connections
   - Timeout: 100ms per request

4. **Error handling**
   - Exceptions: `VLLMUnavailableError`, `VLLMTimeoutError`
   - Retry logic: 2 retries with exponential backoff
   - Fallback: If vLLM fails, fall back to fuzzy

**Acceptance Criteria**:
- ✅ vLLM client connects successfully
- ✅ Health check works
- ✅ Timeout handling (100ms)
- ✅ Graceful fallback on failure

**Testing**:
```bash
# Verify vLLM endpoint
curl http://192.168.86.200:11434/v1/models

# Run vLLM client tests
pytest services/universal_router/tests/test_vllm_client.py -v

# Test timeout handling
python3 -c "
from services.universal_router.clients.vllm_client import VLLMClient
import asyncio

async def test():
    client = VLLMClient(timeout=0.01)  # 10ms timeout
    try:
        await client.generate('test prompt')
    except TimeoutError:
        print('Timeout handled correctly')

asyncio.run(test())
"
```

**Deliverables**:
- [ ] `services/universal_router/clients/vllm_client.py` - vLLM client
- [ ] `services/universal_router/tests/test_vllm_client.py` - vLLM tests

---

### Day 7 (Tuesday): Routing Prompt Engineering

**Tasks**:

1. **Prompt template**
   - File: `services/universal_router/prompts/routing_prompt.py`
   - Template: Jinja2 template for routing prompt
   - Includes: Agent registry JSON, user request, context

2. **Agent registry JSON serialization**
   - Function: `serialize_agent_registry() -> str`
   - Format: Compact JSON with agent name, capabilities, keywords
   - Size: Minimize to reduce prompt tokens

3. **Prompt optimization**
   - Test: Various request types (ONEX, debugging, review, etc.)
   - Optimize: For <50ms inference time
   - Tune: Temperature, top_p, max_tokens

4. **Response parsing**
   - Function: `parse_vllm_response(response: str) -> RouteResponse`
   - Handle: Invalid JSON, missing fields, low confidence

**Acceptance Criteria**:
- ✅ Prompt generates valid JSON responses
- ✅ Inference time <50ms p95
- ✅ Confidence scores >0.7 for common requests
- ✅ Correct agent selected for test cases

**Testing**:
```bash
# Test prompt with vLLM
python3 services/universal_router/prompts/test_routing_prompt.py

# Benchmark inference time
python3 services/universal_router/prompts/benchmark_vllm.py

# Test cases:
# 1. "Help me implement ONEX patterns" → agent-onex-architect (0.95)
# 2. "Debug this error message" → agent-debugger (0.90)
# 3. "Review my pull request" → agent-code-reviewer (0.88)
```

**Deliverables**:
- [ ] `services/universal_router/prompts/routing_prompt.py` - Prompt template
- [ ] `services/universal_router/prompts/test_routing_prompt.py` - Prompt tests
- [ ] `services/universal_router/prompts/benchmark_vllm.py` - Benchmark script

---

### Day 8 (Wednesday): Tier Orchestration

**Tasks**:

1. **Tier orchestrator**
   - File: `services/universal_router/core/tier_orchestrator.py`
   - Function: `route_with_fallback(request: UniversalRouteRequest) -> RouteResponse`
   - Logic: Cache → vLLM → Fuzzy → Remote LLM (4-tier cascade)

2. **Tier 2: vLLM router**
   - File: `services/universal_router/routers/vllm_router.py`
   - Function: `route_with_vllm(request: UniversalRouteRequest) -> RouteResponse`
   - Confidence threshold: 0.7

3. **Tier 4: Remote LLM router** (placeholder)
   - File: `services/universal_router/routers/remote_llm_router.py`
   - Function: `route_with_remote_llm(request: UniversalRouteRequest) -> RouteResponse`
   - Providers: Anthropic (Haiku), Gemini (Flash), Together
   - Selection: Round-robin or cheapest-first

4. **Confidence-based fallback**
   - Logic: If confidence <0.7, fall back to next tier
   - Tracking: Record which tier was used for each request

**Acceptance Criteria**:
- ✅ 4-tier cascade works end-to-end
- ✅ Fallback triggered on low confidence
- ✅ Fallback triggered on vLLM failure
- ✅ Correct tier recorded in database

**Testing**:
```bash
# Test tier orchestration
pytest services/universal_router/tests/test_tier_orchestrator.py -v

# Integration test: Cache → vLLM
curl -X POST http://localhost:8070/v1/route \
  -H "Content-Type: application/json" \
  -d '{"request": "Help me implement ONEX patterns"}'
# Expected: tier_used = "vllm", confidence > 0.7

# Force fallback (disable vLLM)
export VLLM_ENABLED=false
curl -X POST http://localhost:8070/v1/route \
  -H "Content-Type: application/json" \
  -d '{"request": "Help me implement ONEX patterns"}'
# Expected: tier_used = "fuzzy"
```

**Deliverables**:
- [ ] `services/universal_router/core/tier_orchestrator.py` - Tier orchestrator
- [ ] `services/universal_router/routers/vllm_router.py` - vLLM router
- [ ] `services/universal_router/routers/remote_llm_router.py` - Remote LLM router (placeholder)
- [ ] `services/universal_router/tests/test_tier_orchestrator.py` - Orchestrator tests

---

### Day 9 (Thursday): vLLM Configuration & Tuning

**Tasks**:

1. **vLLM configuration review**
   - Verify: vLLM running at 192.168.86.200:11434
   - Model: Llama-3.1-8B-Instruct
   - Settings: Prefix caching enabled, batch size optimized

2. **Prefix caching setup**
   - Feature: Cache agent registry (common prefix)
   - Benefit: 30-40% latency improvement for cache hits

3. **Batch size tuning**
   - Test: Various batch sizes (1, 4, 8, 16, 32)
   - Optimize: Balance throughput vs latency
   - Target: <50ms p95 latency

4. **Concurrency tuning**
   - Test: Various concurrency levels (10, 50, 100, 200)
   - Monitor: GPU utilization, memory usage
   - Target: 100+ req/s throughput

5. **Performance benchmarking**
   - Tool: Custom benchmark script
   - Metrics: Latency (p50/p95/p99), throughput, GPU utilization
   - Compare: Baseline (no caching) vs optimized

**Acceptance Criteria**:
- ✅ vLLM responds in 20-50ms p95
- ✅ Throughput: 100+ req/s
- ✅ GPU utilization: 70-90%
- ✅ Prefix caching working (verify in vLLM logs)

**Testing**:
```bash
# Benchmark vLLM latency
python3 services/universal_router/benchmarks/vllm_latency.py

# Load test with vLLM
locust -f services/universal_router/tests/loadtest_vllm.py --host=http://localhost:8070

# Monitor GPU utilization
nvidia-smi -l 1
# or
curl http://192.168.86.200:11434/v1/health
```

**Deliverables**:
- [ ] vLLM configuration documented
- [ ] `services/universal_router/benchmarks/vllm_latency.py` - Benchmark script
- [ ] Performance tuning results (markdown doc)
- [ ] GPU utilization metrics

---

### Day 10 (Friday): Integration & Testing

**Tasks**:

1. **End-to-end integration test**
   - File: `services/universal_router/tests/test_e2e_vllm.py`
   - Scenarios:
     - Cache miss → vLLM → cache → DB
     - vLLM failure → fuzzy fallback
     - Low confidence → fuzzy fallback
     - High load (100+ req/s)

2. **Performance regression tests**
   - Compare: Phase 1 (fuzzy only) vs Phase 2 (vLLM)
   - Metrics: Latency, throughput, cost per request
   - Ensure: No performance degradation

3. **Cost tracking validation**
   - Verify: vLLM cost tracked correctly (~$0.000004 per request)
   - Verify: Database logs include cost data
   - Calculate: Projected monthly cost

4. **Documentation update**
   - File: `services/universal_router/README.md`
   - Add: vLLM setup instructions, configuration options
   - Add: Performance benchmarks, cost analysis

5. **Deployment preparation**
   - Update: `deployment/docker-compose.yml` with vLLM config
   - Add: Environment variables for vLLM endpoint
   - Add: Health check for vLLM dependency

**Acceptance Criteria**:
- ✅ All E2E tests pass
- ✅ vLLM integration works in Docker Compose
- ✅ Cost tracking accurate
- ✅ Documentation complete
- ✅ Ready for Phase 3

**Testing**:
```bash
# Run all tests
pytest services/universal_router/tests/ -v

# E2E test with vLLM
pytest services/universal_router/tests/test_e2e_vllm.py -v

# Load test (100 req/s for 10 minutes)
locust -f services/universal_router/tests/loadtest_vllm.py \
  --host=http://localhost:8070 \
  --users=100 \
  --spawn-rate=10 \
  --run-time=10m

# Verify cost tracking
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT routing_tier, AVG(estimated_cost_usd) FROM universal_router_events GROUP BY routing_tier;"
```

**Deliverables**:
- [ ] `services/universal_router/tests/test_e2e_vllm.py` - E2E tests
- [ ] Updated `deployment/docker-compose.yml`
- [ ] Updated `services/universal_router/README.md`
- [ ] Performance comparison report

---

### Phase 2 Success Criteria

**Functional**:
- ✅ vLLM integration works end-to-end
- ✅ 4-tier fallback cascade operational
- ✅ Confidence-based tier selection
- ✅ Cost tracking for all tiers

**Performance**:
- ✅ vLLM: 20-50ms p95 latency
- ✅ Throughput: 100+ req/s sustained
- ✅ GPU utilization: 70-90%
- ✅ Weighted avg latency: <40ms

**Quality**:
- ✅ >80% unit test coverage (maintained)
- ✅ All E2E tests pass
- ✅ Load test passes (100 req/s for 10 min)
- ✅ Documentation updated

**Deliverables**:
- ✅ vLLM integration complete
- ✅ 4-tier fallback cascade working
- ✅ Performance benchmarks
- ✅ Cost tracking operational

---

## Phase 3: Multi-Protocol Support (Week 3)

**Duration**: 5 working days (Mon-Fri)
**Goal**: gRPC, Kafka, WebSocket, and framework adapters

### Day 11 (Monday): gRPC Server

**Tasks**:

1. **Protocol Buffer definitions**
   - File: `services/universal_router/proto/universal_router.proto`
   - Services: `UniversalRouter` with `Route()` and `RouteStream()` methods
   - Messages: `RouteRequest`, `RouteResponse`, `AgentRecommendation`, `PerformanceMetrics`

2. **Generate Python code**
   - Command: `python -m grpc_tools.protoc ...`
   - Output: `*_pb2.py` and `*_pb2_grpc.py` files

3. **gRPC server implementation**
   - File: `services/universal_router/grpc_server.py`
   - Port: 50051
   - Features: Unary RPC, streaming RPC

4. **Integration with core router**
   - Reuse: Existing tier orchestrator
   - Convert: gRPC request → `UniversalRouteRequest`
   - Convert: `RouteResponse` → gRPC response

**Acceptance Criteria**:
- ✅ gRPC server starts on port 50051
- ✅ Unary RPC works (single request/response)
- ✅ Streaming RPC works (multiple responses)
- ✅ Integration with tier orchestrator

**Testing**:
```bash
# Generate Python code from proto
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. services/universal_router/proto/universal_router.proto

# Start gRPC server
python services/universal_router/grpc_server.py

# Test with grpcurl
grpcurl -plaintext -d '{"request": "test"}' localhost:50051 universal_router.v1.UniversalRouter/Route

# Test streaming
grpcurl -plaintext -d '{"request": "test"}' localhost:50051 universal_router.v1.UniversalRouter/RouteStream
```

**Deliverables**:
- [ ] `services/universal_router/proto/universal_router.proto` - Protocol Buffer definitions
- [ ] `services/universal_router/grpc_server.py` - gRPC server
- [ ] Generated protobuf files
- [ ] gRPC tests

---

### Day 12 (Tuesday): Kafka Event Bus

**Tasks**:

1. **Create Kafka topics**
   - Topics: `universal-router.routing.requested.v1`, `universal-router.routing.completed.v1`, `universal-router.routing.failed.v1`
   - Partitions: 3 per topic
   - Replication: 1 (single-broker setup)

2. **Kafka consumer**
   - File: `services/universal_router/kafka_consumer.py`
   - Library: `aiokafka`
   - Features: Auto-commit, error handling, correlation ID propagation

3. **Kafka producer**
   - File: `services/universal_router/kafka_producer.py`
   - Library: `aiokafka`
   - Features: Async publishing, retry logic

4. **Event schemas**
   - File: `services/universal_router/events/schemas.py`
   - Schemas: `RoutingRequestEvent`, `RoutingCompletedEvent`, `RoutingFailedEvent`
   - Format: JSON (Avro optional)

**Acceptance Criteria**:
- ✅ Kafka topics created
- ✅ Consumer subscribes and processes events
- ✅ Producer publishes events
- ✅ Correlation ID preserved across events

**Testing**:
```bash
# Create Kafka topics
docker exec omninode-bridge-redpanda rpk topic create \
  universal-router.routing.requested.v1 \
  universal-router.routing.completed.v1 \
  universal-router.routing.failed.v1

# Start Kafka consumer
python services/universal_router/kafka_consumer.py

# Publish test event
python3 -c "
from services.universal_router.kafka_producer import publish_routing_request
import asyncio

async def test():
    await publish_routing_request({'request': 'test', 'correlation_id': '123'})

asyncio.run(test())
"

# Verify event consumed
# (check consumer logs)
```

**Deliverables**:
- [ ] `services/universal_router/kafka_consumer.py` - Kafka consumer
- [ ] `services/universal_router/kafka_producer.py` - Kafka producer
- [ ] `services/universal_router/events/schemas.py` - Event schemas
- [ ] Kafka integration tests

---

### Day 13 (Wednesday): WebSocket Server

**Tasks**:

1. **WebSocket endpoint**
   - File: `services/universal_router/api/websocket.py`
   - Endpoint: `WS /v1/stream`
   - Features: Connection pooling, broadcast support

2. **Message format**
   - Type: JSON messages
   - Types: `route_request`, `route_progress`, `route_complete`, `route_error`

3. **Progress updates**
   - Updates: Sent during routing (tier transitions)
   - Example: "Checking cache...", "Querying vLLM...", "Complete!"

4. **Multi-client support**
   - Features: Multiple concurrent WebSocket connections
   - Broadcast: Route progress to all connected clients (optional)

**Acceptance Criteria**:
- ✅ WebSocket endpoint works
- ✅ Real-time progress updates sent
- ✅ Multiple concurrent connections supported
- ✅ Connection cleanup on disconnect

**Testing**:
```bash
# Start WebSocket server
uvicorn services.universal_router.main:app --reload

# Test with websocat
websocat ws://localhost:8070/v1/stream

# Send request:
{"type": "route_request", "payload": {"request": "test"}}

# Receive progress updates:
{"type": "route_progress", "payload": {"stage": "cache", "progress": 0.25}}
{"type": "route_progress", "payload": {"stage": "vllm", "progress": 0.75}}
{"type": "route_complete", "payload": {"recommendations": [...]}}
```

**Deliverables**:
- [ ] `services/universal_router/api/websocket.py` - WebSocket endpoint
- [ ] WebSocket message schemas
- [ ] WebSocket integration tests
- [ ] WebSocket client example (Python)

---

### Day 14 (Thursday): Framework Adapters

**Tasks**:

1. **Claude Code adapter**
   - File: `adapters/claude_code/universal_router_adapter.py`
   - Library: Python package installable with pip
   - Usage: `from universal_router import ClaudeCodeAdapter`

2. **LangChain adapter**
   - File: `adapters/langchain/universal_router_adapter.py`
   - Integration: LangChain `AgentExecutor` factory
   - Usage: Convert routing result to LangChain agent

3. **AutoGPT adapter** (optional)
   - File: `adapters/autogpt/universal_router_adapter.py`
   - Integration: AutoGPT agent factory

4. **Adapter documentation**
   - File: `adapters/README.md`
   - Content: Installation, usage examples, API reference

**Acceptance Criteria**:
- ✅ Claude Code adapter works
- ✅ LangChain adapter works
- ✅ Adapters installable with pip
- ✅ Documentation complete

**Testing**:
```bash
# Install adapter
pip install -e adapters/claude_code/

# Test Claude Code adapter
python3 -c "
from universal_router import ClaudeCodeAdapter

adapter = ClaudeCodeAdapter(base_url='http://localhost:8070')
result = adapter.route('Help me implement ONEX patterns')
print(result.recommendations[0].agent_name)
"

# Test LangChain adapter
python3 -c "
from universal_router.langchain import LangChainAdapter

adapter = LangChainAdapter(base_url='http://localhost:8070')
executor = adapter.route({'query': 'Help me debug this error'})
print(executor.agent)
"
```

**Deliverables**:
- [ ] `adapters/claude_code/universal_router_adapter.py` - Claude Code adapter
- [ ] `adapters/langchain/universal_router_adapter.py` - LangChain adapter
- [ ] `adapters/README.md` - Adapter documentation
- [ ] Adapter unit tests

---

### Day 15 (Friday): Integration & Testing

**Tasks**:

1. **Multi-protocol integration test**
   - File: `services/universal_router/tests/test_multi_protocol.py`
   - Scenarios:
     - HTTP → route
     - gRPC → route
     - Kafka → route
     - WebSocket → route
     - All protocols in parallel

2. **Framework adapter tests**
   - File: `adapters/tests/test_adapters.py`
   - Test: Each adapter with mock Universal Router

3. **Performance testing**
   - Load test: All protocols simultaneously
   - Metrics: Latency, throughput, error rate
   - Target: No degradation vs single-protocol

4. **Documentation**
   - File: `docs/architecture/MULTI_PROTOCOL_API.md`
   - Content: Protocol specifications, examples, best practices

**Acceptance Criteria**:
- ✅ All protocols work concurrently
- ✅ Framework adapters tested
- ✅ Load test passes
- ✅ Documentation complete

**Testing**:
```bash
# Run all multi-protocol tests
pytest services/universal_router/tests/test_multi_protocol.py -v

# Load test (all protocols)
python services/universal_router/tests/loadtest_all_protocols.py

# Test adapters
pytest adapters/tests/test_adapters.py -v
```

**Deliverables**:
- [ ] `services/universal_router/tests/test_multi_protocol.py` - Multi-protocol tests
- [ ] `adapters/tests/test_adapters.py` - Adapter tests
- [ ] `docs/architecture/MULTI_PROTOCOL_API.md` - Documentation
- [ ] Load test results

---

### Phase 3 Success Criteria

**Functional**:
- ✅ gRPC server operational
- ✅ Kafka event bus integrated
- ✅ WebSocket real-time updates
- ✅ 2+ framework adapters complete

**Performance**:
- ✅ All protocols <50ms p95 latency
- ✅ Concurrent protocol usage works
- ✅ No performance degradation

**Quality**:
- ✅ >80% unit test coverage (maintained)
- ✅ Multi-protocol tests pass
- ✅ Load test passes
- ✅ Documentation complete

**Deliverables**:
- ✅ gRPC server
- ✅ Kafka integration
- ✅ WebSocket server
- ✅ Framework adapters
- ✅ Multi-protocol documentation

---

## Phase 4: Observability & Production (Week 4)

**Duration**: 5 working days (Mon-Fri)
**Goal**: Complete observability, production hardening, launch

### Day 16 (Monday): Prometheus Metrics

**Tasks**:

1. **Metrics implementation**
   - File: `services/universal_router/observability/metrics.py`
   - Metrics: See architecture doc (5 key metrics)
   - Library: `prometheus_client`

2. **Metrics endpoint**
   - Endpoint: `GET /metrics`
   - Format: Prometheus text format
   - Features: Auto-update, labels

3. **Custom metrics**
   - Tier-specific: Latency, cost, usage
   - Cache metrics: Hit rate, size, evictions
   - GPU metrics: Utilization, memory

4. **Metrics integration**
   - Update: All routing code to record metrics
   - Ensure: Non-blocking (async)

**Acceptance Criteria**:
- ✅ Metrics endpoint returns valid Prometheus format
- ✅ All 5 key metrics implemented
- ✅ Metrics update in real-time
- ✅ Prometheus scrapes successfully

**Testing**:
```bash
# Test metrics endpoint
curl http://localhost:8070/metrics

# Verify metrics format
curl http://localhost:8070/metrics | promtool check metrics

# Configure Prometheus scrape
# (add to prometheus.yml)
scrape_configs:
  - job_name: 'universal-router'
    static_configs:
      - targets: ['localhost:8070']

# Verify Prometheus scraping
curl http://localhost:9090/api/v1/targets
```

**Deliverables**:
- [ ] `services/universal_router/observability/metrics.py` - Metrics implementation
- [ ] Prometheus scrape configuration
- [ ] Metrics documentation

---

### Day 17 (Tuesday): Grafana Dashboards

**Tasks**:

1. **Dashboard design**
   - Dashboards: 5 dashboards (see architecture doc)
   - Tool: Grafana JSON model

2. **Routing performance dashboard**
   - Panels: Latency (p50/p95/p99), request rate, error rate
   - Filters: By tier, by framework, by time range

3. **Cost analysis dashboard**
   - Panels: Cost per request, daily/weekly/monthly spend, savings vs baseline

4. **Cache performance dashboard**
   - Panels: Hit rate, cache size, evictions, top routes

5. **GPU monitoring dashboard**
   - Panels: GPU utilization, vLLM throughput, memory usage

6. **Tier distribution dashboard**
   - Panels: Requests by tier (pie chart), fallback rate, confidence distribution

**Acceptance Criteria**:
- ✅ All 5 dashboards created
- ✅ Dashboards importable to Grafana
- ✅ Real-time data displayed
- ✅ Filters and drill-downs work

**Testing**:
```bash
# Import dashboards to Grafana
curl -X POST http://localhost:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @services/universal_router/observability/dashboards/routing_performance.json

# Verify dashboards
open http://localhost:3000/dashboards
```

**Deliverables**:
- [ ] 5 Grafana dashboard JSON files
- [ ] Dashboard import script
- [ ] Dashboard documentation (screenshots, usage)

---

### Day 18 (Wednesday): OpenTelemetry Tracing

**Tasks**:

1. **OpenTelemetry setup**
   - Library: `opentelemetry-api`, `opentelemetry-sdk`
   - Exporter: Jaeger
   - Features: Span creation, trace propagation

2. **Instrumentation**
   - Instrument: All routing tiers (cache, vLLM, fuzzy, remote)
   - Spans: Create span for each tier
   - Attributes: Tier name, latency, confidence, cost

3. **Trace propagation**
   - Context: Propagate across async calls
   - Correlation: Link traces with correlation ID

4. **Jaeger integration**
   - Setup: Jaeger in Docker Compose
   - Port: 16686 (UI)
   - Test: View traces in Jaeger UI

**Acceptance Criteria**:
- ✅ Spans created for all tiers
- ✅ Traces viewable in Jaeger
- ✅ Correlation ID linked to traces
- ✅ End-to-end trace visualization

**Testing**:
```bash
# Start Jaeger
docker-compose up -d jaeger

# Make routing request
curl -X POST http://localhost:8070/v1/route \
  -H "Content-Type: application/json" \
  -d '{"request": "test"}'

# View trace in Jaeger
open http://localhost:16686

# Search by correlation ID
# (paste correlation_id from response)
```

**Deliverables**:
- [ ] OpenTelemetry instrumentation
- [ ] Jaeger integration
- [ ] Tracing documentation

---

### Day 19 (Thursday): Production Hardening

**Tasks**:

1. **Rate limiting**
   - Library: `slowapi` or custom middleware
   - Limits: 100 req/min per user, 1000 req/min per IP
   - Response: 429 Too Many Requests

2. **Circuit breaker**
   - Library: `pybreaker`
   - Services: vLLM, remote LLM, database
   - Thresholds: 5 failures in 1 minute → open circuit

3. **Graceful shutdown**
   - Signal: Handle SIGTERM, SIGINT
   - Actions: Close connections, flush buffers, finish in-flight requests

4. **Docker health checks**
   - Command: `curl -f http://localhost:8070/v1/health`
   - Interval: 10s, Timeout: 5s, Retries: 3

5. **Security hardening**
   - HTTPS: TLS/SSL certificates
   - Auth: API key authentication (optional)
   - CORS: Restrict origins

**Acceptance Criteria**:
- ✅ Rate limiting works
- ✅ Circuit breaker works
- ✅ Graceful shutdown works
- ✅ Health checks pass

**Testing**:
```bash
# Test rate limiting
for i in {1..150}; do
  curl -X POST http://localhost:8070/v1/route -d '{"request": "test"}' &
done
# Expected: 50 requests return 429

# Test circuit breaker
# (stop vLLM service, make 10 requests, circuit should open)

# Test graceful shutdown
docker-compose stop universal-router
# (check logs for graceful shutdown)

# Test health check
docker inspect universal-router | grep Health
```

**Deliverables**:
- [ ] Rate limiting implementation
- [ ] Circuit breaker implementation
- [ ] Graceful shutdown logic
- [ ] Updated Docker health checks

---

### Day 20 (Friday): Documentation & Launch

**Tasks**:

1. **API reference**
   - File: `docs/api/UNIVERSAL_ROUTER_API.md`
   - Content: All endpoints, request/response examples, error codes
   - Format: OpenAPI/Swagger spec

2. **Deployment guide**
   - File: `docs/deployment/UNIVERSAL_ROUTER_DEPLOYMENT.md`
   - Content: Setup, configuration, troubleshooting, monitoring

3. **Cost optimization guide**
   - File: `docs/guides/COST_OPTIMIZATION.md`
   - Content: Caching strategies, tier tuning, budget alerts

4. **Troubleshooting guide**
   - File: `docs/guides/TROUBLESHOOTING.md`
   - Content: Common issues, debugging tips, support

5. **Launch checklist**
   - [ ] All tests pass
   - [ ] Documentation complete
   - [ ] Performance benchmarks met
   - [ ] Production config reviewed
   - [ ] Monitoring dashboards set up
   - [ ] Runbook created

6. **Final testing**
   - Chaos test: Kill services randomly
   - Soak test: 24-hour continuous load
   - Stress test: 1000+ req/s burst

**Acceptance Criteria**:
- ✅ All documentation complete
- ✅ Launch checklist signed off
- ✅ Final tests pass
- ✅ Ready for production

**Testing**:
```bash
# Chaos test
python services/universal_router/tests/chaos_test.py

# Soak test (24 hours)
locust -f services/universal_router/tests/loadtest.py \
  --host=http://localhost:8070 \
  --users=50 \
  --spawn-rate=5 \
  --run-time=24h

# Stress test (1000 req/s)
locust -f services/universal_router/tests/stress_test.py \
  --host=http://localhost:8070 \
  --users=1000 \
  --spawn-rate=100
```

**Deliverables**:
- [ ] Complete API documentation
- [ ] Deployment guide
- [ ] Cost optimization guide
- [ ] Troubleshooting guide
- [ ] Launch checklist
- [ ] Final test results

---

### Phase 4 Success Criteria

**Observability**:
- ✅ Prometheus metrics exported
- ✅ Grafana dashboards operational
- ✅ OpenTelemetry tracing functional
- ✅ All metrics tracked

**Production Readiness**:
- ✅ Rate limiting works
- ✅ Circuit breaker works
- ✅ Graceful shutdown works
- ✅ Security hardened

**Documentation**:
- ✅ API reference complete
- ✅ Deployment guide complete
- ✅ Troubleshooting guide complete
- ✅ Cost optimization guide complete

**Testing**:
- ✅ Chaos test passes
- ✅ Soak test (24h) passes
- ✅ Stress test (1000 req/s) passes

**Deliverables**:
- ✅ Production-ready Universal Router
- ✅ Complete observability stack
- ✅ Comprehensive documentation
- ✅ Launch-ready system

---

## Success Metrics & KPIs

### Performance Targets

| Metric | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Target |
|--------|---------|---------|---------|---------|--------|
| **P50 Latency** | <10ms | <20ms | <20ms | <10ms | <10ms |
| **P95 Latency** | <15ms | <40ms | <50ms | <50ms | <50ms |
| **P99 Latency** | <25ms | <100ms | <100ms | <100ms | <100ms |
| **Throughput** | 100 req/s | 100 req/s | 100 req/s | 1000 req/s | 100+ req/s |
| **Cache Hit Rate** | 50% | 60% | 65% | 70% | 60-70% |
| **Cost per Request** | $0 | $0.000004 | $0.000004 | $0.000004 | <$0.00001 |

### Quality Targets

| Metric | Target | Acceptable |
|--------|--------|------------|
| **Unit Test Coverage** | >80% | >70% |
| **Integration Test Pass Rate** | 100% | 95% |
| **Load Test Pass Rate** | 100% | 100% |
| **Routing Accuracy** | >95% | >90% |
| **Uptime** | 99.9% | 99% |

---

## Risk Mitigation

### High-Priority Risks

**1. PR #22 Merge Delay**
- **Risk**: PR #22 takes longer than 1-2 days to resolve
- **Impact**: Delays entire Universal Router project
- **Mitigation**:
  - Prioritize PR #22 fixes immediately
  - Parallelize work: Documentation can start while PR #22 is being fixed
  - Escalate if PR #22 not merged by 2025-11-09

**2. vLLM GPU Unavailable**
- **Risk**: vLLM endpoint at 192.168.86.200:11434 not working
- **Impact**: Phase 2 blocked
- **Mitigation**:
  - Verify vLLM endpoint before Phase 2 starts
  - Have fallback plan: Use remote LLM tier only if vLLM unavailable
  - Document vLLM setup procedure

**3. Performance Degradation**
- **Risk**: Multi-protocol support causes performance issues
- **Impact**: Fails to meet latency/throughput targets
- **Mitigation**:
  - Comprehensive load testing at each phase
  - Performance profiling and optimization
  - Circuit breakers to isolate slow services

**4. Cost Overruns (Remote LLM Tier)**
- **Risk**: Remote LLM tier used more than expected (>5%)
- **Impact**: Higher operational costs
- **Mitigation**:
  - Rate limiting on remote LLM tier
  - Cost monitoring and alerts
  - Budget caps per user/session

---

## Communication & Reporting

### Daily Standup

**Format**: Async (Slack/Discord)
**Time**: 9:00 AM
**Content**:
- What I completed yesterday
- What I'm working on today
- Any blockers

### Weekly Review

**Format**: Written report
**Frequency**: End of each week (Friday)
**Content**:
- Phase completion status
- Key metrics achieved
- Issues encountered and resolved
- Next week's plan

### Milestone Reports

**Format**: Comprehensive markdown document
**Frequency**: After each phase
**Content**:
- Phase summary
- Success criteria validation
- Performance benchmarks
- Lessons learned
- Recommendations for next phase

---

## Post-Launch Plan

### Week 5: Monitoring & Optimization

**Goals**:
- Monitor production metrics for 1 week
- Identify bottlenecks and optimization opportunities
- Tune configuration based on real usage

**Tasks**:
- [ ] Daily metric review (latency, throughput, cost)
- [ ] Optimize cache TTL and eviction policy
- [ ] Tune vLLM batch size and concurrency
- [ ] Adjust tier confidence thresholds
- [ ] Address any production issues

### Week 6: Feature Enhancements

**Goals**:
- Implement 2-3 high-priority feature requests
- Improve routing quality based on feedback
- Add missing protocol features

**Potential Features**:
- Semantic caching (similar requests)
- Agent performance tracking
- Multi-model vLLM support
- Advanced cost analytics

### Week 7+: Ongoing Maintenance

**Tasks**:
- Weekly performance reviews
- Monthly cost analysis
- Quarterly security audits
- Continuous optimization

---

## Appendix

### Useful Commands

**Service Management**:
```bash
# Start all services
docker-compose up -d

# Start Universal Router only
docker-compose up -d universal-router

# View logs
docker logs -f universal-router

# Restart service
docker restart universal-router

# Stop all services
docker-compose down
```

**Testing**:
```bash
# Run all tests
pytest services/universal_router/tests/ -v

# Run specific test
pytest services/universal_router/tests/test_cache.py::test_cache_hit -v

# Run with coverage
pytest services/universal_router/tests/ --cov=services/universal_router --cov-report=html

# Load test
locust -f services/universal_router/tests/loadtest.py --host=http://localhost:8070
```

**Database**:
```bash
# Connect to database
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge

# Query routing events
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT * FROM universal_router_events ORDER BY created_at DESC LIMIT 10;"

# Check metrics
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT routing_tier, COUNT(*), AVG(total_latency_ms) FROM universal_router_events GROUP BY routing_tier;"
```

**Monitoring**:
```bash
# Check Prometheus metrics
curl http://localhost:8070/metrics

# View Grafana dashboards
open http://localhost:3000

# View Jaeger traces
open http://localhost:16686
```

---

**Document Version**: 1.0.0
**Last Updated**: 2025-11-07
**Status**: Awaiting PR #22 Merge
**Next Update**: After PR #22 resolves
