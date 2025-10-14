# Autonomous OmniNode Code Generation - Event-Driven Architecture (MVP)

## Overview

Build an event-driven autonomous code generation system that transforms PRDs into fully functional OmniNodes using Redpanda/Kafka for asynchronous communication between omniclaude and omniarchon. The system leverages existing event bus infrastructure, ONEX patterns, and intelligence services to generate YAML contracts, Pydantic models, and business logic.

**Scope**: Focus on core repositories only (omnibase_core, omniarchon, omninode_bridge, omni_spi, omniclaude). Other repositories (omnibase_infra, omniplan) will be ported later.

## Event-Driven Architecture

### Communication Pattern

**Event Bus**: Redpanda (already deployed at `omninode-bridge-redpanda:9092`)

**Topic Structure**:
- Request topics: `omninode.codegen.request.{operation}.v1`
- Response topics: `omninode.codegen.response.{operation}.v1`
- Status topics: `omninode.codegen.status.{session_id}.v1`

**Services**:
- **omniclaude**: Workflow orchestrator, publishes codegen requests
- **omniarchon**: Intelligence service, consumes requests and publishes intelligence
- **Shared DB**: PostgreSQL for state persistence and coordination

### Event Flow

```
PRD Input
    ↓
[omniclaude] Publish: codegen.request.analyze.v1
    ↓ (via Redpanda)
[omniarchon] Consume → LangExtract + ResearchOrchestrator
    ↓
[omniarchon] Publish: codegen.response.analyze.v1
    ↓ (via Redpanda)
[omniclaude] Consume → Generate tasks
    ↓
[omniclaude] Publish: codegen.request.generate.{type}.v1
    ↓ (via Redpanda)
[omniarchon] Consume → Quality validation
    ↓
[omniarchon] Publish: codegen.response.validate.v1
    ↓ (via Redpanda)
[omniclaude] Consume → Write files if valid
```

## Key Discoveries from omni** Repositories

### Existing Assets to Leverage

**omniagent** (archived but rich):
- `prd_parser.py`: Production-ready PRD markdown parser with node type classification (COMPUTE/EFFECT/REDUCER/ORCHESTRATOR keyword detection)
- `prd_decomposition_service.py`: Task decomposition with priority, complexity, dependencies, critical path analysis
- `prd_to_node_generator.py`: LangGraph-based workflow orchestrator with verification loops
- `contract_generation_service.py`: Contract and subcontract generation
- `node_generation_service.py`: Node code generation with test/docs

**omnibase_3** (TO BE PORTED LATER):
- `builder_dockerfile.py`: Type-safe Dockerfile builder with Pydantic models
- For MVP: Create local Dockerfile generation in omniclaude

**omnibase_core**:
- Mixin system: `MixinEventBus`, `MixinCaching`, `MixinHealthCheck`, etc.
- Contract models for declarative composition
- ONEX Four-Node architecture enforcement

**omninode_bridge**:
- Event models (`ServiceLifecycleEvent`, `ToolExecutionEvent`) with `to_kafka_topic()` methods
- `kafka_client.py`: Production Kafka client with DLQ, retries, compression, batching
- Tool metadata standard v0.1 for registry integration

**omni_spi**:
- O.N.E. protocol specifications
- Tool metadata standard v0.1

### Reuse Strategy (Concurrent Work Stream Context)

**Critical Context**: Core library (`omnibase_core`), SPI (`omni_spi`), Bridge (`omninode_bridge`), and Archon (`omniarchon`) are undergoing **concurrent standardization** while we build MVP code. All components need Pydantic 2.x alignment.

**Strategy**:

1. **Copy and adapt** omniagent code with **version isolation**:
   - Copy to `agents/lib/legacy/` with original Pydantic 1.x
   - Create **adapter layer** in `agents/lib/` that wraps legacy code with Pydantic 2.x interfaces
   - When core library stabilizes, replace adapters with direct imports

