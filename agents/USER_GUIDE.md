# User Guide

**Version**: 1.0
**Last Updated**: 2025-10-15
**Target Audience**: Developers, DevOps Engineers, System Administrators

This guide provides comprehensive instructions for using agent framework features including template caching, parallel generation, mixin learning, pattern feedback, event optimization, monitoring, and structured logging.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Quick Start Examples](#quick-start-examples)
3. [Stream 2: Template Caching](#stream-2-template-caching)
4. [Stream 3: Parallel Generation](#stream-3-parallel-generation)
5. [Stream 4: Mixin Learning](#stream-4-mixin-learning)
6. [Stream 5: Pattern Feedback](#stream-5-pattern-feedback)
7. [Stream 6: Event Optimization](#stream-6-event-optimization)
8. [Stream 7: Monitoring](#stream-7-monitoring)
9. [Stream 8: Structured Logging](#stream-8-structured-logging)
10. [Best Practices](#best-practices)
11. [Common Patterns](#common-patterns)
12. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Prerequisites

- **Python**: 3.10 or higher
- **PostgreSQL**: 13 or higher (for metrics persistence)
- **Kafka**: 2.8 or higher (optional, for event processing)
- **Dependencies**: Install via `poetry install`

### Installation

1. **Install dependencies**:
```bash
cd ${PROJECT_ROOT}
poetry install
```

2. **Apply database migrations**:
```bash
poetry run python -m agents.lib.migrations apply
```

3. **Verify installation**:
```bash
poetry run python -c "from agents.lib.template_cache import TemplateCache; print('✅ Agent framework installed')"
```

### Environment Setup

Create a `.env` file in the `agents/` directory:

```bash
# Database configuration
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DATABASE=omniclaude
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password

# Kafka configuration (optional)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# Monitoring configuration
ENABLE_METRICS=true
PROMETHEUS_PORT=9090

# Logging configuration
LOG_LEVEL=INFO
LOG_DIR=/var/log/agents
```

---

## Quick Start Examples

### Example 1: Basic Code Generation with Caching

```python
from pathlib import Path
from uuid import uuid4
from agents.lib.template_cache import TemplateCache
from agents.lib.structured_logger import get_logger

# Initialize logger
logger = get_logger(__name__, component="codegen-basic")
logger.set_correlation_id(uuid4())

# Initialize template cache
cache = TemplateCache(max_templates=50, ttl_seconds=1800)

# Warmup cache with common templates
cache.warmup(
    templates_dir=Path("/path/to/templates"),
    template_types=["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]
)

# Load template (will use cache on subsequent calls)
content, hit = cache.get(
    template_name="NodeDatabaseEffect",
    template_type="EFFECT",
    file_path=Path("/path/to/effect_template.py"),
    loader_func=lambda p: p.read_text()
)

logger.info("Template loaded", metadata={
    "cache_hit": hit,
    "content_size": len(content)
})

# Check cache statistics
stats = cache.get_stats()
print(f"Cache hit rate: {stats['hit_rate']:.1%}")
print(f"Time saved: {stats['time_saved_ms']:.0f}ms")
```

### Example 2: Parallel Node Generation

```python
from uuid import uuid4
from agents.lib.parallel_generator import ParallelGenerator, GenerationJob
from agents.lib.structured_logger import get_logger

logger = get_logger(__name__, component="codegen-parallel")
correlation_id = uuid4()
logger.set_correlation_id(correlation_id)

# Initialize parallel generator
generator = ParallelGenerator(max_workers=3, timeout_seconds=120)

# Create generation jobs
jobs = [
    GenerationJob(
        job_id=uuid4(),
        node_type="EFFECT",
        microservice_name="UserService",
        domain="authentication",
        analysis_result=prd_analysis,
        output_directory="/output/user_service"
    ),
    GenerationJob(
        job_id=uuid4(),
        node_type="COMPUTE",
        microservice_name="UserService",
        domain="validation",
        analysis_result=prd_analysis,
        output_directory="/output/user_service"
    ),
    GenerationJob(
        job_id=uuid4(),
        node_type="REDUCER",
        microservice_name="UserService",
        domain="persistence",
        analysis_result=prd_analysis,
        output_directory="/output/user_service"
    )
]

# Generate nodes in parallel
try:
    results = await generator.generate_nodes_parallel(
        jobs=jobs,
        session_id=correlation_id
    )

    # Process results
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    logger.info("Parallel generation complete", metadata={
        "total": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "avg_duration_ms": sum(r.duration_ms for r in results) / len(results)
    })

finally:
    # Always cleanup
    await generator.cleanup()
```

### Example 3: ML-Powered Mixin Recommendations

```python
from agents.lib.mixin_learner import MixinLearner
from agents.lib.structured_logger import get_logger

logger = get_logger(__name__, component="mixin-learning")

# Initialize mixin learner
learner = MixinLearner(auto_train=True)

# Wait for model training if needed
if not learner.is_trained():
    logger.info("Training mixin compatibility model...")
    metrics = await learner.train_model(min_samples=100)
    logger.info("Model trained", metadata={
        "accuracy": metrics.accuracy,
        "precision": metrics.precision,
        "training_samples": metrics.training_samples
    })

# Get mixin recommendations
recommendations = learner.recommend_mixins(
    node_type="EFFECT",
    required_capabilities=["caching", "logging", "metrics"],
    existing_mixins=["MixinHealthCheck"],
    max_recommendations=5
)

print("Recommended mixins:")
for mixin, confidence, explanation in recommendations:
    print(f"  {mixin}: {confidence:.1%}")
    print(f"    {explanation}")

# Predict compatibility for specific pair
prediction = learner.predict_compatibility(
    mixin_a="MixinCaching",
    mixin_b="MixinRetry",
    node_type="EFFECT"
)

if prediction.compatible:
    print(f"\n✅ {prediction.mixin_a} + {prediction.mixin_b} are compatible")
    print(f"   Confidence: {prediction.confidence:.1%}")
    print(f"   {prediction.explanation}")
else:
    print(f"\n❌ {prediction.mixin_a} + {prediction.mixin_b} are incompatible")
    print(f"   Confidence: {prediction.confidence:.1%}")
```

---

## Stream 2: Template Caching

### Basic Usage

The template cache reduces template load times by 50% (from 100ms to 50ms) with intelligent LRU eviction and content-based invalidation.

#### Initializing the Cache

```python
from agents.lib.template_cache import TemplateCache

# Create cache with custom configuration
cache = TemplateCache(
    max_templates=100,      # Maximum templates to cache
    max_size_mb=50,         # Maximum memory usage (MB)
    ttl_seconds=3600,       # Time-to-live (1 hour)
    enable_persistence=True # Track metrics in database
)
```

#### Loading Templates

```python
from pathlib import Path

# First load (cache miss)
content, hit = cache.get(
    template_name="NodeAPIEffect",
    template_type="EFFECT",
    file_path=Path("/templates/effect_template.py"),
    loader_func=lambda p: p.read_text()
)
print(f"First load - Cache hit: {hit}")  # False

# Second load (cache hit)
content, hit = cache.get(
    template_name="NodeAPIEffect",
    template_type="EFFECT",
    file_path=Path("/templates/effect_template.py"),
    loader_func=lambda p: p.read_text()
)
print(f"Second load - Cache hit: {hit}")  # True
```

#### Cache Warmup

Preload frequently used templates on startup:

```python
cache.warmup(
    templates_dir=Path("/templates"),
    template_types=["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]
)
print("Cache warmed up with common templates")
```

#### Monitoring Cache Performance

```python
# Get basic stats
stats = cache.get_stats()
print(f"Hit rate: {stats['hit_rate']:.1%}")
print(f"Cached templates: {stats['cached_templates']}")
print(f"Time saved: {stats['time_saved_ms']:.0f}ms")
print(f"Performance improvement: {stats['improvement_percent']:.1f}%")

# Get detailed stats with per-template breakdown
detailed = cache.get_detailed_stats()
print("\nMost accessed templates:")
for template in detailed['templates'][:5]:
    print(f"  {template['name']}: {template['access_count']} accesses")
```

#### Cache Invalidation

```python
# Invalidate specific template (e.g., after file modification)
cache.invalidate("NodeAPIEffect")

# Invalidate all templates (e.g., during deployment)
cache.invalidate_all()
```

### Advanced Usage

#### Content-Based Invalidation

The cache automatically detects file changes using SHA-256 hashing:

```python
# Template file is modified externally
# Next access automatically invalidates and reloads:
content, hit = cache.get(
    template_name="NodeAPIEffect",
    template_type="EFFECT",
    file_path=Path("/templates/effect_template.py"),
    loader_func=lambda p: p.read_text()
)
# hit will be False if file was modified
```

#### Custom Loader Functions

```python
def load_with_preprocessing(file_path: Path) -> str:
    """Custom loader with preprocessing"""
    raw_content = file_path.read_text()
    # Add custom preprocessing
    processed = raw_content.replace("{{timestamp}}", str(datetime.now()))
    return processed

content, hit = cache.get(
    template_name="ProcessedTemplate",
    template_type="EFFECT",
    file_path=Path("/templates/template.py"),
    loader_func=load_with_preprocessing
)
```

### Best Practices

1. **Warmup on startup**: Preload common templates to achieve high hit rates immediately
2. **Monitor hit rates**: Target ≥80% hit rate; adjust `max_templates` if lower
3. **Set appropriate TTL**: Balance freshness vs. performance (default 1 hour is good for most cases)
4. **Use content-based invalidation**: Don't manually invalidate unless necessary
5. **Enable persistence**: Track metrics to identify optimization opportunities

---

## Stream 3: Parallel Generation

### Basic Usage

Parallel generation provides 2.5-3.3x throughput improvement for multi-node code generation using thread pools.

#### Simple Parallel Generation

```python
from uuid import uuid4
from agents.lib.parallel_generator import ParallelGenerator, GenerationJob

# Initialize generator
generator = ParallelGenerator(
    max_workers=3,          # Concurrent workers
    timeout_seconds=120,    # Per-job timeout
    enable_metrics=True     # Track performance
)

# Create jobs
jobs = [
    GenerationJob(
        job_id=uuid4(),
        node_type=node_type,
        microservice_name="UserService",
        domain=domain,
        analysis_result=prd_analysis,
        output_directory="/output"
    )
    for node_type, domain in [
        ("EFFECT", "authentication"),
        ("COMPUTE", "validation"),
        ("REDUCER", "persistence")
    ]
]

# Execute in parallel
results = await generator.generate_nodes_parallel(
    jobs=jobs,
    session_id=uuid4()
)

# Process results
for result in results:
    if result.success:
        print(f"✅ {result.node_type} generated in {result.duration_ms:.0f}ms")
    else:
        print(f"❌ {result.node_type} failed: {result.error}")
```

#### Progress Tracking

```python
# In a separate async task or timer
while generator._completed_jobs < generator._total_jobs:
    progress = generator.get_progress()
    print(f"Progress: {progress['progress_percent']:.1f}% "
          f"({progress['completed_jobs']}/{progress['total_jobs']})")
    await asyncio.sleep(1)
```

#### Error Handling

```python
from omnibase_core.errors import OnexError

try:
    results = await generator.generate_nodes_parallel(jobs, session_id)

    # Check for partial failures
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    if failed:
        print(f"Warning: {len(failed)} jobs failed:")
        for result in failed:
            print(f"  - {result.node_type}: {result.error}")

except OnexError as e:
    # All jobs failed
    print(f"Complete failure: {e.message}")
    print(f"Details: {e.details}")
```

### Advanced Usage

#### Custom Worker Count

Optimize worker count based on your system:

```python
import os

# Use CPU count for I/O-bound operations
cpu_count = os.cpu_count() or 1
optimal_workers = min(cpu_count, 4)  # Cap at 4 for I/O operations

generator = ParallelGenerator(max_workers=optimal_workers)
```

#### Timeout Configuration

Different node types may need different timeouts:

```python
# For complex nodes, increase timeout
generator = ParallelGenerator(timeout_seconds=300)  # 5 minutes
```

#### Resource Cleanup

Always cleanup resources properly:

```python
generator = ParallelGenerator()
try:
    results = await generator.generate_nodes_parallel(jobs, session_id)
finally:
    await generator.cleanup()  # Shutdown thread pool, close connections
```

### Best Practices

1. **Optimal worker count**: Use 3-4 workers for I/O-bound operations
2. **Timeout appropriately**: Set timeout based on slowest expected node generation
3. **Handle partial failures**: Process successful results even if some jobs fail
4. **Monitor progress**: For long-running batches, implement progress tracking
5. **Always cleanup**: Use try/finally or context managers to ensure cleanup

---

## Stream 4: Mixin Learning

### Basic Usage

ML-powered mixin compatibility prediction with ≥95% accuracy using Random Forest classifier.

#### Training the Model

```python
from agents.lib.mixin_learner import MixinLearner

# Initialize learner
learner = MixinLearner(auto_train=False)

# Train model with historical data
metrics = await learner.train_model(
    min_samples=50,         # Minimum samples required
    test_size=0.2,          # 20% for testing
    cross_val_folds=5       # 5-fold cross-validation
)

print(f"Model Performance:")
print(f"  Accuracy: {metrics.accuracy:.1%}")
print(f"  Precision: {metrics.precision:.1%}")
print(f"  Recall: {metrics.recall:.1%}")
print(f"  F1 Score: {metrics.f1_score:.1%}")
print(f"  Training samples: {metrics.training_samples}")
print(f"  Cross-validation: {sum(metrics.cross_val_scores)/len(metrics.cross_val_scores):.1%}")
```

#### Predicting Compatibility

```python
# Check if two mixins are compatible
prediction = learner.predict_compatibility(
    mixin_a="MixinCaching",
    mixin_b="MixinLogging",
    node_type="EFFECT"
)

print(f"Mixins: {prediction.mixin_a} + {prediction.mixin_b}")
print(f"Compatible: {prediction.compatible}")
print(f"Confidence: {prediction.confidence:.1%}")
print(f"Explanation: {prediction.explanation}")
print(f"Learned from {prediction.learned_from_samples} samples")
```

#### Getting Mixin Recommendations

```python
# Get recommendations for a node
recommendations = learner.recommend_mixins(
    node_type="EFFECT",
    required_capabilities=["caching", "logging", "health_check"],
    existing_mixins=["MixinMetrics"],
    max_recommendations=5
)

print("Recommended mixins:")
for mixin, confidence, explanation in recommendations:
    print(f"\n  {mixin}")
    print(f"    Confidence: {confidence:.1%}")
    print(f"    {explanation}")
```

#### Continuous Learning

```python
# Update model with new feedback
await learner.update_from_feedback(
    mixin_a="MixinCaching",
    mixin_b="MixinCircuitBreaker",
    node_type="EFFECT",
    success=True,
    retrain_threshold=100  # Retrain after 100 new samples
)
```

### Advanced Usage

#### Custom Model Path

```python
from pathlib import Path

learner = MixinLearner(
    model_path=Path("/custom/path/mixin_model.pkl"),
    auto_train=True,
    min_confidence_threshold=0.75
)
```

#### Model Persistence

```python
# Model is automatically saved after training
metrics = await learner.train_model()

# Model is automatically loaded on next initialization
learner2 = MixinLearner()  # Loads existing model
assert learner2.is_trained()
```

#### Batch Predictions

```python
# Predict multiple combinations
mixin_pairs = [
    ("MixinCaching", "MixinLogging"),
    ("MixinRetry", "MixinCircuitBreaker"),
    ("MixinTimeout", "MixinValidation")
]

for mixin_a, mixin_b in mixin_pairs:
    prediction = learner.predict_compatibility(
        mixin_a=mixin_a,
        mixin_b=mixin_b,
        node_type="EFFECT"
    )
    print(f"{mixin_a} + {mixin_b}: {prediction.confidence:.1%}")
```

### Best Practices

1. **Train with sufficient data**: Minimum 50 samples, 100+ recommended
2. **Monitor accuracy**: Retrain if accuracy drops below 90%
3. **Use continuous learning**: Update model with production feedback
4. **Set confidence thresholds**: Only accept predictions with ≥70% confidence
5. **Validate recommendations**: Review ML recommendations before applying

---

## Stream 5: Pattern Feedback

### Basic Usage

Pattern feedback system for continuous learning achieving ≥90% precision.

#### Recording Feedback

```python
from uuid import uuid4
from agents.lib.pattern_feedback import PatternFeedbackCollector, PatternFeedback

collector = PatternFeedbackCollector()

# Record pattern matching feedback
feedback = PatternFeedback(
    session_id=uuid4(),
    detected_pattern="authentication_pattern",
    detected_confidence=0.85,
    actual_pattern="oauth2_pattern",
    feedback_type="incorrect",
    capabilities_matched=["auth", "security"],
    false_positives=["basic_auth"],
    false_negatives=["oauth2", "jwt"],
    user_provided=True
)

feedback_id = await collector.record_feedback(feedback, user_provided=True)
print(f"Feedback recorded: {feedback_id}")
```

#### Analyzing Pattern Performance

```python
# Analyze specific pattern
analysis = await collector.analyze_feedback(
    pattern_name="authentication_pattern",
    min_samples=20
)

if analysis.sufficient_data:
    print(f"Pattern: {analysis.pattern_name}")
    print(f"Precision: {analysis.precision:.1%}")
    print(f"Samples: {analysis.sample_count}")
    print(f"Correct: {analysis.correct_count}")
    print(f"Incorrect: {analysis.incorrect_count}")

    print("\nTop false positives:")
    for fp, count in list(analysis.false_positive_counts.items())[:3]:
        print(f"  {fp}: {count} occurrences")

    print("\nRecommendations:")
    for rec in analysis.recommendations:
        print(f"  - {rec}")
else:
    print(f"Insufficient data: {analysis.sample_count} samples (need {min_samples})")
```

#### Tuning Pattern Thresholds

```python
# Get recommended confidence threshold for pattern
threshold = await collector.tune_pattern_threshold(
    pattern_name="authentication_pattern",
    target_precision=0.92
)

if threshold:
    print(f"Recommended confidence threshold: {threshold:.2f}")
    # Apply threshold in pattern matching system
```

#### Global Metrics

```python
# Get overall pattern matching performance
metrics = await collector.get_global_precision_metrics()

print(f"Overall Metrics:")
print(f"  Overall precision: {metrics['overall_precision']:.1%}")
print(f"  Patterns analyzed: {metrics['patterns_analyzed']}")
print(f"  Meeting target (90%): {metrics['patterns_meeting_target']}")

if metrics['needs_improvement']:
    print("\nPatterns needing attention:")
    for pattern in metrics['needs_improvement']:
        print(f"  {pattern['pattern']}: {pattern['precision']:.1%}")
        print(f"    Recommendations: {', '.join(pattern['recommendations'][:2])}")
```

### Advanced Usage

#### Bulk Analysis

```python
# Analyze all patterns
all_analyses = await collector.get_all_pattern_analyses(min_samples=20)

# Sort by precision (lowest first - need most attention)
for analysis in all_analyses[:5]:
    print(f"{analysis.pattern_name}: {analysis.precision:.1%} "
          f"({analysis.sample_count} samples)")
```

#### Custom Feedback Types

```python
# Different feedback types
feedback_correct = PatternFeedback(
    session_id=uuid4(),
    detected_pattern="api_rest",
    detected_confidence=0.95,
    actual_pattern="api_rest",
    feedback_type="correct"  # Pattern matched correctly
)

feedback_partial = PatternFeedback(
    session_id=uuid4(),
    detected_pattern="database_orm",
    detected_confidence=0.75,
    actual_pattern="database_raw_sql",
    feedback_type="partial"  # Partially correct (database, but wrong subtype)
)

feedback_adjusted = PatternFeedback(
    session_id=uuid4(),
    detected_pattern="cache_redis",
    detected_confidence=0.70,
    actual_pattern="cache_memcached",
    feedback_type="adjusted"  # Close but needed adjustment
)
```

### Best Practices

1. **Record all pattern matches**: Both correct and incorrect for accurate learning
2. **Include false positives/negatives**: Essential for improving precision
3. **User feedback priority**: User-provided feedback has 2x learning weight
4. **Regular analysis**: Analyze patterns weekly to identify issues early
5. **Target 90% precision**: Use global metrics to track overall system health

---

## Stream 6: Event Optimization

### Basic Usage

High-performance event processing with batch processing, circuit breaker, and connection pooling achieving p95 latency ≤200ms.

#### Publishing Single Events

```python
from agents.lib.event_optimizer import EventOptimizer
from agents.lib.codegen_events import NodeGeneratedEvent

# Initialize optimizer
optimizer = EventOptimizer(
    bootstrap_servers="localhost:9092",
    config=OptimizerConfig(
        enable_compression=True,
        compression_threshold_bytes=1024,
        max_producer_pool_size=3
    )
)

# Publish event
event = NodeGeneratedEvent(
    service="codegen",
    correlation_id=uuid4(),
    payload={
        "node_type": "EFFECT",
        "microservice": "UserService",
        "status": "generated"
    }
)

await optimizer.publish_event(event)
```

#### Batch Publishing

```python
# Publish multiple events efficiently
events = [
    NodeGeneratedEvent(service="codegen", payload={"task": 1}),
    NodeGeneratedEvent(service="codegen", payload={"task": 2}),
    NodeGeneratedEvent(service="codegen", payload={"task": 3})
]

await optimizer.publish_batch(events)
```

#### Using Batch Processor

```python
from agents.lib.batch_processor import BatchProcessor, BatchConfig

# Create batch processor
batch_processor = optimizer.create_batch_processor()

# Or create standalone batch processor
async def process_batch(events):
    # Custom batch processing logic
    print(f"Processing batch of {len(events)} events")
    # ... processing logic

processor = BatchProcessor(
    processor_func=process_batch,
    config=BatchConfig(
        max_batch_size=10,
        max_wait_ms=100
    )
)

# Add events (automatically batches and flushes)
await processor.add_event(event1)
await processor.add_event(event2)
# ... events are automatically flushed when batch is full or timeout occurs

# Manual flush
await processor.flush()
```

### Advanced Usage

#### Circuit Breaker Configuration

```python
from agents.lib.event_optimizer import CircuitBreakerConfig

optimizer = EventOptimizer(
    bootstrap_servers="localhost:9092",
    circuit_config=CircuitBreakerConfig(
        failure_threshold=5,       # Open after 5 failures
        recovery_timeout_ms=10000, # Wait 10s before testing recovery
        success_threshold=2        # Close after 2 successes
    )
)

# Circuit breaker automatically handles failures
try:
    await optimizer.publish_event(event)
except RuntimeError as e:
    if "Circuit breaker is OPEN" in str(e):
        print("Service temporarily unavailable, circuit breaker is open")
        # Handle gracefully (e.g., queue for retry)
```

#### Custom Compression

```python
from agents.lib.event_optimizer import OptimizerConfig

optimizer = EventOptimizer(
    bootstrap_servers="localhost:9092",
    config=OptimizerConfig(
        enable_compression=True,
        compression_threshold_bytes=2048,  # Compress only large payloads
        max_producer_pool_size=5           # Larger pool for high throughput
    )
)
```

#### Monitoring Event Processing

The optimizer automatically tracks metrics to the database:

```python
# Metrics are automatically recorded for:
# - Event processing duration
# - Success/failure rates
# - Batch sizes
# - Queue wait times
# - Retry counts

# Query metrics later:
from agents.lib.persistence import CodegenPersistence

persistence = CodegenPersistence()
pool = await persistence._ensure_pool()

async with pool.acquire() as conn:
    metrics = await conn.fetch("""
        SELECT
            event_type,
            avg(processing_duration_ms) as avg_duration,
            count(*) as total_events,
            sum(CASE WHEN success THEN 1 ELSE 0 END)::float / count(*) as success_rate
        FROM event_processing_metrics
        WHERE created_at >= NOW() - INTERVAL '1 hour'
        GROUP BY event_type
    """)

    for metric in metrics:
        print(f"{metric['event_type']}: {metric['avg_duration']:.0f}ms, "
              f"{metric['success_rate']:.1%} success")
```

### Best Practices

1. **Use batch publishing**: 10-15ms per event vs 50-100ms for single events
2. **Configure circuit breaker**: Prevent cascading failures in distributed systems
3. **Enable compression**: Reduce network usage for payloads >1KB
4. **Monitor metrics**: Track success rates and latency to detect issues
5. **Pool connections**: Reuse producers to reduce connection overhead

---

## Stream 7: Monitoring

### Basic Usage

Comprehensive monitoring with 100% critical path coverage, real-time alerting, and Prometheus export.

#### Recording Metrics

```python
from agents.lib.monitoring import get_monitoring_system, MetricType

monitoring = get_monitoring_system()

# Record different metric types
await monitoring.record_metric(
    name="template_load_duration_ms",
    value=45.2,
    metric_type=MetricType.HISTOGRAM,
    labels={"template_type": "EFFECT"},
    help_text="Template load duration in milliseconds"
)

await monitoring.record_metric(
    name="cache_hit_rate",
    value=0.85,
    metric_type=MetricType.GAUGE,
    labels={"cache": "template"},
    help_text="Template cache hit rate"
)

await monitoring.record_metric(
    name="generation_count",
    value=1,
    metric_type=MetricType.COUNTER,
    labels={"node_type": "EFFECT"},
    help_text="Total number of nodes generated"
)
```

#### Collecting System Metrics

```python
# Collect metrics from all subsystems
metrics = await monitoring.collect_all_metrics(time_window_minutes=60)

print(f"Collection completed in {metrics['collection_time_ms']:.0f}ms")

# Template cache metrics
cache = metrics['template_cache']
print(f"\nTemplate Cache:")
print(f"  Hit rate: {cache['overall_hit_rate']:.1%}")
print(f"  Avg load time: {cache['avg_load_time_ms']:.1f}ms")
print(f"  Total templates: {cache['total_templates']}")

# Parallel generation metrics
parallel = metrics['parallel_generation']
print(f"\nParallel Generation:")
print(f"  Parallel usage: {parallel['parallel_usage_rate']:.1%}")
print(f"  Avg speedup: {parallel['avg_speedup']:.2f}x")

# Event processing metrics
events = metrics['event_processing']
print(f"\nEvent Processing:")
print(f"  Success rate: {events['overall_success_rate']:.1%}")
print(f"  P95 latency: {events['p95_latency_ms']:.0f}ms")
```

#### Health Status Tracking

```python
# Update component health
await monitoring.update_health_status(
    component="template_cache",
    healthy=True,
    status="healthy",
    metadata={"cache_size_mb": 25.5, "hit_rate": 0.87}
)

# Check for unhealthy components
summary = monitoring.get_monitoring_summary()
if summary['health']['overall_status'] != 'healthy':
    print("System health degraded:")
    for component, status in summary['health']['components'].items():
        if not status['healthy']:
            print(f"  {component}: {status['error']}")
```

#### Alert Management

```python
from agents.lib.monitoring import AlertSeverity

# Get active alerts
critical_alerts = monitoring.get_active_alerts(severity=AlertSeverity.CRITICAL)

if critical_alerts:
    print(f"{len(critical_alerts)} critical alerts:")
    for alert in critical_alerts:
        print(f"  [{alert.severity.value}] {alert.component}: {alert.message}")
        print(f"    Threshold: {alert.threshold}, Actual: {alert.actual_value}")

# Get recently resolved alerts
resolved = monitoring.get_resolved_alerts(hours=24)
print(f"\n{len(resolved)} alerts resolved in last 24 hours")
```

### Advanced Usage

#### Custom Thresholds

```python
from agents.lib.monitoring import MonitoringSystem, MonitoringThresholds

# Define custom thresholds
thresholds = MonitoringThresholds(
    template_load_ms_warning=40.0,
    template_load_ms_critical=80.0,
    cache_hit_rate_warning=0.75,
    cache_hit_rate_critical=0.65,
    pattern_precision_warning=0.88,
    pattern_precision_critical=0.82
)

monitoring = MonitoringSystem(thresholds=thresholds)
```

#### Prometheus Integration

```python
# Export metrics in Prometheus format
prom_metrics = await monitoring.export_prometheus_metrics()

# Serve via HTTP endpoint
from aiohttp import web

async def metrics_handler(request):
    metrics = await monitoring.export_prometheus_metrics()
    return web.Response(text=metrics, content_type='text/plain')

app = web.Application()
app.router.add_get('/metrics', metrics_handler)
web.run_app(app, port=9090)
```

#### Dashboard Integration

```python
# Get data for monitoring dashboard
dashboard_data = {
    "timestamp": datetime.now().isoformat(),
    "metrics": await monitoring.collect_all_metrics(60),
    "summary": monitoring.get_monitoring_summary(),
    "critical_alerts": [
        {
            "component": a.component,
            "message": a.message,
            "created_at": a.created_at.isoformat()
        }
        for a in monitoring.get_active_alerts(severity=AlertSeverity.CRITICAL)
    ]
}

# Send to dashboard backend
# await dashboard_client.post("/api/metrics", json=dashboard_data)
```

### Best Practices

1. **Record all critical metrics**: Template loads, generation times, cache hits, event latency
2. **Set appropriate thresholds**: Based on baseline performance and SLOs
3. **Monitor health status**: Check component health every minute
4. **Export to Prometheus**: Enable long-term trend analysis and alerting
5. **Review alerts daily**: Address critical alerts within 1 hour, warnings within 24 hours

---

## Stream 8: Structured Logging

### Basic Usage

High-performance structured JSON logging with correlation IDs and <1ms overhead per log entry.

#### Simple Logging

```python
from agents.lib.structured_logger import get_logger

logger = get_logger(__name__, component="codegen-workflow")

# Log with structured metadata
logger.info("Task started", metadata={
    "task_id": "123",
    "node_type": "EFFECT",
    "domain": "authentication"
})

logger.warning("Cache near capacity", metadata={
    "usage_percent": 85,
    "max_templates": 100
})

logger.error("Generation failed", metadata={
    "task_id": "123",
    "error_type": "timeout"
})
```

#### Correlation ID Tracking

```python
from uuid import uuid4
from agents.lib.structured_logger import get_logger

logger = get_logger(__name__, component="agent-researcher")

# Set correlation ID for request tracing
correlation_id = uuid4()
logger.set_correlation_id(correlation_id)

# All subsequent logs include correlation_id
logger.info("Research started", metadata={"query": "authentication patterns"})
logger.info("Research completed", metadata={"results_count": 42})

# Output:
# {"timestamp": "...", "level": "INFO", "message": "Research started",
#  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
#  "component": "agent-researcher", "metadata": {"query": "authentication patterns"}}
```

#### Using Context Managers

```python
from agents.lib.log_context import async_log_context

async def process_request(request_id: str):
    async with async_log_context(correlation_id=request_id):
        # All logs in this context automatically include correlation_id
        logger.info("Processing request", metadata={"request": request_id})

        result = await do_work()

        logger.info("Request completed", metadata={"result": result})
        # correlation_id automatically cleared when context exits
```

#### Error Logging

```python
try:
    result = risky_operation()
except ValueError as e:
    logger.error(
        "Validation failed",
        metadata={"operation": "validate_input", "input": user_input},
        exc_info=e  # Includes full stack trace
    )
    raise
except Exception as e:
    logger.critical(
        "Unexpected error",
        metadata={"operation": "process"},
        exc_info=e
    )
    raise
```

### Advanced Usage

#### Multi-Phase Workflows

```python
from agents.lib.structured_logger import get_logger
from agents.lib.log_context import async_log_context
from uuid import uuid4

logger = get_logger(__name__, component="workflow-coordinator")

async def execute_workflow(request):
    correlation_id = uuid4()

    async with async_log_context(correlation_id=correlation_id):
        logger.info("Workflow started", metadata={"workflow_id": request.id})

        # Phase 1: Research
        logger.info("Phase started", metadata={"phase": "research"})
        research_results = await research_phase(request)
        logger.info("Phase completed", metadata={
            "phase": "research",
            "results_count": len(research_results)
        })

        # Phase 2: Generation
        logger.info("Phase started", metadata={"phase": "generation"})
        generated_nodes = await generation_phase(research_results)
        logger.info("Phase completed", metadata={
            "phase": "generation",
            "nodes_count": len(generated_nodes)
        })

        logger.info("Workflow completed", metadata={
            "correlation_id": str(correlation_id),
            "total_duration_ms": 1234
        })
```

#### Global Context

```python
from agents.lib.structured_logger import set_global_correlation_id, get_correlation_id

# Set correlation ID globally (thread-safe)
set_global_correlation_id(uuid4())

# All loggers automatically use this correlation ID
logger1.info("Message from logger 1")
logger2.info("Message from logger 2")

# Both logs include the same correlation_id

# Retrieve current correlation ID
current_id = get_correlation_id()
```

#### Log Rotation

```python
from agents.lib.log_rotation import configure_global_rotation, LogRotationConfig

# Configure log rotation for all loggers
config = LogRotationConfig(
    log_dir="/var/log/agents",
    max_bytes=100 * 1024 * 1024,  # 100MB per file
    backup_count=30,               # Keep 30 files
    compression=True               # Compress rotated files
)

configure_global_rotation(config=config)
```

#### Querying JSON Logs

```bash
# Using jq to query JSON logs
cat /var/log/agents/workflow.log | jq 'select(.correlation_id == "550e8400-e29b-41d4-a716-446655440000")'

# Find all errors in last hour
cat /var/log/agents/workflow.log | jq 'select(.level == "ERROR" and .timestamp > "2025-01-15T09:00:00")'

# Get statistics
cat /var/log/agents/workflow.log | jq -s 'group_by(.component) | map({component: .[0].component, count: length})'
```

### Best Practices

1. **Use structured metadata**: Don't use f-strings, use metadata dict
2. **Set correlation IDs**: Always use correlation IDs for multi-step workflows
3. **Use context managers**: Automatically manage correlation ID lifecycle
4. **Include exception info**: Always pass exc_info for errors
5. **Configure rotation**: Prevent disk space issues with log rotation

---

## Best Practices

### Performance Optimization

1. **Template Caching**:
   - Warmup cache on startup
   - Monitor hit rates (target ≥80%)
   - Use content-based invalidation (automatic)

2. **Parallel Generation**:
   - Use 3-4 workers for I/O-bound operations
   - Set timeouts appropriate to task complexity
   - Handle partial failures gracefully

3. **Event Processing**:
   - Batch events when possible (10x performance improvement)
   - Enable compression for large payloads
   - Use circuit breaker for resilience

### Monitoring and Observability

1. **Metrics Collection**:
   - Record all critical operations
   - Use appropriate metric types (counter/gauge/histogram)
   - Set meaningful labels for aggregation

2. **Alerting**:
   - Set thresholds based on baselines + SLOs
   - Review critical alerts within 1 hour
   - Tune thresholds to reduce false positives

3. **Logging**:
   - Use correlation IDs for all multi-step operations
   - Include structured metadata (not f-strings)
   - Configure log rotation to prevent disk issues

### Machine Learning

1. **Mixin Learning**:
   - Train with ≥100 samples for best accuracy
   - Continuously update model with production feedback
   - Only accept predictions with ≥70% confidence

2. **Pattern Feedback**:
   - Record both correct and incorrect matches
   - Include false positives/negatives
   - Target ≥90% precision

### Error Handling

1. **Graceful Degradation**:
   - Handle partial failures in parallel generation
   - Use circuit breaker for external services
   - Provide fallback mechanisms

2. **Error Reporting**:
   - Always include context in error logs
   - Use correlation IDs for error tracing
   - Record error metrics for monitoring

---

## Common Patterns

### Pattern 1: End-to-End Code Generation

```python
async def generate_microservice(prd_path: Path, output_dir: Path):
    correlation_id = uuid4()
    logger = get_logger(__name__, component="codegen-e2e")
    logger.set_correlation_id(correlation_id)

    # Initialize components
    cache = TemplateCache()
    cache.warmup(templates_dir=TEMPLATES_DIR, template_types=ALL_TYPES)

    generator = ParallelGenerator(max_workers=3)
    monitoring = get_monitoring_system()

    try:
        # Analyze PRD
        logger.info("Analyzing PRD", metadata={"prd": str(prd_path)})
        analysis = await analyze_prd(prd_path)

        # Create generation jobs
        jobs = create_jobs(analysis, output_dir)

        # Generate in parallel
        logger.info("Starting parallel generation", metadata={"jobs": len(jobs)})
        results = await generator.generate_nodes_parallel(jobs, correlation_id)

        # Record metrics
        for result in results:
            await monitoring.record_metric(
                name="generation_duration_ms",
                value=result.duration_ms,
                metric_type=MetricType.HISTOGRAM,
                labels={"node_type": result.node_type}
            )

        # Report success
        successful = [r for r in results if r.success]
        logger.info("Generation complete", metadata={
            "total": len(results),
            "successful": len(successful),
            "failed": len(results) - len(successful)
        })

        return results

    finally:
        await generator.cleanup()
```

### Pattern 2: ML-Enhanced Pattern Matching

```python
async def match_pattern_with_ml(contract: dict, confidence_threshold: float = 0.7):
    logger = get_logger(__name__, component="pattern-matcher")

    # Initialize ML components
    learner = MixinLearner(auto_train=True)
    feedback_collector = PatternFeedbackCollector()

    # Detect pattern (simplified)
    detected_pattern, confidence = detect_pattern(contract)

    # Get ML recommendation
    recommendation = learner.recommend_mixins(
        node_type=contract['node_type'],
        required_capabilities=contract.get('capabilities', []),
        max_recommendations=1
    )

    # Record feedback for learning
    if recommendation:
        feedback = PatternFeedback(
            session_id=uuid4(),
            detected_pattern=detected_pattern,
            detected_confidence=confidence,
            actual_pattern=recommendation[0][0],  # Use ML recommendation
            feedback_type="correct" if confidence >= confidence_threshold else "adjusted"
        )
        await feedback_collector.record_feedback(feedback)

    logger.info("Pattern matched", metadata={
        "pattern": detected_pattern,
        "confidence": confidence,
        "ml_recommendation": recommendation[0][0] if recommendation else None
    })

    return detected_pattern if confidence >= confidence_threshold else recommendation[0][0]
```

### Pattern 3: Monitored Event Processing

```python
async def process_events_with_monitoring(events: List[BaseEvent]):
    logger = get_logger(__name__, component="event-processor")
    monitoring = get_monitoring_system()

    optimizer = EventOptimizer(
        bootstrap_servers="localhost:9092",
        config=OptimizerConfig(enable_compression=True)
    )

    try:
        start_time = time.time()

        # Process in batches
        await optimizer.publish_batch(events)

        duration_ms = (time.time() - start_time) * 1000

        # Record metrics
        await monitoring.record_metric(
            name="batch_processing_duration_ms",
            value=duration_ms,
            metric_type=MetricType.HISTOGRAM,
            labels={"batch_size": str(len(events))}
        )

        logger.info("Events processed", metadata={
            "count": len(events),
            "duration_ms": duration_ms,
            "avg_per_event_ms": duration_ms / len(events)
        })

    except Exception as e:
        await monitoring.update_health_status(
            component="event_processor",
            healthy=False,
            status="critical",
            error_message=str(e)
        )
        logger.error("Event processing failed", exc_info=e)
        raise

    finally:
        await optimizer.cleanup()
```

---

## Troubleshooting

### Template Cache Issues

**Problem**: Low cache hit rate (<60%)

**Solutions**:
1. Check if templates are frequently modified (invalidation)
2. Increase `max_templates` if many unique templates
3. Increase `ttl_seconds` if templates don't change often
4. Use warmup to preload common templates

**Problem**: High memory usage

**Solutions**:
1. Reduce `max_templates`
2. Reduce `max_size_mb`
3. Check for large templates (use `get_detailed_stats()`)

### Parallel Generation Issues

**Problem**: Jobs timing out

**Solutions**:
1. Increase `timeout_seconds`
2. Reduce `max_workers` (may be resource contention)
3. Check for blocking I/O in generation code
4. Monitor system resources during generation

**Problem**: Poor speedup (<2x)

**Solutions**:
1. Ensure operations are truly parallel (not sequential)
2. Check for shared resource contention
3. Verify template cache is enabled
4. Profile to identify bottlenecks

### Mixin Learning Issues

**Problem**: Low model accuracy (<90%)

**Solutions**:
1. Increase training data (need ≥100 samples)
2. Check data quality (balanced success/failure)
3. Retrain model with more samples
4. Review feature engineering

**Problem**: Model predictions seem incorrect

**Solutions**:
1. Check model metrics (`get_metrics()`)
2. Verify training data quality
3. Use predictions only with high confidence (≥0.7)
4. Continuously update with production feedback

### Pattern Feedback Issues

**Problem**: Low precision (<85%)

**Solutions**:
1. Analyze false positives/negatives
2. Tune confidence thresholds
3. Improve pattern keywords
4. Collect more user feedback (higher learning weight)

**Problem**: Insufficient data for analysis

**Solutions**:
1. Record all pattern matches (correct and incorrect)
2. Encourage user feedback
3. Lower `min_samples` temporarily for early analysis
4. Wait for more production usage

### Event Optimization Issues

**Problem**: Circuit breaker frequently opening

**Solutions**:
1. Check Kafka connectivity
2. Increase `failure_threshold`
3. Increase `recovery_timeout_ms`
4. Monitor downstream service health

**Problem**: High latency (>200ms p95)

**Solutions**:
1. Enable batch processing
2. Increase `max_batch_size`
3. Reduce `max_wait_ms` (but may reduce batching efficiency)
4. Check network latency to Kafka
5. Enable compression for large payloads

### Monitoring Issues

**Problem**: Too many false positive alerts

**Solutions**:
1. Adjust thresholds based on baseline performance
2. Increase warning/critical thresholds
3. Add alert deduplication window
4. Review alert history to tune thresholds

**Problem**: Metrics collection slow (>1s)

**Solutions**:
1. Reduce `time_window_minutes`
2. Add database indexes on timestamp columns
3. Use database query optimization
4. Consider caching frequently accessed metrics

### Logging Issues

**Problem**: Correlation IDs not appearing in logs

**Solutions**:
1. Verify `set_correlation_id()` is called
2. Use `async_log_context` context manager
3. Check if correlation ID is being cleared unintentionally
4. Verify logger is using `StructuredLogger`

**Problem**: Log files growing too large

**Solutions**:
1. Configure log rotation
2. Adjust `max_bytes` and `backup_count`
3. Enable compression
4. Reduce log level (INFO instead of DEBUG)

---

## Next Steps

- **Deep Dive**: Read [Architecture](./ARCHITECTURE.md) for system design details
- **Operations**: See [Operations Guide](./OPERATIONS_GUIDE.md) for deployment and monitoring
- **Integration**: Check [Integration Guide](./INTEGRATION_GUIDE.md) for cross-stream patterns
- **API Reference**: Consult [API Reference](./API_REFERENCE.md) for detailed API documentation

---

## Support

For questions or issues:
1. Check [Troubleshooting](#troubleshooting) section
2. Review [Best Practices](#best-practices)
3. Consult [API Reference](./API_REFERENCE.md)
4. Check test suites for usage examples
