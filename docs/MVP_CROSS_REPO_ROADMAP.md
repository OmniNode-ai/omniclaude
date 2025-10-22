# MVP Cross-Repository Roadmap - Self-Improving Code Generation Platform

**Generated**: October 22, 2025
**Timeline**: 3-5 days (with 2.67x velocity multiplier)
**Status**: 75% complete, Day 1 ✅

---

## Executive Summary

### The Vision
Event-driven, self-improving code generation system where generated nodes auto-register with service mesh, patterns are learned continuously, and the system can generate the next version of itself.

### Current Progress
| Repository | Status | Completion | MVP Blockers |
|------------|--------|------------|--------------|
| **omnibase_core** | ✅ Complete | 100% | None |
| **omniclaude** | 🟡 In Progress | 75-80% | Stage 4.5 pipeline, pattern storage |
| **omninode_bridge** | ✅ Ready | 90% | Orchestrator adaptation |
| **omniarchon** | 🔴 Degraded | 78% | DB connectivity, pattern API |

### Critical Issues
1. ⚠️ **Omniarchon database connectivity failing** (503 errors) - 1-2 days to fix
2. ⚠️ **Hook persistence broken** (DB_PASSWORD not set) - 15 minutes to fix
3. ⚠️ **Pattern storage API missing** - 3-5 days to implement

### Timeline to MVP
- **Optimistic**: 3 days (if all blockers resolved quickly)
- **Realistic**: 5 days (accounting for infrastructure issues)
- **Pessimistic**: 7 days (if dependencies require rework)

---

## Repository Status & Dependencies

### Dependency Graph
```
omnibase_core (100% ✅)
    ↓ (provides base classes, errors, contracts)
    ├─→ omninode_bridge (90% ✅)
    │       ↓ (provides orchestrators, reducers, event bus)
    │       └─→ omniclaude (75% 🟡)
    │               ↓ (generates nodes)
    │               └─→ [Generated Nodes]
    └─→ omniarchon (78% 🔴)
            ↓ (provides intelligence, pattern storage)
            └─→ omniclaude (75% 🟡)
```

### Critical Path
```
1. Fix omniarchon DB connectivity (1-2 days) ← BLOCKING
   ↓
2. Implement pattern storage API (3-5 days) ← BLOCKING
   ↓
3. Complete omniclaude Stage 4.5 (2-3 days)
   ↓
4. Integrate orchestrator in omninode_bridge (1-2 days)
   ↓
5. Test end-to-end generation (1 day)
   ↓
MVP COMPLETE (7-13 days critical path)
```

**With parallel execution and 2.67x velocity**: **3-5 actual days**

---

## Detailed Repository Breakdown

### 1. omnibase_core ✅ (100% Complete)

**Status**: Production-ready, no MVP blockers

**What's Available**:
- ✅ Error system: `OnexError` + 200+ error codes
- ✅ Base classes: `NodeCoreBase`, `NodeEffect`, `NodeCompute`, `NodeReducer`, `NodeOrchestrator`
- ✅ Contracts: `ModelContractBase` + 4 specialized + 6 subcontracts
- ✅ Utilities: `UUIDService`, `ONEXContainer`, structured logging
- ✅ Enums: 128+ definitions

**Critical Correction**:
- **Package name**: `omnibase` (NOT `omnibase_core`)
- **Import path**: `from omnibase.core.*` (NOT `from omnibase_core.*`)

**Actions Needed**:
1. Update research documentation with correct package name
2. Fix import paths in generation templates
3. Add dependency to omniclaude:
   ```toml
   omnibase = { path = "/Volumes/PRO-G40/Code/omnibase_3", develop = true }
   ```

**Effort**: 1 hour (documentation updates)

---

### 2. omniclaude 🟡 (75-80% Complete)

**Status**: Day 1 complete, Week 1 in progress