2. **Use abstract interfaces** for core dependencies:
   - Define local interfaces matching omnibase_core contracts (e.g., `INodeEffectService`, `IMixinEventBus`)
   - Implement with current omnibase_core when available, or local stubs when not
   - Add feature flags: `USE_CORE_STABLE=false` to control which implementation is used

3. **Local template system** (until omnibase_infra is ported):
   - Create local node templates in `agents/templates/`
   - Parse templates as strings with placeholder substitution
   - Track template version in `generation_artifacts.template_version`

4. **Bridge integration via events only**:
   - Copy event model **patterns** (not direct imports) to avoid version coupling
   - Define local event models that match omninode_bridge schema but are independently versionable
   - Use Kafka as the contract boundary (schema evolution via topic versioning)

5. **Dynamic mixin discovery**:
   - Query omnibase_core filesystem for available mixins (no import needed)
   - Parse mixin files to extract metadata and compatibility info
   - Generate code that **references** mixins by string (will import at runtime)

**Version Migration Path**:
```
Phase 1 (Now): MVP with adapters and local interfaces
    ↓
Phase 2 (Core stabilizes): Feature flag to use stable core
    ↓
Phase 3 (Post-stabilization): Remove adapters, direct imports
```

**Files to Support Version Flexibility**:
- `agents/lib/version_config.py` - Feature flags for dependency versions
- `agents/lib/adapters/` - Adapter layer for cross-version compatibility
- `agents/lib/interfaces/` - Local interface definitions
- `agents/lib/legacy/` - Copied code from omniagent (Pydantic 1.x)
- `agents/templates/` - Local node templates (until omnibase_infra ported)

## Implementation Components

### 1. Event Models & Kafka Integration

**File**: `agents/lib/codegen_events.py`

Extend omninode_bridge event patterns:
- `CodegenAnalysisRequest(BaseEvent)` - PRD analysis request
- `CodegenAnalysisResponse(BaseEvent)` - Parsed PRD + node type hints
- `CodegenGenerationRequest(BaseEvent)` - Template + contract generation
- `CodegenValidationRequest(BaseEvent)` - Quality check request
- `CodegenValidationResponse(BaseEvent)` - ONEX compliance scores
- `CodegenStatusEvent(BaseEvent)` - Real-time status updates

Each event includes `to_kafka_topic()` method:
```python
def to_kafka_topic(self) -> str:
    return f"dev.omniclaude.codegen.{self.event.value}.v1"
```

**File**: `agents/lib/kafka_codegen_client.py`

Kafka client for code generation (copy patterns from `omninode_bridge/kafka_client.py`):
- Initialize with `bootstrap_servers: omninode-bridge-redpanda:9092`
- Topic management and auto-creation
- Async publish/subscribe patterns
- Correlation ID tracking for request/response matching
- Consumer group: `omniclaude-codegen-consumer`
- DLQ handling, circuit breaker, retry with exponential backoff

### 2. PRD Analysis Service (Event-Driven)

**File**: `agents/lib/prd_analyzer.py`

PRD analysis workflow:
1. Publish `CodegenAnalysisRequest` to Redpanda
2. Include: PRD content, correlation_id, workspace context
3. Subscribe to `codegen.response.analyze.v1` topic
4. Wait for response with timeout (30s default)
5. Extract: node types, domain concepts, required mixins, external systems

Response contains intelligence from omniarchon:
- Semantic analysis (from LangExtract)
- Similar node patterns (from ResearchOrchestrator)
- Recommended mixins (from Pattern Learning)
- Quality baseline expectations

### 3. Local Template Engine (Until omnibase_infra Ported)

**File**: `agents/lib/omninode_template_engine.py`

Template loading and generation:
- Load templates from local `agents/templates/` directory
- Parse customization points (REPOSITORY_NAME, DOMAIN, MICROSERVICE_NAME)
- Support mixin composition from omnibase_core
- Generate versioned directory structures (v1_0_0/)
- Create `__init__.py` files with proper exports

