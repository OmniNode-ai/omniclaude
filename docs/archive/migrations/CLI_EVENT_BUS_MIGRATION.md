# CLI Event Bus Migration - Phase 4 Architecture

**Status**: Planning (Phase 4)
**Current Phase**: Phase 1 (POC) - Direct synchronous calls
**Target Phase**: Phase 4 - Event-driven architecture
**Document Version**: 1.0.0
**Last Updated**: 2025-10-21

---

## Overview

This document describes the migration path from Phase 1 (POC) direct synchronous calls to Phase 4 event bus architecture for the ONEX node generation CLI.

**Key Principle**: *Every interface is an adapter for event bus messages*

---

## Architecture Comparison

### Phase 1 (POC) - Direct Calls

```
┌─────────────┐
│ User Input  │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│ CLI Handler         │
│ - Direct call       │
│ - Synchronous       │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ GenerationPipeline  │
│ - 6 stages          │
│ - 14 gates          │
└──────┬──────────────┘
       │
       ▼
┌─────────────┐
│ Results     │
│ Display     │
└─────────────┘
```

**Characteristics**:
- **Latency**: ~40 seconds (pipeline execution time)
- **Blocking**: User waits for entire pipeline
- **Fault Tolerance**: Pipeline failure = CLI failure
- **Scalability**: Single-threaded, sequential execution
- **Observability**: Local logging only

---

### Phase 4 (Future) - Event Bus

```
┌─────────────┐
│ User Input  │
└──────┬──────┘
       │
       ▼
┌────────────────────────────┐
│ NodeCLIAdapterEffect       │
│ (EFFECT node)              │
│ - Publishes events         │
│ - Subscribes to responses  │
└──────┬─────────────────────┘
       │ publishes PromptSubmitted
       ▼
┌────────────────────────────┐
│ Event Bus (Kafka/Redis)    │
│ - Durable message queue    │
│ - Topic-based routing      │
└──────┬─────────────────────┘
       │ consumed by
       ▼
┌────────────────────────────┐
│ NodeGenerationOrchestrator │
│ Orchestrator (ONEX)        │
│ - Consumes PromptSubmitted │
│ - Orchestrates pipeline    │
└──────┬─────────────────────┘
       │
       ▼
┌────────────────────────────┐
│ GenerationPipeline         │
│ - 6 stages                 │
│ - 14 gates                 │
│ - Emits progress events    │
└──────┬─────────────────────┘
       │ publishes GenerationCompleted
       ▼
┌────────────────────────────┐
│ Event Bus                  │
└──────┬─────────────────────┘
       │ consumed by
       ▼
┌────────────────────────────┐
│ NodeCLIAdapterEffect       │
│ - Displays progress        │
│ - Shows results            │
└────────────────────────────┘
```

**Characteristics**:
- **Latency**: <5ms (publish event) + async execution
- **Blocking**: User gets immediate feedback, progress updates
- **Fault Tolerance**: Pipeline failure isolated, retryable
- **Scalability**: Horizontal scaling, multiple consumers
- **Observability**: Distributed tracing, metrics, event replay

---

## Event Flow Specification

### 1. User Submits Prompt

**CLI publishes**:
```yaml
event_type: PromptSubmitted
topic: generation.pipeline.prompt_submitted
payload:
  prompt_text: "Create EFFECT node for database writes"
  output_directory: "/path/to/output"
  requested_by: "cli_user"
  correlation_id: "7c9e6679-7425-40de-944b-e07fc1f90ae7"
```

**Orchestrator consumes** → Starts pipeline execution

---

### 2. Pipeline Execution Stages

**Orchestrator publishes progress events**:

```yaml
# Stage 1: Parsing
event_type: ParsingStarted
topic: generation.pipeline.parsing_started
correlation_id: "7c9e6679-7425-40de-944b-e07fc1f90ae7"

# Stage 1 Complete
event_type: ParsingCompleted
topic: generation.pipeline.parsing_completed
payload:
  parsed_data:
    node_type: EFFECT
    service_name: postgres_writer
    confidence_score: 0.85
  parsing_duration_ms: 4523

# Stage 2: Pre-Validation
event_type: PreValidationStarted
topic: generation.pipeline.pre_validation_started

# ... (additional stages)
```

**CLI consumes** → Displays progress to user in real-time

---

### 3. Pipeline Completion

**Success Case**:
```yaml
event_type: PipelineCompleted
topic: generation.pipeline.completed
correlation_id: "7c9e6679-7425-40de-944b-e07fc1f90ae7"
payload:
  node_type: EFFECT
  service_name: postgres_writer
  output_path: "/path/to/node_infrastructure_postgres_writer_effect"
  files_written: [...]
  total_duration_seconds: 38.5
  validation_passed: true
  compilation_passed: true
```

**Failure Case**:
```yaml
event_type: PipelineFailed
topic: generation.pipeline.failed
correlation_id: "7c9e6679-7425-40de-944b-e07fc1f90ae7"
payload:
  failed_stage: "pre_validation"
  error_code: "MISSING_DEPENDENCY"
  error_message: "omnibase_core.nodes.node_effect.NodeEffect not found"
  recovery_suggestions:
    - "Run: poetry install omnibase_core"
    - "Verify omnibase_core version >=2.0"
```

**CLI consumes** → Displays results, shows success/failure

---

## Code Migration Strategy

### Current Implementation (Phase 1)

```python
# cli/lib/cli_handler.py
class CLIHandler:
    async def generate_node(self, prompt: str, output_directory: str) -> PipelineResult:
        # Phase 1: Direct synchronous call
        pipeline = GenerationPipeline()
        result = await pipeline.execute(prompt, output_directory)
        return result
```

### Target Implementation (Phase 4)

```python
# cli/lib/cli_handler.py
class CLIHandler:
    def __init__(self):
        self.event_bus = EventBusClient()
        self.event_subscriber = EventBusSubscriber()

    async def generate_node(self, prompt: str, output_directory: str) -> PipelineResult:
        # Phase 4: Event bus publish/subscribe
        correlation_id = uuid4()

        # Publish PromptSubmitted event
        event = ModelPromptSubmitted(
            event_type="PromptSubmitted",
            correlation_id=correlation_id,
            payload={
                "prompt_text": prompt,
                "output_directory": output_directory,
            }
        )

        await self.event_bus.publish(
            topic="generation.pipeline.prompt_submitted",
            event=event
        )

        # Subscribe to result
        result = await self._subscribe_for_result(correlation_id)
        return result

    async def _subscribe_for_result(self, correlation_id: UUID) -> PipelineResult:
        """Subscribe to pipeline completion events."""
        result_future = asyncio.Future()

        async def handle_result(event):
            if event.correlation_id == correlation_id:
                if event.event_type == "PipelineCompleted":
                    result_future.set_result(event.to_pipeline_result())
                elif event.event_type == "PipelineFailed":
                    result_future.set_exception(...)

        await self.event_subscriber.subscribe(
            topics=[
                "generation.pipeline.completed",
                "generation.pipeline.failed"
            ],
            handler=handle_result
        )

        # Wait for result (with timeout)
        return await asyncio.wait_for(result_future, timeout=300)
```

---

## New ONEX Nodes for Phase 4

### 1. NodeCLIAdapterEffect

**Purpose**: CLI becomes an EFFECT node that adapts user input to event bus

**File Structure**:
```
node_cli_adapter_effect/
├── v1_0_0/
│   ├── node.py                    # NodeCLIAdapterEffect
│   ├── models/
│   │   ├── model_cli_input.py     # User prompt input
│   │   └── model_cli_output.py    # Display results
│   └── contract.yaml              # EFFECT contract
└── node.manifest.yaml
```

