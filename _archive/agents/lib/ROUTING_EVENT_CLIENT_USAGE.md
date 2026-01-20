# Routing Event Client - Usage Guide

Production-ready Kafka client for event-based agent routing requests.

## Overview

The `RoutingEventClient` enables agents to request intelligent routing decisions via Kafka events instead of direct `AgentRouter` instantiation. This provides:

- **Service Decoupling**: Agents don't need direct access to routing logic
- **Scalability**: Routing service can scale independently
- **Observability**: Complete event trail in Kafka topics
- **Fallback**: Graceful degradation to local routing on service unavailable
- **Performance**: <100ms p95 response time with request-response pattern

## Quick Start

### Basic Usage (Context Manager)

```python
from agents.lib.routing_event_client import RoutingEventClientContext

async def route_my_request():
    async with RoutingEventClientContext() as client:
        recommendations = await client.request_routing(
            user_request="optimize my database queries",
            max_recommendations=3,
        )

        if recommendations:
            best = recommendations[0]
            print(f"Selected agent: {best['agent_name']}")
            print(f"Confidence: {best['confidence']['total']:.2%}")
            print(f"Reason: {best['reason']}")
```

### Convenience Wrapper (Simplest)

```python
from agents.lib.routing_event_client import route_via_events

async def simple_routing():
    recommendations = await route_via_events(
        user_request="optimize my API performance",
        context={"domain": "api_development"},
        max_recommendations=3,
        timeout_ms=5000,
        fallback_to_local=True,  # Use local routing on failure
    )

    return recommendations[0] if recommendations else None
```

### Manual Lifecycle Management

```python
from agents.lib.routing_event_client import RoutingEventClient

async def manual_lifecycle():
    client = RoutingEventClient(
        bootstrap_servers="192.168.86.200:9092",
        request_timeout_ms=5000,
    )

    # Start client (connects to Kafka)
    await client.start()

    try:
        # Make multiple requests with same client
        rec1 = await client.request_routing("optimize database")
        rec2 = await client.request_routing("fix API errors")
        rec3 = await client.request_routing("improve UI performance")

        return [rec1, rec2, rec3]

    finally:
        # Always stop client to cleanup connections
        await client.stop()
```

## Configuration

### Environment Variables

```bash
# Kafka bootstrap servers (REQUIRED)
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092

# Feature flag to enable/disable event routing (default: true)
USE_EVENT_ROUTING=true
```

### Constructor Options

```python
client = RoutingEventClient(
    bootstrap_servers="192.168.86.200:9092",  # Kafka brokers
    request_timeout_ms=5000,                   # Default request timeout
    consumer_group_id="my-app-routing",        # Optional consumer group
)
```

## Request Options

### Full Request Options

```python
recommendations = await client.request_routing(
    user_request="optimize my database queries",

    # Optional context for better routing
    context={
        "domain": "database_optimization",
        "previous_agent": "agent-api-architect",
        "current_file": "api/database.py",
    },

    # Routing options
    max_recommendations=5,           # Max agents to return (1-10)
    min_confidence=0.6,              # Min confidence threshold (0.0-1.0)
    routing_strategy="enhanced_fuzzy_matching",  # Strategy name
    timeout_ms=5000,                 # Request timeout in ms
)
```

### Context Fields

Provide rich context for better routing decisions:

```python
context = {
    # Domain context
    "domain": "api_development",           # Domain hint
    "current_file": "api/endpoints.py",    # Current file path

    # Execution context
    "previous_agent": "agent-frontend",    # Last agent used
    "project_path": "/path/to/project",    # Project directory
    "project_name": "my-app",              # Project name

    # Correlation context
    "correlation_id": "abc-123",           # Request correlation ID
    "claude_session_id": "def-456",        # Claude session ID
}
```

## Response Format

### Recommendation Structure

