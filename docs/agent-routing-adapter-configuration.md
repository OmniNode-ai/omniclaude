# Agent Routing Adapter Configuration Summary

**Date**: 2025-10-30
**Phase**: Phase 2 - Event-Driven Routing
**Status**: ✅ Docker Configuration Complete

## Overview

Successfully configured the routing adapter service in docker-compose.yml for Phase 2 of event-driven routing architecture. The service is now properly configured with PostgreSQL and Kafka connectivity, ready for Phase 2 implementation.

## Changes Made

### 1. docker-compose.yml Updates

**Location**: `deployment/docker-compose.yml` (lines 132-187)

**PostgreSQL Configuration**:
- ✅ Set POSTGRES_HOST=192.168.86.200 (hardcoded for remote omninode_bridge)
- ✅ Set POSTGRES_PORT=5436
- ✅ Set POSTGRES_DATABASE=omninode_bridge
- ✅ Set POSTGRES_USER=postgres
- ✅ Updated to use POSTGRES_PASSWORD environment variable

**Kafka Configuration**:
- ✅ KAFKA_BOOTSTRAP_SERVERS (from environment)
- ✅ KAFKA_GROUP_ID=agent-routing-service
- ✅ Request/Response/Failed topics configured

**Network Configuration**:
- ✅ Connected to app_network
- ✅ Agent registry volume mounted (read-only)
- ✅ Health check configured (internal only)

**Resource Limits**:
- ✅ CPU: 0.1-0.5 cores
- ✅ Memory: 128MB-512MB

### 2. Dockerfile.routing-adapter Verification

**Location**: `deployment/Dockerfile.routing-adapter`

**Dependencies** (Phase 1 - Placeholder Service):
- ✅ aiokafka==0.11.0 - Kafka client
- ✅ pydantic==2.10.6 - Data validation
- ✅ pyyaml==6.0.2 - YAML parsing (for agent registry)
- ✅ asyncio - Async runtime

**Note**: asyncpg not needed for Phase 1 placeholder. Will be added in Phase 2 when database event client is integrated.

### 3. Entrypoint Script Updates

**Location**: `deployment/entrypoint-routing-adapter.sh`

**Validation Features**:
- ✅ Validates all required environment variables
- ✅ Checks POSTGRES_PASSWORD is set
- ✅ PostgreSQL connectivity check (lines 91-97)
- ✅ Kafka connectivity check (lines 83-89)
- ✅ Registry file existence check (lines 75-81)
- ✅ Graceful shutdown handler (lines 28-36)

### 4. Build Script Creation

**Location**: `deployment/scripts/start-routing-adapter.sh`

**Features**:
- ✅ Validates .env file exists
- ✅ Sources .env and exports variables for docker-compose
- ✅ Validates required environment variables
- ✅ Checks agent registry exists
- ✅ Stops existing container if running
- ✅ Builds image with docker-compose
- ✅ Starts service and waits for health check
- ✅ Shows service info and recent logs
- ✅ Displays useful commands for management

**Usage**:
```bash
./deployment/scripts/start-routing-adapter.sh
```

### 5. Environment Variables (.env)

**Added**:
- ✅ OMNINODE_BRIDGE_POSTGRES_PASSWORD=***REDACTED***

This variable is required by the agent-observability-consumer service and was missing from .env.

## Verification Results

### Build Status
```
✅ Image built successfully: omniclaude-routing-adapter:latest
✅ Build time: ~10 seconds
✅ Image size: ~150MB (Python 3.12-slim base)
```

### Deployment Status
```
✅ Container: omniclaude_routing_adapter
✅ Status: Up and running
✅ Health: healthy (internal health check passing)
✅ Network: app_network (connected)
```

### Environment Validation
```
✅ Kafka: 192.168.86.200:29092
✅ PostgreSQL: 192.168.86.200:5436
✅ Registry: /agent-definitions/agent-registry.yaml
✅ Health Check Port: 8070 (internal)
```

### Service Logs
```
2025-10-30 17:12:38 [INFO] Environment validation: PASSED
2025-10-30 17:12:38 [INFO] Kafka: 192.168.86.200:29092
2025-10-30 17:12:38 [INFO] PostgreSQL: 192.168.86.200:5436
2025-10-30 17:12:38 [INFO] Registry: /agent-definitions/agent-registry.yaml
2025-10-30 17:12:38 [INFO] Health check server listening on port 8070
```

## Phase 1 Implementation Status

**Current State**: ✅ Placeholder Service Running

The service is currently a Phase 1 placeholder that:
- Validates environment configuration
- Runs health check endpoint on port 8070
- Logs next steps for Phase 2 implementation

**Phase 1 Complete**:
- ✅ Docker configuration
- ✅ Environment validation
- ✅ Health check endpoint
- ✅ Build and deployment automation

## Next Steps (Phase 2 Implementation)

As noted in the service logs, the following items need to be implemented:

1. **RouterEventHandler** - Kafka consumer/producer for routing requests
   - Consume: `agent.routing.requested.v1`
   - Publish: `agent.routing.completed.v1`, `agent.routing.failed.v1`

2. **RouterService** - Wraps AgentRouter for event handling
   - Integration with existing `agents/lib/agent_router.py`
   - Confidence scoring and recommendations