**What's Working** ✅:
- 6-stage generation pipeline (2,658 LOC, 95%+ quality)
- AI Quorum refinement (4 models, 85% → 95%+ boost)
- Event bus templates (Day 1 complete)
- 90% reusable pattern catalog (8,300 LOC identified)
- Import-first strategy (reduces generation by 85-90%)

**MVP Gaps** (9 days remaining):

#### Week 1: Event Bus Integration (Days 2-5)
| Day | Task | Status | Effort |
|-----|------|--------|--------|
| Day 1 | Event bus templates | ✅ Complete | 3h (done) |
| **Day 2** | **Stage 4.5 pipeline integration** | ⏳ Next | 8h → 3h |
| Day 3 | Test with real node | ⏳ Pending | 4h → 1.5h |
| Day 4 | Orchestrator template | ⏳ Pending | 4h → 1.5h |
| Day 5 | Week 1 wrap-up | ⏳ Pending | 4h → 1.5h |

**Day 2 Blockers**:
- Need to fix hook DB persistence (15 min)
- Need to implement `_stage_4_5_event_bus_integration()` in generation_pipeline.py

#### Week 2: Continuous Learning (Days 6-10)
| Day | Task | Depends On | Effort |
|-----|------|-----------|--------|
| Day 6-7 | Pattern storage integration | omniarchon API | 8h → 3h |
| Day 8-9 | RAG-enhanced generation | Pattern storage | 8h → 3h |
| Day 10 | Metrics dashboard | Metrics collection | 4h → 1.5h |

**Week 2 Blockers**:
- ⚠️ **Requires omniarchon pattern storage API** (not yet implemented)
- ⚠️ **Requires omniarchon DB connectivity fix**

**Total Remaining Effort**: 52h → **19.5h actual** (with 2.67x velocity)

**Dependencies**:
- ⚠️ **omniarchon**: Pattern storage API, DB connectivity
- ✅ **omninode_bridge**: Event bus infrastructure (ready)
- ✅ **omnibase_core**: Base classes (ready)

---

### 3. omninode_bridge ✅ (90% Complete)

**Status**: Infrastructure ready, orchestrator needs adaptation

**What's Available** ✅:
- ✅ **NodeBridgeWorkflowOrchestrator**: LlamaIndex 6-step workflow (production-ready)
- ✅ **NodeBridgeReducer**: Streaming aggregation (>1000 items/sec)
- ✅ **Event Bus Infrastructure**: 13 Kafka topics operational
- ✅ **Service Mesh**: Consul, Kafka, PostgreSQL, OnexTree integration
- ✅ **Battle-tested Patterns**: Circuit breakers, health checks, DLQ, retry logic

**MVP Gaps** (2-3 days):

#### Required Nodes
1. **NodeCodegenOrchestrator** (1-2 days)
   - Adapt existing `NodeBridgeWorkflowOrchestrator` pattern (95% reuse)
   - 6-step workflow: Parse → Intelligence → Architecture → Generate → Validate → Write
   - LlamaIndex-based with event-driven coordination
   - **Blocker**: Requires omniarchon intelligence APIs working

2. **NodeCodegenMetricsReducer** (1 day)
   - Extend existing `NodeBridgeReducer` pattern (70% reuse)
   - Aggregate generation metrics (quality, latency, cost, model performance)
   - Stream to PostgreSQL canonical store
   - **Blocker**: None (can start immediately)

3. **CLI Integration** (1 day)
   - Connect `cli/generate_node.py` to workflow orchestrator
   - Publish `NODE_GENERATION_REQUESTED` events
   - Subscribe to `NODE_GENERATION_COMPLETED` events
   - **Blocker**: Requires orchestrator complete

**Total Effort**: 14-19 days → **5-7 actual days** (with reuse and parallel execution)

**Dependencies**:
- ⚠️ **omniarchon**: Intelligence gathering APIs must be working
- ✅ **omniclaude**: Event bus templates (ready)
- ✅ **omnibase_core**: Base classes (ready)

---

### 4. omniarchon 🔴 (78% Complete)

**Status**: Services degraded, critical infrastructure issues

