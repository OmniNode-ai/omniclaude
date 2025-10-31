# Consul Service Registry Documentation

**Service Discovery Platform**: Consul 1.17
**Container**: `omninode-bridge-consul`
**Datacenter**: `omninode-bridge`

## Overview

Consul provides service discovery, health checking, and configuration management for the OmniNode Bridge infrastructure. Currently running but not yet integrated with database-adapter-effect service.

## Container Configuration

### Docker Container

```bash
# Container name
omninode-bridge-consul

# Image
hashicorp/consul:1.17

# Status
Up 18 hours (healthy)

# Port mappings
0.0.0.0:28500->8500/tcp    # HTTP API
0.0.0.0:28600->8600/udp    # DNS
```

### Access Methods

#### Local HTTP API

```bash
# Via mapped port
curl http://localhost:28500/v1/catalog/services

# Via container exec
docker exec omninode-bridge-consul consul catalog services
```

#### Docker Internal Network

```bash
# Service name: omninode-bridge-consul
# Network: omninode-bridge-network
# Internal address: 172.20.0.2:8500
```

## Current Service Registry Status

### Active Services

As of 2025-10-30, only the default Consul service is registered:

```bash
$ docker exec omninode-bridge-consul consul catalog services
consul
```

### Registered Nodes

```bash
$ docker exec omninode-bridge-consul consul catalog nodes
Node          ID        Address     DC
3a2c2472f238  eb04da50  172.20.0.2  omninode-bridge
```

**Node Details**:
- **Node ID**: `3a2c2472f238` (Docker container ID)
- **Consul ID**: `eb04da50`
- **Address**: `172.20.0.2` (Docker internal network)
- **Datacenter**: `omninode-bridge`

## Service Discovery Patterns

### Expected Service Registration (Not Yet Implemented)

The database-adapter-effect service SHOULD register with Consul but currently does NOT. Expected registration pattern:

```json
{
  "ID": "database-adapter-effect-1",
  "Name": "database-adapter-effect",
  "Tags": [
    "effect-node",
    "database",
    "kafka-consumer",
    "v1.0.0"
  ],
  "Address": "172.20.0.X",
  "Port": 8080,
  "Meta": {
    "version": "1.0.0",
    "node_type": "effect",
    "consumer_group": "database-adapter-effect-group",
    "kafka_topics": "workflow-started,workflow-completed,workflow-failed,step-completed,state-transition,state-aggregation-completed,stamp-created,node-heartbeat"
  },
  "Check": {
    "HTTP": "http://172.20.0.X:8080/health",
    "Interval": "30s",
    "Timeout": "5s",
    "DeregisterCriticalServiceAfter": "90s"
  }
}
```

### Health Check Configuration

**Expected Health Checks** (from contract.yaml):

#### 1. PostgreSQL Connectivity

```yaml
name: postgresql_connectivity
type: database
interval_seconds: 30
timeout_seconds: 5
critical: true
```

**Implementation**: `_check_database_health()` method in node.py (line 206)

```python
async def _check_database_health(self) -> tuple[HealthStatus, str, dict[str, Any]]:
    """Check PostgreSQL database connection health."""
    return await check_database_connection(
        self._connection_manager, timeout_seconds=2.0
    )
```

#### 2. Kafka Consumer

```yaml
name: kafka_consumer
type: network
interval_seconds: 60
timeout_seconds: 3
critical: false
```

**Status**: Not yet exposed to Consul

#### 3. Circuit Breaker Status

```yaml
name: circuit_breaker_status
type: internal
interval_seconds: 30
critical: true
```

**Implementation**: Part of `get_health_status()` (line 1339)

```python
# Check circuit breaker state
circuit_breaker_state = self._circuit_breaker.get_state()
if circuit_breaker_state.value == "open":
    database_status = "UNHEALTHY"
```

### Service Discovery API Endpoints

#### Catalog API

```bash
# List all services
curl http://localhost:28500/v1/catalog/services | jq '.'

# Get specific service details
curl http://localhost:28500/v1/catalog/service/database-adapter-effect | jq '.'

# List all nodes
curl http://localhost:28500/v1/catalog/nodes | jq '.'
```

