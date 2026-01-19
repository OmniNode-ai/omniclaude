# Debug Loop Implementation Plan — ONEX Node Architecture

**Status**: Ready for Implementation
**Last Updated**: 2025-11-09
**Version**: 2.0 (ONEX Revision)
**Branch**: `claude/omninode-debug-rewards-clarification-011CUxhsawPLtZFyyC5capVP`

---

## Executive Summary

This document provides a **revised implementation plan** using **ONEX node-based architecture** with automated node generation.

**Architecture Shift**: Traditional service classes → ONEX 4-node architecture (Effect, Compute, Reducer, Orchestrator)

**Key Benefits**:
- ✅ **95% less boilerplate** via node generator (10-25s per node)
- ✅ **Type-safe contracts** with omnibase_core/omnibase_spi
- ✅ **ONEX compliance** enforced automatically
- ✅ **Separation of concerns** (I/O, logic, state, workflow)

**User's Direction**: _"let's build it in two parts, let's build the debug information part first and then we can add in the compute tokens, I want to use the enhancements to the debug system so we can start using that intelligence immediately"_

---

## Part 1: Debug Intelligence Core (ONEX)

### Node Architecture (11 nodes)

**ONEX Pattern**:
```
AgentExecutionLogger.complete()
    ↓
NodeDebugLoopOrchestrator (coordinates workflow)
    ├─ NodeDebugSTFExtractorCompute (extract patterns)
    ├─ NodeDebugSTFStorageEffect (PostgreSQL I/O)
    ├─ NodeSTFQualityCompute (score quality)
    ├─ NodeSTFMatcherCompute (find similar)
    ├─ NodeErrorSuccessMappingReducer (aggregate patterns)
    └─ NodeGoldenStateManagerReducer (track proven solutions)
    ↓
Manifest Injector (enriched with STFs)
```

**11 Nodes Generated**:

| Node Name | Type | Purpose | omnibase Integration |
|-----------|------|---------|---------------------|
| `NodeDebugSTFStorageEffect` | Effect | PostgreSQL CRUD for STFs | `NodeEffectService`, `IDatabaseProtocol` |
| `NodeModelPriceCatalogEffect` | Effect | Model price catalog CRUD | `NodeEffectService`, `IDatabaseProtocol` |
| `NodeDebugSTFExtractorCompute` | Compute | Extract STFs from executions | `NodeComputeService` (pure) |
| `NodeSTFQualityCompute` | Compute | 5-dimension quality scoring | `NodeComputeService` (cacheable) |
| `NodeSTFMatcherCompute` | Compute | Similarity matching | `NodeComputeService` (cacheable) |
| `NodeSTFHashCompute` | Compute | SHA-256 generation | `NodeComputeService` (pure) |
| `NodeErrorPatternExtractorCompute` | Compute | Error normalization | `NodeComputeService` (pure) |
| `NodeCostTrackerCompute` | Compute | Calculate LLM costs | `NodeComputeService` (pure) |
| `NodeErrorSuccessMappingReducer` | Reducer | Error→success FSM | `NodeReducerService` (intent-based) |
| `NodeGoldenStateManagerReducer` | Reducer | Golden state FSM | `NodeReducerService` (intent-based) |
| `NodeDebugLoopOrchestrator` | Orchestrator | Workflow coordination | `NodeOrchestratorService` |

### Database Schema (Same as v1.0)

**5 Tables** (no changes from original plan):
1. `debug_transform_functions` (STF registry)
2. `model_price_catalog` (LLM pricing)
3. `debug_execution_attempts` (correlation tracking)
4. `debug_error_success_mappings` (confidence metrics)
5. `debug_golden_states` (proven solutions)

### Week-by-Week Breakdown

**Week 1: Database + Contracts**
- Days 1-2: Create database migration (manual)
- Days 3-5: Design 11 ONEX v2.0 contracts (YAML)

**Week 2: Generate Effect + Compute Nodes (6 nodes)**
- Day 6: Generate `NodeDebugSTFStorageEffect` (10-25s)
- Day 7: Generate `NodeModelPriceCatalogEffect` (10-25s)
- Day 8-10: Generate 5 Compute nodes (STFExtractor, Quality, Matcher, Hash, ErrorPattern)
- Integration: Connect to PostgreSQL via `omnibase_spi.protocols.IDatabaseProtocol`

**Week 3: Generate Reducer + Orchestrator (3 nodes)**
- Day 11-12: Generate `NodeErrorSuccessMappingReducer` + `NodeGoldenStateManagerReducer`
- Day 13-14: Generate `NodeDebugLoopOrchestrator`
- Day 15: Integration testing (full workflow)

**Week 4: Integration + Testing**
- Days 16-18: Integrate with `AgentExecutionLogger`
- Days 19-20: Integrate with manifest injector, end-to-end testing

