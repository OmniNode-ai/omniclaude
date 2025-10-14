# Agent Offloading Plan: Hybrid Execution Architecture

**Version**: 1.0
**Date**: 2025-10-06
**Status**: Planning Phase

---

## 📋 Executive Summary

This plan outlines the architecture for offloading Claude Code agent execution to a hybrid infrastructure combining:
- **Local AI Lab** (4 machines, 96GB VRAM, $0 cost)
- **Zen MCP Integration** (Intelligent routing, multi-model orchestration)
- **Cloud Providers** (Gemini, GLM, Together AI - fallback/specialized)

**Key Goals**:
1. **Minimize Claude's context usage** by 85-93% (from 100K+ to <15K tokens)
2. **Maximize local execution** to reduce API costs by ~70%
3. **Enable parallel execution** across hybrid infrastructure for 60-80% time savings
4. **Maintain quality gates** and framework compliance (23 gates, 47 mandatory functions)

---

## 🎯 Problem Statement

### Current State
- **50 specialized agents** executing in Claude's context
- **High token usage**: 50-200K tokens per complex task
- **Sequential execution**: Long wait times for multi-step tasks
- **API costs**: All execution through Anthropic APIs
- **Underutilized resources**: AI lab capacity at 25-40% usage

### Target State
- **Claude as router**: <15K tokens per task (85-93% reduction)
- **Hybrid execution**: 70% local, 30% cloud
- **Parallel workflows**: 14 concurrent executions (4 local + 10 cloud)
- **Cost reduction**: ~70% savings through local-first strategy
- **Performance gains**: 60-80% faster through parallelization

---

## 🏗️ Architecture Overview

### Three-Tier Execution Model

