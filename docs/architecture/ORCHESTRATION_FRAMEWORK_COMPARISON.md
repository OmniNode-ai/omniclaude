# Orchestration Framework Comparison for ONEX

**Your Plan**: LlamaIndex Workflows for orchestrator nodes
**Alternative Suggested**: Laddr for multi-agent coordination

Let me clarify the differences and provide a recommendation.

---

## LlamaIndex Workflows vs Laddr vs Others

### 1. LlamaIndex Workflows 🔄

**What it is**: Event-driven workflow orchestration framework (part of LlamaIndex ecosystem)

**Architecture**:
```python
from llama_index.core.workflow import Workflow, StartEvent, StopEvent, step

class MyWorkflow(Workflow):
    @step
    async def step_1(self, ev: StartEvent) -> MyEvent:
        # Process step 1
        return MyEvent(data=result)

    @step
    async def step_2(self, ev: MyEvent) -> StopEvent:
        # Process step 2
        return StopEvent(result=final_result)

# Run workflow
workflow = MyWorkflow()
result = await workflow.run(user_input="...")
```

**Key Features**:
- ✅ Event-driven architecture (fits ONEX)
- ✅ Step decorators for workflow definition
- ✅ Built-in state management
- ✅ Async-first
- ✅ Integrates with LlamaIndex RAG components
- ✅ Type-safe events (Pydantic models)

**ONEX Integration Pattern**:
```python
class NodeWorkflowOrchestrator:
    """ONEX Orchestrator using LlamaIndex Workflows."""

    async def execute_orchestration(
        self,
        contract: ModelContractOrchestrator
    ) -> Any:
        # Create workflow from contract
        workflow = self._build_workflow_from_contract(contract)

        # Execute workflow
        result = await workflow.run(
            user_request=contract.user_request,
            context=contract.context
        )

        return ModelOrchestratorOutput(
            result=result,
            orchestration_method="llamaindex_workflows",
            success=True
        )
```

**Pros for OmniClaude**:
- ✅ Already in LlamaIndex ecosystem (if using LlamaIndex for RAG)
- ✅ Event-driven = fits your Kafka architecture naturally
- ✅ Step-based = maps cleanly to ONEX node types
- ✅ State management = built-in (vs manual state tracking)
- ✅ Well-documented, actively maintained (45K stars)