#### Health API

```bash
# Get service health
curl http://localhost:28500/v1/health/service/database-adapter-effect | jq '.'

# Get node health
curl http://localhost:28500/v1/health/node/3a2c2472f238 | jq '.'
```

#### Agent API

```bash
# Register service
curl -X PUT http://localhost:28500/v1/agent/service/register \
  -d @service-definition.json

# Deregister service
curl -X PUT http://localhost:28500/v1/agent/service/deregister/database-adapter-effect-1
```

## Implementation Gaps

### Missing Components

1. **No Consul Registration Code**

   Search results show NO Consul-related code in database adapter:
   ```bash
   $ grep -r "consul" omninode_bridge/nodes/database_adapter_effect/
   # No results
   ```

2. **No Service Discovery Infrastructure**

   No Consul client integration in:
   - `node.py` (main node implementation)
   - `registry_bridge_database_adapter.py` (dependency injection)
   - Infrastructure layer

3. **No Health Endpoint Exposure**

   Health checks exist internally but not exposed via HTTP:
   - `get_health_status()` method implemented (line 1339)
   - Returns `ModelHealthResponse` with comprehensive status
   - NOT exposed via HTTP API for Consul to query

4. **No Service Metadata Management**

   Missing metadata for service discovery:
   - Node version
   - Kafka consumer group
   - Subscribed topics
   - Performance metrics endpoint

### Required Implementation

To enable Consul service discovery, implement:

#### 1. Consul Client Integration

```python
# Add to node.py initialization
from consul.aio import Consul

async def initialize(self) -> None:
    # ... existing initialization ...

    # Step 7: Register with Consul
    try:
        self._consul_client = Consul(
            host=os.getenv("CONSUL_HOST", "localhost"),
            port=int(os.getenv("CONSUL_PORT", "28500"))
        )

        await self._register_service()
        logger.info("Service registered with Consul")
    except Exception as e:
        logger.warning(f"Consul registration failed (non-critical): {e}")
        self._consul_client = None
```

#### 2. Service Registration

```python
async def _register_service(self) -> None:
    """Register database-adapter-effect service with Consul."""
    service_definition = {
        "ID": f"database-adapter-effect-{uuid4().hex[:8]}",
        "Name": "database-adapter-effect",
        "Tags": [
            "effect-node",
            "database",
            "kafka-consumer",
            f"version-{self._version}"
        ],
        "Address": os.getenv("SERVICE_HOST", "localhost"),
        "Port": int(os.getenv("SERVICE_PORT", "8080")),
        "Meta": {
            "version": "1.0.0",
            "node_type": "effect",
            "consumer_group": "database-adapter-effect-group",
            "kafka_topics": ",".join(self._kafka_consumer.subscribed_topics)
        },
        "Check": {
            "HTTP": f"http://{os.getenv('SERVICE_HOST', 'localhost')}:{os.getenv('SERVICE_PORT', '8080')}/health",
            "Interval": "30s",
            "Timeout": "5s",
            "DeregisterCriticalServiceAfter": "90s"
        }
    }

    await self._consul_client.agent.service.register(**service_definition)
```

#### 3. HTTP Health Endpoint

```python
# Add FastAPI or aiohttp server for health endpoint

from aiohttp import web

async def health_handler(request):
    """HTTP health endpoint for Consul health checks."""
    health_status = await self.get_health_status()

    if health_status.database_status == "HEALTHY":
        status_code = 200
    elif health_status.database_status == "DEGRADED":
        status_code = 429  # Too Many Requests (rate limiting)
    else:
        status_code = 503  # Service Unavailable

    return web.json_response(
        {
            "status": health_status.database_status,
            "database_version": health_status.database_version,
            "connection_pool": {
                "size": health_status.connection_pool_size,
                "available": health_status.connection_pool_available,
                "in_use": health_status.connection_pool_in_use
            },
            "uptime_seconds": health_status.uptime_seconds,
            "error_message": health_status.error_message
        },
        status=status_code
    )

# Start health server
app = web.Application()
app.router.add_get('/health', health_handler)
runner = web.AppRunner(app)
await runner.setup()
site = web.TCPSite(runner, '0.0.0.0', 8080)
await site.start()
```