**Contract**:
```yaml
node_type: EFFECT
side_effects:
  - name: publish_prompt_submitted
    description: Publishes PromptSubmitted event to event bus
    idempotent: false
  - name: subscribe_pipeline_results
    description: Subscribes to pipeline completion events
    idempotent: true
```

**Implementation**:
```python
class NodeCLIAdapterEffect(NodeEffect):
    async def execute_effect(self, contract: ModelContractEffect) -> ModelCLIOutput:
        # Publish prompt to event bus
        await self.event_bus.publish(
            topic="generation.pipeline.prompt_submitted",
            event=ModelPromptSubmitted(...)
        )

        # Subscribe and wait for result
        result = await self._wait_for_result(correlation_id)

        return ModelCLIOutput(result=result)
```

---

### 2. NodeGenerationOrchestratorOrchestrator

**Purpose**: Orchestrates pipeline execution from event bus triggers

**File Structure**:
```
node_generation_orchestrator_orchestrator/
├── v1_0_0/
│   ├── node.py                                # NodeGenerationOrchestratorOrchestrator
│   ├── models/
│   │   ├── model_orchestrator_input.py        # PromptSubmitted event
│   │   └── model_orchestrator_output.py       # PipelineCompleted event
│   └── contract.yaml                          # ORCHESTRATOR contract
└── node.manifest.yaml
```

**Contract**:
```yaml
node_type: ORCHESTRATOR
dependencies:
  - node_prompt_parser_compute
  - node_validator_compute
  - node_code_generator_effect
workflow:
  - trigger: PromptSubmitted
  - orchestrate: GenerationPipeline
  - emit: PipelineCompleted | PipelineFailed
```

**Implementation**:
```python
class NodeGenerationOrchestratorOrchestrator(NodeOrchestrator):
    async def execute_orchestration(
        self,
        contract: ModelContractOrchestrator
    ) -> ModelOrchestratorOutput:
        # Execute pipeline
        pipeline = GenerationPipeline()
        result = await pipeline.execute(
            prompt=contract.input.prompt_text,
            output_directory=contract.input.output_directory
        )

        # Publish result event
        if result.success:
            await self.event_bus.publish(
                topic="generation.pipeline.completed",
                event=ModelPipelineCompleted(result)
            )
        else:
            await self.event_bus.publish(
                topic="generation.pipeline.failed",
                event=ModelPipelineFailed(result)
            )

        return ModelOrchestratorOutput(result=result)
```

---

## Migration Checklist

### Phase 1 → Phase 2 (Preparation)

- [ ] Extract core logic into `CLIHandler`
- [ ] Define event schemas in `schemas/pipeline_events.yaml` ✅ (Already done)
- [ ] Create Pydantic models for events
- [ ] Write event serialization/deserialization logic

### Phase 2 → Phase 3 (Event Bus Integration)

- [ ] Set up Kafka/Redis event bus infrastructure
- [ ] Create event bus client library
- [ ] Implement event publisher
- [ ] Implement event subscriber with correlation ID tracking
- [ ] Add connection pooling and retry logic

### Phase 3 → Phase 4 (ONEX Node Refactor)

- [ ] Create `NodeCLIAdapterEffect` node
- [ ] Create `NodeGenerationOrchestratorOrchestrator` node
- [ ] Update `CLIHandler` to use event bus
- [ ] Wire event bus connections in orchestrator
- [ ] Add distributed tracing (correlation IDs)

### Phase 4 (Testing & Validation)

- [ ] Test event-driven flow end-to-end
- [ ] Validate fault tolerance (pipeline failure scenarios)
- [ ] Performance testing (latency, throughput)
- [ ] Load testing (concurrent requests)
- [ ] Chaos engineering (event bus failures)

### Phase 5 (Deployment)

- [ ] Deploy event bus infrastructure
- [ ] Deploy NodeGenerationOrchestratorOrchestrator
- [ ] Deploy updated CLI with NodeCLIAdapterEffect
- [ ] Monitor event bus metrics
- [ ] Gradual rollout with canary deployment

