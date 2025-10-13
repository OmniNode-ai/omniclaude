# Complete Agent System Integration Guide

## Overview

The agent-workflow-coordinator can leverage the ENTIRE parallel execution system to provide end-to-end workflow orchestration with:
- ✅ Comprehensive context gathering
- ✅ Validated task decomposition
- ✅ Parallel multi-agent execution
- ✅ Actual code generation (not just planning)
- ✅ AI Quorum validation
- ✅ Complete observability

## System Components

### 1. Context Manager (`context_manager.py`)

**Gathers comprehensive global context before any work begins:**

```python
from context_manager import ContextManager

manager = ContextManager()
global_context = await manager.gather_global_context(
    user_prompt="Build JWT authentication system",
    workspace_path="/path/to/project",
    rag_queries=[
        "JWT authentication best practices",
        "ONEX Effect node patterns",
        "Token refresh strategies"
    ],
    max_rag_results=5
)

# Result: ~200ms execution time
# {
#   "rag:domain-patterns": {...},
#   "pattern:onex-architecture": {...},
#   "structure:/path/to/project": {...}
# }
```

**Benefits:**
- Single context gathering operation (no duplicate queries)
- 60-80% token reduction vs per-agent gathering
- RAG intelligence integrated
- File system awareness

### 2. Task Architect (`task_architect.py`)

**Decomposes natural language into structured task definitions:**

```python
from task_architect import TaskArchitect

architect = TaskArchitect()
task_plan = await architect.analyze_prompt(
    user_prompt="Create JWT auth with refresh tokens",
    global_context=global_context
)

# Result:
# {
#   "analysis": "Multi-step auth implementation",
#   "tasks": [
#     {
#       "task_id": "gen-token-effect",
#       "agent": "coder",
#       "description": "Generate JWT token Effect node",
#       "input_data": {...},
#       "context_requirements": ["pattern:onex-effect", "rag:jwt-patterns"],
#       "dependencies": []
#     },
#     {
#       "task_id": "gen-refresh-compute",
#       "agent": "coder",
#       "description": "Generate token refresh Compute node",
#       "context_requirements": ["pattern:onex-compute"],
#       "dependencies": ["gen-token-effect"]
#     },
#     {
#       "task_id": "debug-auth-flow",
#       "agent": "debug",
#       "description": "Validate auth flow quality",
#       "dependencies": ["gen-token-effect", "gen-refresh-compute"]
#     }
#   ]
# }
```

### 3. Validated Task Architect (`validated_task_architect.py`)

**Adds AI Quorum validation with retry:**

```python
from validated_task_architect import ValidatedTaskArchitect

architect = ValidatedTaskArchitect()
result = await architect.breakdown_tasks_with_validation(
    user_prompt="Create JWT auth system",
    global_context=global_context
)

# Result includes:
# {
#   "breakdown": {...},
#   "validated": true,
#   "attempts": 2,  # Retried once based on quorum feedback
#   "quorum_result": {
#     "decision": "PASS",
#     "confidence": 0.87,
#     "model_responses": [...]
#   }
# }
```

**Quorum Models:**
- Gemini Flash (1.0 weight)
- Codestral @ Mac Studio (1.5 weight)
- DeepSeek-Lite @ RTX 5090 (2.0 weight)
- Llama 3.1 @ RTX 4090 (1.2 weight)
- DeepSeek-Full @ Mac Mini (1.8 weight)

### 4. Agent Dispatcher (`agent_dispatcher.py`)

**Executes multiple agents in parallel with dependency tracking:**

```python
from agent_dispatcher import ParallelCoordinator
from agent_model import AgentTask

coordinator = ParallelCoordinator(
    use_enhanced_router=True,
    router_confidence_threshold=0.6
)
await coordinator.initialize()

# Convert task plan to AgentTask objects
tasks = [
    AgentTask(
        task_id=task_def["task_id"],
        description=task_def["description"],
        input_data={
            **task_def["input_data"],
            "pre_gathered_context": filtered_context
        },
        dependencies=task_def["dependencies"]
    )
    for task_def in task_plan["tasks"]
]

# Execute in parallel with dependency resolution
results = await coordinator.execute_parallel(tasks)

# Results: {task_id: AgentResult}
# Automatically handles:
# - Parallel execution of independent tasks
# - Sequential execution of dependent tasks
# - Enhanced router for agent selection
# - Trace logging for all operations
```

### 5. Coder Agent (`agent_coder_pydantic.py`)

**Generates ACTUAL PRODUCTION CODE using Pydantic AI:**