**Node Generation Time**: ~11 nodes × 20s = **3.5 minutes** 🚀

---

## Part 2: Token Economy (ONEX)

### Node Architecture (9 nodes)

**ONEX Pattern**:
```
Contribution Event (STF created)
    ↓
NodeContributionRewardOrchestrator
    ├─ NodeContributionValidatorCompute (validate quality)
    ├─ NodeRewardCalculatorCompute (calculate tokens)
    ├─ NodeNoveltyScoreCompute (novelty multiplier)
    ├─ NodeTokenLedgerEffect (publish to Kafka)
    └─ NodeTokenBalanceReducer (materialize balance)
         └─ NodeBalanceCacheEffect (cache in Valkey)
```

**9 Nodes Generated**:

| Node Name | Type | Purpose | omnibase Integration |
|-----------|------|---------|---------------------|
| `NodeTokenLedgerEffect` | Effect | Publish to Kafka | `NodeEffectService`, `IEventBusProtocol` |
| `NodeBalanceCacheEffect` | Effect | Cache in Valkey | `NodeEffectService`, `ICacheProtocol` |
| `NodeRewardCalculatorCompute` | Compute | Calculate rewards | `NodeComputeService` (pure) |
| `NodeNoveltyScoreCompute` | Compute | Calculate novelty | `NodeComputeService` (cacheable) |
| `NodeTokenSpenderCompute` | Compute | Calculate deductions | `NodeComputeService` (pure) |
| `NodeContributionValidatorCompute` | Compute | Validate contributions | `NodeComputeService` (pure) |
| `NodeTokenBalanceReducer` | Reducer | Materialize balances | `NodeReducerService` (FSM) |
| `NodeContributionRewardOrchestrator` | Orchestrator | Reward workflow | `NodeOrchestratorService` |
| `NodeTokenSpendOrchestrator` | Orchestrator | Spend workflow | `NodeOrchestratorService` |

### Week-by-Week Breakdown

**Week 5: Kafka + Effect Nodes**
- Days 21-22: Create Kafka topics (manual)
- Days 23-25: Generate 2 Effect nodes (TokenLedger, BalanceCache)

**Week 6: Compute Nodes**
- Days 26-30: Generate 4 Compute nodes (RewardCalculator, NoveltyScore, TokenSpender, ContributionValidator)

**Week 7: Reducer + Orchestrator**
- Days 31-33: Generate Reducer + 2 Orchestrators
- Days 34-35: Integration testing

**Week 8: Deployment**
- Days 36-40: Container config, Kafka consumer service, production deployment

**Node Generation Time**: ~9 nodes × 20s = **3 minutes** 🚀

---

## ONEX Integration Checklist

### omnibase_core Requirements

**All Nodes Must**:
- [ ] Import from `omnibase_core.core.infrastructure_service_bases`
- [ ] Use `ModelONEXContainer` for dependency injection
- [ ] Import contracts from `omnibase_core.models.contracts`
- [ ] Use error types from `omnibase_core.errors`

**Effect Nodes**:
```python
from omnibase_core.core.infrastructure_service_bases import NodeEffectService
from omnibase_core.models.contracts import ModelContractEffect

class NodeDebugSTFStorageEffect(NodeEffectService):
    async def execute_effect(self, contract: ModelContractEffect):
        ...
```

**Compute Nodes**:
```python
from omnibase_core.core.infrastructure_service_bases import NodeComputeService

class NodeSTFQualityCompute(NodeComputeService):
    async def execute_compute(self, contract: ModelContractCompute):
        # Pure function, no side effects
        ...
```

**Reducer Nodes**:
```python
from omnibase_core.core.infrastructure_service_bases import NodeReducerService
from omnibase_core.models import ModelIntent

class NodeTokenBalanceReducer(NodeReducerService):
    async def execute_reduction(self, contract: ModelContractReducer):
        # Pure FSM: emit intents, don't execute side effects
        return ModelReducerOutput(
            aggregated_data={...},
            intents=[ModelIntent(...)]
        )
```

**Orchestrator Nodes**:
```python
from omnibase_core.core.infrastructure_service_bases import NodeOrchestratorService

class NodeDebugLoopOrchestrator(NodeOrchestratorService):
    async def execute_orchestration(self, contract: ModelContractOrchestrator):
        # Coordinate all nodes
        ...
```

### omnibase_spi Requirements

**Protocols**:
```python
from omnibase_spi.protocols import (
    IDatabaseProtocol,      # PostgreSQL operations
    IEventBusProtocol,      # Kafka operations
    ICacheProtocol          # Valkey operations
)
```

