# Node Generation Dependency Matrix

**Quick Reference**: What to import vs what to generate for ONEX node generation

---

## Decision Tree

```
User Prompt → Analyze Node Type → Select Dependencies → Generate Node-Specific Code
```

---

## 1. ALWAYS Import (Never Generate)

### Base Infrastructure (omnibase_core)

```python
# Base node classes - ALWAYS import
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.nodes.node_orchestrator import NodeOrchestrator
from omnibase_core.nodes.node_reducer import NodeReducer
from omnibase_core.nodes.node_compute import NodeCompute

# Container & DI - ALWAYS import
from omnibase_core.models.container.model_onex_container import ModelONEXContainer

# Contracts - ALWAYS import
from omnibase_core.models.contracts.model_contract_effect import ModelContractEffect
from omnibase_core.models.contracts.model_contract_orchestrator import ModelContractOrchestrator
from omnibase_core.models.contracts.model_contract_reducer import ModelContractReducer
from omnibase_core.models.contracts.model_contract_compute import ModelContractCompute

# Error handling - ALWAYS import
from omnibase_core import EnumCoreErrorCode, ModelOnexError
from omnibase_core.enums.enum_log_level import EnumLogLevel as LogLevel
from omnibase_core.logging.structured import emit_log_event_sync as emit_log_event

# Standard aliases - ALWAYS use
OnexError = ModelOnexError
```

### Services (omninode_bridge.services)

```python
# Event bus - import if event-driven coordination needed
from omninode_bridge.services.event_bus import EventBusService

# Kafka - import if Kafka integration needed
from omninode_bridge.services.kafka_client import KafkaClient

# PostgreSQL - import if database persistence needed
from omninode_bridge.services.postgres_client import PostgresClient

# Canonical store - import if optimistic concurrency control needed
from omninode_bridge.services.canonical_store import CanonicalStoreService
```

### Mixins (omninode_bridge.nodes.mixins)

```python
# Health checks - import for ALL production nodes
from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin, HealthStatus

# Introspection - import if self-reporting/heartbeat needed
from omninode_bridge.nodes.mixins.introspection_mixin import IntrospectionMixin
```

---

## 2. ALWAYS Generate (Node-Specific)

### Directory Structure

```
nodes/<node_name>_<type>/v1_0_0/
├── __init__.py                    # GENERATE: Package initialization
├── node.py                        # GENERATE: Main node implementation
├── contract.yaml                  # GENERATE: Contract specification
├── models/
│   ├── __init__.py                # GENERATE: Models package init
│   ├── inputs/
│   │   ├── __init__.py            # GENERATE
│   │   └── model_*_input.py       # GENERATE: Input models
│   ├── outputs/
│   │   ├── __init__.py            # GENERATE
│   │   └── model_*_output.py      # GENERATE: Output models
│   ├── entities/                  # Optional: domain entities
│   │   ├── __init__.py            # GENERATE if needed
│   │   └── model_*.py             # GENERATE: Entity models
│   └── events/                    # Optional: custom events
│       ├── __init__.py            # GENERATE if needed
│       └── model_*_event.py       # GENERATE: Event models
└── enums/
    ├── __init__.py                # GENERATE: Enums package init
    └── enum_*.py                  # GENERATE: Enumerations
```

### Code Files to Generate

| File | Purpose | Required? |
|------|---------|-----------|
| `node.py` | Main node class | ✅ Always |
| `contract.yaml` | Contract spec | ✅ Always |
| `model_*_input.py` | Input models | ✅ Always |
| `model_*_output.py` | Output models | ✅ Always |
| `enum_*.py` | Enumerations | ✅ If FSM states or types needed |
| `model_*_event.py` | Event models | ⚠️ If custom events needed |
| `model_*.py` (entities) | Domain entities | ⚠️ If domain models needed |
| `main.py` | Standalone entry point | ⚠️ If standalone service |
| `main_standalone.py` | Standalone service | ⚠️ If HTTP service |

---

## 3. Conditional Imports (Depends on Node Type)

### By Node Type

#### Effect Nodes

