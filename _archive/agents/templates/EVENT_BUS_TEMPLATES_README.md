# Event Bus Integration Templates

## Overview

These Jinja2 templates provide event bus initialization and lifecycle management for generated ONEX Effect nodes. They enable automatic Kafka event publishing and Consul service registration.

**Stage**: 4.5 (Event Bus Integration)
**Created**: 2025-10-22
**Reference**: `../omniarchon/python/src/intelligence/nodes/node_intelligence_adapter_effect.py`

---

## Templates

### 1. `event_bus_init_effect.py.jinja2`

**Purpose**: Adds event bus infrastructure to Effect node `__init__` method.

**Usage**: Include this template snippet in the `__init__` method after regular initialization.

**Variables Required**:
- `kafka_bootstrap_servers`: Kafka bootstrap servers (default: `omninode-bridge-redpanda:9092`)
- `service_name`: Service name (e.g., `"database-writer"`)
- `node_name`: Full node name (e.g., `"NodePostgresqlWriterEffect"`)
- `node_name_lower`: Lowercase node name for instance ID (e.g., `"nodepostgresqlwritereffect"`)

**Generated Code**:
```python
# Event bus infrastructure (Stage 4.5: Event Bus Integration)
self.event_publisher: Optional[EventPublisher] = None
self._bootstrap_servers = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "omninode-bridge-redpanda:9092"
)
self._service_name = "database-writer"
self._instance_id = f"nodepostgresqlwritereffect-{uuid4().hex[:8]}"
self._node_id = uuid4()

# Lifecycle state
self.is_running = False
self._shutdown_event = asyncio.Event()

logger.info(
    f"NodePostgresqlWriterEffect initialized | "
    f"service={self._service_name} | "
    f"instance={self._instance_id}"
)
```

---

### 2. `event_bus_lifecycle.py.jinja2`

**Purpose**: Adds lifecycle methods (`initialize()`, `shutdown()`, `_publish_introspection_event()`) to Effect node class.

**Usage**: Include these methods in the generated Effect node class.

**Variables Required**:
- `node_name`: Full node name (e.g., `"NodePostgresqlWriterEffect"`)

**Generated Methods**:

#### `initialize()`
Initializes event publisher and publishes introspection event for Consul registration.

**Steps**:
1. Creates EventPublisher for Kafka
2. Publishes introspection event
3. Marks node as running

**Raises**: `RuntimeError` if initialization fails

---

#### `shutdown()`
Graceful shutdown with resource cleanup.

**Steps**:
1. Signals shutdown
2. Closes event publisher
3. Cleans up resources

**Note**: Does not raise exceptions - logs warnings on failure.

---

#### `_publish_introspection_event()`
Publishes introspection event for Consul service registration.

**Event Payload**:
- `node_id`: Unique node identifier
- `instance_id`: Instance identifier
- `service_name`: Service name
- `node_type`: Always "effect"
- `capabilities`: List of node capabilities
- `health_check_endpoint`: Health check URL
- `metadata`: Additional metadata (node class, initialization time)

**Topic**: `dev.omninode.system.introspection.v1`

---

#### `_get_node_capabilities()`
Returns list of capabilities this node provides. Override in generated nodes to specify actual capabilities.

**Default**: `["effect_operations"]`

---

## Required Imports

When using these templates, add the following imports to the generated Effect node:

```python
import asyncio
import os
from datetime import datetime
from typing import Optional
from uuid import uuid4

# Event infrastructure (from omniarchon)
# Import path depends on project structure:
# - Within omniarchon: from src.events.publisher.event_publisher import EventPublisher
# - As installed package: from omniarchon.events.publisher import EventPublisher
from src.events.publisher.event_publisher import EventPublisher
```

**Important**: The `EventPublisher` import path varies by deployment:
- **Within omniarchon project**: `from src.events.publisher.event_publisher import EventPublisher`
- **As installed package**: `from omniarchon.events.publisher import EventPublisher`
- **Docker/microservice**: Verify the package structure in your container

**Reference**: `../omniarchon/python/src/events/publisher/event_publisher.py`

---

## Integration with Effect Node Template

### In `effect_node_template.py`

**1. Add imports section**:
```python
import asyncio
import os
from datetime import datetime
from typing import Optional
from uuid import uuid4

from omniarchon.events.publisher import EventPublisher
```

**2. Include initialization in `__init__` method**:
```python
def __init__(self, container: ModelONEXContainer):
    super().__init__(container)
    self.container = container
    self.logger = logging.getLogger(__name__)

    # Mixin initialization
    {MIXIN_INITIALIZATION}

    # Event bus initialization (Stage 4.5)
    {% include 'event_bus_init_effect.py.jinja2' %}
```