#### 4. Service Deregistration

```python
async def shutdown(self) -> None:
    """Graceful shutdown with Consul deregistration."""
    # ... existing shutdown logic ...

    # Deregister from Consul
    if self._consul_client:
        try:
            await self._consul_client.agent.service.deregister(
                self._service_id
            )
            logger.info("Service deregistered from Consul")
        except Exception as e:
            logger.warning(f"Consul deregistration failed: {e}")

    # Close Consul client
    if self._consul_client:
        await self._consul_client.close()
```

## Service Discovery Queries

### Query by Service Name

```bash
# Get all instances of database-adapter-effect
curl http://localhost:28500/v1/catalog/service/database-adapter-effect | jq '.'
```

**Expected Response**:
```json
[
  {
    "ID": "database-adapter-effect-a1b2c3d4",
    "Node": "3a2c2472f238",
    "Address": "172.20.0.3",
    "Datacenter": "omninode-bridge",
    "TaggedAddresses": {
      "lan": "172.20.0.3",
      "wan": "172.20.0.3"
    },
    "NodeMeta": {},
    "ServiceID": "database-adapter-effect-a1b2c3d4",
    "ServiceName": "database-adapter-effect",
    "ServiceTags": [
      "effect-node",
      "database",
      "kafka-consumer",
      "version-1.0.0"
    ],
    "ServiceAddress": "172.20.0.3",
    "ServicePort": 8080,
    "ServiceMeta": {
      "version": "1.0.0",
      "node_type": "effect",
      "consumer_group": "database-adapter-effect-group",
      "kafka_topics": "workflow-started,workflow-completed,..."
    },
    "ServiceEnableTagOverride": false,
    "CreateIndex": 123,
    "ModifyIndex": 456
  }
]
```

### Query by Tags

```bash
# Get all effect nodes
curl 'http://localhost:28500/v1/catalog/service/database-adapter-effect?tag=effect-node' | jq '.'

# Get all database services
curl 'http://localhost:28500/v1/catalog/service/database-adapter-effect?tag=database' | jq '.'
```

### Health Checks

```bash
# Get only healthy instances
curl 'http://localhost:28500/v1/health/service/database-adapter-effect?passing=true' | jq '.'
```

**Expected Response**:
```json
[
  {
    "Node": {
      "ID": "eb04da50",
      "Node": "3a2c2472f238",
      "Address": "172.20.0.2",
      "Datacenter": "omninode-bridge"
    },
    "Service": {
      "ID": "database-adapter-effect-a1b2c3d4",
      "Service": "database-adapter-effect",
      "Tags": ["effect-node", "database"],
      "Address": "172.20.0.3",
      "Port": 8080
    },
    "Checks": [
      {
        "Node": "3a2c2472f238",
        "CheckID": "serfHealth",
        "Name": "Serf Health Status",
        "Status": "passing",
        "Notes": "",
        "Output": "Agent alive and reachable"
      },
      {
        "Node": "3a2c2472f238",
        "CheckID": "service:database-adapter-effect-a1b2c3d4",
        "Name": "Service 'database-adapter-effect' check",
        "Status": "passing",
        "Notes": "",
        "Output": "HTTP GET http://172.20.0.3:8080/health: 200 OK"
      }
    ]
  }
]
```

## Configuration

### Environment Variables

```bash
# Consul connection
CONSUL_HOST=omninode-bridge-consul
CONSUL_PORT=8500

# Service registration
SERVICE_HOST=database-adapter-effect
SERVICE_PORT=8080
SERVICE_VERSION=1.0.0

# Health check configuration
HEALTH_CHECK_INTERVAL=30s
HEALTH_CHECK_TIMEOUT=5s
HEALTH_CHECK_DEREGISTER_AFTER=90s
```

### Docker Compose Integration

```yaml
services:
  database-adapter-effect:
    image: omninode-bridge/database-adapter-effect:1.0.0
    environment:
      - CONSUL_HOST=omninode-bridge-consul
      - CONSUL_PORT=8500
      - SERVICE_HOST=database-adapter-effect
      - SERVICE_PORT=8080
    networks:
      - omninode-bridge-network
    depends_on:
      - omninode-bridge-consul
      - omninode-bridge-postgres
      - omninode-bridge-redpanda
```