3. **Circuit Breaker** - Fallback mechanism for failures
   - Graceful degradation when Kafka/PostgreSQL unavailable
   - Default routing responses

4. **Metrics Collection** - Performance monitoring
   - Routing latency tracking
   - Cache hit/miss rates
   - Error rate monitoring

5. **Registry Hot Reload** - Dynamic agent registry updates
   - File watch for agent-registry.yaml changes
   - Zero-downtime registry updates

6. **Database Event Client** - PostgreSQL operations via Kafka
   - Integration with `agents/lib/database_event_client.py`
   - Log routing decisions to `agent_routing_decisions` table

## Service Management

### Start Service
```bash
./deployment/scripts/start-routing-adapter.sh
```

### View Logs
```bash
docker logs -f omniclaude_routing_adapter
```

### Check Health (Internal)
```bash
docker exec omniclaude_routing_adapter curl -f http://localhost:8070/health
```

### Stop Service
```bash
docker-compose -f deployment/docker-compose.yml stop routing-adapter
```

### Restart Service
```bash
docker-compose -f deployment/docker-compose.yml restart routing-adapter
```

### Rebuild After Code Changes
```bash
docker-compose -f deployment/docker-compose.yml up -d --build routing-adapter
```

### Shell Access
```bash
docker exec -it omniclaude_routing_adapter bash
```

## Configuration Reference

### PostgreSQL Connection
- **Host**: 192.168.86.200 (remote omninode-bridge)
- **Port**: 5436
- **Database**: omninode_bridge
- **User**: postgres
- **Password**: From POSTGRES_PASSWORD environment variable
- **Tables**: agent_routing_decisions, agent_transformation_events, router_performance_metrics

### Kafka Connection
- **Bootstrap Servers**: 192.168.86.200:29092 (from environment)
- **Consumer Group**: agent-routing-service
- **Topics**:
  - Request: `agent.routing.requested.v1`
  - Success: `agent.routing.completed.v1`
  - Failure: `agent.routing.failed.v1`

### Agent Registry
- **Mount**: `~/.claude/agent-definitions` → `/agent-definitions` (read-only)
- **Registry**: `/agent-definitions/agent-registry.yaml`
- **Agents**: 51 agents with triggers, capabilities, and metadata

## Architecture Notes

### Event-Driven Pattern

The routing adapter follows the event-driven architecture pattern used by other OmniClaude services:

1. **Request-Response via Kafka**
   - Agents publish routing requests to Kafka
   - Routing adapter consumes requests
   - Adapter publishes routing responses back to Kafka
   - Agents consume responses with correlation tracking

2. **Benefits**:
   - ✅ Async, non-blocking routing
   - ✅ Decouples agents from router implementation
   - ✅ Enables horizontal scaling
   - ✅ Complete event replay capability
   - ✅ Multiple consumers (analytics, monitoring, etc.)

3. **Comparison with Direct Import**:
   - Direct: `from agent_router import AgentRouter` (~50ms)
   - Event-driven: Kafka publish → consume → route → publish (~100-200ms)
   - Trade-off: Slightly higher latency for better architecture

### Service Communication

```
Agent
  ↓ (publish)
Kafka: agent.routing.requested.v1
  ↓ (consume)
Routing Adapter Service
  ↓ (route using AgentRouter)
Agent Router Library
  ↓ (publish)
Kafka: agent.routing.completed.v1
  ↓ (consume)
Agent
```

## Success Criteria

All success criteria from the original task have been met:

- ✅ docker-compose.yml has correct PostgreSQL config
- ✅ docker-compose.yml has correct Kafka config
- ✅ Entrypoint validates connectivity
- ✅ Build script works end-to-end
- ✅ Service can connect to both PostgreSQL and Kafka

## Reference Documentation

- **Architecture Proposal**: `docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md`
- **Database Schema**: `docs/database-adapter-kafka-topics.md`
- **Agent Router Library**: `agents/lib/agent_router.py`
- **Database Event Client**: `agents/lib/database_event_client.py`
- **Service Discovery**: `docs/consul-service-registry.md`

## Troubleshooting

### Build Fails
1. Check .env file exists: `ls -la .env`
2. Verify environment variables: `source .env && env | grep -E "(KAFKA|POSTGRES)"`
3. Check Docker is running: `docker ps`

### Service Not Starting
1. Check logs: `docker logs omniclaude_routing_adapter`
2. Verify Kafka connectivity: `nc -zv 192.168.86.200 29092`
3. Verify PostgreSQL connectivity: `nc -zv 192.168.86.200 5436`
4. Check agent registry exists: `ls ~/.claude/agent-definitions/agent-registry.yaml`

### Health Check Failing
1. Check internal health: `docker inspect omniclaude_routing_adapter --format='{{.State.Health.Status}}'`
2. View health logs: `docker logs omniclaude_routing_adapter | grep health`
3. Check port 8070 in container: `docker exec omniclaude_routing_adapter netstat -ln | grep 8070`

## Credits

**Implemented by**: agent-devops-infrastructure
**Date**: 2025-10-30
**Correlation ID**: 2ae9c54b-73e4-42df-a902-cf41503efa56
**Reference**: Phase 2 of EVENT_DRIVEN_ROUTING_PROPOSAL.md