**File**: `agents/templates/effect_node_template.py`

Local EFFECT node template (copied from omnibase_infra patterns):
```python
EFFECT_NODE_TEMPLATE = """
#!/usr/bin/env python3
\"\"\"
{DOMAIN} {MICROSERVICE_NAME} Effect Node - ONEX 4-Node Architecture Implementation.

{BUSINESS_DESCRIPTION}

This microservice handles {DOMAIN} {MICROSERVICE_NAME} operations:
- [OPERATION_1]: [Description]
- [OPERATION_2]: [Description]  
- [OPERATION_3]: [Description]

Key Features:
- [FEATURE_1]: [Description]
- [FEATURE_2]: [Description]
- [FEATURE_3]: [Description]
\"\"\"

import asyncio
import logging
from typing import Dict, List, Optional, Union, Any
from uuid import UUID, uuid4

from omnibase_core.core.node_effect import ModelEffectInput, ModelEffectOutput
from omnibase_core.core.node_effect_service import NodeEffectService
from omnibase_core.core.onex_container import ModelONEXContainer as ONEXContainer

# Mixin imports (generated based on requirements)
{MIXIN_IMPORTS}

from .models.model_{MICROSERVICE_NAME}_input import Model{MICROSERVICE_NAME_PASCAL}Input
from .models.model_{MICROSERVICE_NAME}_output import Model{MICROSERVICE_NAME_PASCAL}Output
from .models.model_{MICROSERVICE_NAME}_config import Model{MICROSERVICE_NAME_PASCAL}Config
from .enums.enum_{MICROSERVICE_NAME}_operation_type import Enum{MICROSERVICE_NAME_PASCAL}OperationType


class Node{DOMAIN_PASCAL}{MICROSERVICE_NAME_PASCAL}Effect(NodeEffectService{MIXIN_INHERITANCE}):
    \"\"\"
    {DOMAIN} {MICROSERVICE_NAME} Effect Node - ONEX 4-Node Architecture Implementation.
    
    {BUSINESS_DESCRIPTION}
    \"\"\"
    
    # Configuration loaded from container or environment
    config: Model{MICROSERVICE_NAME_PASCAL}Config
    
    def __init__(self, container: ONEXContainer):
        \"\"\"Initialize {MICROSERVICE_NAME} effect node with container injection.\"\"\"
        super().__init__(container)
        self.node_type = "effect"
        self.domain = "{DOMAIN}"
        {MIXIN_INITIALIZATION}
    
    async def process_effect(
        self, 
        input_data: Model{MICROSERVICE_NAME_PASCAL}Input
    ) -> Model{MICROSERVICE_NAME_PASCAL}Output:
        \"\"\"
        Process the effect operation.
        
        Args:
            input_data: Input envelope with operation data
            
        Returns:
            Output envelope with result data
            
        Raises:
            OnexError: For operation failures
        \"\"\"
        # TODO: Implement business logic based on requirements
        # {BUSINESS_LOGIC_STUB}
        
        return Model{MICROSERVICE_NAME_PASCAL}Output(
            success=True,
            result_data={{}},
            metadata={{}},
            correlation_id=input_data.correlation_id
        )
    
    async def validate_input(
        self, 
        input_data: Model{MICROSERVICE_NAME_PASCAL}Input
    ) -> bool:
        \"\"\"
        Validate input data before processing.
        
        Args:
            input_data: Input to validate
            
        Returns:
            True if valid, False otherwise
        \"\"\"
        # TODO: Implement input validation logic
        return True
    
    async def get_health_status(self) -> Dict[str, Any]:
        \"\"\"
        Get current health status of the effect node.
        
        Returns:
            Health status dictionary
        \"\"\"
        return {{
            "status": "healthy",
            "node_type": self.node_type,
            "domain": self.domain,
            "timestamp": asyncio.get_event_loop().time()
        }}
"""
```

