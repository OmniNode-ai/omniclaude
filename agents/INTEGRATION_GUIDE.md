# Phase 7 Integration Guide

**Version**: 1.0
**Status**: Complete
**Date**: 2025-10-15

---

## Table of Contents

1. [Overview](#overview)
2. [Component Integration](#component-integration)
3. [Workflow Integration](#workflow-integration)
4. [Database Integration](#database-integration)
5. [Migration from Phase 6](#migration-from-phase-6)
6. [Testing Integration](#testing-integration)
7. [External Systems](#external-systems)

---

## Overview

This guide explains how Phase 7 components integrate with each other and with existing OmniNode systems. Phase 7 introduces 8 new streams that enhance the code generation pipeline with intelligence, performance, and observability.

### Integration Philosophy

Phase 7 follows a **layered integration approach**:

1. **Foundation Layer (Stream 1)**: Database schema provides persistent storage
2. **Service Layer (Streams 2, 3, 6)**: Core services build on database foundation
3. **Intelligence Layer (Streams 4, 5)**: ML and pattern matching use services
4. **Observability Layer (Streams 7, 8)**: Monitoring and logging wrap everything

### Key Integration Points

```
┌────────────────────────────────────────────────────────┐
│                 Application Code                        │
│  (Your agents, workflows, code generation)             │
└─────────────────┬──────────────────────────────────────┘
                  │
         ┌────────┴────────┐
         │                 │
         ▼                 ▼
┌──────────────┐   ┌──────────────┐
│  Structured  │   │  Monitoring  │
│   Logging    │   │    System    │
│  (Stream 8)  │   │  (Stream 7)  │
└──────┬───────┘   └──────┬───────┘
       │                  │
       └────────┬─────────┘
                │
                ▼
┌─────────────────────────────────────┐
│    Core Services (Streams 2,3,6)    │
│  ┌─────────┐  ┌─────────┐  ┌─────┐ │
│  │Template │  │Parallel │  │Event│ │
│  │  Cache  │  │  Gen    │  │Proc │ │
│  └─────────┘  └─────────┘  └─────┘ │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Intelligence (Streams 4,5)         │
│  ┌──────────┐    ┌──────────┐       │
│  │  Mixin   │    │ Pattern  │       │
│  │ Learning │    │ Feedback │       │
│  └──────────┘    └──────────┘       │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│     Database (Stream 1)              │
│  PostgreSQL + Analytics Views        │
└─────────────────────────────────────┘
```

---

## Component Integration

### Stream 1: Database Integration

All Phase 7 components integrate with the database layer for persistence and analytics.

#### Integration Pattern

```python
from agents.lib.persistence import OmniNodePersistence
from uuid import uuid4

# Initialize persistence layer
persistence = OmniNodePersistence()

# All components use this for database operations
session_id = uuid4()
await persistence.insert_performance_metric(
    session_id=session_id,
    node_type="EFFECT",
    phase="generation",
    duration_ms=150.5,
    metadata={"cache_hit": True}
)
```

#### Database Connection Management

```python
# Shared connection pool (configured once)
from agents.lib.db import get_db_pool

pool = await get_db_pool()

# All components use the same pool
async with pool.acquire() as conn:
    result = await conn.fetchrow("SELECT * FROM ...")
```

#### Analytics Views Integration

```python
# Query analytics views for dashboards
from agents.lib.persistence import OmniNodePersistence

persistence = OmniNodePersistence()

# Get template cache efficiency
cache_efficiency = await persistence.get_template_cache_efficiency()

# Get performance metrics summary
performance_summary = await persistence.get_performance_metrics_summary(
    time_window_minutes=60
)

# Get mixin compatibility summary
mixin_summary = await persistence.get_mixin_compatibility_summary()
```

---

### Stream 2: Template Cache Integration

The template cache integrates with the template engine and code generation workflow.

#### Template Engine Integration

```python
from agents.lib.omninode_template_engine import OmniNodeTemplateEngine

# Create engine with caching enabled (default)
engine = OmniNodeTemplateEngine(enable_cache=True)

# Templates are automatically cached on first load
templates = engine.templates  # Dict of loaded templates

# Cache is transparent - no code changes needed
# The engine handles cache hits/misses automatically

# Get cache statistics
stats = engine.get_cache_stats()
print(f"Hit rate: {stats['hit_rate']:.1%}")
```

#### Workflow Integration

```python
from agents.lib.codegen_workflow import CodegenWorkflow

# Workflow automatically uses cached templates
workflow = CodegenWorkflow()

# Generate code (uses cache internally)
result = await workflow.generate_from_prd(
    prd_content=prd_text,
    output_directory="/output"
)

# Cache performance is automatically logged
# Check logs or monitoring for cache statistics
```

#### Cache Invalidation Integration

```python
# Invalidate cache when templates change
from agents.lib.omninode_template_engine import OmniNodeTemplateEngine

engine = OmniNodeTemplateEngine()

# Option 1: Invalidate specific template
engine.invalidate_cache("EFFECT_template")

# Option 2: Invalidate all templates
engine.invalidate_cache()

# Option 3: Content-based invalidation (automatic)
# Cache automatically detects file changes via SHA-256 hash
# No manual invalidation needed in most cases
```

---

### Stream 3: Parallel Generation Integration

Parallel generation integrates with the code generation workflow and template cache.

#### Workflow Integration

```python
from agents.lib.codegen_workflow import CodegenWorkflow
from agents.parallel_execution.agent_code_generator import ParallelCodeGenerator

# Create workflow with parallel generation enabled
workflow = CodegenWorkflow()
generator = ParallelCodeGenerator(max_workers=4)

# Generate multiple nodes in parallel
node_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]

# Parallel execution (automatic)
results = await generator.generate_parallel(
    prd_content=prd_text,
    node_types=node_types,
    output_directory="/output"
)

# Results contain all generated code + performance metrics
print(f"Throughput improvement: {results['speedup']:.1f}x")
```

#### Template Cache Sharing

```python
# Template cache is shared across parallel workers (thread-safe)
from agents.lib.template_cache import TemplateCache
from agents.lib.omninode_template_engine import OmniNodeTemplateEngine

# Create cache (once, shared by all workers)
cache = TemplateCache(max_templates=100, max_size_mb=50)

# Engine uses shared cache
engine = OmniNodeTemplateEngine(enable_cache=True)

# Parallel workers all benefit from shared cache
# No additional configuration needed
```

#### Performance Tracking Integration

```python
# Performance metrics are automatically tracked
from agents.lib.persistence import OmniNodePersistence

persistence = OmniNodePersistence()

# Query parallel generation performance
metrics = await persistence.get_performance_metrics_summary(
    time_window_minutes=60
)

# Filter by parallel execution
parallel_metrics = [m for m in metrics if m.get('parallel_execution')]
avg_speedup = sum(m['speedup'] for m in parallel_metrics) / len(parallel_metrics)
print(f"Average parallel speedup: {avg_speedup:.1f}x")
```

---

### Stream 4: Mixin Learning Integration

Mixin learning integrates with the mixin selection process in code generation.

#### Code Generation Integration

```python
from agents.lib.mixin_learning import MixinLearningModel
from agents.lib.codegen_workflow import CodegenWorkflow

# Initialize ML model
ml_model = MixinLearningModel()

# Predict mixin compatibility during generation
async def generate_with_ml(node_type: str, candidate_mixins: list[str]):
    # Get compatibility predictions
    predictions = await ml_model.predict_compatibility(
        node_type=node_type,
        mixin_combinations=candidate_mixins
    )

    # Sort by compatibility score (descending)
    sorted_mixins = sorted(
        predictions.items(),
        key=lambda x: x[1],
        reverse=True
    )

    # Use top-scoring mixins
    recommended_mixins = [m for m, score in sorted_mixins if score > 0.80]

    return recommended_mixins
```

#### Feedback Loop Integration

```python
# Update model with actual results
from agents.lib.persistence import OmniNodePersistence

persistence = OmniNodePersistence()

# After code generation, record success/failure
await persistence.update_mixin_compatibility(
    node_type="EFFECT",
    mixin_combination=["TimestampMixin", "ValidationMixin"],
    success=True,  # or False if generation failed
    conflict_patterns={}  # or {"error": "description"}
)

# Model automatically learns from feedback
# Future predictions improve with more data
```

#### Analytics Integration

```python
# Query mixin compatibility analytics
from agents.lib.persistence import OmniNodePersistence

persistence = OmniNodePersistence()

# Get compatibility summary
summary = await persistence.get_mixin_compatibility_summary()

# Analyze low-compatibility combinations
low_compat = [s for s in summary if s['compatibility_score'] < 0.70]
for combo in low_compat:
    print(f"{combo['node_type']}: {combo['mixin_combination']}")
    print(f"  Score: {combo['compatibility_score']:.2f}")
    print(f"  Failures: {combo['failure_count']}")
```

---

### Stream 5: Pattern Feedback Integration

Pattern feedback integrates with code validation and quality checks.

#### Quality Validation Integration

```python
from agents.lib.pattern_matcher import PatternMatcher
from agents.lib.quality_validator import QualityValidator

# Initialize pattern matcher
matcher = PatternMatcher()

# Use in quality validation
validator = QualityValidator()

async def validate_with_patterns(generated_code: str):
    # Detect patterns
    detected_patterns = matcher.detect_patterns(generated_code)

    # Check for anti-patterns
    issues = []
    for pattern in detected_patterns:
        if pattern.is_anti_pattern:
            issues.append({
                "pattern": pattern.name,
                "confidence": pattern.confidence,
                "location": pattern.location
            })

    # Record feedback
    await validator.validate_and_record_feedback(
        code=generated_code,
        patterns=detected_patterns,
        issues=issues
    )

    return issues
```

#### Feedback Collection Integration

```python
from agents.lib.persistence import OmniNodePersistence
from agents.lib.pattern_matcher import FeedbackType

persistence = OmniNodePersistence()

# Record pattern feedback
await persistence.record_pattern_feedback(
    pattern_name="unused_import",
    feedback_type=FeedbackType.TRUE_POSITIVE,
    confidence_score=0.92,
    user_weight=1.0,  # User feedback
    is_correct=True,
    metadata={"file": "node_effect.py", "line": 15}
)

# Or automated feedback
await persistence.record_pattern_feedback(
    pattern_name="missing_docstring",
    feedback_type=FeedbackType.FALSE_POSITIVE,
    confidence_score=0.75,
    user_weight=0.5,  # Automated feedback (lower weight)
    is_correct=False,
    metadata={"reason": "docstring present but not detected"}
)
```

#### Analytics Integration

```python
# Query pattern feedback analytics
from agents.lib.persistence import OmniNodePersistence

persistence = OmniNodePersistence()

# Get pattern analysis
analysis = await persistence.get_pattern_feedback_analysis()

# Find patterns with low precision
low_precision = [p for p in analysis if p['precision'] < 0.85]
for pattern in low_precision:
    print(f"{pattern['pattern_name']}:")
    print(f"  Precision: {pattern['precision']:.2f}")
    print(f"  False positives: {pattern['false_positive_count']}")
```

---

### Stream 6: Event Processing Integration

Event processing integrates with the event system for optimized batch processing.

#### Event System Integration

```python
from agents.lib.event_processor import EventProcessor
from agents.lib.events import ModelEvent

# Initialize event processor
processor = EventProcessor(batch_size=10, batch_timeout_ms=100)

# Process events in batches
async def process_events(events: list[ModelEvent]):
    # Events are automatically batched
    for event in events:
        await processor.process_event(event)

    # Batch metrics automatically recorded
    metrics = processor.get_metrics()
    print(f"Batch size: {metrics['batch_size']}")
    print(f"Processing time: {metrics['processing_duration_ms']}ms")
```

#### Performance Tracking Integration

```python
from agents.lib.persistence import OmniNodePersistence

persistence = OmniNodePersistence()

# Record event processing metrics
await persistence.insert_event_processing_metric(
    event_type="code_generated",
    processing_duration_ms=45,
    queue_wait_time_ms=10,
    success=True,
    retry_count=0,
    batch_size=10,
    metadata={"node_type": "EFFECT"}
)

# Query event processing health
health = await persistence.get_event_processing_health()
print(f"P95 latency: {health['p95_latency_ms']}ms")
print(f"Success rate: {health['success_rate']:.1%}")
```

---

### Stream 7: Monitoring Integration

Monitoring integrates with all Phase 7 components for comprehensive observability.

#### Component Metrics Integration

```python
from agents.lib.monitoring import record_metric, MetricType

# Record metrics from any component
async def my_operation():
    start_time = time.time()

    # Perform operation
    result = await perform_work()

    # Record metric
    duration_ms = (time.time() - start_time) * 1000
    await record_metric(
        name="my_operation_duration_ms",
        value=duration_ms,
        metric_type=MetricType.GAUGE,
        labels={"component": "my_component"},
        help_text="Duration of my operation in milliseconds"
    )

    return result
```

#### Alert Integration

```python
from agents.lib.alert_manager import get_alert_manager, AlertRule, AlertSeverity

# Add custom alert rules
manager = get_alert_manager()

rule = AlertRule(
    name="high_error_rate",
    metric_name="error_rate",
    threshold=0.10,  # 10% error rate
    severity=AlertSeverity.CRITICAL,
    comparison="greater_than",
    duration_seconds=300
)

manager.add_rule(rule)

# Alerts are automatically generated when thresholds exceeded
# Check active alerts
active = manager.get_active_alerts()
for alert in active:
    print(f"[{alert.severity.value}] {alert.message}")
```

#### Health Check Integration

```python
from agents.lib.health_checker import check_system_health, get_overall_health_status

# Check system health
health_results = await check_system_health()

for component, result in health_results.items():
    print(f"{component}: {result.status.value}")
    if result.status != HealthStatus.HEALTHY:
        print(f"  Issue: {result.message}")

# Get overall status
overall = get_overall_health_status()
if overall != HealthStatus.HEALTHY:
    print(f"System health: {overall.value}")
```

#### Dashboard Integration

```python
from agents.lib.monitoring import collect_all_metrics

# Collect metrics for dashboard
metrics = await collect_all_metrics(time_window_minutes=60)

# Metrics organized by component
template_cache_metrics = metrics.get('template_cache', {})
parallel_gen_metrics = metrics.get('parallel_generation', {})
mixin_learning_metrics = metrics.get('mixin_learning', {})

# Display in dashboard
dashboard_data = {
    "cache_hit_rate": template_cache_metrics.get('overall_hit_rate', 0),
    "parallel_speedup": parallel_gen_metrics.get('avg_speedup', 0),
    "mixin_accuracy": mixin_learning_metrics.get('accuracy', 0)
}
```

---

### Stream 8: Structured Logging Integration

Structured logging integrates with all components for correlation tracking.

#### Logger Setup Integration

```python
from agents.lib.structured_logger import get_logger
from agents.lib.log_context import async_log_context
from uuid import uuid4

# Get logger for your component
logger = get_logger(__name__, component="my-agent")

# Use in async functions with correlation ID
async def my_workflow(task_id: str):
    correlation_id = uuid4()

    async with async_log_context(correlation_id=correlation_id):
        logger.info("Workflow started", metadata={"task_id": task_id})

        # All logs automatically include correlation_id
        result = await perform_work()

        logger.info("Workflow completed", metadata={"result": result})

    return result
```

#### Decorator Integration

```python
from agents.lib.log_context import with_log_context
from uuid import uuid4

# Use decorator for automatic context management
@with_log_context(component="agent-researcher")
async def research_task(correlation_id: uuid4(), query: str):
    logger.info("Research started", metadata={"query": query})

    # Correlation ID automatically propagated
    results = await search(query)

    logger.info("Research completed", metadata={"result_count": len(results)})

    return results
```

#### Cross-Component Tracing

```python
# Pass correlation_id across component boundaries
from uuid import UUID

async def main_workflow(correlation_id: UUID):
    # Component A
    async with async_log_context(correlation_id=correlation_id):
        logger.info("Main workflow started")
        result_a = await component_a()

    # Component B (same correlation_id)
    async with async_log_context(correlation_id=correlation_id):
        logger.info("Calling component B")
        result_b = await component_b(result_a)

    # All logs have same correlation_id
    # Query logs: grep <correlation_id> *.log
```

#### Monitoring Integration

```python
# Structured logs feed into monitoring system
from agents.lib.structured_logger import get_logger
from agents.lib.monitoring import record_metric, MetricType

logger = get_logger(__name__)

async def operation():
    start = time.time()

    try:
        result = await perform_work()
        duration_ms = (time.time() - start) * 1000

        # Log with structured metadata
        logger.info("Operation succeeded", metadata={
            "duration_ms": duration_ms,
            "result": result
        })

        # Also record metric
        await record_metric("operation_duration_ms", duration_ms, MetricType.GAUGE)

        return result

    except Exception as e:
        logger.error("Operation failed", metadata={"error": str(e)})
        await record_metric("operation_errors_total", 1, MetricType.COUNTER)
        raise
```

---

## Workflow Integration

### Complete Code Generation Workflow

This example shows how all Phase 7 components integrate in a complete workflow:

```python
from uuid import uuid4
from agents.lib.codegen_workflow import CodegenWorkflow
from agents.lib.structured_logger import get_logger
from agents.lib.log_context import async_log_context
from agents.lib.monitoring import record_metric, MetricType
from agents.lib.persistence import OmniNodePersistence

logger = get_logger(__name__, component="codegen-workflow")
persistence = OmniNodePersistence()

async def complete_workflow(prd_content: str, output_dir: str):
    """
    Complete code generation workflow with all Phase 7 integrations.
    """
    # Create correlation ID for tracing
    correlation_id = uuid4()
    session_id = uuid4()

    async with async_log_context(correlation_id=correlation_id):
        logger.info("Workflow started", metadata={
            "session_id": str(session_id),
            "output_dir": output_dir
        })

        start_time = time.time()

        try:
            # Step 1: Initialize workflow
            workflow = CodegenWorkflow()

            # Step 2: Mixin learning predictions
            logger.info("Getting mixin recommendations")
            recommended_mixins = await workflow.get_mixin_recommendations(
                node_types=["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]
            )

            # Step 3: Parallel code generation (uses template cache)
            logger.info("Generating code in parallel")
            generation_result = await workflow.generate_from_prd(
                prd_content=prd_content,
                output_directory=output_dir,
                enable_parallel=True,
                max_workers=4
            )

            # Step 4: Pattern validation
            logger.info("Validating generated code")
            validation_result = await workflow.validate_patterns(
                generated_code=generation_result['code']
            )

            # Step 5: Record performance metrics
            duration_ms = (time.time() - start_time) * 1000

            await persistence.insert_performance_metric(
                session_id=session_id,
                node_type="workflow",
                phase="complete",
                duration_ms=duration_ms,
                metadata={
                    "parallel_speedup": generation_result.get('speedup', 1.0),
                    "cache_hit_rate": generation_result.get('cache_hit_rate', 0.0),
                    "validation_issues": len(validation_result.get('issues', []))
                }
            )

            # Step 6: Record monitoring metrics
            await record_metric(
                name="workflow_duration_ms",
                value=duration_ms,
                metric_type=MetricType.GAUGE,
                labels={"workflow": "codegen_complete"}
            )

            # Step 7: Update mixin learning model
            for node_type, mixins in generation_result.get('used_mixins', {}).items():
                await persistence.update_mixin_compatibility(
                    node_type=node_type,
                    mixin_combination=mixins,
                    success=True,
                    conflict_patterns={}
                )

            logger.info("Workflow completed successfully", metadata={
                "duration_ms": duration_ms,
                "files_generated": len(generation_result.get('files', []))
            })

            return {
                "success": True,
                "session_id": session_id,
                "correlation_id": correlation_id,
                "duration_ms": duration_ms,
                "result": generation_result
            }

        except Exception as e:
            logger.error("Workflow failed", metadata={"error": str(e)})

            # Record failure metric
            await record_metric(
                name="workflow_errors_total",
                value=1,
                metric_type=MetricType.COUNTER,
                labels={"workflow": "codegen_complete", "error": type(e).__name__}
            )

            raise

# Usage
result = await complete_workflow(
    prd_content=open("prd.md").read(),
    output_dir="/output/generated"
)

print(f"Workflow completed in {result['duration_ms']:.0f}ms")
print(f"Correlation ID: {result['correlation_id']}")
```

---

## Database Integration

### Connection Pool Management

```python
# Initialize once at application startup
from agents.lib.db import initialize_db_pool, get_db_pool, close_db_pool

# Startup
await initialize_db_pool(
    dsn="postgresql://user:pass@localhost:5432/dbname",
    min_size=10,
    max_size=20
)

# Use throughout application
pool = await get_db_pool()
async with pool.acquire() as conn:
    result = await conn.fetchrow("SELECT * FROM ...")

# Shutdown
await close_db_pool()
```

### Transaction Management

```python
from agents.lib.persistence import OmniNodePersistence

persistence = OmniNodePersistence()

# Atomic operations
async def atomic_update():
    async with persistence.transaction():
        # All operations in transaction
        await persistence.insert_performance_metric(...)
        await persistence.update_mixin_compatibility(...)
        # Committed together or rolled back on error
```

### Migration Management

```bash
# Apply new migrations
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/007_new_feature.sql

# Verify migration
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -c "SELECT version, description FROM schema_migrations ORDER BY version DESC LIMIT 1;"
```

---

## Migration from Phase 6

### Step-by-Step Migration

#### 1. Database Migration

```bash
# Backup existing database
pg_dump -h localhost -p 5432 -U postgres omninode_bridge \
  -f backup_before_phase7.sql

# Apply Phase 7 migration
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/006_phase7_schema_enhancements.sql

# Verify migration
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -c "SELECT COUNT(*) FROM mixin_compatibility_matrix;"
```

#### 2. Code Updates

**Before (Phase 6)**:
```python
from agents.lib.codegen_workflow import CodegenWorkflow

# Sequential generation
workflow = CodegenWorkflow()
result = await workflow.generate_from_prd(prd_content, output_dir)
```

**After (Phase 7)**:
```python
from agents.lib.codegen_workflow import CodegenWorkflow
from agents.lib.structured_logger import get_logger
from agents.lib.log_context import async_log_context
from uuid import uuid4

logger = get_logger(__name__, component="codegen")

# Parallel generation with logging and monitoring
workflow = CodegenWorkflow()

correlation_id = uuid4()
async with async_log_context(correlation_id=correlation_id):
    logger.info("Starting code generation")

    result = await workflow.generate_from_prd(
        prd_content=prd_content,
        output_directory=output_dir,
        enable_parallel=True,  # NEW: Parallel execution
        max_workers=4
    )

    logger.info("Code generation completed", metadata={
        "speedup": result.get('speedup', 1.0),
        "cache_hit_rate": result.get('cache_hit_rate', 0.0)
    })
```

#### 3. Configuration Updates

**Add to configuration file**:
```yaml
# config.yaml
phase_7:
  template_cache:
    enabled: true
    max_templates: 100
    max_size_mb: 50
    ttl_seconds: 3600

  parallel_generation:
    enabled: true
    max_workers: 4

  monitoring:
    enabled: true
    alert_webhook_url: ${WEBHOOK_URL}

  logging:
    format: json
    level: INFO
```

#### 4. Monitoring Setup

```python
# Add monitoring initialization
from agents.lib.monitoring import initialize_monitoring_system
from agents.lib.alert_manager import load_alert_config

# At application startup
await initialize_monitoring_system()
load_alert_config('agents/configs/alert_config.yaml')
```

#### 5. Testing Migration

```bash
# Run all Phase 7 tests
python -m pytest agents/tests/test_phase7_schema.py -v
python -m pytest agents/tests/test_template_cache.py -v
python -m pytest agents/tests/test_monitoring.py -v
python -m pytest agents/tests/test_structured_logging.py -v

# Expected: 125+ tests passing (26 + 22 + 30 + 27 + ...)
```

### Gradual Migration Strategy

**Phase 1: Database Only** (Low Risk)
- Apply database migration
- No code changes required
- Tables are ready but not used yet

**Phase 2: Monitoring & Logging** (Medium Risk)
- Add structured logging to existing code
- Enable monitoring without alerts
- Observe metrics, no behavioral changes

**Phase 3: Template Caching** (Low Risk)
- Enable template caching (transparent)
- Monitor cache hit rate
- Fallback to uncached if issues

**Phase 4: Parallel Generation** (Medium Risk)
- Enable parallel generation for non-critical workflows
- Monitor performance improvement
- Rollback if issues detected

**Phase 5: ML & Pattern Matching** (Low Risk)
- Enable mixin learning (advisory only)
- Enable pattern feedback (warnings only)
- Don't block on low scores yet

**Phase 6: Full Integration** (High Confidence)
- All Phase 7 features enabled
- Alerts enabled
- ML recommendations enforced

---

## Testing Integration

### Integration Test Example

```python
import pytest
from uuid import uuid4
from agents.lib.codegen_workflow import CodegenWorkflow
from agents.lib.persistence import OmniNodePersistence
from agents.lib.monitoring import get_monitoring_system, collect_all_metrics

@pytest.mark.asyncio
async def test_complete_integration():
    """Test complete Phase 7 integration."""
    # Setup
    workflow = CodegenWorkflow()
    persistence = OmniNodePersistence()
    monitoring = get_monitoring_system()
    session_id = uuid4()

    # Execute workflow
    result = await workflow.generate_from_prd(
        prd_content="Sample PRD content",
        output_directory="/tmp/test_output",
        enable_parallel=True
    )

    # Verify template cache was used
    cache_stats = workflow.template_engine.get_cache_stats()
    assert cache_stats['hit_rate'] > 0.80, "Cache hit rate should be >80%"

    # Verify parallel generation worked
    assert result.get('speedup', 1.0) > 2.0, "Parallel speedup should be >2x"

    # Verify metrics were recorded
    metrics = await collect_all_metrics(time_window_minutes=1)
    assert len(metrics) > 0, "Metrics should be collected"

    # Verify database persistence
    perf_summary = await persistence.get_performance_metrics_summary(
        time_window_minutes=1
    )
    assert len(perf_summary) > 0, "Performance metrics should be persisted"

    # Verify monitoring health
    from agents.lib.health_checker import check_system_health
    health = await check_system_health()
    assert all(h.status == "HEALTHY" for h in health.values()), "All components should be healthy"
```

### Component-Specific Tests

```python
# Test template cache integration
@pytest.mark.asyncio
async def test_template_cache_integration():
    from agents.lib.omninode_template_engine import OmniNodeTemplateEngine

    engine = OmniNodeTemplateEngine(enable_cache=True)

    # First load (cache miss)
    templates1 = engine.templates
    stats1 = engine.get_cache_stats()
    assert stats1['misses'] > 0

    # Second load (cache hit)
    engine._load_templates()
    stats2 = engine.get_cache_stats()
    assert stats2['hits'] > stats1['hits']

# Test monitoring integration
@pytest.mark.asyncio
async def test_monitoring_integration():
    from agents.lib.monitoring import record_metric, MetricType, collect_all_metrics

    # Record metric
    await record_metric("test_metric", 100.0, MetricType.GAUGE)

    # Verify collection
    metrics = await collect_all_metrics(time_window_minutes=1)
    assert any(m['name'] == 'test_metric' for m in metrics.get('custom', []))

# Test logging integration
@pytest.mark.asyncio
async def test_logging_integration():
    from agents.lib.structured_logger import get_logger
    from agents.lib.log_context import async_log_context
    from uuid import uuid4

    logger = get_logger(__name__)
    correlation_id = uuid4()

    async with async_log_context(correlation_id=correlation_id):
        logger.info("Test message", metadata={"test": True})

    # Verify log file contains correlation_id
    # (In actual test, read log file and verify)
```

---

## External Systems

### ELK Stack Integration

```yaml
# Logstash configuration
input {
  file {
    path => "/var/log/omniclaude/agents/*.log"
    codec => "json"
  }
}

filter {
  # Logs are already JSON, no parsing needed
  # Add custom fields if needed
  mutate {
    add_field => { "environment" => "production" }
  }
}

output {
  elasticsearch {
    hosts => ["localhost:9200"]
    index => "omniclaude-agents-%{+YYYY.MM.dd}"
  }
}
```

**Query logs by correlation_id**:
```bash
# Elasticsearch query
curl -X GET "localhost:9200/omniclaude-agents-*/_search" -H 'Content-Type: application/json' -d'
{
  "query": {
    "term": {
      "correlation_id": "a1a999e1-8766-4d4d-8525-e858ea6ab5d6"
    }
  }
}
'
```

### Prometheus Integration

```python
# Export Prometheus metrics
from agents.scripts.monitoring_dashboard import generate_dashboard

# Generate Prometheus format
prometheus_metrics = generate_dashboard(format="prometheus")

# Serve via HTTP endpoint (Flask example)
from flask import Flask, Response

app = Flask(__name__)

@app.route('/metrics')
def metrics():
    return Response(prometheus_metrics, mimetype='text/plain')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
```

**Prometheus scrape config**:
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'omniclaude-agents'
    static_configs:
      - targets: ['localhost:8080']
    scrape_interval: 15s
```

### Grafana Dashboards

```json
{
  "dashboard": {
    "title": "OmniClaude Phase 7 Metrics",
    "panels": [
      {
        "title": "Template Cache Hit Rate",
        "targets": [
          {
            "expr": "cache_hit_rate{component=\"template_cache\"}"
          }
        ]
      },
      {
        "title": "Parallel Generation Speedup",
        "targets": [
          {
            "expr": "parallel_speedup{component=\"parallel_generation\"}"
          }
        ]
      },
      {
        "title": "Mixin Learning Accuracy",
        "targets": [
          {
            "expr": "mixin_accuracy{component=\"mixin_learning\"}"
          }
        ]
      }
    ]
  }
}
```

### Webhook Integration

```python
# Configure webhook for alerts
# In alert_config.yaml:
channels:
  - name: slack_webhook
    type: webhook
    enabled: true
    config:
      url: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
      method: "POST"
      headers:
        Content-Type: "application/json"

# Alerts automatically sent to webhook
# Payload format:
# {
#   "alert_name": "cache_hit_rate_low",
#   "severity": "warning",
#   "message": "Cache hit rate below 70%",
#   "timestamp": "2025-10-15T21:00:00Z",
#   "metadata": {...}
# }
```

---

## See Also

- [API Reference](./API_REFERENCE.md) - Complete API documentation
- [User Guide](./USER_GUIDE.md) - Usage examples and best practices
- [Architecture](./ARCHITECTURE.md) - System architecture and design
- [Operations Guide](./OPERATIONS_GUIDE.md) - Deployment and operations
- [Summary](./SUMMARY.md) - Executive summary

---

**Document Version**: 1.0
**Last Updated**: 2025-10-15
**Status**: Complete