---

## Benefits of Event Bus Architecture

### 1. **Fault Tolerance**
- Pipeline failures don't crash CLI
- Automatic retry on transient failures
- Dead letter queue for persistent failures

### 2. **Scalability**
- Horizontal scaling of orchestrator instances
- Load balancing across consumers
- Independent scaling of CLI and pipeline

### 3. **Observability**
- Distributed tracing with correlation IDs
- Event replay for debugging
- Real-time monitoring dashboards

### 4. **Flexibility**
- Multiple consumers for same events (analytics, monitoring)
- Easy to add new event-driven features
- Decoupled CLI and pipeline evolution

### 5. **User Experience**
- Immediate feedback (<5ms publish latency)
- Real-time progress updates
- Non-blocking CLI operations

---

## Event Bus Technology Options

### Option 1: Kafka (Recommended)

**Pros**:
- High throughput (millions events/sec)
- Durable message storage
- Event replay capability
- Excellent ecosystem

**Cons**:
- Higher operational complexity
- Resource intensive (memory, disk)

**Use Case**: Production deployment with high volume

---

### Option 2: Redis Streams

**Pros**:
- Lightweight, easy to deploy
- Low latency
- Simpler than Kafka

**Cons**:
- Lower durability than Kafka
- Limited event retention
- Fewer ecosystem tools

**Use Case**: Development, testing, low-volume production

---

### Option 3: AWS EventBridge

**Pros**:
- Fully managed (no ops)
- Integrates with AWS services
- Built-in schema registry

**Cons**:
- Vendor lock-in
- Higher cost at scale
- Less control over infrastructure

**Use Case**: AWS-native deployments

---

## Performance Comparison

| Metric | Phase 1 (POC) | Phase 4 (Event Bus) |
|--------|---------------|---------------------|
| CLI Response Time | 40 seconds | <5ms (publish) |
| User Feedback | End only | Real-time progress |
| Fault Isolation | None | Full isolation |
| Horizontal Scaling | No | Yes |
| Concurrent Requests | 1 | Unlimited (queue) |
| Event Replay | No | Yes |
| Distributed Tracing | No | Yes |

---

## Rollback Strategy

If Phase 4 migration encounters issues:

1. **Immediate Rollback**: Keep Phase 1 CLI as fallback
2. **Feature Flag**: Toggle between Phase 1 and Phase 4 at runtime
3. **Graceful Degradation**: Fall back to direct calls if event bus unavailable

```python
# Feature flag pattern
class CLIHandler:
    async def generate_node(self, prompt: str, output_directory: str) -> PipelineResult:
        if feature_flags.is_enabled("event_bus_cli"):
            # Phase 4: Event bus
            return await self._generate_via_event_bus(prompt, output_directory)
        else:
            # Phase 1: Direct call
            return await self._generate_direct(prompt, output_directory)
```

---

## Success Criteria

### Phase 4 Migration Complete When:

- ✅ CLI publishes events instead of direct calls
- ✅ Orchestrator consumes events and executes pipeline
- ✅ Real-time progress updates displayed to user
- ✅ Fault tolerance tested and validated
- ✅ Performance meets targets (<5ms CLI latency)
- ✅ Event replay demonstrated
- ✅ Distributed tracing operational
- ✅ Production monitoring in place

---

## References

- [Pipeline Event Schemas](../schemas/pipeline_events.yaml)
- [ONEX Architecture Patterns](../OMNIBASE_CORE_NODE_PARADIGM.md)
- [Generation Pipeline Implementation](../agents/lib/generation_pipeline.py)
- [POC Architecture](../docs/POC_PIPELINE_ARCHITECTURE.md)
- [Option C Implementation Plan](../OPTION_C_IMPLEMENTATION_PLAN.md)

---

**Document Status**: Complete
**Ready for Phase 4 Implementation**: Yes
**Estimated Migration Effort**: 2-3 weeks
**Risk Level**: Low (clear rollback path)
