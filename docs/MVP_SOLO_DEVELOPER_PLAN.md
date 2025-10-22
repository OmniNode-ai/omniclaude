# MVP Plan - Solo Developer Edition (You + Claude)

**Reality Check**: It's just you and me. Let's be realistic about what one developer can accomplish in 3-4 weeks while maintaining quality.

**Strategy**: Focus on **highest-value features first**, use polys for parallelization, defer nice-to-haves.

---

## Solo Developer Prioritization

### ✅ What We Have Working NOW (Don't Touch)
- Generation pipeline: 95%+ quality (60/60 tests passing)
- Stage 5.5 refinement: 85% → 95%+ transformation
- Quorum validation: 4-model consensus
- Pre-commit automation

**Don't break what's working.** Build on top incrementally.

---

## Minimum Viable Product (2 Weeks, Not 4)

### Week 1: Event Bus Integration (MVP Core)

**Goal**: Generated nodes can join event bus and register with Consul

**Day 1-2**: Stage 4.5 Implementation
- [ ] Add EventPublisher to Effect node template
- [ ] Add `initialize()` and `shutdown()` methods
- [ ] Add introspection event publishing
- [ ] Generate startup script

**Day 3**: Test with Real Node
- [ ] Generate PostgreSQL writer Effect node
- [ ] Run startup script
- [ ] Verify introspection event published
- [ ] Confirm node appears in Consul (if registry working)

**Day 4-5**: Orchestrator Template
- [ ] Add LlamaIndex Workflow base to Orchestrator template
- [ ] Add ModelONEXContainer initialization
- [ ] Add KafkaClient integration
- [ ] Generate test orchestrator node

**Deliverable**: Generated nodes auto-register with service mesh
**Value**: Nodes are production-ready, not just scaffolds

---

### Week 2: Continuous Learning (Proof of Concept)

**Goal**: Demonstrate that system improves with usage

**Day 6-7**: Pattern Storage
- [ ] Add endpoint to omniarchon: `/v1/intelligence/store_pattern`
- [ ] After successful generation (quality >= 0.95), store pattern
- [ ] Store in Qdrant vector DB
- [ ] Test: Generate 20 nodes, verify patterns stored

**Day 8-9**: RAG-Enhanced Generation
- [ ] Modify Stage 1.5 (Intelligence Gathering) to query stored patterns
- [ ] Use vector search: "Find similar successful generations"
- [ ] Pass patterns to Stage 5.5 (Refinement)
- [ ] Test: Does generation quality improve?

**Day 10**: Metrics Dashboard (Simple)
- [ ] Add metrics endpoint: `/v1/metrics/summary`
- [ ] Simple JSON response: success rate, avg quality, total generations
- [ ] CLI command: `poetry run python cli/show_metrics.py`
- [ ] Verify: Can see improvement over time

**Deliverable**: Measurable improvement from pattern learning
**Value**: Proof that continuous learning works

---

## What We're DEFERRING (For Later)

### ❌ Not Doing in MVP
- ~~Model performance tracking database~~ (can add later)
- ~~Automatic model migration~~ (manual for now)
- ~~Full metrics dashboard UI~~ (CLI is enough)
- ~~Self-hosting POC~~ (week 4 stretch goal)
- ~~Cost optimization engine~~ (manual model selection)

### 🔄 Manual Workflows (For Now)
- **Model selection**: You choose which model to use per stage (config file)
- **Quality monitoring**: Run metrics CLI command manually
- **Pattern review**: Query Qdrant directly to see stored patterns
- **Model migration**: Update config, restart, measure quality manually

**Rationale**: These are important but not blocking MVP. Automate after proving value.

---

## Realistic Week 1 Plan (Day-by-Day)

### **Day 1 (Monday): Stage 4.5 Foundation**
```bash
# Morning (4 hours)
1. Create event bus template snippets
   - agents/templates/event_bus_init_effect.py.jinja2
   - agents/templates/event_bus_lifecycle.py.jinja2

2. Update Effect node template
   - Add EventPublisher field to __init__
   - Add initialize() and shutdown() methods

# Afternoon (4 hours)
3. Add introspection event publishing
   - agents/templates/introspection_event.py.jinja2
   - Test template rendering

4. Generate startup script template
   - agents/templates/startup_script.py.jinja2
```