**What's Working** ✅:
- ✅ **78 intelligence APIs** operational across 9 services
- ✅ **25,450+ patterns** indexed with full lineage tracking
- ✅ **Event bus healthy**: Redpanda + Kafka consumer operational
- ✅ **RAG retrieval exists**: ResearchOrchestrator (degraded but functional)

**Critical Infrastructure Issues** 🔴:

#### Blocking Issues (Must Fix for MVP)
1. **Database Connectivity Failure** (1-2 days)
   - Search service: Can't connect to Memgraph/Intelligence/Bridge
   - Intelligence service: Returns 503 "Database connection not available"
   - Freshness DB: Disconnected from intelligence service
   - **Impact**: Pattern storage, RAG queries, intelligence gathering all broken

2. **Missing Core Services** (1 hour)
   - `archon-server` not running
   - `archon-mcp` not running
   - `archon-valkey` not running
   - **Action**: Start services via docker compose

3. **Pattern Storage API Missing** (3-5 days)
   - No `/v1/intelligence/store_pattern` endpoint
   - Required for continuous learning (Week 2)
   - **Blocker**: Must implement before Day 6 of omniclaude plan

**MVP Requirements** (13-21 days):

#### Required APIs
1. **Pattern Storage API** (3-5 days) - NEW
   ```python
   POST /v1/intelligence/store_pattern
   {
     "node_type": "effect",
     "domain": "database",
     "code_sample": "...",
     "quality_score": 0.97,
     "metadata": {...}
   }
   ```

2. **Pattern Retrieval API** (1-2 days) - FIX EXISTING
   - ResearchOrchestrator exists but degraded
   - Fix network connectivity
   - Test RAG query performance

3. **Model Performance Tracking** (2-3 days) - EXTEND EXISTING
   - Add model-specific metrics collection
   - Track cost/latency/quality per model
   - Store in PostgreSQL for trend analysis

4. **Intelligence Gathering** (1-2 days) - FIX EXISTING
   - Multiple APIs ready but network issues
   - Fix connectivity to intelligence service
   - Test integration with omniclaude

**Total Effort**: 13-21 days (critical path blocks omniclaude Week 2)

**Dependencies**:
- ⚠️ **Infrastructure**: Docker networking, database connections
- ✅ **omnibase_core**: Base classes (ready)
- ⚠️ **omniclaude**: Needs working APIs for Week 2

**Immediate Actions** (within 24 hours):
```bash
# 1. Start missing services
cd /Volumes/PRO-G40/Code/omniarchon
docker compose -f deployment/docker-compose.yml up -d archon-server archon-mcp archon-valkey

# 2. Check database connectivity
docker compose logs archon-search | grep -i "error\|failed"
docker compose logs archon-intelligence | grep -i "database"

# 3. Fix network routing (investigate Docker bridge networks)
```

---

## MVP Completion Timeline

### Sequential Critical Path (Pessimistic)
```
Day 1 (Oct 22): ✅ Event bus templates complete
    ↓
Day 2 (Oct 23): Fix omniarchon infrastructure (1-2 days)
    ↓
Day 4 (Oct 25): Complete omniclaude Stage 4.5 (2-3 days)
    ↓
Day 7 (Oct 28): Implement pattern storage API (3-5 days)
    ↓
Day 12 (Nov 2): Integrate RAG-enhanced generation (2-3 days)
    ↓
Day 15 (Nov 5): Add metrics dashboard (1 day)
    ↓
Day 16 (Nov 6): MVP COMPLETE

Timeline: 15 days (pessimistic)
```