```
┌─────────────────────────────────────────────────────────────┐
│                    TIER 0: Claude Code                      │
│  Role: Lightweight Router & Validator                       │
│  Context: 5-15K tokens (down from 50-200K)                 │
│                                                              │
│  1. Receive user request                                    │
│  2. Route to optimal agent via EnhancedRouter              │
│  3. Decompose into parallel tasks (if applicable)          │
│  4. Select execution tier per task                          │
│  5. Offload to Pydantic AI executors                       │
│  6. Aggregate and validate structured responses            │
└─────────────────────────────────────────────────────────────┘
                            |
                            ▼
┌─────────────────────────────────────────────────────────────┐
│               TIER 1: Local AI Lab (Primary)                │
│  Capacity: 4 machines, 96GB VRAM, 60-75% available         │
│  Cost: $0                                                    │
│  Latency: 600-1200ms                                        │
│                                                              │
│  ┌─────────────┬──────────────────────────────────┐        │
│  │ Machine     │ Model & Specialization           │        │
│  ├─────────────┼──────────────────────────────────┤        │
│  │ RTX 5090    │ DeepSeek-Coder-V2-Lite          │        │
│  │ (201:8000)  │ → Code generation, refactoring   │        │
│  │             │ Weight: 2.0, Capacity: 65%       │        │
│  ├─────────────┼──────────────────────────────────┤        │
│  │ Mac Studio  │ Codestral 22B                   │        │
│  │ (200:11434) │ → Code review, architecture      │        │
│  │             │ Weight: 1.5, Capacity: 60%       │        │
│  ├─────────────┼──────────────────────────────────┤        │
│  │ RTX 4090    │ Llama 3.1 8B                    │        │
│  │ (201:8001)  │ → General reasoning, debugging   │        │
│  │             │ Weight: 1.2, Capacity: 75%       │        │
│  ├─────────────┼──────────────────────────────────┤        │
│  │ Mac Mini    │ 5 models (gpt-oss, deepseek, etc)│       │
│  │ (101:11434) │ → Testing, overflow, specialized │        │
│  │             │ Capacity: 70%                    │        │
│  └─────────────┴──────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────┘
                            |
                            ▼
┌─────────────────────────────────────────────────────────────┐
│            TIER 2: Zen MCP Integration (Hybrid)             │
│  Role: Intelligent multi-model orchestration                │
│  Cost: Mixed (local or cloud, Zen decides)                  │
│  Latency: 1000-2000ms                                       │
│                                                              │
│  Available Tools:                                            │
│  - mcp__zen__debug → agent-debug-intelligence               │
│  - mcp__zen__thinkdeep → Complex investigation             │
│  - mcp__zen__planner → agent-workflow-coordinator           │
│  - mcp__zen__codereview → agent-pr-review                   │
│  - mcp__zen__precommit → agent-commit                       │
│  - mcp__zen__consensus → Multi-model decision making        │
│                                                              │
│  Zen auto-routes to best available model (local or cloud)   │
└─────────────────────────────────────────────────────────────┘
                            |
                            ▼
┌─────────────────────────────────────────────────────────────┐
│           TIER 3: Cloud Providers (Fallback)                │
│  Capacity: Unlimited                                         │
│  Cost: $$$ (per API call)                                   │
│  Latency: 1000-3000ms                                       │
│                                                              │
│  ┌─────────────────┬───────────────────────────────┐       │
│  │ Provider        │ Use Case                      │       │
│  ├─────────────────┼───────────────────────────────┤       │
│  │ Gemini 2.5 Pro  │ Complex, high-priority tasks  │       │
│  │ (Score: 100)    │ 1M context, thinking mode     │       │
│  │                 │ → Architecture, design        │       │
│  ├─────────────────┼───────────────────────────────┤       │
│  │ GLM-4.6 (Z.ai)  │ Code tasks, high concurrency  │       │
│  │ (Score: 83)     │ 35 concurrent requests        │       │
│  │                 │ → Batch code operations       │       │
│  ├─────────────────┼───────────────────────────────┤       │
│  │ Gemini Flash    │ Simple, fast tasks            │       │
│  │ (Score: 61)     │ 1M context, optimized speed   │       │
│  │                 │ → Documentation, formatting   │       │
│  ├─────────────────┼───────────────────────────────┤       │
│  │ Together AI     │ Specialized models            │       │
│  │ OpenRouter      │ Model marketplace access      │       │
│  └─────────────────┴───────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 Core Components

### 1. Capacity-Aware Router Extension

**File**: `agents/lib/capacity_aware_router.py`

Extends `EnhancedAgentRouter` with capacity-aware routing:

```python
class CapacityAwareRouter(EnhancedAgentRouter):
    """Extended router with AI lab capacity awareness."""

    async def route_with_capacity(
        self,
        user_request: str,
        context: Dict[str, Any],
        agent_name: str
    ) -> ExecutionPlan:
        """
        Route agent execution to optimal compute resource.

        Decision Tree:
        1. Check AI lab capacity (Tier 1)
        2. Check Zen MCP availability (Tier 2)
        3. Fall back to cloud providers (Tier 3)
        """
```

**Key Features**:
- Complexity estimation for tasks
- Real-time capacity checking
- Cost vs performance optimization
- Automatic fallback on capacity exhaustion

### 2. AI Lab Manager

**File**: `agents/lib/ai_lab_manager.py`

Manages local AI lab resources and load balancing:

```python
class AILabManager:
    """Manages local AI lab resources and load balancing."""

    def __init__(self):
        self.machines = {
            'mac_studio': {...},
            'rtx_5090': {...},
            'rtx_4090': {...},
            'mac_mini': {...}
        }

    def select_model(self, agent_domain: str) -> Dict:
        """Select best available model for agent domain."""

    async def execute_on_lab(
        self,
        model_endpoint: str,
        model_name: str,
        prompt: str,
        **kwargs
    ) -> str:
        """Execute inference on AI lab model."""