**ALWAYS Import**:
```python
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.models.contracts.model_contract_effect import ModelContractEffect
from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin
```

**Conditional Imports** (based on requirements):
```python
# If Kafka integration
from omninode_bridge.services.kafka_client import KafkaClient

# If PostgreSQL persistence
from omninode_bridge.services.postgres_client import PostgresClient

# If HTTP API calls
import httpx  # External dependency

# If file operations
from pathlib import Path
```

#### Orchestrator Nodes

**ALWAYS Import**:
```python
from omnibase_core.nodes.node_orchestrator import NodeOrchestrator
from omnibase_core.models.contracts.model_contract_orchestrator import ModelContractOrchestrator
from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin
from omninode_bridge.nodes.mixins.introspection_mixin import IntrospectionMixin
```

**Conditional Imports**:
```python
# If event-driven coordination
from omninode_bridge.services.event_bus import EventBusService

# If FSM state management
from .models.enum_workflow_state import EnumWorkflowState
from .models.enum_workflow_event import EnumWorkflowEvent

# If parallel execution
from omnibase_core.nodes.model_load_balancer import ModelLoadBalancer
```

#### Reducer Nodes

**ALWAYS Import**:
```python
from omnibase_core.nodes.node_reducer import NodeReducer
from omnibase_core.models.contracts.model_contract_reducer import ModelContractReducer
from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin
```

**Conditional Imports**:
```python
# If streaming aggregation
from collections import defaultdict
from collections.abc import AsyncIterator

# If state persistence
from omninode_bridge.services.postgres_client import PostgresClient

# If FSM state management
from omnibase_core.models.contracts.subcontracts import ModelFSMSubcontract
```

#### Compute Nodes

**ALWAYS Import**:
```python
from omnibase_core.nodes.node_compute import NodeCompute
from omnibase_core.models.contracts.model_contract_compute import ModelContractCompute
```

**Conditional Imports**:
```python
# If caching needed
from omnibase_core.models.configuration.model_compute_cache_config import ModelComputeCacheConfig

# If performance monitoring needed
from omnibase_core.monitoring.performance_monitor import PerformanceMonitor
```

---

## 4. Generation Decision Matrix

### Input: User Prompt Analysis

Extract from prompt:
1. **Node Type**: Effect, Orchestrator, Reducer, or Compute
2. **Node Name**: Descriptive name (e.g., "DatabaseWriter", "WorkflowCoordinator")
3. **Purpose**: High-level description
4. **Dependencies**: Kafka, PostgreSQL, HTTP APIs, etc.
5. **Special Features**: FSM, introspection, health checks, etc.

### Output: Dependency List + Code Generation Plan

#### Step 1: Determine Base Class

| Prompt Keywords | Node Type | Base Class |
|----------------|-----------|------------|
| "database write", "API call", "file operation", "side effect" | Effect | `NodeEffect` |
| "workflow", "coordinate", "orchestrate", "FSM", "multi-step" | Orchestrator | `NodeOrchestrator` |
| "aggregate", "reduce", "collect", "persist state", "streaming" | Reducer | `NodeReducer` |
| "transform", "calculate", "compute", "pure function" | Compute | `NodeCompute` |

#### Step 2: Determine Mixins

| Requirement | Mixin | Import |
|-------------|-------|--------|
| Production node (always) | HealthCheckMixin | `from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin` |
| Self-reporting/heartbeat | IntrospectionMixin | `from omninode_bridge.nodes.mixins.introspection_mixin import IntrospectionMixin` |

#### Step 3: Determine Service Dependencies

| Requirement | Service | Import |
|-------------|---------|--------|
| Event-driven coordination | EventBusService | `from omninode_bridge.services.event_bus import EventBusService` |
| Kafka streaming | KafkaClient | `from omninode_bridge.services.kafka_client import KafkaClient` |
| PostgreSQL persistence | PostgresClient | `from omninode_bridge.services.postgres_client import PostgresClient` |
| Optimistic concurrency | CanonicalStoreService | `from omninode_bridge.services.canonical_store import CanonicalStoreService` |