### **Day 2 (Tuesday): Stage 4.5 Integration**
```bash
# Morning (4 hours)
1. Implement _stage_4_5_event_bus_integration()
   - generation_pipeline.py line ~900
   - Inject event bus code into node.py
   - Generate startup script

2. Add Stage 4.5 to pipeline flow
   - Insert between Stage 4 (generation) and Stage 5 (validation)

# Afternoon (4 hours)
3. Write tests for Stage 4.5
   - agents/tests/test_stage_4_5_event_bus.py
   - Verify event bus code generation
   - Verify startup script generation

4. Run full pipeline test
   - Generate test Effect node
   - Verify event bus code present
   - All tests passing
```

### **Day 3 (Wednesday): Real Node Test**
```bash
# Morning (4 hours)
1. Generate PostgreSQL writer Effect node
   poetry run python cli/generate_node.py \
     "Create EFFECT node for PostgreSQL database write operations"

2. Inspect generated code
   - Verify EventPublisher present
   - Verify initialize() method
   - Verify startup script

# Afternoon (4 hours)
3. Test startup (simulated)
   - Run startup script in test environment
   - Verify no errors
   - Check if introspection event would be published

4. Document findings
   - What works? What needs fixes?
   - Update templates if needed
```

### **Day 4 (Thursday): Orchestrator Template**
```bash
# Morning (4 hours)
1. Create orchestrator event bus template
   - agents/templates/event_bus_init_orchestrator.py.jinja2
   - Inherit from LlamaIndex.Workflow
   - Add ModelONEXContainer
   - Add KafkaClient

# Afternoon (4 hours)
2. Update Orchestrator node template
   - agents/templates/orchestrator_node_template.py
   - Add workflow step decorators
   - Add event publishing

3. Test orchestrator generation
   - Generate test orchestrator
   - Verify LlamaIndex Workflow integration
```

### **Day 5 (Friday): Week 1 Wrap-Up**
```bash
# Morning (4 hours)
1. Generate 3 different node types
   - Effect: PostgreSQL writer
   - Compute: Data transformer
   - Orchestrator: Workflow coordinator

2. Verify all have event bus integration

# Afternoon (4 hours)
3. Run full test suite
   - All 60+ tests passing
   - No regressions

4. Commit Week 1 deliverables
   git add -A
   git commit -m "feat(stage-4.5): event bus integration for all node types"

5. Update documentation
   - MVP_EVENT_BUS_INTEGRATION.md with findings
```

**Week 1 Success Criteria**:
- ✅ Generated nodes have event bus code
- ✅ Startup scripts generated automatically
- ✅ Introspection events published on startup
- ✅ All tests passing

---

## Realistic Week 2 Plan (Day-by-Day)

### **Day 6 (Monday): Pattern Storage Backend**
```bash
# Morning (4 hours)
1. Add pattern storage endpoint to omniarchon
   cd ../omniarchon
   # Add to python/src/intelligence/app.py
   @app.post("/v1/intelligence/store_pattern")

2. Connect to Qdrant (if available) or PostgreSQL
   - Store: node_type, domain, code_sample, quality_score

# Afternoon (4 hours)
3. Add pattern storage to generation pipeline
   cd ../omniclaude
   # In generation_pipeline.py, after successful generation:
   if result.quality_score >= 0.95:
       await intelligence_service.store_pattern(...)

4. Test: Generate 5 nodes, verify patterns stored
```

### **Day 7 (Tuesday): Pattern Retrieval**
```bash
# Morning (4 hours)
1. Add pattern retrieval endpoint
   @app.get("/v1/intelligence/get_patterns")

2. Implement vector search or SQL query
   - Find similar patterns by node_type + domain

# Afternoon (4 hours)
3. Update Stage 1.5 (Intelligence Gathering)
   - Query patterns from omniarchon
   - Pass to Stage 5.5 (Refinement)

4. Test: Does refinement improve with patterns?
```

### **Day 8 (Wednesday): Proof of Concept Test**
```bash
# Full Day (8 hours)
1. Baseline test (no patterns)
   - Generate 10 nodes
   - Record quality scores
   - Average quality: ???

2. With patterns (after storing 20 patterns)
   - Generate 10 more nodes
   - Record quality scores
   - Compare: Did quality improve?

3. Document findings
   - Does RAG help? By how much?
   - Which node types benefit most?
```

### **Day 9 (Thursday): Metrics CLI**
```bash
# Morning (4 hours)
1. Create metrics storage (simple JSON file for MVP)
   - Store after each generation
   - Format: {timestamp, node_type, quality, latency, model}

# Afternoon (4 hours)
2. Create metrics CLI
   cli/show_metrics.py
   - Show total generations
   - Show average quality
   - Show trend (improving?)

3. Test metrics collection
   - Generate 20 nodes
   - Run show_metrics.py
   - Verify metrics accurate
```