Mixin composition logic:
- Query available mixins from omnibase_core/mixins/
- Map PRD requirements to mixins (event_bus, caching, health_check, etc.)
- Check mixin compatibility (stored in pattern learning DB)
- Generate proper mixin inheritance chain

### 4. Contract & Model Generation

**File**: `agents/lib/contract_generator.py`

YAML contract generation:
- Parse mixin requirements from PRD analysis
- Generate subcontract YAMLs for each mixin capability
- Reference omnibase_core contract models as templates
- Use semantic intelligence to infer contract fields
- Validate against ONEX contract schemas

Pydantic model generation:
- Generate input/output envelopes (ModelEffectInput/ModelEffectOutput patterns)
- Create configuration models
- Generate enums for operation types
- Ensure ONEX compliance (no Any types, proper protocols)
- Add type annotations and docstrings

### 5. Business Logic Generator

**File**: `agents/lib/business_logic_generator.py`

Node implementation generation:
- Inherit from appropriate base (NodeEffectService, NodeComputeService, etc.)
- Implement required abstract methods
- Add mixin compositions
- Generate method stubs with comprehensive docstrings
- Embed agent prompt in comments for future AI assistance
- Include error handling and logging patterns

Generation modes:
- **Stub mode**: Generate method signatures with TODO comments
- **Pattern mode**: Use pattern matching for common operations (CRUD, transformations)
- **AI-assisted mode**: Embed full context for AI completion (future phase)

### 6. Quality Validation Service (Event-Driven)

**File**: `agents/lib/quality_validator.py`

Validation workflow:
1. Publish `CodegenValidationRequest` with generated code
2. omniarchon consumes and runs:
   - Static analysis (mypy compatibility check)
   - ONEX compliance scoring (via QualityScorer)
   - Pattern validation (via Pattern Learning)
3. Receive `CodegenValidationResponse` with:
   - Quality score (0-1 scale)
   - ONEX compliance score
   - Detected violations
   - Improvement suggestions
4. If score < threshold (0.8), regenerate or flag for human review

### 7. Workflow Integration

**Extend**: `agents/parallel_execution/dispatch_runner.py`

New workflow phase integration:

**Phase 0.5: PRD Analysis (Event-Driven)**
- Detect PRD input from user prompt
- Publish analysis request to Redpanda
- Wait for intelligence response
- Generate hierarchical task breakdown
- Store session in `generation_sessions` table

**Phase 2.5: Code Generation**
- For each task in hierarchy:
  - Load appropriate template
  - Generate contracts and models
  - Generate node implementation
  - Publish validation request
  - Wait for quality response
  - Write files if validated

**Phase 3.5: Quality Validation**
- Aggregate validation responses
- Check ONEX compliance
- Run static analysis locally
- Track quality scores in database

### 8. Database Integration

**Migration**: `agents/migrations/003_code_generation.sql`

Tables for code generation tracking:

```sql
CREATE TABLE generation_sessions (
    session_id UUID PRIMARY KEY,
    correlation_id UUID UNIQUE,
    prd_content TEXT,
    workflow_run_id UUID REFERENCES workflow_steps(run_id),
    status TEXT, -- 'analyzing', 'generating', 'validating', 'complete', 'failed'
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE generation_artifacts (
    artifact_id UUID PRIMARY KEY,
    session_id UUID REFERENCES generation_sessions(session_id),
    artifact_type TEXT, -- 'contract', 'model', 'enum', 'node', 'test'
    file_path TEXT,
    content TEXT,
    quality_score DECIMAL,
    validation_status TEXT,
    template_version TEXT,
    created_at TIMESTAMP
);

CREATE TABLE generation_intelligence (
    intelligence_id UUID PRIMARY KEY,
    session_id UUID REFERENCES generation_sessions(session_id),
    intelligence_type TEXT, -- 'semantic', 'pattern', 'quality'
    source_service TEXT, -- 'langextract', 'research_orchestrator', 'quality_scorer'
    intelligence_data JSONB,
    received_at TIMESTAMP
);

CREATE TABLE mixin_compatibility (
    mixin_name TEXT,
    compatible_with TEXT[],
    incompatible_with TEXT[],
    requires TEXT[],
    usage_count INT DEFAULT 0,
    success_rate DECIMAL
);
```