## Monitoring and Observability

### Service Health States

| State | HTTP Code | Meaning |
|-------|-----------|---------|
| passing | 200 | Service healthy, all checks pass |
| warning | 429 | Service degraded (high pool utilization) |
| critical | 503 | Service unhealthy (database unreachable) |

### Health Check Logs

```bash
# View Consul agent logs
docker logs omninode-bridge-consul -f

# Filter for health check events
docker logs omninode-bridge-consul 2>&1 | grep "health check"
```

### Service Discovery Events

```bash
# Watch service registrations
consul watch -type=services \
  -http-addr=http://localhost:28500 \
  /usr/local/bin/notify-service-change.sh

# Watch service health
consul watch -type=service -service=database-adapter-effect \
  -http-addr=http://localhost:28500 \
  /usr/local/bin/notify-health-change.sh
```

## Best Practices

### 1. Service Registration

- **Unique Service IDs**: Use UUID or hostname-based IDs to prevent conflicts
- **Meaningful Tags**: Use tags for filtering (effect-node, database, version)
- **Rich Metadata**: Include version, consumer group, topics in metadata
- **Graceful Deregistration**: Always deregister on shutdown

### 2. Health Checks

- **HTTP vs Script**: Prefer HTTP health checks for simplicity
- **Check Intervals**: 30s is reasonable for most services
- **Timeout Configuration**: Set timeout < interval to prevent overlaps
- **Deregister Timing**: Set to 3x interval for transient failures

### 3. Service Discovery

- **Cache Service Lookups**: Use Consul's blocking queries for efficiency
- **Filter by Health**: Always query with `?passing=true` for production
- **Handle Failures**: Implement fallback for service discovery failures
- **Version Compatibility**: Use tags/metadata for version-aware discovery

## References

### Consul Documentation

- **Catalog API**: https://developer.hashicorp.com/consul/api-docs/catalog
- **Health API**: https://developer.hashicorp.com/consul/api-docs/health
- **Agent API**: https://developer.hashicorp.com/consul/api-docs/agent/service
- **Service Registration**: https://developer.hashicorp.com/consul/docs/discovery/services

### OmniNode Bridge Files

- **Database Adapter Contract**: `/contracts/effects/database_adapter_effect.yaml`
- **Node Implementation**: `nodes/database_adapter_effect/v1_0_0/node.py`
- **Health Check Mixin**: `nodes/mixins/health_mixin.py`
- **Registry**: `nodes/database_adapter_effect/v1_0_0/registry/registry_bridge_database_adapter.py`

### Related Documentation

- **Kafka Topics**: `/docs/database-adapter-kafka-topics.md`
- **Database Schema**: `/docs/database/DATABASE_GUIDE.md`
- **Bridge Architecture**: `/docs/architecture/ARCHITECTURE.md`

---

## Summary

### Current Status

✅ Consul running healthy
✅ Docker container accessible (port 28500)
✅ Health check infrastructure in node.py
❌ No service registration implementation
❌ No HTTP health endpoint
❌ No Consul client integration
❌ No service discovery queries

### Next Steps

1. **Add Consul Client**: Integrate `python-consul` library
2. **Implement Registration**: Add service registration in `initialize()`
3. **Expose Health Endpoint**: Add HTTP server with `/health` endpoint
4. **Service Deregistration**: Add cleanup in `shutdown()`
5. **Documentation**: Update deployment docs with Consul patterns
6. **Testing**: Verify service discovery and health checks

### Implementation Priority

**High Priority**:
- HTTP health endpoint (required for Consul health checks)
- Service registration/deregistration (basic service discovery)

**Medium Priority**:
- Rich service metadata (Kafka topics, consumer group)
- Health check tuning (intervals, timeouts)

**Low Priority**:
- Service watch handlers (event-driven updates)
- Advanced health checks (custom scripts)

---

**Last Updated**: 2025-10-30
**Correlation ID**: 9e416a8e-a6ba-446b-aa17-1362f68ab911