### **Day 10 (Friday): Week 2 Wrap-Up**
```bash
# Morning (4 hours)
1. Generate 30 nodes with full learning enabled
   - First 10: Bootstrap (no patterns)
   - Next 20: With pattern learning
   - Measure improvement

# Afternoon (4 hours)
2. Commit Week 2 deliverables
   git add -A
   git commit -m "feat: continuous learning with pattern storage and metrics"

3. Update roadmap with findings
   - Did quality improve? By how much?
   - Is RAG retrieval effective?
   - What's next priority?
```

**Week 2 Success Criteria**:
- ✅ Patterns stored after successful generation
- ✅ Pattern retrieval integrated in Stage 1.5
- ✅ Measurable quality improvement
- ✅ Metrics CLI shows trend

---

## MVP Complete! (After 2 Weeks)

### What We'll Have
1. **Generated nodes join event bus** (Stage 4.5)
2. **Continuous learning active** (pattern storage + RAG)
3. **Measurable improvement** (metrics show quality increase)
4. **Production-ready nodes** (not just scaffolds)

### What We Can Measure
```bash
$ poetry run python cli/show_metrics.py

OMNICLAUDE Generation Metrics
==============================
Total Generations: 50
Average Quality: 0.957 (↑ 0.023 from baseline)
Success Rate: 98.0%
Average Latency: 8.2s

Quality Trend:
  First 10: 0.934 avg
  Last 10:  0.971 avg  (+3.7% improvement)

Pattern Learning:
  Patterns Stored: 47
  RAG Retrieval Rate: 92% (46/50 generations used patterns)
  Quality Boost from RAG: +2.1% avg

Top Performing Node Types:
  1. Effect: 0.982 avg quality
  2. Compute: 0.951 avg quality
  3. Orchestrator: 0.938 avg quality
```

### What We'll Prove
- ✅ Event bus integration works
- ✅ Continuous learning improves quality
- ✅ RAG pattern retrieval is effective
- ✅ System gets better with usage

---

## Beyond MVP (Week 3-4 - If You Want)

### Optional: Model Performance Tracking
- Track cost/latency/quality per model
- Manual model selection (no automation yet)
- Estimated: 3 days

### Optional: Self-Hosting POC
- Generate 1-2 pipeline stages as ONEX nodes
- Test event-driven execution
- Estimated: 4-5 days

### Optional: Metrics Dashboard UI
- Simple React dashboard
- Real-time metrics visualization
- Estimated: 3-4 days

**But honestly?** After 2 weeks you'll have a **working, learning, improving code generation system**. That's the MVP. Everything else is polish.

---

## How to Work Efficiently (Solo Developer)

### Use Polys for Parallelization
When you have independent tasks, spawn multiple polys:

```bash
# Example: Day 1 afternoon
"Spawn 3 polys:
- Poly 1: Create event_bus_init_effect.py.jinja2
- Poly 2: Create event_bus_lifecycle.py.jinja2
- Poly 3: Create introspection_event.py.jinja2"

# All complete in parallel, saves 2-3 hours
```

### Use Existing Patterns
Don't reinvent:
- Copy EventPublisher pattern from omniarchon
- Copy ModelONEXContainer pattern from omninode_bridge
- Copy LlamaIndex Workflow pattern from workflow_node.py

### Test Incrementally
Don't build everything then test:
- Generate after each stage addition
- Run tests after each template change
- Commit after each working feature

### Document as You Go
Future you will thank you:
- Update MVP docs with findings
- Note what worked, what didn't
- Track quality improvements

---

## Honest Assessment

**Can you do this in 2 weeks?**
Yes, if you:
- Focus on MVP features only
- Use polys to parallelize work
- Don't get distracted by nice-to-haves
- Test incrementally
- Commit working code frequently

**Will it be production-ready?**
The generated nodes will be. The learning system will be proof-of-concept quality but functional.

**Is it worth it?**
Hell yes. You'll have:
- Self-improving code generation
- Event-driven architecture
- Measurable quality gains
- Foundation for full automation later

**What's the realistic timeline?**
- Week 1: 40 hours of focused work (Stage 4.5 + testing)
- Week 2: 40 hours of focused work (learning + metrics)
- Total: 80 hours over 2 weeks

If you can dedicate 8 hours/day for 10 days, this is absolutely doable.

---

**Let's build this thing.** 🚀

Which day would you like to start with? I can begin implementing Day 1 tasks right now.