**Mixins**:
```python
from omnibase_spi.mixins import (
    RetryMixin,             # Automatic retry logic
    CircuitBreakerMixin,    # Circuit breaker pattern
    ObservabilityMixin      # Logging/tracing
)
```

**Validators**:
```python
from omnibase_spi.validators import (
    ContractValidator,      # Validate contracts
    NodeValidator           # Validate node structure
)
```

---

## Node Generation Commands

### Generate Effect Node

```bash
poetry run python cli/generate_node.py \
  "Create EFFECT node for storing STFs in PostgreSQL.
   Operations: store, retrieve, search, update_usage.
   Use omnibase_core.NodeEffectService and omnibase_spi.IDatabaseProtocol." \
  --output ./generated_nodes/debug_loop \
  --node-type effect \
  --enable-intelligence
```

### Generate Compute Node

```bash
poetry run python cli/generate_node.py \
  "Create COMPUTE node for calculating 5-dimension STF quality score.
   Pure deterministic function with caching.
   Use omnibase_core.NodeComputeService." \
  --output ./generated_nodes/debug_loop \
  --node-type compute
```

### Generate Reducer Node

```bash
poetry run python cli/generate_node.py \
  "Create REDUCER node for materializing token balances from transaction stream.
   FSM pattern with intent emission (no direct side effects).
   Use omnibase_core.NodeReducerService." \
  --output ./generated_nodes/token_economy \
  --node-type reducer
```

### Generate Orchestrator Node

```bash
poetry run python cli/generate_node.py \
  "Create ORCHESTRATOR node for debug loop workflow.
   Coordinate: extract → store → score → match → map errors → nominate golden.
   Use omnibase_core.NodeOrchestratorService with all debug nodes injected." \
  --output ./generated_nodes/debug_loop \
  --node-type orchestrator
```

---

## Testing Strategy

### Node-Level Testing

**Effect Nodes**:
- Mock protocols (`IDatabaseProtocol`, `IEventBusProtocol`)
- Test retry and circuit breaker
- Integration tests with real PostgreSQL/Kafka/Valkey

**Compute Nodes**:
- Pure function unit tests
- Verify determinism (same input → same output)
- Cache effectiveness (>60% hit rate)
- Performance (<100ms)

**Reducer Nodes**:
- FSM state transition tests
- Verify intent emission (no direct side effects)
- Idempotency testing

**Orchestrator Nodes**:
- End-to-end workflow tests
- Error handling at each step
- Graceful degradation

---

## Success Criteria

### Part 1 Success

**Functional**:
- [ ] 11 nodes generated and ONEX-compliant
- [ ] STFs automatically extracted from executions
- [ ] Quality scores calculated (<100ms)
- [ ] STF recommendations in manifest (<200ms overhead)
- [ ] Error→success mappings created
- [ ] Golden states nominated

**Performance**:
- [ ] Full debug loop workflow: <2000ms
- [ ] Database queries: <50ms (indexed)
- [ ] Cache hit rate: >60%

### Part 2 Success

**Functional**:
- [ ] 9 nodes generated and ONEX-compliant
- [ ] Tokens earned automatically on contributions
- [ ] Tokens spent on LLM queries
- [ ] Balances materialized from Kafka (<100ms)
- [ ] Valkey cache hit rate >80%

**Economic**:
- [ ] Earnings ≥ spending for active contributors
- [ ] Token velocity >0.1/day
- [ ] Fair distribution (Gini <0.5)

---

## Timeline Summary

| Phase | Duration | Nodes Generated | Manual Work |
|-------|----------|-----------------|-------------|
| Part 1 | 4 weeks | 11 nodes (3.5 min) | DB schema, contracts, integration |
| Part 2 | 4 weeks | 9 nodes (3 min) | Kafka topics, integration, deployment |
| **Total** | **8 weeks** | **20 nodes (6.5 min)** | **~6 weeks manual, 6.5 min automated** |

**Time Savings**: 95% less coding (node generator automates boilerplate)

---

## Next Steps

1. **Review and Approve**
   - [ ] User approves ONEX architecture
   - [ ] Confirm omnibase_core/omnibase_spi integration approach
   - [ ] Approve node generator usage

2. **Day 1 Kickoff**
   - [ ] Create database migration (5 tables)
   - [ ] Design first ONEX contract (NodeDebugSTFStorageEffect)
   - [ ] Test node generator CLI

3. **Day 6: First Node Generation**
   - [ ] Generate `NodeDebugSTFStorageEffect`
   - [ ] Verify ONEX compliance
   - [ ] Integration test with PostgreSQL

---

**End of ONEX Implementation Plan**

**Version**: 2.0 (ONEX Revision)
**Status**: Ready for Day 1 implementation
**Key Change**: Traditional services → ONEX 4-node architecture with automated generation