```python
# Automatically invoked by dispatcher
# Receives filtered context per task
# Generates complete, runnable ONEX nodes

# Example output:
{
  "generated_code": """
\"\"\"
NodeJWTTokenGeneratorEffect - ONEX Effect Node

Generates JWT tokens with configurable expiration and signing.
\"\"\"

from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import jwt

class JWTTokenInput(BaseModel):
    user_id: str = Field(..., description="User identifier")
    expiration_minutes: int = Field(default=60)

class JWTTokenOutput(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: datetime

class NodeJWTTokenGeneratorEffect:
    async def execute(self, input_data: JWTTokenInput) -> JWTTokenOutput:
        # Complete implementation with proper error handling
        ...
  """,
  "node_name": "NodeJWTTokenGeneratorEffect",
  "node_type": "Effect",
  "quality_score": 0.89,
  "validation_passed": true
}
```

### 6. Quorum Validation (`quorum_minimal.py`)

**Multi-model consensus validation:**

```python
from quorum_minimal import MinimalQuorum

quorum = MinimalQuorum()
result = await quorum.validate_intent(
    user_prompt="Create JWT auth",
    task_breakdown=task_plan
)

# Decision: PASS | RETRY | FAIL
# Confidence: 0.0 - 1.0
# Deficiencies: [] (list of issues if any)
```

## Complete Integration Example

**End-to-end workflow using all components:**