### 9. omniarchon Event Handlers

**File**: `../omniarchon/services/intelligence/src/services/codegen_intelligence_service.py`

Intelligence service handlers:
- Subscribe to `codegen.request.*` topics
- Handle analysis requests using existing services:
  - LangExtract for semantic analysis
  - ResearchOrchestrator for pattern discovery
  - QualityScorer for validation
- Publish responses to `codegen.response.*` topics
- Track request/response in intelligence service DB

Event handlers:
- `handle_analysis_request()` - PRD semantic analysis
- `handle_validation_request()` - Quality scoring
- `handle_pattern_request()` - Pattern matching
- `handle_mixin_recommendation()` - Mixin suggestions

### 10. Configuration

**File**: `agents/lib/codegen_config.py`

Configuration for generation behavior:

```python
class CodegenConfig:
    # Kafka configuration
    kafka_bootstrap_servers: str = "omninode-bridge-redpanda:9092"
    consumer_group: str = "omniclaude-codegen"
    
    # Generation control
    generate_contracts: bool = True
    generate_models: bool = True
    generate_enums: bool = True
    generate_business_logic: bool = False  # Start with stubs
    generate_tests: bool = True
    
    # Quality gates
    quality_threshold: float = 0.8
    onex_compliance_threshold: float = 0.7
    require_human_review: bool = True
    
    # Intelligence timeouts
    analysis_timeout_seconds: int = 30
    validation_timeout_seconds: int = 20
    
    # Mixin configuration
    auto_select_mixins: bool = True
    mixin_confidence_threshold: float = 0.7
```

## Implementation Phases

### Phase 1: Event Infrastructure (Week 1)

1. Create event models in `codegen_events.py`
2. Implement `kafka_codegen_client.py` using omninode_bridge patterns
3. Add database migration `003_code_generation.sql`
4. Test event publishing/consuming locally
5. Create codegen topic namespace in Redpanda

### Phase 2: Intelligence Integration (Week 1-2)

1. Implement `prd_analyzer.py` with event-driven intelligence requests
2. Add omniarchon event handlers for codegen requests
3. Test PRD → intelligence → response flow
4. Validate semantic analysis and pattern discovery

### Phase 3: Local Template System (Week 2-3)

1. Create local node templates in `agents/templates/`
2. Implement `omninode_template_engine.py`
3. Implement mixin composition logic
4. Generate directory structures and `__init__` files
5. Test template generation with sample inputs

### Phase 4: Contract & Model Generation (Week 3-4)

1. Implement `contract_generator.py`
2. Generate YAML subcontracts
3. Generate Pydantic models from contracts
4. Create enum generators
5. Test with various node types (Effect, Compute, Reducer, Orchestrator)

### Phase 5: Business Logic & Validation (Week 4-5)

1. Create `business_logic_generator.py`
2. Implement stub generation with TODOs
3. Add pattern-based generation for common operations
4. Implement `quality_validator.py` with event-driven validation
5. Test validation flow with omniarchon QualityScorer

### Phase 6: Workflow Integration (Week 5-6)

1. Extend `dispatch_runner.py` with codegen phases
2. Implement end-to-end workflow: PRD → working code
3. Add status tracking and progress updates
4. Implement error recovery and retry logic
5. Test complete pipeline

### Phase 7: Refinement & Optimization (Week 6-7)

1. Add mixin compatibility learning
2. Improve pattern matching with feedback loop
3. Optimize event processing performance
4. Add comprehensive monitoring and logging
5. Document usage and best practices

## Cross-Repository Coordination

### Dependency Documents Created

To coordinate concurrent work streams, MVP plan documents have been created in each repository:

**omnibase_core**: `!!!MVP_PLAN_CORE_LIBRARY_REQUIREMENTS!!!.md`
- Mixin metadata and discovery requirements
- Base node class interface stability
- Contract validation API requirements

**omniarchon**: `!!!MVP_PLAN_INTELLIGENCE_SERVICES!!!.md`
- Event handler framework for codegen topics
- LangExtract, QualityScorer, Pattern Learning event wrappers
- Intelligence service requirements and API contracts

**omninode_bridge**: `!!!MVP_PLAN_EVENT_INFRASTRUCTURE!!!.md`
- Codegen topic namespace setup
- Event schema requirements
- DLQ monitoring needs

**omni_spi**: `!!!MVP_PLAN_PROTOCOL_REQUIREMENTS!!!.md`
- Tool metadata validator requirements
- Protocol compliance for generated artifacts

Each document includes:
- Critical path dependencies for code generation
- Priority ranking (BLOCKER / HIGH / MEDIUM / LOW)
- Estimated completion time
- Interface contracts and schemas
- Success criteria
- Contact point (links back to omniclaude plan)

## Success Criteria

- Generate ONEX-compliant nodes with 80%+ quality score
- Event-driven communication with <2s latency for intelligence requests
- All generated code passes ONEX compliance validation
- Proper mixin composition with compatibility checking
- Dead letter queue handling for failed events
- Complete audit trail in generation database
- Pattern learning improves generation quality over time
- Generated code includes versioning, contracts, and models

## Key Files

**New files in omniclaude:**

- `agents/lib/codegen_events.py` - Event models for code generation
- `agents/lib/kafka_codegen_client.py` - Kafka client for codegen events
- `agents/lib/prd_analyzer.py` - Event-driven PRD analysis
- `agents/lib/omninode_template_engine.py` - Template engine
- `agents/lib/contract_generator.py` - Contract and model generation
- `agents/lib/business_logic_generator.py` - Code generation engine
- `agents/lib/quality_validator.py` - Event-driven validation
- `agents/lib/codegen_config.py` - Configuration management
- `agents/migrations/003_code_generation.sql` - Database schema
- `agents/templates/` - Local node templates (until omnibase_infra ported)

**New files in omniarchon:**

- `services/intelligence/src/services/codegen_intelligence_service.py` - Intelligence handlers
- `services/intelligence/src/api/codegen_events.py` - Event model mirrors

**Modified files:**

- `agents/parallel_execution/dispatch_runner.py` - Add codegen phases
- `agents/lib/db.py` - Add codegen table access

**Reference files (read-only):**

- `../omninode_bridge/src/omninode_bridge/services/kafka_client.py` - Kafka patterns
- `../omninode_bridge/src/omninode_bridge/models/events.py` - Event model patterns
- `../omnibase_core/src/omnibase_core/models/contracts/*.py` - Contract models
- `../omnibase_core/src/omnibase_core/mixins/*.py` - Available mixins

## Advantages of Event-Driven Architecture

1. **Decoupling**: omniclaude and omniarchon remain independent
2. **Scalability**: Can process multiple generation requests concurrently
3. **Resilience**: Dead letter queues, retries, circuit breakers
4. **Async**: Non-blocking intelligence requests, better UX
5. **Audit Trail**: All events persisted in Kafka for debugging
6. **Flexibility**: Easy to add new intelligence services or consumers
7. **Infrastructure Reuse**: Leverage existing Redpanda deployment

## Notes on Porting Strategy

**omnibase_infra**: Node templates will be ported later. For MVP, create local templates in `agents/templates/` based on omnibase_infra patterns.

**omniplan**: RSD methodology will be ported later. For MVP, use simple priority scoring in task decomposition.

**omnibase_3**: Dockerfile generation will be ported later. For MVP, create local Dockerfile generation in omniclaude.

**omniagent**: Copy and adapt existing code with version isolation until core libraries stabilize.
