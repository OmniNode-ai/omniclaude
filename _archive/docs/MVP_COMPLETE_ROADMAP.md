# Complete MVP Roadmap - Self-Optimizing Code Generation Platform

**Vision**: Event-driven, self-improving code generation system that learns from every generation, measures model performance, and migrates from expensive cloud models to cheap local models while maintaining quality.

**Timeline**: 3-4 weeks to full MVP
**Status**: 75% infrastructure complete, need wiring + learning layer

---

## Executive Summary

### The Big Picture

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER NATURAL LANGUAGE PROMPT                  │
└──────────────────────┬──────────────────────────────────────────┘
                       │ (publish NODE_GENERATION_REQUESTED event)
                       ↓
┌─────────────────────────────────────────────────────────────────┐
│         OMNINODE_BRIDGE - Workflow Orchestrator                  │
│  (LlamaIndex Workflows - manages generation workflow)           │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ PRD Analysis │→ │ Intelligence │→ │ Contract     │→ ...     │
│  │ Step         │  │ Gathering    │  │ Building     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│         ↓                   ↓                  ↓                 │
│    (publishes workflow events with correlation_id)              │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ↓
┌─────────────────────────────────────────────────────────────────┐
│         OMNIARCHON - Intelligence Service Adapter                │
│  (subscribes to intelligence request events)                     │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────────┤
│  │ Intelligence Features (via EventPublisher):                   │
│  │ - RAG pattern matching (from 34 production nodes)            │
│  │ - Code quality assessment                                     │
│  │ - Architecture recommendations                                │
│  │ - Continuous learning (stores successful patterns)           │
│  │ - Model performance tracking (cost/latency/accuracy)         │
│  └──────────────────────────────────────────────────────────────┤
│         ↓ (publishes INTELLIGENCE_GATHERED events)               │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ↓
┌─────────────────────────────────────────────────────────────────┐
│         OMNICLAUDE - Generation Pipeline (Event-Driven)          │
│  (7 stages as ONEX nodes, subscribe to workflow events)         │
│                                                                   │
│  Each stage:                                                      │
│  1. Subscribes to input events                                   │
│  2. Executes generation step                                     │
│  3. Publishes output events                                      │
│  4. Records metrics (latency, tokens, model used, quality)      │
│  └──────────────────────────────────────────────────────────────┤
│         ↓ (publishes NODE_GENERATED event)                       │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ↓
┌─────────────────────────────────────────────────────────────────┐
│         OMNINODE_BRIDGE - Metrics Reducer                        │
│  (aggregates generation metrics for learning)                    │
│                                                                   │
│  Aggregates:                                                      │
│  - Success rate per model (Gemini vs GLM vs Llama)              │
│  - Cost per generation ($$$ for cloud, $ for local)             │
│  - Latency per stage (which models are fast?)                   │
│  - Quality scores (validation pass rate)                        │
│  - Pattern reuse (how often RAG helps)                          │
│  └──────────────────────────────────────────────────────────────┤
│         ↓ (publishes METRICS_AGGREGATED event)                   │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ↓
┌─────────────────────────────────────────────────────────────────┐
│         OMNIARCHON - Model Selection Intelligence                │
│  (learns which models work best for which tasks)                 │
│                                                                   │
│  Learns:                                                          │
│  - "Gemini 2.5 Flash: 97% quality, $0.05/gen, 2.3s avg"        │
│  - "Llama 3.1 8B: 92% quality, $0.001/gen, 1.1s avg"           │
│  - "DeepSeek-Lite: 89% quality, $0.002/gen, 0.8s avg"          │
│  └──────────────────────────────────────────────────────────────┤
│  Decision Engine: "After 100 generations, migrate Stage 3       │
│  (Business Logic) from Gemini to Llama 3.1 (saves 98% cost)"    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ↓
                Generated ONEX Node
                (auto-registers with Consul)
                (publishes introspection event)