**3. Include lifecycle methods in class body**:
```python
class Node{MICROSERVICE_NAME_PASCAL}Effect(NodeEffect{MIXIN_INHERITANCE}):
    """
    {MICROSERVICE_NAME} EFFECT Node
    ...
    """

    def __init__(self, container: ModelONEXContainer):
        # ... initialization code ...

    # Event bus lifecycle methods
    {% include 'event_bus_lifecycle.py.jinja2' %}

    async def process(self, input_data, correlation_id):
        # ... existing process method ...
```

---

## Example: Generated PostgreSQL Writer Effect Node

### Initialization
```python
def __init__(self, container: ModelONEXContainer):
    super().__init__(container)
    self.container = container
    self.logger = logging.getLogger(__name__)

    # Event bus infrastructure (Stage 4.5: Event Bus Integration)
    self.event_publisher: Optional[EventPublisher] = None
    self._bootstrap_servers = os.getenv(
        "KAFKA_BOOTSTRAP_SERVERS",
        "omninode-bridge-redpanda:9092"
    )
    self._service_name = "postgresql-writer"
    self._instance_id = f"nodepostgresqlwritereffect-{uuid4().hex[:8]}"
    self._node_id = uuid4()

    # Lifecycle state
    self.is_running = False
    self._shutdown_event = asyncio.Event()

    logger.info(
        f"NodePostgresqlWriterEffect initialized | "
        f"service={self._service_name} | "
        f"instance={self._instance_id}"
    )
```

### Usage
```python
# Create and initialize node
node = NodePostgresqlWriterEffect(container)
await node.initialize()  # Connects to Kafka, registers with Consul

# Use node for operations
result = await node.process(input_data, correlation_id)

# Graceful shutdown
await node.shutdown()  # Closes event publisher, cleans up
```

---

## Environment Variables

**KAFKA_BOOTSTRAP_SERVERS**:
- Description: Kafka bootstrap servers for event publishing
- Default: `omninode-bridge-redpanda:9092`
- Example: `kafka-broker-1:9092,kafka-broker-2:9092`

---

## Testing Recommendations

### Unit Tests
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_initialize_success():
    """Test successful initialization with event publisher."""
    node = NodePostgresqlWriterEffect(container)

    with patch('omniarchon.events.publisher.EventPublisher') as mock_publisher:
        mock_publisher.return_value.publish = AsyncMock()

        await node.initialize()

        assert node.is_running
        assert node.event_publisher is not None
        mock_publisher.return_value.publish.assert_called_once()

@pytest.mark.asyncio
async def test_initialize_failure_cleanup():
    """Test cleanup on initialization failure."""
    node = NodePostgresqlWriterEffect(container)

    with patch('omniarchon.events.publisher.EventPublisher') as mock_publisher:
        mock_publisher.side_effect = RuntimeError("Connection failed")

        with pytest.raises(RuntimeError):
            await node.initialize()

        assert not node.is_running

@pytest.mark.asyncio
async def test_shutdown_graceful():
    """Test graceful shutdown."""
    node = NodePostgresqlWriterEffect(container)

    with patch('omniarchon.events.publisher.EventPublisher') as mock_publisher:
        mock_publisher.return_value.publish = AsyncMock()
        mock_publisher.return_value.close = AsyncMock()

        await node.initialize()
        await node.shutdown()

        assert not node.is_running
        mock_publisher.return_value.close.assert_called_once()
```

### Integration Tests
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_introspection_event_published():
    """Test that introspection event is published to Kafka."""
    node = NodePostgresqlWriterEffect(container)

    # Use real Kafka consumer to verify event
    consumer = create_kafka_consumer(
        topics=["dev.omninode.system.introspection.v1"]
    )

    await node.initialize()

    # Consume and verify introspection event
    msg = consumer.poll(timeout=5.0)
    assert msg is not None

    event = json.loads(msg.value().decode('utf-8'))
    assert event["event_type"] == "node.introspection.v1"
    assert event["payload"]["service_name"] == "postgresql-writer"
    assert event["payload"]["node_type"] == "effect"

    await node.shutdown()
```

---

## Quality Checks

- [x] Valid Jinja2 syntax
- [x] Follows omniarchon pattern exactly
- [x] All variables clearly documented
- [x] Error handling included
- [x] Logging statements present
- [x] Imports documented
- [x] Testing recommendations provided

---

## Related Documentation

- **Reference Implementation**: `../omniarchon/python/src/intelligence/nodes/node_intelligence_adapter_effect.py`
- **Event Bus Architecture**: `docs/CLI_EVENT_BUS_MIGRATION.md`
- **Generation Pipeline**: `docs/GENERATION_PIPELINE.md`
- **ONEX Node Paradigm**: `OMNIBASE_CORE_NODE_PARADIGM.md`

---

## Changelog

### 2025-10-22 - Initial Creation
- Created `event_bus_init_effect.py.jinja2` for initialization
- Created `event_bus_lifecycle.py.jinja2` for lifecycle methods
- Added introspection event publishing for Consul registration
- Documented required imports and usage patterns