```python
{
    "agent_name": "agent-performance",
    "agent_title": "Performance Optimization Specialist",
    "confidence": {
        "total": 0.92,                    # Overall confidence (0.0-1.0)
        "trigger_score": 0.95,            # Trigger match (40% weight)
        "context_score": 0.90,            # Context alignment (30% weight)
        "capability_score": 0.88,         # Capability match (20% weight)
        "historical_score": 0.95,         # Historical success (10% weight)
        "explanation": "High confidence match on 'optimize' trigger"
    },
    "reason": "Strong trigger match with 'optimize' keyword",
    "definition_path": "/Users/jonah/.claude/agent-definitions/agent-performance.yaml",
    "alternatives": ["agent-database-architect", "agent-api-architect"]
}
```

### Multiple Recommendations

```python
recommendations = await client.request_routing(
    user_request="optimize my API",
    max_recommendations=3,
)

# Recommendations are sorted by confidence (highest first)
for i, rec in enumerate(recommendations, 1):
    print(f"{i}. {rec['agent_name']} ({rec['confidence']['total']:.2%})")
    print(f"   {rec['reason']}")
```

## Error Handling

### Timeout Handling

```python
from asyncio import TimeoutError

try:
    recommendations = await client.request_routing(
        user_request="optimize database",
        timeout_ms=1000,  # Very short timeout
    )
except TimeoutError:
    print("Routing request timed out")
    # Use fallback logic
```

### Kafka Connection Errors

```python
from aiokafka.errors import KafkaError

try:
    await client.start()
except KafkaError as e:
    print(f"Failed to connect to Kafka: {e}")
    # Use local routing fallback
```

### Graceful Fallback

```python
from agents.lib.routing_event_client import route_via_events

# Automatic fallback to local routing on any error
recommendations = await route_via_events(
    user_request="optimize database",
    fallback_to_local=True,  # Enable fallback (default: True)
)

# Will return recommendations even if Kafka is unavailable
```

## Advanced Usage

### Health Check for Circuit Breaker

```python
async def routing_with_circuit_breaker():
    async with RoutingEventClientContext() as client:
        # Check health before requesting
        if not await client.health_check():
            print("Routing service unhealthy, using fallback")
            return fallback_routing()

        # Service healthy, use event routing
        return await client.request_routing("optimize database")
```

### Concurrent Requests

```python
import asyncio

async def concurrent_routing():
    async with RoutingEventClientContext() as client:
        # Send multiple requests in parallel
        tasks = [
            client.request_routing(f"optimize {domain}")
            for domain in ["database", "API", "frontend"]
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter successful results
        recommendations = [
            r for r in results
            if isinstance(r, list) and len(r) > 0
        ]

        return recommendations
```

### Feature Flag Control

```python
import os

# Disable event routing (use local routing)
os.environ["USE_EVENT_ROUTING"] = "false"

# Now all route_via_events calls will use local routing
recommendations = await route_via_events("optimize database")
```

### Custom Bootstrap Servers

```python
# Production Kafka cluster
client = RoutingEventClient(
    bootstrap_servers="kafka-prod-1:9092,kafka-prod-2:9092,kafka-prod-3:9092",
    request_timeout_ms=5000,
)

# Local development
client = RoutingEventClient(
    bootstrap_servers="localhost:9092",
    request_timeout_ms=5000,
)

# Docker internal network
client = RoutingEventClient(
    bootstrap_servers="omninode-bridge-redpanda:9092",
    request_timeout_ms=5000,
)
```

## Testing

### Run Integration Tests

```bash
# Run all tests
pytest agents/lib/test_routing_event_client.py -v

# Run specific test
pytest agents/lib/test_routing_event_client.py::TestRoutingEventClient::test_routing_request_success -v

# Run with verbose output
pytest agents/lib/test_routing_event_client.py -v -s
```

### Mock for Unit Tests

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def mock_routing_client():
    client = MagicMock()
    client.request_routing = AsyncMock(return_value=[
        {
            "agent_name": "agent-performance",
            "agent_title": "Performance Specialist",
            "confidence": {
                "total": 0.92,
                "trigger_score": 0.95,
                "context_score": 0.90,
                "capability_score": 0.88,
                "historical_score": 0.95,
                "explanation": "Test recommendation",
            },
            "reason": "Test match",
            "definition_path": "/path/to/agent.yaml",
        }
    ])
    return client