#### Step 4: Generate Node-Specific Models

| Model Type | Generate? | Example |
|------------|-----------|---------|
| Input | ✅ Always | `model_stamp_request_input.py` |
| Output | ✅ Always | `model_stamp_response_output.py` |
| Entity | ⚠️ If domain models | `model_workflow_execution.py` |
| Event | ⚠️ If custom events | `model_workflow_event.py` |
| Enum (States) | ✅ If FSM | `enum_workflow_state.py` |
| Enum (Types) | ✅ If categorization | `enum_operation_type.py` |

#### Step 5: Generate Contract YAML

```yaml
name: <node_name>
version: "1.0.0"
description: <description>
node_type: <effect|orchestrator|reducer|compute>

# Type-specific subcontracts
<subcontract_type>_subcontract:
  # Configuration based on node type
```

---

## 5. Example Decision Flow

### Example Prompt

```
Create a node that listens for workflow execution events from Kafka,
aggregates metrics by namespace, and persists aggregated state to PostgreSQL.
```

### Analysis

- **Keywords**: "listens for events", "aggregates", "persists state"
- **Node Type**: Reducer (aggregation + state persistence)
- **Dependencies**: Kafka (input), PostgreSQL (output)
- **Features**: Streaming aggregation, namespace isolation

### Decision

**Base Class**: `NodeReducer`

**Mixins**: `HealthCheckMixin` (production standard)

**Services**:
- `KafkaClient` (event streaming)
- `PostgresClient` (state persistence)

**Generate**:
- `node.py` - Main reducer implementation
- `contract.yaml` - Reducer contract with aggregation subcontract
- `model_reducer_input_state.py` - Input state model
- `model_reducer_output_state.py` - Output state model
- `enum_aggregation_type.py` - Aggregation type enum
- `enum_reducer_event.py` - Reducer event enum

**DON'T Generate** (import instead):
- `NodeReducer` base class
- `ModelContractReducer`
- `ModelONEXContainer`
- `KafkaClient`
- `PostgresClient`
- `HealthCheckMixin`

---

## 6. Import Template by Node Type

### Effect Node Template

```python
#!/usr/bin/env python3
"""Node<Name>Effect - <Description>."""

# Standard library
import asyncio
import time
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID, uuid4

# omnibase_core (ALWAYS IMPORT)
from omnibase_core import EnumCoreErrorCode, ModelOnexError
from omnibase_core.enums.enum_log_level import EnumLogLevel as LogLevel
from omnibase_core.logging.structured import emit_log_event_sync as emit_log_event
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omnibase_core.models.contracts.model_contract_effect import ModelContractEffect
from omnibase_core.nodes.node_effect import NodeEffect

# Aliases
OnexError = ModelOnexError

# Services (CONDITIONAL - based on requirements)
from omninode_bridge.services.kafka_client import KafkaClient  # If Kafka
from omninode_bridge.services.postgres_client import PostgresClient  # If PostgreSQL

# Mixins (ALWAYS for production)
from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin, HealthStatus

# Node-specific models (GENERATE)
from .models.model_*_input import Model*Input
from .models.model_*_output import Model*Output
```

### Orchestrator Node Template

```python
#!/usr/bin/env python3
"""Node<Name>Orchestrator - <Description>."""

# Standard library
import asyncio
import time
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID, uuid4

# omnibase_core (ALWAYS IMPORT)
from omnibase_core import EnumCoreErrorCode, ModelOnexError
from omnibase_core.enums.enum_log_level import EnumLogLevel as LogLevel
from omnibase_core.logging.structured import emit_log_event_sync as emit_log_event
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omnibase_core.models.contracts.model_contract_orchestrator import ModelContractOrchestrator
from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

# Aliases
OnexError = ModelOnexError

# Services (CONDITIONAL)
from omninode_bridge.services.event_bus import EventBusService  # If event-driven
from omninode_bridge.services.kafka_client import KafkaClient  # If Kafka

# Mixins (ALWAYS for production)
from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin, HealthStatus
from omninode_bridge.nodes.mixins.introspection_mixin import IntrospectionMixin

# Node-specific models (GENERATE)
from .models.enum_workflow_state import EnumWorkflowState
from .models.enum_workflow_event import EnumWorkflowEvent
from .models.model_*_output import Model*Output
```