```

**Key Features**:
- Specialization-based routing (code gen → DeepSeek, review → Codestral)
- Capacity scoring (weight × availability × specialization match)
- Dual protocol support (Ollama + vLLM/OpenAI-compatible)
- Real-time capacity tracking

### 3. Pydantic AI Agent Executor

**File**: `agents/executor/pydantic_executor.py`

Executes agents with offloaded context using Pydantic AI:

```python
class OffloadedAgentExecutor:
    """
    Executes agents using Pydantic AI with offloaded context.

    This keeps Claude's context minimal - Claude just routes and validates.
    The heavy lifting happens in offloaded models with full agent context.
    """

    async def execute_agent(
        self,
        request: AgentExecutionRequest,
        execution_tier: Literal["local", "zen_mcp", "cloud"]
    ) -> AgentExecutionResult:
        """Execute agent with full context offloaded to selected model."""
```

**Key Features**:
- Structured input/output with Pydantic models
- Full agent context building (instructions + files + intelligence)
- Multi-provider model support (Ollama, vLLM, Anthropic, OpenAI)
- Quality score validation
- Artifact tracking

### 4. Hybrid Parallel Coordinator

**File**: `agents/executor/parallel_coordinator.py`

Coordinates parallel execution across AI lab and cloud:

```python
class HybridParallelCoordinator:
    """
    Coordinates parallel execution across AI lab and cloud providers.

    Key Features:
    - Intelligent work distribution (local vs cloud)
    - Cost-optimized allocation (local first, cloud for overflow)
    - Performance-optimized allocation (cloud for complex tasks)
    - Mixed execution (some local, some cloud, all parallel)
    """

    async def execute_parallel(
        self,
        tasks: List[ParallelTask],
        strategy: Literal["cost_optimized", "performance_optimized", "balanced"]
    ) -> Dict[str, AgentExecutionResult]:
        """Execute tasks in parallel across AI lab and cloud."""
```

**Key Features**:
- Dependency graph resolution
- Three execution strategies (cost/performance/balanced)
- Machine-specific assignment (by specialization)
- Provider-specific assignment (by complexity)
- Result aggregation and validation

---

## 📊 Context Usage Optimization

### Before: Claude Executes Agents Directly

```
User Request (1K tokens)
  ↓
Agent Instructions (2-5K tokens)
  ↓
Intelligence Gathering (5-10K tokens)
  ↓
File Contents (20-50K tokens)
  ↓
Task Execution (10-50K tokens)
  ↓
Result Formatting (2-5K tokens)
────────────────────────────────
Total: 50-120K tokens in Claude's context
```

### After: Claude Routes, Offloaded Model Executes

```
Claude's Context:
  User Request (1K tokens)
  ↓
  Routing Logic (2K tokens)
  ↓
  Intelligence References Only (1K tokens)
  ↓
  File Path List (1K tokens)
  ↓
  Structured Response (2-5K tokens)
  ────────────────────────────────
  Total: 7-10K tokens (85-90% reduction)