### Parallel Execution (Optimistic with 2.67x velocity)
```
Day 1 (Oct 22): ✅ Event bus templates complete
    ↓
Day 2 (Oct 23):
  ├─ Poly 1: Fix omniarchon DB (1-2 days)
  ├─ Poly 2: Complete Stage 4.5 (8h → 3h)
  └─ Poly 3: Start metrics reducer (1 day)
    ↓
Day 3 (Oct 24):
  ├─ Poly 1: Pattern storage API (3-5 days)
  ├─ Poly 2: Test real node generation (4h → 1.5h)
  └─ Poly 3: CLI integration (1 day)
    ↓
Day 4 (Oct 25):
  ├─ Poly 1: RAG integration (2-3 days)
  └─ Poly 2: Metrics dashboard (4h → 1.5h)
    ↓
Day 5 (Oct 26): MVP COMPLETE

Timeline: 3-5 days (optimistic with parallel execution)
```

**Realistic Estimate**: **5 days** (accounting for infrastructure debugging and integration testing)

---

## Risk Assessment

### High Risk Issues
1. **Omniarchon DB Connectivity** (Risk: HIGH, Impact: CRITICAL)
   - Multiple services can't connect to databases
   - Requires Docker networking investigation
   - Could take 1-2 days to diagnose and fix
   - **Mitigation**: Start immediately, use experienced DevOps if stuck

2. **Pattern Storage API Complexity** (Risk: MEDIUM, Impact: HIGH)
   - New endpoint requires 3-5 days
   - Blocks Week 2 of omniclaude plan
   - Unknown integration issues
   - **Mitigation**: Start early, use existing API patterns as template

3. **Hook Persistence Failure** (Risk: LOW, Impact: MEDIUM)
   - Simple fix (set DB_PASSWORD)
   - 15 minute fix
   - **Mitigation**: Fix immediately

### Medium Risk Issues
1. **Orchestrator Integration** (Risk: MEDIUM, Impact: MEDIUM)
   - New LlamaIndex workflow needed
   - 95% reusable but needs testing
   - **Mitigation**: Follow existing NodeBridgeWorkflowOrchestrator pattern

2. **RAG Performance** (Risk: MEDIUM, Impact: LOW)
   - ResearchOrchestrator degraded
   - May need optimization
   - **Mitigation**: Profile and optimize if needed

### Low Risk Issues
1. **Import Path Corrections** (Risk: LOW, Impact: LOW)
   - omnibase_core → omnibase package name
   - Simple find/replace
   - **Mitigation**: Fix with migration script

---

## Success Criteria

### MVP Completion Checklist

**omniclaude**:
- [ ] Stage 4.5 pipeline integration complete
- [ ] Generated nodes include event bus code
- [ ] Startup scripts generated automatically
- [ ] Pattern storage integration working
- [ ] RAG-enhanced generation functional
- [ ] Metrics dashboard showing trends

**omninode_bridge**:
- [ ] NodeCodegenOrchestrator operational
- [ ] NodeCodegenMetricsReducer aggregating data
- [ ] CLI integration publishing/subscribing events
- [ ] End-to-end workflow tested

**omniarchon**:
- [ ] Database connectivity restored
- [ ] Pattern storage API implemented
- [ ] Pattern retrieval working
- [ ] Model performance tracking functional
- [ ] Intelligence gathering APIs tested

**omnibase_core**:
- [x] All components stable (already complete)
- [ ] Import paths corrected in dependent repos

### MVP Demo Scenario
```
1. User runs: poetry run python cli/generate_node.py "Create PostgreSQL writer Effect node"
   ↓
2. CLI publishes NODE_GENERATION_REQUESTED event
   ↓
3. NodeCodegenOrchestrator receives event, executes 6-step workflow:
   - Intelligence gathering (RAG queries omniarchon)
   - Architecture decisions
   - Code generation (omniclaude pipeline)
   - Validation and refinement
   - File writing
   ↓
4. Generated node includes:
   - Event bus initialization
   - Startup script
   - Introspection event publishing
   - Production-ready code
   ↓
5. Node can be started: python node_postgres_writer_effect/startup.py
   ↓
6. Node auto-registers with Consul via introspection event
   ↓
7. Metrics reducer tracks:
   - Generation time: 8.2s
   - Quality score: 0.97
   - Model used: Gemini 2.5 Flash
   - Cost: $0.05
   ↓
8. Pattern stored in omniarchon for future RAG queries
   ↓
9. Metrics dashboard shows:
   - Total generations: 1
   - Avg quality: 0.97
   - Success rate: 100%

Result: End-to-end self-improving code generation demonstrated ✅
```