### Reducer Node Template

```python
#!/usr/bin/env python3
"""Node<Name>Reducer - <Description>."""

# Standard library
import asyncio
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID, uuid4

# omnibase_core (ALWAYS IMPORT)
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omnibase_core.models.contracts.model_contract_reducer import ModelContractReducer
from omnibase_core.nodes.node_reducer import NodeReducer

# Services (CONDITIONAL)
from omninode_bridge.services.postgres_client import PostgresClient  # If persistence
from omninode_bridge.services.kafka_client import KafkaClient  # If streaming

# Mixins (ALWAYS for production)
from omninode_bridge.nodes.mixins.health_mixin import HealthCheckMixin, HealthStatus

# Node-specific models (GENERATE)
from .models.model_input_state import ModelReducerInputState
from .models.model_output_state import ModelReducerOutputState
from .models.enum_aggregation_type import EnumAggregationType
```

### Compute Node Template

```python
#!/usr/bin/env python3
"""Node<Name>Compute - <Description>."""

# Standard library
from typing import Any
from uuid import uuid4

# omnibase_core (ALWAYS IMPORT)
from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omnibase_core.models.contracts.model_contract_compute import ModelContractCompute
from omnibase_core.nodes.node_compute import NodeCompute

# Node-specific models (GENERATE)
from .models.model_compute_input import ModelComputeInput
from .models.model_compute_output import ModelComputeOutput
```

---

## 7. Validation Checklist

Before generating code, verify:

### Imports Validation

- [ ] Base class imported from omnibase_core (NOT generated)
- [ ] Contract model imported from omnibase_core (NOT generated)
- [ ] Container imported from omnibase_core (NOT generated)
- [ ] Services imported from omninode_bridge.services (NOT generated)
- [ ] Mixins imported from omninode_bridge.nodes.mixins (NOT generated)
- [ ] Node-specific models referenced from local `.models` (WILL BE generated)

### Code Generation Validation

- [ ] Node class extends correct base class
- [ ] Mixins included as multiple inheritance (if needed)
- [ ] Container passed to `__init__` and `super().__init__(container)`
- [ ] Dependencies resolved from container
- [ ] Abstract method implemented (execute_effect/orchestration/reduction/compute)
- [ ] Health checks registered (if HealthCheckMixin used)
- [ ] ONEX v2.0 naming conventions followed (suffix-based)

### File Generation Validation

- [ ] Directory structure follows conventions (`nodes/<name>_<type>/v1_0_0/`)
- [ ] All `__init__.py` files generated
- [ ] Contract YAML generated with correct node_type
- [ ] Input/output models generated in correct directories
- [ ] Enums generated in `enums/` directory
- [ ] Main node file (`node.py`) generated with complete implementation

---

**End of Dependency Matrix**

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────┐
│ ONEX Node Generation Quick Reference                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ ALWAYS IMPORT (omnibase_core):                             │
│   • Node<Type> base classes                                │
│   • ModelContract<Type>                                    │
│   • ModelONEXContainer                                     │
│   • ModelOnexError, EnumCoreErrorCode                      │
│                                                             │
│ ALWAYS IMPORT (omninode_bridge.services):                  │
│   • KafkaClient (if Kafka)                                 │
│   • PostgresClient (if PostgreSQL)                         │
│   • EventBusService (if event-driven)                      │
│                                                             │
│ ALWAYS IMPORT (omninode_bridge.nodes.mixins):              │
│   • HealthCheckMixin (production standard)                 │
│   • IntrospectionMixin (if self-reporting)                 │
│                                                             │
│ ALWAYS GENERATE:                                           │
│   • node.py (main implementation)                          │
│   • contract.yaml (contract spec)                          │
│   • model_*_input.py (input models)                        │
│   • model_*_output.py (output models)                      │
│   • enum_*.py (enumerations)                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