```

---

## Phase 1: Repository Integration (Week 1)

### 1.1 Omnibase Core - Event Models (2 days) ✅ 95% DONE

**Status**: Almost complete, just need validation

**Existing**:
- ✅ `ModelEventEnvelope` - standardized event wrapper
- ✅ `ModelNodeIntrospectionEvent` - service discovery
- ✅ `MixinIntrospectionPublisher` - auto-registration mixin
- ✅ `ModelONEXContainer` - dependency injection

**TODO**:
- [ ] Add `ModelGenerationMetrics` event model
  ```python
  class ModelGenerationMetrics(BaseModel):
      correlation_id: UUID
      stage: str                    # "prd_analysis", "contract_building", etc.
      model_used: str               # "gemini-2.5-flash", "llama-3.1-8b"
      tokens_input: int
      tokens_output: int
      latency_ms: int
      cost_usd: float
      quality_score: float          # 0.0-1.0 from validation
      success: bool
      timestamp: datetime
  ```

- [ ] Add `ModelIntelligenceRequest` / `ModelIntelligenceResponse` events
  ```python
  class ModelIntelligenceRequest(BaseModel):
      correlation_id: UUID
      request_type: str             # "rag_pattern_matching", "code_assessment"
      context: Dict[str, Any]
      node_type: str
      domain: str

  class ModelIntelligenceResponse(BaseModel):
      correlation_id: UUID
      patterns_found: List[Dict]
      recommendations: List[str]
      confidence: float
      sources: List[str]            # Which production nodes were referenced
  ```

**Validation**: Run tests in omnibase_core, ensure all models serialize correctly

---

### 1.2 Omniarchon - Intelligence Event Adapter (3 days) 🔄 IN PROGRESS

**Branch**: `feature/event-bus-integration` ✅ (commit f80c8c9)

**Completed**:
- ✅ `NodeIntelligenceAdapterEffect` - event-driven intelligence service
- ✅ EventPublisher integration
- ✅ Kafka consumer for CODE_ANALYSIS_REQUESTED events

**TODO**:
- [ ] Add generation-specific intelligence endpoint
  ```python
  @app.post("/v1/intelligence/generation_assist")
  async def generation_assist(request: ModelIntelligenceRequest):
      """Provide intelligence for code generation."""
      # RAG pattern matching
      patterns = await rag_service.find_similar_patterns(
          node_type=request.node_type,
          domain=request.domain,
          match_count=5
      )

      # Best practices lookup
      best_practices = await knowledge_base.get_domain_practices(
          domain=request.domain
      )

      # Return recommendations
      return ModelIntelligenceResponse(
          patterns_found=patterns,
          recommendations=best_practices,
          confidence=calculate_confidence(patterns),
          sources=[p["source_node"] for p in patterns]
      )
  ```

- [ ] Add continuous learning endpoint (stores successful generations)
  ```python
  @app.post("/v1/intelligence/learn_pattern")
  async def learn_pattern(
      node_type: str,
      domain: str,
      generated_code: str,
      quality_score: float,
      correlation_id: UUID
  ):
      """Store successful generation pattern for future reference."""
      if quality_score >= 0.95:  # Only learn from high-quality generations
          await knowledge_base.store_pattern(
              pattern_type="generated_node",
              node_type=node_type,
              domain=domain,
              code_sample=generated_code,
              quality_score=quality_score,
              metadata={"correlation_id": str(correlation_id)}
          )
  ```

- [ ] Add model performance tracking endpoint
  ```python
  @app.post("/v1/intelligence/record_model_performance")
  async def record_model_performance(metrics: ModelGenerationMetrics):
      """Record model performance for future optimization."""
      await metrics_db.insert(
          table="model_performance",
          data={
              "model_name": metrics.model_used,
              "stage": metrics.stage,
              "latency_ms": metrics.latency_ms,
              "cost_usd": metrics.cost_usd,
              "quality_score": metrics.quality_score,
              "success": metrics.success,
              "timestamp": metrics.timestamp
          }
      )

      # Trigger model selection re-evaluation if enough data
      total_generations = await metrics_db.count_by_model(metrics.model_used)
      if total_generations % 100 == 0:  # Every 100 generations
          await trigger_model_selection_analysis(metrics.stage)
  ```

**Testing**: Deploy to omniarchon cluster, verify events flow through adapter

---

### 1.3 Omninode Bridge - Workflow Orchestrator (4 days)

**Status**: Orchestrator framework exists, need generation workflow

**Existing**:
- ✅ `NodeBridgeWorkflowOrchestrator` (LlamaIndex Workflows)
- ✅ `ModelONEXContainer` dependency injection
- ✅ KafkaClient integration
- ✅ Workflow step pattern with `@step` decorator

**TODO**:
- [ ] Create `NodeGenerationWorkflowOrchestrator` workflow
  ```python
  class NodeGenerationWorkflowOrchestrator(Workflow):
      """Orchestrates ONEX node generation workflow."""

      @step
      async def parse_prompt(self, event: StartEvent) -> PromptParsedEvent:
          """Stage 1: Parse natural language prompt."""
          # Publish PROMPT_PARSING_REQUESTED event
          # Wait for PROMPT_PARSED response
          return PromptParsedEvent(parsed_data=...)

      @step
      async def gather_intelligence(
          self, event: PromptParsedEvent
      ) -> IntelligenceGatheredEvent:
          """Stage 1.5: Gather intelligence from omniarchon."""
          # Publish INTELLIGENCE_REQUESTED event
          # Wait for INTELLIGENCE_RESPONSE
          return IntelligenceGatheredEvent(intelligence=...)

      @step
      async def build_contract(
          self, event: IntelligenceGatheredEvent
      ) -> ContractBuiltEvent:
          """Stage 2: Build ONEX contract with quorum validation."""
          # Publish CONTRACT_BUILDING_REQUESTED
          # Wait for CONTRACT_BUILT
          return ContractBuiltEvent(contract=...)

      # ... (7 stages total)

      @step
      async def complete_generation(
          self, event: FilesWrittenEvent
      ) -> StopEvent:
          """Publish NODE_GENERATED event."""
          await self.kafka_client.publish_event(
              topic="omninode.generation.node_generated.v1",
              event_type="NODE_GENERATED",
              payload={
                  "correlation_id": self.correlation_id,
                  "output_path": event.output_path,
                  "node_type": event.node_type,
                  "success": True,
              }
          )

          return StopEvent(result=event.result)
  ```

- [ ] Create `NodeMetricsReducer` for aggregating generation metrics
  ```python
  class NodeMetricsReducer:
      """Aggregates generation metrics for learning."""

      def __init__(self, container: ModelONEXContainer):
          self.topics = [
              "omninode.generation.metrics.recorded.v1",
              "omninode.generation.node_generated.v1",
          ]
          self.aggregation_window_ms = 5000  # 5 seconds

          # Aggregated state
          self.metrics_by_model: Dict[str, List[float]] = {}
          self.success_rate_by_stage: Dict[str, float] = {}
          self.total_cost_usd: float = 0.0

      async def _reduce_event(self, event: Any) -> None:
          """Aggregate metrics event."""
          if event.type == "METRICS_RECORDED":
              model = event.payload["model_used"]
              quality = event.payload["quality_score"]

              if model not in self.metrics_by_model:
                  self.metrics_by_model[model] = []

              self.metrics_by_model[model].append(quality)
              self.total_cost_usd += event.payload["cost_usd"]

      async def _publish_state_update(self) -> None:
          """Publish aggregated metrics for model selection."""
          # Calculate average quality per model
          model_performance = {
              model: {
                  "avg_quality": sum(scores) / len(scores),
                  "sample_count": len(scores),
              }
              for model, scores in self.metrics_by_model.items()
          }

          await self.kafka_client.publish_event(
              topic="omninode.metrics.aggregated.v1",
              event_type="METRICS_AGGREGATED",
              payload={
                  "model_performance": model_performance,
                  "total_cost_usd": self.total_cost_usd,
                  "aggregation_window_ms": self.aggregation_window_ms,
              }
          )
  ```

**Testing**: Run workflow with real generation request, verify all steps execute

---

### 1.4 Omniclaude - Event-Driven Generation Pipeline (5 days)

**Status**: Pipeline complete, needs event bus integration (Stage 4.5)

**TODO**:
- [ ] Implement Stage 4.5: Event Bus Integration (from MVP_EVENT_BUS_INTEGRATION.md)
  - Add EventPublisher to all generated nodes
  - Add `initialize()` and `shutdown()` methods
  - Add introspection event publishing
  - Generate startup scripts

- [ ] Convert each pipeline stage to subscribe/publish events
  ```python
  class Stage1PRDAnalysis:
      async def execute(self, correlation_id: UUID):
          """Subscribe to PROMPT_PARSING_REQUESTED, publish PROMPT_PARSED."""
          # Listen for event
          event = await self.event_consumer.poll()

          # Execute stage
          parsed_data = await self.prd_analyzer.analyze(event.prompt)

          # Publish result
          await self.event_publisher.publish(
              event_type="PROMPT_PARSED",
              payload={
                  "correlation_id": correlation_id,
                  "parsed_data": parsed_data,
              }
          )

          # Record metrics
          await self.record_metrics(
              stage="prd_analysis",
              model_used="gemini-2.5-flash",
              latency_ms=...,
              quality_score=parsed_data.confidence,
          )
  ```

- [ ] Add metrics recording to every stage
  ```python
  async def record_metrics(
      self,
      stage: str,
      model_used: str,
      latency_ms: int,
      quality_score: float,
      tokens_input: int = 0,
      tokens_output: int = 0,
  ):
      """Record stage metrics for continuous learning."""
      cost_usd = self._calculate_cost(
          model=model_used,
          tokens_input=tokens_input,
          tokens_output=tokens_output
      )

      metrics = ModelGenerationMetrics(
          correlation_id=self.correlation_id,
          stage=stage,
          model_used=model_used,
          tokens_input=tokens_input,
          tokens_output=tokens_output,
          latency_ms=latency_ms,
          cost_usd=cost_usd,
          quality_score=quality_score,
          success=True,
          timestamp=datetime.utcnow(),
      )

      await self.event_publisher.publish(
          event_type="GENERATION_METRICS_RECORDED",
          payload=metrics.model_dump(),
      )
  ```

- [ ] Add model selection configuration
  ```yaml
  # config/model_selection.yaml
  stages:
    prd_analysis:
      models:
        - name: "gemini-2.5-flash"
          priority: 1
          cost_per_1k_tokens: 0.00015
          latency_target_ms: 2000
          quality_threshold: 0.85
        - name: "llama-3.1-8b"
          priority: 2
          cost_per_1k_tokens: 0.00001
          latency_target_ms: 1500
          quality_threshold: 0.80

      migration_rules:
        - condition: "quality_avg >= 0.90 AND sample_size >= 100"
          action: "migrate_to_next_priority"
          reason: "High quality with enough samples, try cheaper model"
  ```

**Testing**: Generate 10 nodes end-to-end with metrics recording

---

## Phase 2: Continuous Learning Layer (Week 2)

### 2.1 Pattern Storage & Retrieval (3 days)

**Location**: Omniarchon intelligence service

**TODO**:
- [ ] Implement pattern storage after successful generation
  ```python
  async def store_successful_pattern(
      node_type: str,
      domain: str,
      generated_code: str,
      contract: Dict,
      quality_score: float,
      correlation_id: UUID
  ):
      """Store successful generation for future RAG retrieval."""
      # Extract key patterns
      patterns = extract_code_patterns(generated_code)

      # Store in vector database (Qdrant)
      await vector_db.upsert(
          collection="successful_generations",
          points=[{
              "id": str(correlation_id),
              "vector": await embeddings.encode(generated_code),
              "payload": {
                  "node_type": node_type,
                  "domain": domain,
                  "patterns": patterns,
                  "quality_score": quality_score,
                  "contract_summary": extract_contract_summary(contract),
                  "timestamp": datetime.utcnow().isoformat(),
              }
          }]
      )
  ```

- [ ] Implement RAG-enhanced generation
  ```python
  async def get_generation_intelligence(
      node_type: str,
      domain: str,
      prompt: str
  ) -> IntelligenceContext:
      """Get RAG intelligence for generation."""
      # Vector search for similar successful generations
      similar_generations = await vector_db.search(
          collection="successful_generations",
          query_vector=await embeddings.encode(prompt),
          filter={
              "node_type": node_type,
              "domain": domain,
              "quality_score": {"$gte": 0.90}  # Only high-quality examples
          },
          limit=5
      )

      # Extract patterns
      patterns = [
          gen.payload["patterns"] for gen in similar_generations
      ]

      return IntelligenceContext(
          similar_patterns=patterns,
          best_practices=aggregate_best_practices(similar_generations),
          confidence=calculate_confidence(similar_generations),
      )
  ```

**Testing**: Generate 20 nodes, verify patterns are stored and retrieved

---

### 2.2 Model Performance Tracking (2 days)

**Location**: Omniarchon + PostgreSQL metrics database

**TODO**:
- [ ] Create metrics database schema
  ```sql
  CREATE TABLE model_performance (
      id UUID PRIMARY KEY,
      correlation_id UUID,
      stage VARCHAR(50),
      model_name VARCHAR(100),
      tokens_input INT,
      tokens_output INT,
      latency_ms INT,
      cost_usd DECIMAL(10, 6),
      quality_score DECIMAL(3, 2),
      success BOOLEAN,
      timestamp TIMESTAMP,
      INDEX idx_model_stage (model_name, stage),
      INDEX idx_timestamp (timestamp)
  );

  CREATE TABLE model_selection_decisions (
      id UUID PRIMARY KEY,
      stage VARCHAR(50),
      previous_model VARCHAR(100),
      new_model VARCHAR(100),
      reason TEXT,
      expected_quality DECIMAL(3, 2),
      expected_cost_savings_pct DECIMAL(5, 2),
      timestamp TIMESTAMP
  );
  ```

- [ ] Implement performance aggregation query
  ```python
  async def get_model_performance_summary(
      stage: str,
      time_window_hours: int = 24
  ) -> Dict[str, ModelPerformance]:
      """Get aggregated performance metrics per model."""
      query = """
          SELECT
              model_name,
              COUNT(*) as total_generations,
              AVG(quality_score) as avg_quality,
              AVG(latency_ms) as avg_latency_ms,
              SUM(cost_usd) as total_cost_usd,
              AVG(cost_usd) as avg_cost_usd,
              COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate_pct
          FROM model_performance
          WHERE stage = $1
            AND timestamp >= NOW() - INTERVAL '$2 hours'
          GROUP BY model_name
          ORDER BY avg_quality DESC
      """

      results = await db.fetch_all(query, stage, time_window_hours)

      return {
          row["model_name"]: ModelPerformance(
              avg_quality=row["avg_quality"],
              avg_latency_ms=row["avg_latency_ms"],
              total_cost_usd=row["total_cost_usd"],
              avg_cost_usd=row["avg_cost_usd"],
              success_rate_pct=row["success_rate_pct"],
              sample_count=row["total_generations"]
          )
          for row in results
      }
  ```

**Testing**: Generate 50 nodes with different models, verify metrics aggregation

---

### 2.3 Automatic Model Selection (3 days)

**Location**: Omniarchon intelligence service

**TODO**:
- [ ] Implement model selection decision engine
  ```python
  class ModelSelectionEngine:
      """Decides which model to use for each stage."""

      async def evaluate_model_migration(
          self,
          stage: str,
          current_model: str
      ) -> Optional[ModelMigrationDecision]:
          """Evaluate if we should migrate to a cheaper model."""
          # Get performance data
          perf = await get_model_performance_summary(
              stage=stage,
              time_window_hours=24
          )

          current_perf = perf[current_model]

          # Check if we have enough samples
          if current_perf.sample_count < 100:
              return None  # Not enough data

          # Find cheaper alternatives
          cheaper_models = [
              (model, p) for model, p in perf.items()
              if p.avg_cost_usd < current_perf.avg_cost_usd
              and p.sample_count >= 50  # Must have enough data
          ]

          # Sort by quality (descending)
          cheaper_models.sort(key=lambda x: x[1].avg_quality, reverse=True)

          # Check if top cheaper model meets quality threshold
          if cheaper_models:
              best_alternative, alt_perf = cheaper_models[0]

              quality_drop = current_perf.avg_quality - alt_perf.avg_quality
              cost_savings_pct = (
                  (current_perf.avg_cost_usd - alt_perf.avg_cost_usd)
                  / current_perf.avg_cost_usd * 100
              )

              # Migration criteria
              if quality_drop <= 0.03 and cost_savings_pct >= 50:
                  return ModelMigrationDecision(
                      stage=stage,
                      from_model=current_model,
                      to_model=best_alternative,
                      expected_quality=alt_perf.avg_quality,
                      cost_savings_pct=cost_savings_pct,
                      reason=f"Quality drop {quality_drop:.2f} acceptable, "
                             f"saves {cost_savings_pct:.1f}% cost"
                  )

          return None

      async def apply_migration(
          self,
          decision: ModelMigrationDecision
      ) -> None:
          """Apply model migration decision."""
          # Update configuration
          await config_service.update_stage_model(
              stage=decision.stage,
              model=decision.to_model
          )

          # Record decision
          await db.execute("""
              INSERT INTO model_selection_decisions
              (id, stage, previous_model, new_model, reason,
               expected_quality, expected_cost_savings_pct, timestamp)
              VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
          """,
              uuid4(),
              decision.stage,
              decision.from_model,
              decision.to_model,
              decision.reason,
              decision.expected_quality,
              decision.cost_savings_pct
          )

          # Publish event
          await event_publisher.publish(
              event_type="MODEL_MIGRATED",
              payload=decision.model_dump()
          )
  ```

- [ ] Add scheduled model evaluation job
  ```python
  async def evaluate_all_stages():
      """Periodic job to evaluate model performance."""
      engine = ModelSelectionEngine()

      stages = ["prd_analysis", "intelligence_gathering", "contract_building",
                "business_logic", "code_generation", "validation", "refinement"]

      for stage in stages:
          current_model = await config_service.get_stage_model(stage)
          decision = await engine.evaluate_model_migration(stage, current_model)

          if decision:
              logger.info(f"Model migration recommended: {decision}")
              await engine.apply_migration(decision)

  # Schedule every 6 hours
  scheduler.add_job(evaluate_all_stages, "interval", hours=6)
  ```

**Testing**: Run 200 generations with mixed models, verify automatic migrations

---

## Phase 3: Model Optimization & Migration (Week 3)

### 3.1 Model Pretraining Phase (Cloud Models)

**Goal**: Use expensive cloud models (Gemini, GPT-4) to generate high-quality training data

**Process**:
1. Generate 500 nodes using cloud models (Gemini 2.5 Flash + quorum)
2. Record all successful patterns (quality >= 0.95)
3. Store in vector database for RAG retrieval
4. Measure baseline performance metrics

**Cost Budget**: ~$25-50 for 500 generations @ $0.05/gen

**Expected Outcomes**:
- 500 high-quality node examples
- Comprehensive pattern library
- Baseline metrics for comparison

---

### 3.2 Model Migration Phase (Local Models)

**Goal**: Migrate stages to local models once cloud models have "trained" the system

**Migration Strategy**:
```python
# Example migration timeline
Week 1-2 (Pretraining):
  All stages: Gemini 2.5 Flash
  Success rate: 95%+
  Cost: $0.05/generation