async def test_my_feature(mock_routing_client):
    recommendations = await mock_routing_client.request_routing("test")
    assert len(recommendations) == 1
    assert recommendations[0]["agent_name"] == "agent-performance"
```

## Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Request-Response Time | <100ms | p95, cache miss |
| Request-Response Time | <10ms | p95, cache hit |
| Client Start Time | <2s | Kafka connection + partition assignment |
| Memory Overhead | <20MB | Per client instance |
| Success Rate | >95% | Excluding network failures |

## Troubleshooting

### "Client not started" Error

**Problem**: Calling `request_routing()` before `start()`

**Solution**:
```python
# ❌ Wrong
client = RoutingEventClient()
await client.request_routing("test")  # Error!

# ✅ Correct
client = RoutingEventClient()
await client.start()
await client.request_routing("test")
await client.stop()

# ✅ Or use context manager
async with RoutingEventClientContext() as client:
    await client.request_routing("test")
```

### "Consumer failed to get partition assignment"

**Problem**: Kafka topics don't exist or broker unreachable

**Solution**:
1. Verify Kafka is running: `docker ps | grep redpanda`
2. Check topics exist: `docker exec omninode-bridge-redpanda rpk topic list`
3. Verify bootstrap servers: `echo $KAFKA_BOOTSTRAP_SERVERS`
4. Test connectivity: `telnet 192.168.86.200 9092`

### Timeout on Every Request

**Problem**: agent-router-service not running or consuming events

**Solution**:
1. Check service is running: `docker ps | grep agent-router`
2. Check service logs: `docker logs agent-router-service`
3. Verify service is consuming: Check consumer group lag
4. Enable fallback: `fallback_to_local=True`

### Fallback Always Used

**Problem**: Event routing not working, always using local routing

**Solution**:
1. Check feature flag: `echo $USE_EVENT_ROUTING` (should be "true")
2. Verify Kafka connectivity (see above)
3. Check agent-router-service is running
4. Review client logs for specific error messages

## Integration with Polymorphic Agent

### Using in Agent Code

```python
from agents.lib.routing_event_client import route_via_events

async def polymorphic_agent_routing(user_request: str):
    """Use in polymorphic agent for intelligent routing."""

    # Request routing via events (with fallback)
    recommendations = await route_via_events(
        user_request=user_request,
        context={
            "domain": detect_domain(user_request),
            "correlation_id": get_correlation_id(),
        },
        max_recommendations=3,
        fallback_to_local=True,
    )

    if not recommendations:
        return "polymorphic-agent"  # Default fallback

    # Use best recommendation
    selected_agent = recommendations[0]["agent_name"]
    confidence = recommendations[0]["confidence"]["total"]

    print(f"Selected agent: {selected_agent} ({confidence:.2%})")
    return selected_agent
```

## Migration from Local Routing

### Before (Local Routing)

```python
from agents.lib.agent_router import AgentRouter

def old_routing():
    router = AgentRouter()
    recommendations = router.route(
        user_request="optimize database",
        max_recommendations=3,
    )
    return recommendations[0] if recommendations else None
```

### After (Event Routing with Fallback)

```python
from agents.lib.routing_event_client import route_via_events

async def new_routing():
    # Drop-in replacement with event routing + fallback
    recommendations = await route_via_events(
        user_request="optimize database",
        max_recommendations=3,
        fallback_to_local=True,  # Falls back to AgentRouter on failure
    )
    return recommendations[0] if recommendations else None
```

## References

- **Implementation**: `agents/lib/routing_event_client.py`
- **Tests**: `agents/lib/test_routing_event_client.py`
- **Schemas**: `services/routing_adapter/schemas/`
- **Event Architecture**: `services/routing_adapter/IMPLEMENTATION_STATUS.md`
- **Database Pattern**: `agents/lib/database_event_client.py`

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review test examples in `test_routing_event_client.py`
3. Check service logs: `docker logs agent-router-service`
4. Review Kafka topics: `docker exec omninode-bridge-redpanda rpk topic list`

---

**Created**: 2025-10-30
**Version**: 1.0.0
**Status**: Production Ready