```python
import asyncio
from pathlib import Path
from context_manager import ContextManager
from validated_task_architect import ValidatedTaskArchitect
from agent_dispatcher import ParallelCoordinator
from agent_model import AgentTask

async def execute_complete_workflow(user_prompt: str, workspace: str):
    """
    Complete workflow orchestration using the full system.
    """

    print("=" * 60)
    print("COMPLETE AGENT WORKFLOW ORCHESTRATION")
    print("=" * 60)

    # =====================================================================
    # PHASE 0: CONTEXT GATHERING
    # =====================================================================
    print("\n📚 Phase 0: Gathering comprehensive context...")

    context_manager = ContextManager()
    global_context = await context_manager.gather_global_context(
        user_prompt=user_prompt,
        workspace_path=workspace,
        max_rag_results=5
    )

    print(f"   ✓ Context gathered: {context_manager.get_context_summary()}")

    # =====================================================================
    # PHASE 1: TASK DECOMPOSITION WITH VALIDATION
    # =====================================================================
    print("\n🧩 Phase 1: Task decomposition with AI Quorum validation...")

    architect = ValidatedTaskArchitect()
    breakdown_result = await architect.breakdown_tasks_with_validation(
        user_prompt=user_prompt,
        global_context=global_context
    )

    if not breakdown_result["validated"]:
        print(f"   ⚠️  Task breakdown validation failed after {breakdown_result['attempts']} attempts")
        return None

    task_plan = breakdown_result["breakdown"]
    print(f"   ✓ Tasks validated ({breakdown_result['quorum_result']['confidence']:.0%} confidence)")
    print(f"   ✓ {len(task_plan['tasks'])} tasks identified")

    # =====================================================================
    # PHASE 2: CONTEXT FILTERING PER TASK
    # =====================================================================
    print("\n🔍 Phase 2: Filtering context for each task...")

    filtered_contexts = {}
    for task_def in task_plan["tasks"]:
        requirements = task_def.get("context_requirements", [])
        filtered_contexts[task_def["task_id"]] = context_manager.filter_context(
            context_requirements=requirements,
            max_tokens=5000
        )

    print(f"   ✓ Context filtered for {len(filtered_contexts)} tasks")

    # =====================================================================
    # PHASE 3: PARALLEL AGENT EXECUTION
    # =====================================================================
    print("\n⚡ Phase 3: Parallel agent execution...")

    coordinator = ParallelCoordinator(
        use_enhanced_router=True,
        router_confidence_threshold=0.6
    )
    await coordinator.initialize()

    # Convert to AgentTask objects with filtered context
    tasks = []
    for task_def in task_plan["tasks"]:
        task = AgentTask(
            task_id=task_def["task_id"],
            description=task_def["description"],
            input_data={
                **task_def.get("input_data", {}),
                "pre_gathered_context": filtered_contexts.get(task_def["task_id"], {})
            },
            dependencies=task_def.get("dependencies", [])
        )
        tasks.append(task)

    # Execute with dependency tracking
    results = await coordinator.execute_parallel(tasks)

    # =====================================================================
    # PHASE 4: RESULT AGGREGATION & QUALITY REPORTING
    # =====================================================================
    print("\n📊 Phase 4: Aggregating results...")

    aggregated = {
        "workflow_status": "completed",
        "total_tasks": len(tasks),
        "successful_tasks": sum(1 for r in results.values() if r.success),
        "failed_tasks": sum(1 for r in results.values() if not r.success),
        "outputs": {},
        "quality_metrics": {},
        "generated_code": {}
    }

    for task_id, result in results.items():
        if result.success:
            output_data = result.output_data or {}

            # Collect generated code
            if "generated_code" in output_data:
                aggregated["generated_code"][task_id] = output_data["generated_code"]

            # Collect quality metrics
            if "quality_score" in output_data:
                aggregated["quality_metrics"][task_id] = output_data["quality_score"]

            aggregated["outputs"][task_id] = {
                "agent": result.agent_name,
                "execution_time_ms": result.execution_time_ms,
                "summary": output_data
            }

    # Calculate overall quality
    if aggregated["quality_metrics"]:
        avg_quality = sum(aggregated["quality_metrics"].values()) / len(aggregated["quality_metrics"])
        aggregated["average_quality_score"] = avg_quality

    # =====================================================================
    # PHASE 5: DISPLAY RESULTS
    # =====================================================================
    print("\n" + "=" * 60)
    print("WORKFLOW COMPLETE")
    print("=" * 60)
    print(f"  Tasks: {aggregated['successful_tasks']}/{aggregated['total_tasks']} successful")
    print(f"  Avg Quality: {aggregated.get('average_quality_score', 0):.2%}")
    print(f"  Generated Files: {len(aggregated['generated_code'])}")

    # Display generated code files
    if aggregated["generated_code"]:
        print("\n📝 Generated Code:")
        for task_id, code in aggregated["generated_code"].items():
            lines = len(code.split('\n'))
            print(f"   • {task_id}: {lines} lines")

    # Display router stats
    router_stats = coordinator.get_router_stats()
    if router_stats.get('total_routes', 0) > 0:
        print(f"\n🎯 Router Performance:")
        print(f"   • Confidence-based routing: {router_stats.get('router_usage_rate', 0):.0%}")
        print(f"   • Average confidence: {router_stats.get('average_confidence', 0):.0%}")
        print(f"   • Cache hit rate: {router_stats.get('cache', {}).get('hit_rate', 0):.0%}")

    # Cleanup
    await context_manager.cleanup()
    await coordinator.cleanup()

    return aggregated


# =====================================================================
# USAGE EXAMPLE
# =====================================================================

async def main():
    result = await execute_complete_workflow(
        user_prompt="Create a JWT authentication system with refresh tokens and token rotation",
        workspace="/path/to/project"
    )

    if result:
        # Write generated code to files
        for task_id, code in result["generated_code"].items():
            output_path = f"./output/{task_id}.py"
            Path(output_path).parent.mkdir(exist_ok=True)
            Path(output_path).write_text(code)
            print(f"   ✓ Wrote {output_path}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Integration with Agent-Workflow-Coordinator

The coordinator should invoke this system via hooks:

1. **UserPromptSubmit Hook**: Detects "dispatch agent" or "coordinate workflow"
2. **Launches Full Pipeline**: Context → Decomposition → Validation → Execution
3. **Returns Complete Results**: Including generated code, quality metrics, traces

## Database Integration

All events are logged to PostgreSQL:

```sql
-- Context gathering events
INSERT INTO hook_events (source, payload) VALUES
  ('ContextGathering', '{"items": 5, "time_ms": 187}');

-- Task decomposition events
INSERT INTO agent_routing_decisions (agent_name, detection_method, confidence)
  VALUES ('task-architect', 'workflow_coordination', 0.95);

-- Agent execution traces
INSERT INTO execution_traces (trace_id, agent_name, task_id, status)
  VALUES (...);

-- Quality validation events
INSERT INTO agent_transformation_events (transformation_type, validation_result)
  VALUES ('quorum_validation', '{"confidence": 0.87}');
```

## Performance Targets

- **Context Gathering**: <200ms
- **Task Decomposition**: <2s (with LLM)
- **Quorum Validation**: <5s (5 models)
- **Agent Execution**: Parallel (60-80% faster than sequential)
- **Total Workflow**: <30s for complex multi-agent tasks

## Next Steps

1. ✅ Integrate full pipeline into agent-workflow-coordinator
2. ✅ Add workflow orchestration triggers
3. ✅ Enable database logging for all phases
4. ✅ Add performance monitoring dashboard
5. ✅ Create example workflows for common patterns