Offloaded Model's Context:
  Full Agent Instructions (2-5K tokens)
  ↓
  Complete Intelligence Results (5-10K tokens)
  ↓
  Full File Contents (20-50K tokens)
  ↓
  Task Execution (10-50K tokens)
  ────────────────────────────────
  Total: 40-115K tokens (not in Claude's context!)
```

---

## 🚀 Parallel Execution Strategies

### Strategy 1: Cost-Optimized (Default)

**Goal**: Minimize API costs, maximize local usage

**Routing Logic**:
1. Fill all local slots (4 machines = 4 parallel tasks)
2. Cloud only for overflow
3. Prioritize simple tasks for local

**Example Task Distribution**:
```
Task 1: Code generation → RTX 5090 (local)
Task 2: Code review → Mac Studio (local)
Task 3: Testing → RTX 4090 (local)
Task 4: Documentation → Mac Mini (local)
Task 5: Security review → Gemini Flash (cloud, overflow)
```

**Characteristics**:
- Local usage: 100% of capacity
- Cloud usage: Overflow only
- Cost: $0 - $0.10 per task
- Performance: Good (slight queue delays)

### Strategy 2: Performance-Optimized

**Goal**: Minimize latency, maximize quality

**Routing Logic**:
1. Complex tasks (complexity > 0.7) → Cloud (better models)
2. Simple tasks (complexity < 0.7) → Local (faster)
3. Maximize parallelism regardless of cost

**Example Task Distribution**:
```
Task 1: Architecture design (0.9) → Gemini 2.5 Pro (cloud)
Task 2: Refactoring (0.8) → RTX 5090 (local)
Task 3: Testing (0.6) → Mac Studio (local)
Task 4: Documentation (0.4) → Gemini Flash (cloud)
Task 5: Security review (0.7) → Gemini Pro (cloud)
```

**Characteristics**:
- Local usage: 50% of capacity
- Cloud usage: High (50% of tasks)
- Cost: $0.25 - $0.50 per task
- Performance: Excellent (no queuing)

### Strategy 3: Balanced (Recommended)

**Goal**: Balance cost and performance

**Routing Logic**:
1. Score each task for local vs cloud suitability
2. Consider complexity, capacity, cost
3. Distribute to maximize both efficiency and speed

**Scoring Formula**:
```python
local_score = (
    capacity_available * 0.3 +
    (1.0 - complexity) * 0.4 +  # Favor simple for local
    cost_savings * 0.3          # Always better locally
)

cloud_score = (
    complexity * 0.5 +           # Favor complex for cloud
    unlimited_capacity * 0.3 +
    (1.0 - usage_penalty) * 0.2
)
```

**Example Task Distribution**:
```
Task 1: Architecture (0.9) → Gemini Pro (cloud, complex)
Task 2: Refactoring (0.7) → RTX 5090 (local, code-specialized)
Task 3: Testing (0.6) → Mac Studio (local, available)
Task 4: Documentation (0.4) → RTX 4090 (local, simple)
Task 5: Review (0.5) → Mac Mini (local, overflow)
```

**Characteristics**:
- Local usage: 70-80% of capacity
- Cloud usage: 20-30% of tasks
- Cost: $0.10 - $0.20 per task
- Performance: Great (minimal queuing)

---

## 📋 Pydantic AI Integration

### Why Pydantic AI?

1. **Structured Outputs**: Type-safe agent responses with validation
2. **Multi-Provider Support**: Works with OpenAI-compatible APIs (vLLM), Anthropic, Google
3. **Built-in Validation**: Ensures quality gates enforcement
4. **Agent Composition**: Easy chaining and parallel execution
5. **Context Management**: Handles conversation history automatically

### Data Models

```python
from pydantic import BaseModel, Field
from typing import List, Literal

class AgentExecutionRequest(BaseModel):
    """Structured request for agent execution."""
    agent_name: str
    task_description: str
    context: dict
    relevant_files: List[str] = []
    intelligence_context: Optional[dict] = None

class AgentExecutionResult(BaseModel):
    """Structured result from agent execution."""
    success: bool
    result: str
    artifacts: List[dict] = Field(default_factory=list)
    execution_metadata: dict
    quality_score: float = Field(ge=0.0, le=1.0)
    recommendations: List[str] = []

    # Quality gate validation
    @validator('quality_score')
    def validate_quality(cls, v):
        if v < 0.6:
            raise ValueError('Quality score must be >= 0.6')
        return v

class ParallelTask(BaseModel):
    """Single task in parallel execution batch."""
    task_id: str
    agent_name: str
    description: str
    dependencies: List[str] = []
    priority: int = Field(default=5, ge=1, le=10)
    estimated_complexity: float = Field(default=0.5, ge=0.0, le=1.0)
```

### Model Configuration

```python
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.models.anthropic import AnthropicModel

# Local AI Lab (OpenAI-compatible vLLM endpoints)
rtx_5090_model = OpenAIModel(
    model_name="deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
    base_url="http://192.168.86.201:8000/v1",
    api_key="not-needed"
)

rtx_4090_model = OpenAIModel(
    model_name="meta-llama/Meta-Llama-3.1-8B-Instruct",
    base_url="http://192.168.86.201:8001/v1",
    api_key="not-needed"
)

# Mac Studio (Ollama - needs adapter or direct API)
mac_studio_model = OpenAIModel(
    model_name="codestral:22b-v0.1-q4_K_M",
    base_url="http://192.168.86.200:11434",  # May need Ollama → OpenAI adapter
    api_key="not-needed"
)

# Cloud Providers
gemini_model = OpenAIModel(
    model_name="gemini-2.5-pro",
    base_url="https://generativelanguage.googleapis.com/v1beta",
    api_key=os.getenv("GOOGLE_API_KEY")
)

glm_model = OpenAIModel(
    model_name="glm-4.6",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    api_key=os.getenv("ZAI_API_KEY")
)
```

### Agent Creation

```python
# Create Pydantic AI agent with structured output
agent = PydanticAgent(
    model=rtx_5090_model,
    result_type=AgentExecutionResult,
    system_prompt="""You are an expert code generation agent.

    Return structured results with:
    - success: bool
    - result: detailed explanation
    - artifacts: list of created files/changes
    - quality_score: self-assessment (0.0-1.0)
    - recommendations: list of next steps
    """
)

# Execute with full context (offloaded)
result = await agent.run(
    user_prompt=full_agent_context,
    message_history=[]
)

# Result is type-safe and validated
assert isinstance(result.data, AgentExecutionResult)
assert result.data.quality_score >= 0.6
```

---

## 💰 Cost Analysis

### Current Cost Model (All Claude API)

| Scenario | Tokens | Cost (Sonnet 4) | Monthly (100 tasks) |
|----------|--------|-----------------|---------------------|
| Simple task | 30-50K | $0.90-$1.50 | $90-$150 |
| Complex task | 100-150K | $3.00-$4.50 | $300-$450 |
| With intelligence | 150-200K | $4.50-$6.00 | $450-$600 |

**Monthly Estimate**: $450-$600 for 100 tasks/month

### Proposed Cost Model (Hybrid)

| Tier | % of Tasks | Cost/Task | Monthly (100 tasks) |
|------|------------|-----------|---------------------|
| Local (Tier 1) | 70% | $0.00 | $0 |
| Zen MCP (Tier 2) | 10% | $0.00-$1.00 | $0-$10 |
| Cloud (Tier 3) | 20% | $0.50-$2.00 | $10-$40 |

**Monthly Estimate**: $10-$50 for 100 tasks/month

**Cost Reduction**: **~70-90%** ($400-$550 monthly savings)

### ROI on AI Lab Infrastructure

**AI Lab Investment**: ~$8,000 (estimated hardware cost)
**Monthly Savings**: $400-$550
**Payback Period**: 15-20 months
**3-Year Savings**: $14,400-$19,800 (minus electricity ~$500)

---

## ⚡ Performance Analysis

### Sequential Execution (Current)

```
Task 1: 2000ms
Task 2: 2000ms (starts after Task 1)
Task 3: 2000ms (starts after Task 2)
Task 4: 2000ms (starts after Task 3)
────────────────
Total: 8000ms
```

### Parallel Execution (Local Only)

```
Task 1: 2000ms ─┐
Task 2: 2000ms  ├─ All start simultaneously
Task 3: 2000ms  │  (4 machines available)
Task 4: 2000ms ─┘
────────────────
Total: 2000ms (75% faster)
```

### Hybrid Parallel Execution (Proposed)

```
Phase 1 (parallel):
  Task 1: RTX 5090    → 2000ms ─┐
  Task 2: Mac Studio  → 1500ms  ├─ All start simultaneously
  Task 3: RTX 4090    → 1800ms  │
  Task 4: Gemini Pro  → 2200ms ─┘

Total: 2200ms (72% faster than sequential)
Cost: $0.05 (1 cloud task)
```

### Performance Targets

| Metric | Target | Expected |
|--------|--------|----------|
| **Context Reduction** | 85% | 90% |
| **Cost Reduction** | 70% | 80% |
| **Parallel Speedup** | 60% | 72% |
| **Local Execution %** | 70% | 75% |
| **Quality Gate Pass Rate** | 95% | 96% |
| **Routing Accuracy** | 90% | 92% |

---

## 🔄 Implementation Roadmap

### Phase 1: Foundation (Weeks 1-2)

**Goal**: Basic offloading with Pydantic AI

**Tasks**:
1. ✅ Install Pydantic AI: `pip install pydantic-ai`
2. ✅ Create data models (`AgentExecutionRequest`, `AgentExecutionResult`)
3. ✅ Implement `AILabManager` with machine configurations
4. ✅ Test local model execution (RTX 5090, Mac Studio, RTX 4090)
5. ✅ Create simple `OffloadedAgentExecutor` without parallelization

**Deliverables**:
- `agents/lib/ai_lab_manager.py`
- `agents/executor/pydantic_executor.py`
- `agents/models/execution_models.py`

**Success Criteria**:
- Single agent execution on local models works
- Structured responses validated
- Context reduction: >80%

### Phase 2: Intelligent Routing (Weeks 3-4)

**Goal**: Capacity-aware routing across all tiers

**Tasks**:
1. ✅ Extend `EnhancedAgentRouter` → `CapacityAwareRouter`
2. ✅ Implement capacity checking and scoring
3. ✅ Add cloud provider fallback logic
4. ✅ Integrate Zen MCP as Tier 2
5. ✅ Test tier selection logic with various scenarios

**Deliverables**:
- `agents/lib/capacity_aware_router.py`
- `agents/lib/cloud_provider_manager.py`
- `agents/lib/zen_mcp_integration.py`

**Success Criteria**:
- Routing selects optimal tier >90% accuracy
- Local capacity monitored in real-time
- Automatic fallback works correctly

### Phase 3: Parallel Execution (Weeks 5-6)

**Goal**: Hybrid parallel coordination

**Tasks**:
1. ✅ Implement `HybridParallelCoordinator`
2. ✅ Add dependency graph resolution
3. ✅ Create execution strategies (cost/performance/balanced)
4. ✅ Implement machine/provider assignment logic
5. ✅ Add result aggregation and validation

**Deliverables**:
- `agents/executor/parallel_coordinator.py`
- `agents/executor/dependency_resolver.py`

**Success Criteria**:
- 4+ tasks execute in parallel
- Hybrid distribution works (local + cloud)
- Time savings: >60%

### Phase 4: Integration & Testing (Weeks 7-8)

**Goal**: Full integration with existing agent framework

**Tasks**:
1. Update agent definitions to support offloading
2. Modify `agent-workflow-coordinator` to use parallel coordinator
3. Add monitoring and metrics collection
4. Performance benchmarking
5. Cost tracking implementation

**Deliverables**:
- Updated agent YAML configs
- Monitoring dashboard
- Performance metrics

**Success Criteria**:
- All 50 agents support offloading
- Quality gates pass rate: >95%
- Cost reduction: >70%

### Phase 5: Optimization (Weeks 9-10)

**Goal**: Fine-tune performance and costs

**Tasks**:
1. Analyze execution patterns and bottlenecks
2. Optimize machine assignments
3. Tune execution strategies
4. Implement caching for repeated tasks
5. Add predictive capacity planning

**Deliverables**:
- Performance optimization report
- Updated routing algorithms
- Capacity prediction model

**Success Criteria**:
- Routing accuracy: >95%
- Local execution: >75%
- Average task time: <2s

---

## 📐 Technical Specifications

### File Structure

```
agents/
├── lib/
│   ├── enhanced_router.py              # Existing
│   ├── capacity_aware_router.py        # NEW: Capacity-aware routing
│   ├── ai_lab_manager.py               # NEW: AI lab resource management
│   ├── cloud_provider_manager.py       # NEW: Cloud provider integration
│   ├── zen_mcp_integration.py          # NEW: Zen MCP wrapper
│   ├── confidence_scorer.py            # Existing
│   ├── trigger_matcher.py              # Existing
│   ├── capability_index.py             # Existing
│   └── result_cache.py                 # Existing
│
├── executor/
│   ├── pydantic_executor.py            # NEW: Pydantic AI agent executor
│   ├── parallel_coordinator.py         # NEW: Hybrid parallel execution
│   └── dependency_resolver.py          # NEW: Task dependency resolution
│
├── models/
│   ├── execution_models.py             # NEW: Pydantic models
│   ├── task_models.py                  # NEW: Task and batch models
│   └── result_models.py                # NEW: Result aggregation models
│
├── configs/
│   ├── agent-*.yaml                    # Existing: 50 agent definitions
│   └── offloading-config.yaml          # NEW: Offloading configuration
│
└── AGENT_OFFLOADING_PLAN.md           # This document
```

### Dependencies

```toml
# pyproject.toml additions
[tool.poetry.dependencies]
pydantic-ai = "^0.0.13"              # Structured AI agent framework
aiohttp = "^3.9.0"                   # Async HTTP for local models
asyncio = "^3.4.3"                   # Parallel execution
networkx = "^3.2"                    # Dependency graph resolution
```

### Configuration File

```yaml
# agents/configs/offloading-config.yaml
version: "1.0.0"

# AI Lab Configuration
ai_lab:
  machines:
    rtx_5090:
      endpoint: "http://192.168.86.201:8000/v1"
      protocol: "vllm"  # OpenAI-compatible
      model: "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct"
      weight: 2.0
      specialization: ["code_generation", "refactoring"]
      capacity_threshold: 0.9  # Alert if >90% used

    mac_studio:
      endpoint: "http://192.168.86.200:11434"
      protocol: "ollama"
      model: "codestral:22b-v0.1-q4_K_M"
      weight: 1.5
      specialization: ["code_review", "architecture"]
      capacity_threshold: 0.9

    rtx_4090:
      endpoint: "http://192.168.86.201:8001/v1"
      protocol: "vllm"
      model: "meta-llama/Meta-Llama-3.1-8B-Instruct"
      weight: 1.2
      specialization: ["general", "debugging"]
      capacity_threshold: 0.9

    mac_mini:
      endpoint: "http://192.168.86.101:11434"
      protocol: "ollama"
      models: ["gpt-oss:20b", "deepseek-coder-v2:latest"]
      specialization: ["testing", "overflow"]
      capacity_threshold: 0.9

# Cloud Provider Configuration
cloud_providers:
  gemini_pro:
    model: "gemini-2.5-pro"
    base_url: "https://generativelanguage.googleapis.com/v1beta"
    api_key_env: "GOOGLE_API_KEY"
    use_for: ["complex", "high_priority"]
    cost_per_1k_tokens: 0.015
    max_concurrent: 10

  glm_4_6:
    model: "glm-4.6"
    base_url: "https://open.bigmodel.cn/api/paas/v4"
    api_key_env: "ZAI_API_KEY"
    use_for: ["code", "batch"]
    cost_per_1k_tokens: 0.010
    max_concurrent: 35

  gemini_flash:
    model: "gemini-2.5-flash"
    base_url: "https://generativelanguage.googleapis.com/v1beta"
    api_key_env: "GOOGLE_API_KEY"
    use_for: ["simple", "fast"]
    cost_per_1k_tokens: 0.005
    max_concurrent: 10

# Execution Strategies
execution_strategies:
  default: "balanced"

  cost_optimized:
    local_preference: 1.0  # Always prefer local
    cloud_threshold: 0.0   # Only use cloud if local full

  performance_optimized:
    local_preference: 0.5  # Balance local and cloud
    cloud_threshold: 0.7   # Use cloud for complex tasks

  balanced:
    local_preference: 0.7  # Prefer local but flexible
    cloud_threshold: 0.6   # Use cloud for moderately complex

# Parallel Execution
parallel_execution:
  max_local_parallel: 4      # 4 machines
  max_cloud_parallel: 10     # API rate limits
  dependency_resolution: true
  timeout_seconds: 300       # 5 minutes per task
  retry_on_failure: true
  max_retries: 2

# Quality Gates
quality_gates:
  minimum_quality_score: 0.6
  enforce_mandatory_functions: true
  validate_artifacts: true
  check_recommendations: true

# Monitoring
monitoring:
  enabled: true
  metrics:
    - execution_count
    - tier_distribution
    - cost_per_task
    - latency_p50
    - latency_p95
    - quality_score_avg
    - success_rate
  export_format: "json"
  export_path: "/tmp/agent_metrics.json"
```

---

## 🎯 Success Metrics

### Quantitative Metrics

| Metric | Baseline | Target | Stretch Goal |
|--------|----------|--------|--------------|
| **Context Usage** | 100K tokens | <15K tokens | <10K tokens |
| **Cost per Task** | $3-$6 | $0.10-$0.50 | $0-$0.10 |
| **Parallel Speedup** | 1x (sequential) | 3x (60-70% faster) | 4x (75% faster) |
| **Local Execution %** | 0% | 70% | 80% |
| **Routing Accuracy** | N/A | 90% | 95% |
| **Quality Score** | 0.7 | 0.75 | 0.80 |
| **Success Rate** | 90% | 95% | 98% |

### Qualitative Metrics

- **Developer Experience**: Reduced wait times, better visibility
- **System Reliability**: Fallback mechanisms working
- **Cost Predictability**: Clear cost attribution per task
- **Scalability**: Ability to add more local resources easily

---

## 🚨 Risk Mitigation

### Risk 1: Local Model Quality Lower Than Cloud

**Mitigation**:
- Set quality score thresholds (0.6 minimum)
- Automatic retry with cloud if local quality < 0.5
- Track quality metrics by tier
- Gradual rollout (test with non-critical agents first)

### Risk 2: Local Capacity Insufficient During Peaks

**Mitigation**:
- Cloud fallback always available (Tier 3)
- Queue management with max wait times
- Priority-based task scheduling
- Capacity monitoring and alerts

### Risk 3: Network Latency to Local Machines

**Mitigation**:
- All machines on same LAN (minimal latency)
- Timeout protection (5-minute max per task)
- Automatic fallback to cloud on timeout
- Keep machines on wired connections

### Risk 4: Pydantic AI Compatibility Issues

**Mitigation**:
- Test with each provider before rollout
- Maintain adapter layer for provider-specific quirks
- Fallback to direct API calls if Pydantic AI fails
- Pin Pydantic AI version for stability

### Risk 5: Cost Overruns on Cloud Fallback

**Mitigation**:
- Budget alerts and limits
- Cost tracking per task and tier
- Monthly budget caps
- Prefer cheaper cloud options (GLM-4.6, Gemini Flash)

---

## 📚 References

### Internal Documentation
- `/Volumes/PRO-G40/Code/omniarchon/docs/guides/AI_LAB_CONFIGURATION.md`
- `agents/agent-workflow-coordinator.md`
- `agents/core-requirements.yaml` (47 mandatory functions)
- `agents/quality-gates-spec.yaml` (23 quality gates)
- `agents/performance-thresholds.yaml` (33 performance thresholds)

### External Resources
- [Pydantic AI Documentation](https://ai.pydantic.dev/)
- [vLLM OpenAI-Compatible Server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html)
- [Ollama API Documentation](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [Claude Code Agent Framework](https://docs.anthropic.com/en/docs/claude-code/sub-agents)

---

## 🔄 Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2025-10-06 | Initial plan document | Claude + User |

---

## 📝 Next Steps

1. **Review & Approval**: Team review of this plan
2. **Environment Setup**: Install Pydantic AI and dependencies
3. **Prototype**: Build minimal viable version (Phase 1)
4. **Testing**: Validate with 1-2 agents first
5. **Rollout**: Gradual deployment to all 50 agents
6. **Monitoring**: Track metrics and optimize

---

**Status**: Ready for implementation ✅