---

## Resource Requirements

### Development Time
- **Solo developer with polys**: 3-5 actual days
- **Solo developer sequential**: 15 days
- **Team of 3 developers**: 5-7 days

### Infrastructure
- Docker environment with 16GB+ RAM
- PostgreSQL, Qdrant, Memgraph, Kafka/Redpanda
- Consul service registry
- API keys for cloud models (Gemini, etc.)

### External Dependencies
- ✅ omnibase_3 (stable, local)
- ⚠️ Anthropic API (for quorum validation)
- ⚠️ Google Gemini API (for refinement)
- ⚠️ Z.ai GLM API (for quorum validation)

---

## Next Steps (Priority Order)

### Immediate (Today - Oct 22)
1. **Fix hook DB persistence** (15 min)
   ```bash
   export DB_PASSWORD="omninode-bridge-postgres-dev-2024"
   # Restart hook system
   ```

2. **Start missing omniarchon services** (1 hour)
   ```bash
   cd /Volumes/PRO-G40/Code/omniarchon
   docker compose up -d archon-server archon-mcp archon-valkey
   ```

3. **Diagnose DB connectivity** (2-4 hours)
   - Check Docker networking
   - Verify database connections
   - Test service-to-service communication

### Day 2 (Oct 23)
1. **Complete Stage 4.5 integration** (8h → 3h with polys)
   - Implement `_stage_4_5_event_bus_integration()`
   - Add to generation pipeline
   - Write integration tests

2. **Start pattern storage API** (begin 3-5 day task)
   - Design endpoint
   - Implement storage to Qdrant
   - Write tests

### Day 3 (Oct 24)
1. **Test real node generation** (4h → 1.5h)
   - Generate PostgreSQL writer Effect node
   - Verify event bus code present
   - Test startup script
   - Validate introspection event

2. **Continue pattern storage API** (continue 3-5 day task)

### Day 4-5 (Oct 25-26)
1. **Complete pattern storage** (finish 3-5 day task)
2. **Integrate RAG queries** (2-3 days)
3. **Add metrics dashboard** (1 day)
4. **End-to-end testing** (1 day)

### Day 5 Outcome
**MVP COMPLETE** - Self-improving code generation system operational ✅

---

## Appendices

### A. Repository Links
- **omnibase_3**: `/Volumes/PRO-G40/Code/omnibase_3`
- **omniclaude**: `/Volumes/PRO-G40/Code/omniclaude`
- **omninode_bridge**: `/Volumes/PRO-G40/Code/omninode_bridge`
- **omniarchon**: `/Volumes/PRO-G40/Code/omniarchon`

### B. Key Documents
- `OMNICLAUDE_MVP_AND_RELEASE_REQUIREMENTS.md` - Detailed omniclaude analysis
- `OMNINODE_BRIDGE_MVP_AND_RELEASE_REQUIREMENTS.md` - Detailed bridge analysis
- `OMNIARCHON_MVP_AND_RELEASE_REQUIREMENTS.md` - Detailed archon analysis
- `OMNIBASE_CORE_COMPLETION_STATUS.md` - Completion verification
- `DAY_1_COMPLETION_SUMMARY.md` - Day 1 achievements
- `MVP_SOLO_DEVELOPER_PLAN.md` - Original 2-week plan
- `MVP_COMPLETE_ROADMAP.md` - Full vision roadmap

### C. Contact & Support
- **Developer**: Solo developer + Claude (polys)
- **Project**: OmniClaude MVP - Self-Improving Code Generation
- **Timeline**: MVP in 3-5 days, Release in 4-5 weeks

---

**Document Version**: 1.0
**Last Updated**: October 22, 2025
**Status**: Active Development - Day 1 Complete ✅