**Cons**:
- ❌ Tied to LlamaIndex ecosystem (vendor lock-in)
- ❌ Not specifically designed for multi-agent coordination
- ❌ No built-in Kafka integration (you'd add this)

---

### 2. Laddr 🤝

**What it is**: Multi-agent coordination framework with message queues

**Architecture**:
```python
from laddr import Agent, Task, MessageQueue

# Define agents
research_agent = Agent(
    name="researcher",
    capabilities=["web_search", "data_analysis"],
    message_queue=kafka_queue
)

code_agent = Agent(
    name="coder",
    capabilities=["code_generation", "testing"],
    message_queue=kafka_queue
)

# Delegate tasks
task = Task(description="Build authentication system")
research_result = await research_agent.delegate(task, to=code_agent)
```

**Key Features**:
- ✅ Built specifically for multi-agent systems
- ✅ Message queue architecture (Kafka-compatible!)
- ✅ Agent delegation and task routing
- ✅ Horizontal scalability
- ✅ Built-in observability

**ONEX Integration Pattern**:
```python
class NodeLaddrCoordinatorOrchestrator:
    """ONEX Orchestrator using Laddr agents."""

    async def execute_orchestration(
        self,
        contract: ModelContractOrchestrator
    ) -> Any:
        # Create Laddr agents from ONEX nodes
        agents = [
            Agent(
                name=node.agent_name,
                capabilities=node.capabilities,
                message_queue=self.kafka_queue
            )
            for node in contract.nodes
        ]

        # Parallel execution with delegation
        results = await asyncio.gather(*[
            agent.execute(subtask)
            for agent, subtask in zip(agents, contract.subtasks)
        ])

        return ModelOrchestratorOutput(
            results=results,
            orchestration_method="laddr_multi_agent",
            success=True
        )
```

**Pros for OmniClaude**:
- ✅ Kafka message queues = perfect fit for your event bus
- ✅ Multi-agent coordination = designed for this use case
- ✅ Scalability = horizontal scaling built-in
- ✅ Framework-agnostic = works with any agent implementation

**Cons**:
- ❌ Smaller community (183 stars vs 45K)
- ❌ Less mature than LlamaIndex
- ❌ May require more custom integration work

---

### 3. CrewAI 👥

**What it is**: Role-based multi-agent framework

**Architecture**:
```python
from crewai import Agent, Task, Crew

# Define agents by role
researcher = Agent(
    role="Senior Research Analyst",
    goal="Uncover cutting-edge developments in AI",
    tools=[search_tool, scrape_tool]
)

writer = Agent(
    role="Tech Content Strategist",
    goal="Craft compelling content on tech advancements",
    tools=[write_tool]
)

# Create crew
crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, write_task],
    process=Process.sequential  # or parallel
)

result = crew.kickoff()
```

**Pros**:
- ✅ Industry standard (widely used)
- ✅ Role-based = intuitive agent definitions
- ✅ Sequential + parallel processes

**Cons**:
- ❌ Opinionated (forces role-based pattern)
- ❌ Less control over low-level orchestration
- ❌ Not event-driven by default

---

## 🎯 Recommendation for OmniClaude

### Option 1: LlamaIndex Workflows (Your Current Plan) ✅ **RECOMMENDED**

**Use when**:
- You're using LlamaIndex for RAG (or planning to)
- You want workflow orchestration with steps/events
- Your orchestration is primarily **sequential** with some parallelism
- You want built-in state management

**Why it fits ONEX**:
```
LlamaIndex Workflow Step = ONEX Node
─────────────────────────────────────
@step (Effect)         = NodeEffect.execute_effect()
@step (Compute)        = NodeCompute.execute_compute()
@step (Reducer)        = NodeReducer.execute_reduction()
Workflow               = NodeOrchestrator.execute_orchestration()
```

**Integration Pattern**:
```python
# Define ONEX nodes as workflow steps
class ONEXWorkflow(Workflow):
    @step
    async def database_effect(self, ev: StartEvent) -> DataEvent:
        """ONEX Effect: Database query."""
        node = NodeDatabaseQueryEffect(config=self.config)
        result = await node.execute_effect(
            ModelContractEffect(query=ev.query)
        )
        return DataEvent(data=result)

    @step
    async def transform_compute(self, ev: DataEvent) -> TransformEvent:
        """ONEX Compute: Data transformation."""
        node = NodeDataTransformCompute(config=self.config)
        result = await node.execute_compute(
            ModelContractCompute(data=ev.data)
        )
        return TransformEvent(transformed=result)

    @step
    async def aggregate_reducer(self, ev: TransformEvent) -> StopEvent:
        """ONEX Reducer: Aggregate results."""
        node = NodeResultAggregatorReducer(config=self.config)
        result = await node.execute_reduction(
            ModelContractReducer(items=[ev.transformed])
        )
        return StopEvent(result=result)
```

**Verdict**: ✅ **Stick with LlamaIndex Workflows**

---

### Option 2: Hybrid Approach (LlamaIndex + Laddr) 🔀

**Use both**:
- **LlamaIndex Workflows**: For single-agent orchestration (workflow steps)
- **Laddr**: For multi-agent coordination (agent-to-agent communication)

**When**:
- You have complex multi-agent scenarios (multiple agents collaborating)
- You want Kafka-native message passing between agents
- You need horizontal scaling for agent workloads

**Architecture**:
```
┌─────────────────────────────────────────────────────┐
│  Agent 1 (LlamaIndex Workflow)                      │
│  ┌──────┐  ┌──────┐  ┌──────┐                      │
│  │Effect│→ │Compute│→│Reducer│                      │
│  └──────┘  └──────┘  └──────┘                      │
└─────────────────┬───────────────────────────────────┘
                  │ Laddr Message Queue (Kafka)
                  ▼
┌─────────────────────────────────────────────────────┐
│  Agent 2 (LlamaIndex Workflow)                      │
│  ┌──────┐  ┌──────┐  ┌──────┐                      │
│  │Effect│→ │Compute│→│Reducer│                      │
│  └──────┘  └──────┘  └──────┘                      │
└─────────────────────────────────────────────────────┘
```

**Implementation**:
```python
# Agent 1: Uses LlamaIndex Workflow internally
class Agent1Workflow(Workflow):
    @step
    async def process_and_delegate(self, ev: StartEvent) -> StopEvent:
        # Internal workflow steps (ONEX nodes)
        result = await self._internal_processing(ev)

        # Delegate to Agent 2 via Laddr
        laddr_agent = Agent(name="agent2", message_queue=self.kafka_queue)
        delegated_result = await laddr_agent.execute(
            Task(description="Continue processing", data=result)
        )

        return StopEvent(result=delegated_result)
```

**Verdict**: 🔀 **Consider for complex multi-agent scenarios**

---

## 📋 Decision Matrix

| Criteria | LlamaIndex Workflows | Laddr | Hybrid |
|----------|---------------------|-------|--------|
| **Fits ONEX node pattern** | ✅ Perfect | ⚠️ Requires adaptation | ✅ Perfect |
| **Event-driven** | ✅ Yes | ✅ Yes (Kafka) | ✅ Yes |
| **Async-first** | ✅ Yes | ✅ Yes | ✅ Yes |
| **State management** | ✅ Built-in | ⚠️ Manual | ✅ Built-in |
| **Kafka integration** | ⚠️ Manual | ✅ Native | ✅ Native |
| **Multi-agent coordination** | ⚠️ Basic | ✅ Advanced | ✅ Advanced |
| **Community/maturity** | ✅ 45K stars | ⚠️ 183 stars | ✅ Both |
| **Integration effort** | ✅ Low (2-3 days) | ⚠️ Medium (3-4 days) | ⚠️ High (5-7 days) |
| **Vendor lock-in** | ⚠️ LlamaIndex ecosystem | ✅ Framework-agnostic | ⚠️ Both |

---

## 🎯 Final Recommendation

### **Stick with LlamaIndex Workflows** ✅

**Reasoning**:
1. **Perfect ONEX mapping**: Workflow steps = ONEX nodes (Effect, Compute, Reducer)
2. **Event-driven**: Fits your Kafka architecture (you can publish workflow events to Kafka)
3. **Mature ecosystem**: 45K stars, active development, comprehensive docs
4. **State management**: Built-in (vs manual with Laddr)
5. **Lower complexity**: Single framework vs managing two

**When to add Laddr**:
- When you have **>5 agents** coordinating simultaneously
- When you need **horizontal scaling** across agent instances
- When agents need **complex delegation** patterns (agent A → agent B → agent C)

---

## 🔧 Implementation Guide: LlamaIndex Workflows + ONEX

### 1. Install LlamaIndex Workflows

```bash
pip install llama-index-core llama-index-workflows
```

### 2. Define ONEX Node Workflow

**File**: `services/workflow_adapter/onex_workflow_orchestrator.py`

```python
from llama_index.core.workflow import (
    Workflow,
    StartEvent,
    StopEvent,
    step,
    Event
)
from typing import Any, Dict
from pydantic import BaseModel

# Define custom events (map to ONEX contracts)
class EffectCompleteEvent(Event):
    """Event emitted when Effect node completes."""
    result: Any
    correlation_id: str

class ComputeCompleteEvent(Event):
    """Event emitted when Compute node completes."""
    result: Any
    correlation_id: str

class ReducerCompleteEvent(Event):
    """Event emitted when Reducer node completes."""
    result: Any
    correlation_id: str
    intents: list[Dict[str, Any]]

class ONEXWorkflow(Workflow):
    """
    ONEX-compliant workflow using LlamaIndex Workflows.

    Maps ONEX node types to workflow steps:
    - Effect → External I/O step
    - Compute → Pure transformation step
    - Reducer → Aggregation step with intent emission
    - Orchestrator → Workflow itself
    """

    def __init__(self, nodes: Dict[str, Any], **kwargs):
        super().__init__(**kwargs)
        self.nodes = nodes  # ONEX node instances

    @step
    async def execute_effect(
        self,
        ev: StartEvent
    ) -> EffectCompleteEvent:
        """
        ONEX Effect Node Step.

        Handles external I/O: database, API, file system, Kafka.
        """
        effect_node = self.nodes["effect"]

        contract = ModelContractEffect(
            operation=ev.operation,
            correlation_id=ev.correlation_id,
            **ev.params
        )

        result = await effect_node.execute_effect(contract)

        # Publish event to Kafka for observability
        await self._publish_to_kafka(
            topic="workflow.effect.completed",
            event={
                "correlation_id": ev.correlation_id,
                "node_type": "effect",
                "result": result.to_dict()
            }
        )

        return EffectCompleteEvent(
            result=result,
            correlation_id=ev.correlation_id
        )

    @step
    async def execute_compute(
        self,
        ev: EffectCompleteEvent
    ) -> ComputeCompleteEvent:
        """
        ONEX Compute Node Step.

        Pure transformations: business logic, algorithms, data processing.
        """
        compute_node = self.nodes["compute"]

        contract = ModelContractCompute(
            input_data=ev.result,
            correlation_id=ev.correlation_id
        )

        result = await compute_node.execute_compute(contract)

        # Publish to Kafka
        await self._publish_to_kafka(
            topic="workflow.compute.completed",
            event={
                "correlation_id": ev.correlation_id,
                "node_type": "compute",
                "result": result.to_dict()
            }
        )

        return ComputeCompleteEvent(
            result=result,
            correlation_id=ev.correlation_id
        )

    @step
    async def execute_reducer(
        self,
        ev: ComputeCompleteEvent
    ) -> StopEvent:
        """
        ONEX Reducer Node Step.

        Aggregates results, manages state transitions, emits intents.
        """
        reducer_node = self.nodes["reducer"]

        contract = ModelContractReducer(
            items=[ev.result],
            correlation_id=ev.correlation_id,
            current_state=self.context.get("state", {})
        )

        result = await reducer_node.execute_reduction(contract)

        # Store intents for downstream processing
        self.context["intents"] = result.intents
        self.context["state"] = result.aggregated_data

        # Publish to Kafka
        await self._publish_to_kafka(
            topic="workflow.reducer.completed",
            event={
                "correlation_id": ev.correlation_id,
                "node_type": "reducer",
                "state": result.aggregated_data,
                "intents": result.intents
            }
        )

        return StopEvent(
            result=result.aggregated_data,
            intents=result.intents
        )

    async def _publish_to_kafka(self, topic: str, event: Dict[str, Any]):
        """Publish workflow events to Kafka for observability."""
        # Use your existing Kafka producer
        await self.kafka_producer.send(topic, value=event)
```

### 3. ONEX Orchestrator Node Wrapper

**File**: `nodes/node_llamaindex_workflow_orchestrator.py`

```python
class NodeLlamaIndexWorkflowOrchestrator:
    """
    ONEX Orchestrator Node: LlamaIndex Workflows Integration.

    Orchestrates multi-step ONEX workflows using LlamaIndex Workflows framework.
    """

    async def execute_orchestration(
        self,
        contract: ModelContractOrchestrator
    ) -> Any:
        """
        Execute ONEX workflow via LlamaIndex Workflows.

        Contract should specify:
        - nodes: List of ONEX nodes (Effect, Compute, Reducer)
        - workflow_type: "sequential" | "parallel" | "conditional"
        - correlation_id: For traceability
        """
        # Initialize ONEX nodes
        nodes = {
            "effect": await self._load_node(contract.nodes["effect"]),
            "compute": await self._load_node(contract.nodes["compute"]),
            "reducer": await self._load_node(contract.nodes["reducer"])
        }

        # Create workflow
        workflow = ONEXWorkflow(nodes=nodes, timeout=120)

        # Execute workflow
        result = await workflow.run(
            operation=contract.operation,
            correlation_id=contract.correlation_id,
            params=contract.params
        )

        return ModelOrchestratorOutput(
            result=result,
            orchestration_method="llamaindex_workflows",
            nodes_executed=list(nodes.keys()),
            success=True,
            metadata={
                "workflow_duration_ms": workflow.duration_ms,
                "intents_emitted": len(result.intents)
            }
        )
```

---

## 📊 Comparison Summary

**Your Plan (LlamaIndex Workflows)**: ✅ **Correct choice**

- Perfect for ONEX orchestrator nodes
- Event-driven = Kafka-compatible
- Mature, well-documented
- Clean mapping: Workflow steps → ONEX nodes

**Alternative (Laddr)**: Consider later for advanced multi-agent coordination

- Use when you need 5+ agents coordinating
- Kafka-native message passing
- Horizontal scaling built-in

**Recommendation**: **Start with LlamaIndex Workflows, add Laddr if needed for complex multi-agent scenarios**

---

Ready to implement? I can help you:
1. Set up LlamaIndex Workflows adapter
2. Create ONEX node workflow templates
3. Integrate with your existing Kafka event bus
4. Build workflow observability dashboards
