# Agent Routing Adapter Service

**Status**: 🚧 PHASE 1 IN PROGRESS - Docker configuration complete, service implementation pending
**Created**: 2025-10-30
**Reference**: [Event-Driven Routing Proposal](../../../docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md)

---

## Overview

Event-driven agent routing service that consumes routing requests from Kafka and responds with agent recommendations. This service migrates agent routing from synchronous Python execution to event-driven architecture, following the proven pattern from database adapter implementation.

## Current Implementation Status

### ✅ Completed (Phase 1a - Docker Configuration)

- [x] **Dockerfile.routing-adapter**: Python 3.12, minimal dependencies, health checks
- [x] **docker-compose.yml**: Service configuration with environment variables
- [x] **entrypoint-routing-adapter.sh**: Environment validation, graceful shutdown
- [x] **Placeholder main.py**: Health check endpoint on port 8070
- [x] **Dependencies verified**: aiokafka, pydantic, pyyaml in pyproject.toml

### ⏳ Pending (Phase 1b - Service Implementation)

- [ ] **RouterEventHandler**: Kafka consumer/producer for routing events
- [ ] **RouterService**: Business logic wrapper around AgentRouter
- [ ] **Circuit Breaker**: Fallback mechanism for service failures
- [ ] **Metrics Collection**: Prometheus metrics for routing performance
- [ ] **Registry Hot Reload**: Watch for agent registry changes

### 🔜 Future Phases

- **Phase 2**: Client integration (`RoutingEventClient`)
- **Phase 3**: Parallel running & A/B testing
- **Phase 4**: Deprecate synchronous API
- **Phase 5**: Advanced features (quorum, hot reload)

---

## Docker Configuration

### Build Command

```bash
cd /Volumes/PRO-G40/Code/omniclaude
docker build -f deployment/Dockerfile.routing-adapter -t omniclaude-routing-adapter:latest .
```

### Run Command (Standalone)

```bash
docker run --rm \
  -e KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092 \
  -e POSTGRES_HOST=192.168.86.200 \
  -e POSTGRES_PORT=5436 \
  -e POSTGRES_DATABASE=omninode_bridge \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=omninode_remote_2024_secure \
  -e REGISTRY_PATH=/agent-definitions/agent-registry.yaml \
  -v $HOME/.claude/agent-definitions:/agent-definitions:ro \
  -p 8070:8070 \
  omniclaude-routing-adapter:latest
```

### Run via Docker Compose

```bash
cd deployment
docker-compose up -d routing-adapter
```

### Health Check

```bash
curl http://localhost:8070/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "routing-adapter",
  "phase": "placeholder"
}
```

---

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka broker address | `192.168.86.200:29092` |
| `POSTGRES_HOST` | PostgreSQL host | `192.168.86.200` |
| `POSTGRES_PORT` | PostgreSQL port | `5436` |
| `POSTGRES_DATABASE` | Database name | `omninode_bridge` |
| `POSTGRES_USER` | Database user | `postgres` |
| `POSTGRES_PASSWORD` | Database password | `omninode_remote_2024_secure` |
| `REGISTRY_PATH` | Agent registry YAML path | `/agent-definitions/agent-registry.yaml` |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `KAFKA_GROUP_ID` | Consumer group ID | `agent-routing-service` |
| `KAFKA_REQUEST_TOPIC` | Request topic name | `agent.routing.requested.v1` |
| `KAFKA_COMPLETED_TOPIC` | Success response topic | `agent.routing.completed.v1` |
| `KAFKA_FAILED_TOPIC` | Error response topic | `agent.routing.failed.v1` |
| `HEALTH_CHECK_PORT` | HTTP health check port | `8070` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `ROUTING_TIMEOUT_MS` | Routing timeout | `5000` |
| `CACHE_TTL_SECONDS` | Result cache TTL | `3600` |
| `MAX_RECOMMENDATIONS` | Max agents to recommend | `5` |

---

## Service Architecture (Planned)

```
┌─────────────────────────────────────────────────────────────────┐
│                  Agent Routing Adapter Service                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  main.py (Entry Point)                                          │
│    │                                                            │
│    ├─► RouterEventHandler (Kafka Integration)                  │
│    │   - Consumer: agent.routing.requested.v1                  │
│    │   - Producer: agent.routing.completed.v1                  │
│    │   - Producer: agent.routing.failed.v1                     │
│    │   - Correlation tracking                                  │
│    │                                                            │
│    ├─► RouterService (Business Logic)                          │
│    │   - AgentRouter wrapper (existing lib)                    │
│    │   - Circuit breaker for fallback                          │
│    │   - Metrics collection                                    │
│    │   - Registry hot reload                                   │
│    │                                                            │
│    └─► HealthCheckServer (HTTP Endpoint)                       │
│        - GET /health → 200 OK                                  │
│        - GET /metrics → Prometheus metrics                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase 1b: Service Implementation (Current)

**Goal**: Implement functional routing service

**Tasks**:

1. **Create RouterEventHandler** (`router_event_handler.py`)
   - Kafka consumer for routing requests
   - Kafka producer for routing responses
   - Correlation ID tracking
   - Error handling with fallback events

2. **Create RouterService** (`router_service.py`)
   - Wrap existing AgentRouter class
   - Add circuit breaker (use `pybreaker` or custom)
   - Add metrics collection (Prometheus)
   - Add registry hot reload (file watcher)

3. **Update main.py**
   - Initialize RouterEventHandler
   - Initialize RouterService
   - Start event consumption loop
   - Handle graceful shutdown

4. **Add Tests**
   - Unit tests for RouterService
   - Integration tests with Kafka
   - Health check endpoint tests

**Estimated Effort**: 2-3 days

---

## Success Criteria

### Docker Configuration (✅ Complete)

- [x] Service builds successfully
- [x] Starts without errors
- [x] Health check responds
- [x] Environment validation works
- [x] Graceful shutdown works

### Service Implementation (⏳ Pending)

- [ ] Consumes routing requests from Kafka
- [ ] Responds with agent recommendations
- [ ] Logs routing decisions to PostgreSQL
- [ ] Cache hit rate >60% after warmup
- [ ] Routing time <50ms (cache miss), <10ms (cache hit)
- [ ] Circuit breaker activates on failures
- [ ] Registry hot reload works

---

## Next Steps

1. **Implement RouterEventHandler** (request/response via Kafka)
2. **Implement RouterService** (wrap AgentRouter with enhancements)
3. **Add metrics and observability**
4. **Test end-to-end routing flow**
5. **Create RoutingEventClient** (Phase 2)

---

## Related Documentation

- [Event-Driven Routing Proposal](../../../docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md) - Full architecture proposal
- [Database Event-Driven Implementation](../../../docs/EVENT_DRIVEN_DATABASE_IMPLEMENTATION_STATUS.md) - Reference implementation
- [Agent Router Library](../../lib/agent_router.py) - Existing routing logic
- [Agent Registry](~/.claude/agent-definitions/agent-registry.yaml) - Agent definitions

---

## Contact

**Author**: DevOps Infrastructure Specialist (Polymorphic Agent)
**Date**: 2025-10-30
**Correlation ID**: 50cc9c90-35e6-48cd-befd-91ee3ce4b2b1