Week 3 (First Migration):
  Stage 3 (Business Logic): Llama 3.1 8B (local)
  Success rate target: 92%+
  Cost: $0.001/generation (98% cost reduction)

  If success rate >= 92% after 100 generations → migrate Stage 4

Week 4 (Second Migration):
  Stage 4 (Code Generation): DeepSeek-Coder-V2-Lite (local)
  Success rate target: 90%+
  Cost: $0.002/generation

  If success rate >= 90% → migrate Stage 5

Week 5-6 (Aggressive Migration):
  Stages 5-7: Migrate remaining stages
  Keep Stage 1-2 (critical) on Gemini
  Final cost: ~$0.01/generation (80% cost reduction)
```

**Validation Rules**:
- Never migrate if quality drops >5%
- Always keep 2 weeks of rollback capability
- Monitor success rate continuously
- Auto-rollback if success rate < threshold for 24 hours

---

### 3.3 Continuous Improvement Dashboard (3 days)

**Location**: Omniarchon web UI

**TODO**:
- [ ] Create real-time metrics dashboard
  ```typescript
  // Dashboard components
  interface MetricsDashboard {
      // Success rate trend (should increase over time)
      successRateTrend: TimeSeriesChart;

      // Cost per generation (should decrease as we migrate)
      costTrend: TimeSeriesChart;

      // Model distribution (shows migration progress)
      modelDistribution: PieChart;

      // Quality by stage (monitors quality maintenance)
      qualityByStage: BarChart;

      // Recent model migrations
      recentMigrations: MigrationTable;

      // RAG pattern usage (shows learning effectiveness)
      patternReuseRate: Gauge;
  }
  ```

- [ ] Add alerts for quality degradation
  ```python
  async def monitor_quality_degradation():
      """Alert if quality drops below threshold."""
      for stage in STAGES:
          recent_quality = await get_avg_quality(
              stage=stage,
              time_window_hours=24
          )

          baseline_quality = await get_avg_quality(
              stage=stage,
              time_window_hours=168  # 1 week baseline
          )

          quality_drop = baseline_quality - recent_quality

          if quality_drop > 0.05:  # 5% quality drop
              await alert_service.send_alert(
                  severity="high",
                  message=f"Quality degradation detected in {stage}",
                  details={
                      "recent_quality": recent_quality,
                      "baseline_quality": baseline_quality,
                      "drop_pct": quality_drop * 100
                  },
                  recommended_action="Consider rolling back recent model migration"
              )
  ```

**Testing**: Run dashboard with real data, verify all metrics update

---

## Phase 4: Self-Hosting POC (Week 4)

### 4.1 Generate Generation Pipeline Nodes

**Goal**: Use the generation system to generate the next version of itself

**Process**:
1. Generate each pipeline stage as an ONEX node:
   - `NodePRDAnalyzerCompute`
   - `NodeIntelligenceGathererEffect`
   - `NodeContractBuilderCompute`
   - `NodeBusinessLogicGeneratorCompute`
   - `NodeCodeGeneratorEffect`
   - `NodeValidatorCompute`
   - `NodeCodeRefinerEffect`
   - `NodeFileWriterEffect`

2. Deploy generated nodes to omninode_bridge cluster

3. Configure event routing between nodes

4. Run generation request through event-driven pipeline

5. Compare output quality to monolithic pipeline

**Success Criteria**:
- Generated nodes pass all validation
- Event-driven pipeline produces equivalent quality
- Latency < 12s (acceptable overhead for decoupling)
- All nodes auto-register with Consul

---

### 4.2 Self-Improvement Validation

**Experiment**: Does the system improve itself?

1. Generate v1.0 pipeline nodes (using current pipeline)
2. Run 100 generations through v1.0 nodes
3. Measure success rate, capture patterns
4. Generate v1.1 pipeline nodes (using v1.0 nodes with learned patterns)
5. Run 100 generations through v1.1 nodes
6. Compare success rates

**Hypothesis**: v1.1 should have 2-5% higher success rate due to pattern learning

---

## Success Metrics & KPIs

### Week 1 - Integration Complete
- [ ] All 4 repos integrated via events
- [ ] End-to-end generation works via orchestrator
- [ ] Metrics recorded for every generation
- [ ] Success rate: 95%+ (baseline)

### Week 2 - Learning Active
- [ ] 500 successful patterns stored in vector DB
- [ ] RAG retrieval provides relevant patterns
- [ ] Model performance tracked for all models
- [ ] Success rate: 96%+ (learning boost)

### Week 3 - First Migrations
- [ ] Stage 3 migrated to Llama 3.1 8B
- [ ] Cost per generation: $0.03 (40% reduction)
- [ ] Success rate maintained: 93%+
- [ ] Zero rollbacks needed

### Week 4 - Self-Hosting
- [ ] All 7 pipeline stages running as ONEX nodes
- [ ] Event-driven pipeline generates equivalent quality
- [ ] System generates v1.1 of itself
- [ ] Success rate: 97%+ (continuous improvement)

### Long-Term (3 months)
- [ ] 80% of stages on local models
- [ ] Cost per generation: $0.01 (80% reduction)
- [ ] Success rate: 98%+ (learned from 5000+ generations)
- [ ] Pattern library: 2000+ high-quality examples

---

## Risk Mitigation

### Risk 1: Quality Degradation After Migration
**Mitigation**:
- Automatic rollback if success rate < 90%
- 2-week grace period before disabling cloud model
- Continuous A/B testing (10% traffic on new model)

### Risk 2: Local Models Insufficient
**Mitigation**:
- Keep critical stages (PRD, Contract) on cloud models indefinitely
- Use hybrid approach (local for most, cloud for critical)
- Fine-tune local models on successful patterns

### Risk 3: Event Bus Latency
**Mitigation**:
- Keep latency target < 12s end-to-end
- Optimize Kafka throughput (batch sizes, compression)
- Consider synchronous fallback for latency-critical paths

### Risk 4: Pattern Overfitting
**Mitigation**:
- Diversity scoring (don't just store similar patterns)
- Periodic pattern pruning (remove outdated patterns)
- Quality threshold for pattern storage (>= 0.95)

---

## Repository Checklist

### Omnibase Core
- [ ] ModelGenerationMetrics event model
- [ ] ModelIntelligenceRequest/Response events
- [ ] Validate all event models serialize correctly

### Omniarchon
- [ ] Intelligence event adapter (IN PROGRESS ✅)
- [ ] Generation assist endpoint
- [ ] Continuous learning endpoint (store patterns)
- [ ] Model performance tracking endpoint
- [ ] Model selection decision engine

### Omninode Bridge
- [ ] NodeGenerationWorkflowOrchestrator (7-stage workflow)
- [ ] NodeMetricsReducer (aggregate performance metrics)
- [ ] Deploy to cluster with Kafka + Consul

### Omniclaude
- [ ] Stage 4.5: Event Bus Integration
- [ ] Convert all stages to event-driven
- [ ] Add metrics recording to every stage
- [ ] Model selection configuration
- [ ] Cost calculation utilities

---

## Final Architecture

**The Complete System**:
1. **User sends natural language prompt**
2. **Omninode Bridge orchestrator** receives request, starts workflow
3. **Omniclaude stages** subscribe to workflow events, execute, publish results
4. **Omniarchon intelligence** provides RAG patterns and recommendations
5. **Omninode Bridge reducer** aggregates metrics from all stages
6. **Omniarchon model selection** analyzes metrics, migrates models automatically
7. **Generated node** auto-registers with Consul, publishes introspection
8. **System learns** from every generation, stores successful patterns
9. **Success rate increases**, cost decreases over time
10. **System generates next version of itself**

**This is production-grade, self-optimizing AI infrastructure.** 🚀

---

**Document Status**: Complete MVP Roadmap
**Timeline**: 3-4 weeks
**Next Action**: Review with team, assign phases to developers
