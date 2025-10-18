# Agent Framework API Reference

**Version**: 1.0
**Last Updated**: 2025-10-15
**Coverage**: 100% of public APIs across 8 streams

This document provides comprehensive API documentation for all agent framework components including template caching, parallel generation, mixin learning, pattern feedback, event optimization, monitoring, and structured logging.

---

## Table of Contents

1. [Stream 1: Database Schema](#stream-1-database-schema)
2. [Stream 2: Template Caching](#stream-2-template-caching)
3. [Stream 3: Parallel Generation](#stream-3-parallel-generation)
4. [Stream 4: Mixin Learning](#stream-4-mixin-learning)
5. [Stream 5: Pattern Feedback](#stream-5-pattern-feedback)
6. [Stream 6: Event Optimization](#stream-6-event-optimization)
7. [Stream 7: Monitoring](#stream-7-monitoring)
8. [Stream 8: Structured Logging](#stream-8-structured-logging)

---

## Stream 1: Database Schema

### Overview

The framework database schema provides 5 tables, 30 indexes, 5 views, and 2 helper functions for machine learning, performance metrics, and pattern feedback tracking.

### Tables

#### `mixin_compatibility_matrix`

Tracks mixin combinations and compatibility for ML learning.

**Schema**:
```sql
CREATE TABLE mixin_compatibility_matrix (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mixin_a VARCHAR(100) NOT NULL,
  mixin_b VARCHAR(100) NOT NULL,
  node_type VARCHAR(50) NOT NULL,  -- EFFECT, COMPUTE, REDUCER, ORCHESTRATOR
  compatibility_score NUMERIC(5,4) CHECK (compatibility_score >= 0.0 AND compatibility_score <= 1.0),
  success_count INTEGER DEFAULT 0,
  failure_count INTEGER DEFAULT 0,
  last_tested_at TIMESTAMPTZ,
  conflict_reason TEXT,
  resolution_pattern TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(mixin_a, mixin_b, node_type)
);
```

**Indexes**:
- `idx_mixin_compat_score` - On `compatibility_score DESC`
- `idx_mixin_compat_node_type` - On `node_type`
- `idx_mixin_compat_mixins` - On `(mixin_a, mixin_b)`
- `idx_mixin_compat_updated` - On `updated_at DESC`

#### `pattern_feedback_log`

Stores pattern matching feedback for continuous learning.

**Schema**:
```sql
CREATE TABLE pattern_feedback_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL,
  pattern_name VARCHAR(100) NOT NULL,
  detected_confidence NUMERIC(5,4) CHECK (detected_confidence IS NULL OR (detected_confidence >= 0.0 AND detected_confidence <= 1.0)),
  actual_pattern VARCHAR(100),
  feedback_type VARCHAR(50) NOT NULL,  -- correct, incorrect, partial, adjusted
  user_provided BOOLEAN DEFAULT FALSE,
  contract_json JSONB,
  capabilities_matched TEXT[],
  false_positives TEXT[],
  false_negatives TEXT[],
  learning_weight NUMERIC(5,4) DEFAULT 1.0 CHECK (learning_weight >= 0.0 AND learning_weight <= 1.0),
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Indexes**:
- `idx_pattern_feedback_session` - On `session_id`
- `idx_pattern_feedback_pattern` - On `pattern_name`
- `idx_pattern_feedback_type` - On `feedback_type`
- `idx_pattern_feedback_created` - On `created_at DESC`
- `idx_pattern_feedback_user` - On `user_provided` WHERE `user_provided = TRUE`
- `idx_pattern_feedback_contract` - GIN index on `contract_json`

#### `generation_performance_metrics`

Tracks detailed performance metrics for code generation phases.

**Schema**:
```sql
CREATE TABLE generation_performance_metrics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL,
  node_type VARCHAR(50) NOT NULL,
  phase VARCHAR(50) NOT NULL,  -- prd_analysis, template_load, code_gen, validation, persistence, total
  duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
  memory_usage_mb INTEGER,
  cpu_percent NUMERIC(5,2),
  cache_hit BOOLEAN DEFAULT FALSE,
  parallel_execution BOOLEAN DEFAULT FALSE,
  worker_count INTEGER DEFAULT 1 CHECK (worker_count >= 1),
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Indexes**:
- `idx_gen_perf_session` - On `session_id`
- `idx_gen_perf_phase` - On `phase`
- `idx_gen_perf_duration` - On `duration_ms DESC`
- `idx_gen_perf_node_type` - On `node_type`
- `idx_gen_perf_cache` - On `cache_hit` WHERE `cache_hit = TRUE`
- `idx_gen_perf_parallel` - On `parallel_execution` WHERE `parallel_execution = TRUE`
- `idx_gen_perf_created` - On `created_at DESC`
- `idx_gen_perf_metadata` - GIN index on `metadata`

#### `template_cache_metadata`

Tracks template caching statistics for performance optimization.

**Schema**:
```sql
CREATE TABLE template_cache_metadata (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  template_name VARCHAR(200) NOT NULL UNIQUE,
  template_type VARCHAR(50) NOT NULL,  -- node, contract, subcontract, mixin, test
  cache_key VARCHAR(500) NOT NULL,
  file_path TEXT NOT NULL,
  file_hash VARCHAR(64) NOT NULL,  -- SHA-256 hash
  size_bytes INTEGER,
  load_time_ms INTEGER,
  last_accessed_at TIMESTAMPTZ,
  access_count INTEGER DEFAULT 0,
  cache_hits INTEGER DEFAULT 0,
  cache_misses INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Indexes**:
- `idx_template_cache_name` - On `template_name`
- `idx_template_cache_type` - On `template_type`
- `idx_template_cache_accessed` - On `last_accessed_at DESC`
- `idx_template_cache_hits` - On `cache_hits DESC`
- `idx_template_cache_hash` - On `file_hash`

#### `event_processing_metrics`

Tracks event processing performance for optimization.

**Schema**:
```sql
CREATE TABLE event_processing_metrics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type VARCHAR(100) NOT NULL,
  event_source VARCHAR(100) NOT NULL,
  processing_duration_ms INTEGER NOT NULL CHECK (processing_duration_ms >= 0),
  queue_wait_time_ms INTEGER,
  success BOOLEAN NOT NULL,
  error_type VARCHAR(100),
  error_message TEXT,
  retry_count INTEGER DEFAULT 0,
  batch_size INTEGER DEFAULT 1 CHECK (batch_size >= 1),
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Indexes**:
- `idx_event_proc_type` - On `event_type`
- `idx_event_proc_source` - On `event_source`
- `idx_event_proc_success` - On `success`
- `idx_event_proc_created` - On `created_at DESC`
- `idx_event_proc_duration` - On `processing_duration_ms DESC`
- `idx_event_proc_errors` - On `error_type` WHERE `error_type IS NOT NULL`

### Views

#### `mixin_compatibility_summary`

Aggregated mixin compatibility statistics by node type.

**Query**:
```sql
SELECT
  node_type,
  count(*) as total_combinations,
  round(avg(compatibility_score)::numeric, 3) as avg_compatibility,
  sum(success_count) as total_successes,
  sum(failure_count) as total_failures,
  round((sum(success_count)::numeric / NULLIF(sum(success_count + failure_count), 0))::numeric, 3) as success_rate
FROM mixin_compatibility_matrix
GROUP BY node_type
ORDER BY node_type;
```

#### `pattern_feedback_analysis`

Analyzes pattern matching feedback for learning optimization.

**Query**:
```sql
SELECT
  pattern_name,
  feedback_type,
  count(*) as feedback_count,
  round(avg(detected_confidence)::numeric, 3) as avg_confidence,
  sum(CASE WHEN user_provided THEN 1 ELSE 0 END) as user_provided_count,
  round(avg(learning_weight)::numeric, 3) as avg_learning_weight
FROM pattern_feedback_log
GROUP BY pattern_name, feedback_type
ORDER BY pattern_name, feedback_count DESC;
```

#### `performance_metrics_summary`

Aggregated performance metrics with percentiles by phase.

**Query**:
```sql
SELECT
  phase,
  count(*) as execution_count,
  round(avg(duration_ms)::numeric, 2) as avg_duration_ms,
  round(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)::numeric, 2) as p95_duration_ms,
  round(percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms)::numeric, 2) as p99_duration_ms,
  sum(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits,
  sum(CASE WHEN parallel_execution THEN 1 ELSE 0 END) as parallel_executions,
  round(avg(worker_count)::numeric, 1) as avg_workers
FROM generation_performance_metrics
GROUP BY phase
ORDER BY phase;
```

#### `template_cache_efficiency`

Template cache hit rates and efficiency metrics by type.

**Query**:
```sql
SELECT
  template_type,
  count(*) as template_count,
  round(avg(cache_hits)::numeric, 1) as avg_cache_hits,
  round(avg(cache_misses)::numeric, 1) as avg_cache_misses,
  round((sum(cache_hits)::numeric / NULLIF(sum(cache_hits + cache_misses), 0))::numeric, 3) as hit_rate,
  round(avg(load_time_ms)::numeric, 2) as avg_load_time_ms,
  round(sum(size_bytes)::numeric / (1024 * 1024), 2) as total_size_mb
FROM template_cache_metadata
GROUP BY template_type
ORDER BY template_type;
```

#### `event_processing_health`

Event processing health metrics with success rates and performance.

**Query**:
```sql
SELECT
  event_type,
  event_source,
  count(*) as total_events,
  sum(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
  sum(CASE WHEN NOT success THEN 1 ELSE 0 END) as failure_count,
  round((sum(CASE WHEN success THEN 1 ELSE 0 END)::numeric / count(*)::numeric)::numeric, 3) as success_rate,
  round(avg(processing_duration_ms)::numeric, 2) as avg_duration_ms,
  round(avg(queue_wait_time_ms)::numeric, 2) as avg_wait_ms,
  round(avg(retry_count)::numeric, 1) as avg_retries
FROM event_processing_metrics
GROUP BY event_type, event_source
ORDER BY total_events DESC;
```

### Helper Functions

#### `update_mixin_compatibility()`

Updates mixin compatibility matrix with test results and recalculates score.

**Signature**:
```sql
update_mixin_compatibility(
  p_mixin_a VARCHAR,
  p_mixin_b VARCHAR,
  p_node_type VARCHAR,
  p_success BOOLEAN,
  p_conflict_reason TEXT DEFAULT NULL,
  p_resolution_pattern TEXT DEFAULT NULL
) RETURNS UUID
```

**Parameters**:
- `p_mixin_a`: First mixin name
- `p_mixin_b`: Second mixin name
- `p_node_type`: ONEX node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
- `p_success`: Whether combination was successful
- `p_conflict_reason`: Optional conflict description
- `p_resolution_pattern`: Optional resolution pattern

**Returns**: UUID of the compatibility record

**Example**:
```sql
SELECT update_mixin_compatibility(
  'MixinCaching',
  'MixinLogging',
  'EFFECT',
  TRUE,
  NULL,
  NULL
);
```

#### `record_pattern_feedback()`

Records pattern matching feedback with appropriate learning weight.

**Signature**:
```sql
record_pattern_feedback(
  p_session_id UUID,
  p_pattern_name VARCHAR,
  p_detected_confidence NUMERIC,
  p_actual_pattern VARCHAR,
  p_feedback_type VARCHAR,
  p_user_provided BOOLEAN DEFAULT FALSE,
  p_contract_json JSONB DEFAULT NULL
) RETURNS UUID
```

**Parameters**:
- `p_session_id`: Session UUID
- `p_pattern_name`: Detected pattern name
- `p_detected_confidence`: Confidence score (0.0-1.0)
- `p_actual_pattern`: Actual correct pattern
- `p_feedback_type`: Feedback type (correct, incorrect, partial, adjusted)
- `p_user_provided`: Whether feedback came from user
- `p_contract_json`: Optional contract JSON

**Returns**: UUID of the feedback record

**Example**:
```sql
SELECT record_pattern_feedback(
  'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
  'authentication_pattern',
  0.85,
  'oauth2_pattern',
  'incorrect',
  TRUE,
  '{"type": "EFFECT", "capability": "auth"}'::jsonb
);
```

### Pydantic Models

Located in `agents/lib/schema_phase7.py`.

**Key Models**:
- `MixinCompatibilityMatrix` - Mixin compatibility record
- `MixinCompatibilityCreate` - Create new compatibility record
- `PatternFeedbackLog` - Pattern feedback record
- `PatternFeedbackCreate` - Create new feedback record
- `GenerationPerformanceMetrics` - Performance metrics record
- `GenerationPerformanceCreate` - Create new performance record
- `TemplateCacheMetadata` - Cache metadata record
- `TemplateCacheCreate` - Create new cache record
- `TemplateCacheUpdate` - Update cache record
- `EventProcessingMetrics` - Event metrics record
- `EventProcessingCreate` - Create new event record

**View Models**:
- `MixinCompatibilitySummary`
- `PatternFeedbackAnalysis`
- `PerformanceMetricsSummary`
- `TemplateCacheEfficiency`
- `EventProcessingHealth`

---

## Stream 2: Template Caching

### Overview

Intelligent template caching system with LRU eviction, TTL, and content-based invalidation. Target performance: 50ms template load time (50% reduction from 100ms baseline), ≥80% cache hit rate.

### Classes

#### `TemplateCache`

Main cache implementation with LRU eviction and content-based invalidation.

**Location**: `agents/lib/template_cache.py`

**Constructor**:
```python
TemplateCache(
    max_templates: int = 100,
    max_size_mb: int = 50,
    ttl_seconds: int = 3600,
    enable_persistence: bool = True
)
```

**Parameters**:
- `max_templates`: Maximum number of templates to cache (default: 100)
- `max_size_mb`: Maximum cache size in megabytes (default: 50)
- `ttl_seconds`: Time-to-live in seconds (default: 3600 = 1 hour)
- `enable_persistence`: Enable database persistence for metrics (default: True)

**Methods**:

##### `get()`

Get template from cache or load from filesystem.

```python
def get(
    template_name: str,
    template_type: str,
    file_path: Path,
    loader_func: Callable[[Path], str]
) -> Tuple[str, bool]
```

**Parameters**:
- `template_name`: Unique template identifier
- `template_type`: Template type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
- `file_path`: Path to template file
- `loader_func`: Function to load template from file

**Returns**: Tuple of (template_content, cache_hit)

**Example**:
```python
cache = TemplateCache()

content, hit = cache.get(
    template_name="NodeDatabaseEffect",
    template_type="EFFECT",
    file_path=Path("/path/to/effect_template.py"),
    loader_func=lambda p: p.read_text()
)

print(f"Cache hit: {hit}")
print(f"Content length: {len(content)}")
```

##### `invalidate()`

Manually invalidate specific template.

```python
def invalidate(template_name: str) -> None
```

**Parameters**:
- `template_name`: Template to invalidate

**Example**:
```python
cache.invalidate("NodeDatabaseEffect")
```

##### `invalidate_all()`

Invalidate all cached templates.

```python
def invalidate_all() -> None
```

**Example**:
```python
cache.invalidate_all()
```

##### `warmup()`

Warmup cache by preloading common templates.

```python
def warmup(
    templates_dir: Path,
    template_types: list[str]
) -> None
```

**Parameters**:
- `templates_dir`: Directory containing templates
- `template_types`: List of template types to preload

**Example**:
```python
cache.warmup(
    templates_dir=Path("/templates"),
    template_types=["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]
)
```

##### `get_stats()`

Get cache statistics.

```python
def get_stats() -> Dict[str, Any]
```

**Returns**: Dictionary with cache performance metrics

**Returned Fields**:
- `hits`: Number of cache hits
- `misses`: Number of cache misses
- `hit_rate`: Hit rate (0.0-1.0)
- `evictions`: Number of evictions
- `invalidations`: Number of invalidations
- `cached_templates`: Number of templates currently cached
- `total_size_bytes`: Total cache size in bytes
- `total_size_mb`: Total cache size in MB
- `avg_uncached_load_ms`: Average load time for cache misses
- `avg_cached_load_ms`: Average retrieval time for cache hits
- `time_saved_ms`: Total time saved by caching
- `improvement_percent`: Performance improvement percentage
- `capacity_usage_percent`: Capacity usage (0-100%)
- `memory_usage_percent`: Memory usage (0-100%)

**Example**:
```python
stats = cache.get_stats()
print(f"Hit rate: {stats['hit_rate']:.1%}")
print(f"Time saved: {stats['time_saved_ms']:.0f}ms")
print(f"Improvement: {stats['improvement_percent']:.1f}%")
```

##### `get_detailed_stats()`

Get detailed cache statistics including per-template metrics.

```python
def get_detailed_stats() -> Dict[str, Any]
```

**Returns**: Detailed statistics with template-level breakdown

**Additional Fields**:
- `templates`: List of template statistics with:
  - `name`: Template name
  - `type`: Template type
  - `size_bytes`: Template size
  - `access_count`: Number of accesses
  - `age_seconds`: Age since loaded
  - `file_hash`: File hash (truncated)

**Example**:
```python
stats = cache.get_detailed_stats()
for template in stats['templates']:
    print(f"{template['name']}: {template['access_count']} accesses")
```

### Data Classes

#### `CachedTemplate`

Cached template with metadata.

```python
@dataclass
class CachedTemplate:
    template_name: str
    template_type: str
    content: str
    file_path: str
    file_hash: str
    loaded_at: datetime
    last_accessed_at: datetime
    access_count: int = 0
    size_bytes: int = 0
```

### Performance Characteristics

- **Cache lookup**: <1ms (in-memory OrderedDict)
- **Hash computation**: ~5ms for typical template (SHA-256)
- **Cache hit**: <1ms (memory access)
- **Cache miss + load**: ~50ms (filesystem I/O)
- **Improvement**: 50x faster for cache hits
- **Memory overhead**: ~2KB per cached template (metadata)

---

## Stream 3: Parallel Generation

### Overview

Parallel code generation orchestrator using thread pools for 3x+ throughput improvement. Handles resource management, error recovery, and progress tracking.

### Classes

#### `ParallelGenerator`

Main parallel generation orchestrator.

**Location**: `agents/lib/parallel_generator.py`

**Constructor**:
```python
ParallelGenerator(
    max_workers: int = 3,
    timeout_seconds: int = 120,
    enable_metrics: bool = True
)
```

**Parameters**:
- `max_workers`: Maximum number of concurrent workers (default: 3)
- `timeout_seconds`: Timeout for each generation job (default: 120)
- `enable_metrics`: Enable performance metrics tracking (default: True)

**Methods**:

##### `generate_nodes_parallel()`

Generate multiple nodes in parallel.

```python
async def generate_nodes_parallel(
    jobs: List[GenerationJob],
    session_id: UUID
) -> List[GenerationResult]
```

**Parameters**:
- `jobs`: List of generation jobs
- `session_id`: Session ID for tracking

**Returns**: List of generation results (order not guaranteed)

**Raises**: `OnexError` if all jobs fail

**Example**:
```python
from uuid import uuid4

generator = ParallelGenerator(max_workers=3)

jobs = [
    GenerationJob(
        job_id=uuid4(),
        node_type="EFFECT",
        microservice_name="UserService",
        domain="authentication",
        analysis_result=prd_analysis,
        output_directory="/output"
    ),
    GenerationJob(
        job_id=uuid4(),
        node_type="COMPUTE",
        microservice_name="UserService",
        domain="validation",
        analysis_result=prd_analysis,
        output_directory="/output"
    )
]

results = await generator.generate_nodes_parallel(
    jobs=jobs,
    session_id=uuid4()
)

for result in results:
    if result.success:
        print(f"{result.node_type} generated in {result.duration_ms:.0f}ms")
    else:
        print(f"{result.node_type} failed: {result.error}")
```

##### `get_progress()`

Get current progress information.

```python
def get_progress() -> Dict[str, Any]
```

**Returns**: Dictionary with progress details

**Returned Fields**:
- `completed_jobs`: Number of completed jobs
- `total_jobs`: Total number of jobs
- `progress_percent`: Progress percentage
- `remaining_jobs`: Number of remaining jobs

**Example**:
```python
progress = generator.get_progress()
print(f"Progress: {progress['progress_percent']:.1f}%")
```

##### `cleanup()`

Cleanup resources and shutdown worker pool.

```python
async def cleanup() -> None
```

**Example**:
```python
await generator.cleanup()
```

### Data Classes

#### `GenerationJob`

Single node generation job.

```python
@dataclass
class GenerationJob:
    job_id: UUID
    node_type: str
    microservice_name: str
    domain: str
    analysis_result: SimplePRDAnalysisResult
    output_directory: str
```

#### `GenerationResult`

Result of parallel generation.

```python
@dataclass
class GenerationResult:
    job_id: UUID
    success: bool
    node_result: Optional[Dict[str, Any]]
    error: Optional[str]
    duration_ms: float
    node_type: str
    microservice_name: str
```

### Performance Characteristics

- **Sequential generation**: ~5000ms for 3 nodes
- **Parallel generation**: ~1500-2000ms for 3 nodes
- **Speedup**: 2.5-3.3x improvement
- **Worker overhead**: ~100ms setup time
- **Optimal workers**: 3-4 (I/O bound operations)

---

## Stream 4: Mixin Learning

### Overview

ML-powered mixin compatibility learning system with Random Forest classifier achieving ≥95% accuracy. Provides intelligent recommendations for mixin combinations based on historical data.

### Classes

#### `MixinLearner`

Main ML-based mixin compatibility learning system.

**Location**: `agents/lib/mixin_learner.py`

**Constructor**:
```python
MixinLearner(
    model_path: Optional[Path] = None,
    auto_train: bool = False,
    min_confidence_threshold: float = 0.7,
    persistence: Optional[CodegenPersistence] = None
)
```

**Parameters**:
- `model_path`: Path to save/load trained model (default: `/agents/models/mixin_compatibility_rf.pkl`)
- `auto_train`: Whether to auto-train on initialization (default: False)
- `min_confidence_threshold`: Minimum confidence for predictions (default: 0.7)
- `persistence`: Optional persistence instance

**Methods**:

##### `train_model()`

Train compatibility prediction model from historical data.

```python
async def train_model(
    min_samples: int = 50,
    test_size: float = 0.2,
    cross_val_folds: int = 5
) -> ModelMetrics
```

**Parameters**:
- `min_samples`: Minimum training samples required (default: 50)
- `test_size`: Fraction of data for testing (default: 0.2)
- `cross_val_folds`: Number of cross-validation folds (default: 5)

**Returns**: `ModelMetrics` with training results

**Raises**: `ValueError` if insufficient training data

**Example**:
```python
learner = MixinLearner()
metrics = await learner.train_model(min_samples=100)

print(f"Accuracy: {metrics.accuracy:.1%}")
print(f"Precision: {metrics.precision:.1%}")
print(f"F1 Score: {metrics.f1_score:.1%}")
```

##### `predict_compatibility()`

Predict compatibility for mixin pair.

```python
def predict_compatibility(
    mixin_a: str,
    mixin_b: str,
    node_type: str,
    historical_data: Optional[Dict[str, Any]] = None
) -> MixinPrediction
```

**Parameters**:
- `mixin_a`: First mixin name
- `mixin_b`: Second mixin name
- `node_type`: ONEX node type
- `historical_data`: Optional historical compatibility data

**Returns**: `MixinPrediction` with compatibility and confidence

**Raises**: `ValueError` if model not trained

**Example**:
```python
prediction = learner.predict_compatibility(
    mixin_a="MixinCaching",
    mixin_b="MixinLogging",
    node_type="EFFECT"
)

print(f"Compatible: {prediction.compatible}")
print(f"Confidence: {prediction.confidence:.1%}")
print(f"Explanation: {prediction.explanation}")
```

##### `recommend_mixins()`

Recommend mixins for a node type based on required capabilities.

```python
def recommend_mixins(
    node_type: str,
    required_capabilities: List[str],
    existing_mixins: Optional[List[str]] = None,
    max_recommendations: int = 5
) -> List[Tuple[str, float, str]]
```

**Parameters**:
- `node_type`: ONEX node type
- `required_capabilities`: List of required capabilities
- `existing_mixins`: List of already selected mixins (default: None)
- `max_recommendations`: Maximum number of recommendations (default: 5)

**Returns**: List of (mixin_name, confidence, explanation) tuples

**Example**:
```python
recommendations = learner.recommend_mixins(
    node_type="EFFECT",
    required_capabilities=["caching", "logging"],
    existing_mixins=["MixinHealthCheck"],
    max_recommendations=3
)

for mixin, score, explanation in recommendations:
    print(f"{mixin}: {score:.1%} - {explanation}")
```

##### `update_from_feedback()`

Update model with new feedback and optionally retrain.

```python
async def update_from_feedback(
    mixin_a: str,
    mixin_b: str,
    node_type: str,
    success: bool,
    retrain_threshold: int = 100
) -> None
```

**Parameters**:
- `mixin_a`: First mixin
- `mixin_b`: Second mixin
- `node_type`: Node type
- `success`: Whether combination was successful
- `retrain_threshold`: Number of new samples before retraining (default: 100)

**Example**:
```python
await learner.update_from_feedback(
    mixin_a="MixinCaching",
    mixin_b="MixinRetry",
    node_type="EFFECT",
    success=True
)
```

##### `get_metrics()`

Get current model metrics.

```python
def get_metrics() -> Optional[ModelMetrics]
```

**Returns**: `ModelMetrics` or None if not trained

**Example**:
```python
metrics = learner.get_metrics()
if metrics:
    print(f"Model trained with {metrics.training_samples} samples")
    print(f"Cross-validation scores: {metrics.cross_val_scores}")
```

##### `is_trained()`

Check if model is trained.

```python
def is_trained() -> bool
```

**Returns**: True if model is trained

**Example**:
```python
if not learner.is_trained():
    await learner.train_model()
```

### Data Classes

#### `MixinPrediction`

Mixin compatibility prediction result.

```python
@dataclass
class MixinPrediction:
    mixin_a: str
    mixin_b: str
    node_type: str
    compatible: bool
    confidence: float
    learned_from_samples: int
    explanation: str = ""
```

#### `ModelMetrics`

ML model performance metrics.

```python
@dataclass
class ModelMetrics:
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    cross_val_scores: List[float]
    training_samples: int
    test_samples: int
    trained_at: datetime
```

### Performance Characteristics

- **Model training**: ~2-5 seconds for 100-500 samples
- **Prediction**: <10ms per prediction
- **Accuracy**: ≥95% on test set
- **Model size**: ~500KB (serialized)
- **Features**: 15 engineered features per mixin pair

---

## Stream 5: Pattern Feedback

### Overview

Pattern matching feedback system for continuous learning achieving ≥90% precision. Collects and analyzes feedback to improve pattern recognition accuracy.

### Classes

#### `PatternFeedbackCollector`

Main feedback collection and analysis system.

**Location**: `agents/lib/pattern_feedback.py`

**Constructor**:
```python
PatternFeedbackCollector(
    persistence: Optional[CodegenPersistence] = None
)
```

**Parameters**:
- `persistence`: Optional persistence layer (creates default if not provided)

**Methods**:

##### `record_feedback()`

Record pattern matching feedback.

```python
async def record_feedback(
    feedback: PatternFeedback,
    user_provided: bool = False
) -> UUID
```

**Parameters**:
- `feedback`: Feedback data
- `user_provided`: Whether feedback came from user validation (default: False)

**Returns**: UUID of the recorded feedback

**Raises**: `Exception` if recording fails

**Example**:
```python
from uuid import uuid4

collector = PatternFeedbackCollector()

feedback = PatternFeedback(
    session_id=uuid4(),
    detected_pattern="authentication_pattern",
    detected_confidence=0.85,
    actual_pattern="oauth2_pattern",
    feedback_type="incorrect",
    capabilities_matched=["auth", "security"],
    false_positives=["basic_auth"],
    false_negatives=["oauth2"],
    user_provided=True
)

feedback_id = await collector.record_feedback(feedback, user_provided=True)
print(f"Recorded feedback: {feedback_id}")
```

##### `analyze_feedback()`

Analyze feedback for a pattern to identify improvement opportunities.

```python
async def analyze_feedback(
    pattern_name: str,
    min_samples: int = 20,
    use_cache: bool = True
) -> PatternAnalysis
```

**Parameters**:
- `pattern_name`: Pattern to analyze
- `min_samples`: Minimum feedback samples required for analysis (default: 20)
- `use_cache`: Whether to use cached analysis results (default: True)

**Returns**: `PatternAnalysis` with metrics and recommendations

**Example**:
```python
analysis = await collector.analyze_feedback("authentication_pattern")

if analysis.sufficient_data:
    print(f"Precision: {analysis.precision:.1%}")
    print(f"Sample count: {analysis.sample_count}")
    print("Recommendations:")
    for rec in analysis.recommendations:
        print(f"  - {rec}")
```

##### `get_all_pattern_analyses()`

Get analyses for all patterns with sufficient data.

```python
async def get_all_pattern_analyses(
    min_samples: int = 20
) -> List[PatternAnalysis]
```

**Parameters**:
- `min_samples`: Minimum samples required per pattern (default: 20)

**Returns**: List of pattern analyses sorted by precision (ascending)

**Example**:
```python
all_analyses = await collector.get_all_pattern_analyses(min_samples=30)

print("Patterns needing attention:")
for analysis in all_analyses[:5]:  # Bottom 5
    print(f"{analysis.pattern_name}: {analysis.precision:.1%}")
```

##### `tune_pattern_threshold()`

Tune confidence threshold for pattern based on feedback.

```python
async def tune_pattern_threshold(
    pattern_name: str,
    target_precision: float = 0.90
) -> Optional[float]
```

**Parameters**:
- `pattern_name`: Pattern to tune
- `target_precision`: Target precision (default: 0.90 = 90%)

**Returns**: Recommended confidence threshold (0.0-1.0) or None if insufficient data

**Example**:
```python
threshold = await collector.tune_pattern_threshold(
    pattern_name="authentication_pattern",
    target_precision=0.92
)

if threshold:
    print(f"Recommended threshold: {threshold:.2f}")
```

##### `get_global_precision_metrics()`

Get global pattern matching precision metrics.

```python
async def get_global_precision_metrics() -> Dict[str, Any]
```

**Returns**: Dictionary with overall precision metrics

**Returned Fields**:
- `overall_precision`: Weighted average precision
- `patterns_analyzed`: Number of patterns analyzed
- `patterns_meeting_target`: Number meeting target precision
- `target_precision`: Target precision threshold
- `needs_improvement`: List of patterns below target
- `best_patterns`: Top 5 patterns by precision
- `worst_patterns`: Bottom 5 patterns by precision

**Example**:
```python
metrics = await collector.get_global_precision_metrics()

print(f"Overall precision: {metrics['overall_precision']:.1%}")
print(f"Meeting target: {metrics['patterns_meeting_target']}/{metrics['patterns_analyzed']}")

if metrics['needs_improvement']:
    print("\nPatterns needing improvement:")
    for pattern in metrics['needs_improvement']:
        print(f"  {pattern['pattern']}: {pattern['precision']:.1%}")
```

##### `cleanup()`

Cleanup resources.

```python
async def cleanup() -> None
```

**Example**:
```python
await collector.cleanup()
```

### Data Classes

#### `PatternFeedback`

Pattern matching feedback record.

```python
@dataclass
class PatternFeedback:
    session_id: UUID
    detected_pattern: str
    detected_confidence: float
    actual_pattern: str
    feedback_type: str  # 'correct', 'incorrect', 'partial', 'adjusted'
    capabilities_matched: List[str] = field(default_factory=list)
    false_positives: List[str] = field(default_factory=list)
    false_negatives: List[str] = field(default_factory=list)
    user_provided: bool = False
    contract_json: Optional[Dict[str, Any]] = None
```

#### `PatternAnalysis`

Analysis results for pattern feedback.

```python
@dataclass
class PatternAnalysis:
    pattern_name: str
    sufficient_data: bool
    sample_count: int
    precision: float
    recall: Optional[float] = None
    f1_score: Optional[float] = None
    correct_count: int = 0
    incorrect_count: int = 0
    partial_count: int = 0
    false_positive_counts: Dict[str, int] = field(default_factory=dict)
    false_negative_counts: Dict[str, int] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    suggested_threshold: Optional[float] = None
```

### Performance Characteristics

- **Feedback recording**: <50ms
- **Analysis (cached)**: <10ms
- **Analysis (uncached)**: <200ms for 1000 samples
- **Global metrics**: <500ms
- **Cache TTL**: 5 minutes

---

## Stream 6: Event Optimization

### Overview

High-performance event processing with batch processing, circuit breaker, compression, and connection pooling. Target performance: p95 latency ≤200ms (from ~500ms baseline).

### Classes

#### `EventOptimizer`

Main event optimizer with batching, circuit breaker, and connection pooling.

**Location**: `agents/lib/event_optimizer.py`

**Constructor**:
```python
EventOptimizer(
    bootstrap_servers: str,
    config: Optional[OptimizerConfig] = None,
    persistence: Optional[CodegenPersistence] = None,
    batch_config: Optional[BatchConfig] = None,
    circuit_config: Optional[CircuitBreakerConfig] = None
)
```

**Parameters**:
- `bootstrap_servers`: Kafka bootstrap servers
- `config`: Optional optimizer configuration
- `persistence`: Optional persistence layer for metrics
- `batch_config`: Optional batch configuration override
- `circuit_config`: Optional circuit breaker configuration override

**Methods**:

##### `publish_event()`

Publish single event with optimizations.

```python
async def publish_event(event: BaseEvent) -> None
```

**Parameters**:
- `event`: Event to publish

**Example**:
```python
optimizer = EventOptimizer(bootstrap_servers="localhost:9092")

event = MyEvent(
    service="codegen",
    payload={"node_type": "EFFECT", "status": "generated"}
)

await optimizer.publish_event(event)
```

##### `publish_batch()`

Publish batch of events efficiently.

```python
async def publish_batch(events: List[BaseEvent]) -> None
```

**Parameters**:
- `events`: List of events to publish

**Example**:
```python
events = [
    MyEvent(service="codegen", payload={"task": 1}),
    MyEvent(service="codegen", payload={"task": 2}),
    MyEvent(service="codegen", payload={"task": 3})
]

await optimizer.publish_batch(events)
```

##### `create_batch_processor()`

Create a batch processor using this optimizer.

```python
def create_batch_processor() -> BatchProcessor
```

**Returns**: Configured batch processor

**Example**:
```python
batch_processor = optimizer.create_batch_processor()

# Add events to batch
await batch_processor.add_event(event1)
await batch_processor.add_event(event2)

# Events automatically flushed when batch is full or timeout occurs
```

##### `cleanup()`

Cleanup resources.

```python
async def cleanup() -> None
```

**Example**:
```python
await optimizer.cleanup()
```

#### `BatchProcessor`

Batch event processor for improved throughput.

**Location**: `agents/lib/batch_processor.py`

**Constructor**:
```python
BatchProcessor(
    processor_func: Callable[[List[Any]], Any],
    config: Optional[BatchConfig] = None,
    persistence: Optional[CodegenPersistence] = None
)
```

**Parameters**:
- `processor_func`: Async function to process a batch of events
- `config`: Optional batch configuration
- `persistence`: Optional persistence layer for metrics

**Methods**:

##### `add_event()`

Add event to batch.

```python
async def add_event(event: Any) -> Optional[Any]
```

**Parameters**:
- `event`: Event to process

**Returns**: Processing result if batch was flushed, None otherwise

**Example**:
```python
processor = BatchProcessor(
    processor_func=my_batch_handler,
    config=BatchConfig(max_batch_size=10, max_wait_ms=100)
)

result = await processor.add_event(event)
```

##### `flush()`

Force flush current batch.

```python
async def flush() -> Any
```

**Returns**: Processing result

**Example**:
```python
result = await processor.flush()
```

##### `cleanup()`

Cleanup resources and flush remaining events.

```python
async def cleanup() -> None
```

**Example**:
```python
await processor.cleanup()
```

#### `CircuitBreaker`

Circuit breaker for failure resilience.

**Location**: `agents/lib/event_optimizer.py`

**Constructor**:
```python
CircuitBreaker(config: CircuitBreakerConfig)
```

**Methods**:

##### `call()`

Execute function through circuit breaker.

```python
async def call(func, *args, **kwargs) -> Any
```

**Parameters**:
- `func`: Async function to execute
- `*args`: Positional arguments
- `**kwargs`: Keyword arguments

**Returns**: Function result

**Raises**: `RuntimeError` if circuit breaker is OPEN

**Example**:
```python
circuit = CircuitBreaker(CircuitBreakerConfig(
    failure_threshold=5,
    recovery_timeout_ms=10000
))

result = await circuit.call(risky_operation, param1, param2)
```

### Configuration Classes

#### `OptimizerConfig`

Event optimizer configuration.

```python
@dataclass
class OptimizerConfig:
    enable_compression: bool = True
    compression_threshold_bytes: int = 1024  # Compress payloads > 1KB
    max_producer_pool_size: int = 3
    enable_metrics: bool = True
```

#### `BatchConfig`

Batch processing configuration.

```python
@dataclass
class BatchConfig:
    max_batch_size: int = 10
    max_wait_ms: int = 100
    enable_metrics: bool = True
```

#### `CircuitBreakerConfig`

Circuit breaker configuration.

```python
@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5  # Failures before opening
    recovery_timeout_ms: int = 10000  # Time before testing recovery
    success_threshold: int = 2  # Successes to close circuit
```

### Enums

#### `CircuitState`

Circuit breaker states.

```python
class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery
```

### Performance Characteristics

- **Single event latency**: ~50-100ms
- **Batch latency (10 events)**: ~100-150ms (10-15ms per event)
- **Circuit breaker overhead**: <1ms
- **Compression overhead**: ~5-10ms for 10KB payload
- **Producer pool reuse**: ~20ms savings per event

---

## Stream 7: Monitoring

### Overview

Comprehensive monitoring infrastructure with 100% critical path coverage. Provides unified metrics aggregation, real-time threshold checking, alerting, and Prometheus-compatible export.

### Classes

#### `MonitoringSystem`

Main monitoring system for framework components.

**Location**: `agents/lib/monitoring.py`

**Constructor**:
```python
MonitoringSystem(thresholds: Optional[MonitoringThresholds] = None)
```

**Parameters**:
- `thresholds`: Custom threshold configuration (uses defaults if None)

**Methods**:

##### `record_metric()`

Record a metric data point.

```python
async def record_metric(
    name: str,
    value: float,
    metric_type: MetricType,
    labels: Optional[Dict[str, str]] = None,
    help_text: str = ""
) -> None
```

**Parameters**:
- `name`: Metric name (e.g., 'template_load_duration_ms')
- `value`: Metric value
- `metric_type`: Type of metric (COUNTER, GAUGE, HISTOGRAM, SUMMARY)
- `labels`: Optional labels for metric dimensions
- `help_text`: Human-readable description

**Example**:
```python
from lib.monitoring import MonitoringSystem, MetricType

monitoring = MonitoringSystem()

await monitoring.record_metric(
    name="template_load_duration_ms",
    value=45.2,
    metric_type=MetricType.HISTOGRAM,
    labels={"template_type": "EFFECT"},
    help_text="Template load duration in milliseconds"
)
```

##### `collect_all_metrics()`

Collect metrics from all subsystems.

```python
async def collect_all_metrics(
    time_window_minutes: int = 60
) -> Dict[str, Any]
```

**Parameters**:
- `time_window_minutes`: Time window for metric aggregation (default: 60)

**Returns**: Dictionary of aggregated metrics

**Returned Fields**:
- `timestamp`: Collection timestamp
- `time_window_minutes`: Time window used
- `collection_time_ms`: Time taken to collect
- `template_cache`: Template cache metrics
- `parallel_generation`: Parallel generation metrics
- `mixin_learning`: Mixin learning metrics
- `pattern_matching`: Pattern matching metrics
- `event_processing`: Event processing metrics
- `active_alerts_count`: Number of active alerts
- `health_status`: Overall health status

**Example**:
```python
metrics = await monitoring.collect_all_metrics(time_window_minutes=30)

print(f"Collection time: {metrics['collection_time_ms']:.0f}ms")
print(f"Cache hit rate: {metrics['template_cache']['overall_hit_rate']:.1%}")
print(f"Parallel speedup: {metrics['parallel_generation']['avg_speedup']:.2f}x")
```

##### `update_health_status()`

Update health status for a component.

```python
async def update_health_status(
    component: str,
    healthy: bool,
    status: str,
    error_message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None
```

**Parameters**:
- `component`: Component name
- `healthy`: Whether component is healthy
- `status`: Status string ('healthy', 'degraded', 'critical')
- `error_message`: Optional error message if unhealthy
- `metadata`: Optional additional metadata

**Example**:
```python
await monitoring.update_health_status(
    component="template_cache",
    healthy=True,
    status="healthy",
    metadata={"cache_size_mb": 25.5}
)
```

##### `get_active_alerts()`

Get active alerts with optional filtering.

```python
def get_active_alerts(
    severity: Optional[AlertSeverity] = None,
    component: Optional[str] = None
) -> List[MonitoringAlert]
```

**Parameters**:
- `severity`: Filter by severity level (optional)
- `component`: Filter by component name (optional)

**Returns**: List of active alerts

**Example**:
```python
critical_alerts = monitoring.get_active_alerts(severity=AlertSeverity.CRITICAL)

for alert in critical_alerts:
    print(f"[{alert.severity.value}] {alert.message}")
```

##### `get_monitoring_summary()`

Get comprehensive monitoring summary.

```python
def get_monitoring_summary() -> Dict[str, Any]
```

**Returns**: Dictionary with monitoring summary

**Returned Fields**:
- `timestamp`: Summary timestamp
- `health`: Health status breakdown
- `alerts`: Alert counts by severity
- `metrics`: Overall metrics statistics

**Example**:
```python
summary = monitoring.get_monitoring_summary()

print(f"Overall health: {summary['health']['overall_status']}")
print(f"Critical alerts: {summary['alerts']['critical_count']}")
print(f"Total metrics tracked: {summary['metrics']['total_metric_types']}")
```

##### `export_prometheus_metrics()`

Export metrics in Prometheus text format.

```python
async def export_prometheus_metrics() -> str
```

**Returns**: Prometheus-formatted metrics string

**Example**:
```python
prom_metrics = await monitoring.export_prometheus_metrics()

# Write to file for Prometheus scraping
with open("/var/metrics/phase7.prom", "w") as f:
    f.write(prom_metrics)
```

##### `clear_metrics()`

Clear all metrics and reset monitoring state.

```python
async def clear_metrics() -> None
```

**Example**:
```python
await monitoring.clear_metrics()
```

### Configuration Classes

#### `MonitoringThresholds`

Monitoring thresholds configuration.

```python
@dataclass
class MonitoringThresholds:
    # Template caching thresholds
    template_load_ms_warning: float = 50.0
    template_load_ms_critical: float = 100.0
    cache_hit_rate_warning: float = 0.70
    cache_hit_rate_critical: float = 0.60

    # Parallel generation thresholds
    parallel_speedup_warning: float = 2.5
    parallel_speedup_critical: float = 2.0
    generation_time_ms_warning: float = 3000.0
    generation_time_ms_critical: float = 5000.0

    # Mixin learning thresholds
    mixin_accuracy_warning: float = 0.90
    mixin_accuracy_critical: float = 0.85
    compatibility_score_warning: float = 0.80
    compatibility_score_critical: float = 0.70

    # Pattern matching thresholds
    pattern_precision_warning: float = 0.85
    pattern_precision_critical: float = 0.80
    false_positive_rate_warning: float = 0.15
    false_positive_rate_critical: float = 0.20

    # Event processing thresholds
    event_latency_p95_warning: float = 200.0
    event_latency_p95_critical: float = 300.0
    event_success_rate_warning: float = 0.95
    event_success_rate_critical: float = 0.90

    # Quality thresholds
    quality_score_warning: float = 0.80
    quality_score_critical: float = 0.75
    validation_pass_rate_warning: float = 0.90
    validation_pass_rate_critical: float = 0.85
```

### Data Classes

#### `MonitoringAlert`

Monitoring alert with full context.

```python
@dataclass
class MonitoringAlert:
    alert_id: str
    severity: AlertSeverity
    metric_name: str
    threshold: float
    actual_value: float
    message: str
    component: str
    labels: Dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    resolution_message: Optional[str] = None
```

#### `HealthStatus`

Component health status.

```python
@dataclass
class HealthStatus:
    component: str
    healthy: bool
    status: str
    last_check: datetime
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
```

#### `Metric`

Single metric data point.

```python
@dataclass
class Metric:
    name: str
    value: float
    metric_type: MetricType
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    help_text: str = ""
```

### Enums

#### `AlertSeverity`

Alert severity levels.

```python
class AlertSeverity(Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
```

#### `MetricType`

Metric types for classification.

```python
class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"
```

### Convenience Functions

#### `get_monitoring_system()`

Get or create global monitoring system instance.

```python
def get_monitoring_system(
    thresholds: Optional[MonitoringThresholds] = None
) -> MonitoringSystem
```

**Parameters**:
- `thresholds`: Optional custom thresholds

**Returns**: MonitoringSystem instance

#### `record_metric()`

Record a metric data point (convenience function).

```python
async def record_metric(
    name: str,
    value: float,
    metric_type: MetricType,
    labels: Optional[Dict[str, str]] = None,
    help_text: str = ""
) -> None
```

#### `collect_all_metrics()`

Collect metrics from all subsystems (convenience function).

```python
async def collect_all_metrics(time_window_minutes: int = 60) -> Dict[str, Any]
```

#### `update_health_status()`

Update health status for a component (convenience function).

```python
async def update_health_status(
    component: str,
    healthy: bool,
    status: str,
    error_message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None
```

#### `get_active_alerts()`

Get active alerts (convenience function).

```python
def get_active_alerts(
    severity: Optional[AlertSeverity] = None,
    component: Optional[str] = None
) -> List[MonitoringAlert]
```

#### `get_monitoring_summary()`

Get monitoring summary (convenience function).

```python
def get_monitoring_summary() -> Dict[str, Any]
```

#### `export_prometheus_metrics()`

Export Prometheus metrics (convenience function).

```python
async def export_prometheus_metrics() -> str
```

### Performance Characteristics

- **Metric recording**: <50ms
- **Alert generation**: <200ms
- **Metrics collection**: <500ms (all subsystems)
- **Prometheus export**: <100ms
- **Health check**: <10ms per component

---

## Stream 8: Structured Logging

### Overview

High-performance structured JSON logging framework with correlation ID support, component tagging, and <1ms overhead per log entry.

### Classes

#### `StructuredLogger`

Main structured JSON logger with correlation ID support.

**Location**: `agents/lib/structured_logger.py`

**Constructor**:
```python
StructuredLogger(
    name: str,
    component: Optional[str] = None,
    level: LogLevel = LogLevel.INFO
)
```

**Parameters**:
- `name`: Logger name (typically module name)
- `component`: Component identifier (e.g., agent name, service name)
- `level`: Minimum log level to emit (default: INFO)

**Methods**:

##### `set_correlation_id()`

Set correlation ID for request tracing.

```python
def set_correlation_id(correlation_id: UUID | str) -> None
```

**Parameters**:
- `correlation_id`: Correlation ID (UUID or string)

**Example**:
```python
from uuid import uuid4

logger = StructuredLogger(__name__, component="agent-researcher")
logger.set_correlation_id(uuid4())
```

##### `set_session_id()`

Set session ID for session tracking.

```python
def set_session_id(session_id: UUID | str) -> None
```

**Parameters**:
- `session_id`: Session ID (UUID or string)

**Example**:
```python
logger.set_session_id(uuid4())
```

##### `set_component()`

Set component identifier.

```python
def set_component(component: str) -> None
```

**Parameters**:
- `component`: Component identifier

**Example**:
```python
logger.set_component("agent-code-generator")
```

##### `debug()`

Log debug message.

```python
def debug(message: str, metadata: Optional[Dict[str, Any]] = None) -> None
```

**Parameters**:
- `message`: Log message
- `metadata`: Additional structured metadata

**Example**:
```python
logger.debug("Template loaded", metadata={"template": "EFFECT", "size_kb": 12.5})
```

##### `info()`

Log info message.

```python
def info(message: str, metadata: Optional[Dict[str, Any]] = None) -> None
```

**Parameters**:
- `message`: Log message
- `metadata`: Additional structured metadata

**Example**:
```python
logger.info("Task started", metadata={"task_id": "123", "phase": "research"})
```

##### `warning()`

Log warning message.

```python
def warning(message: str, metadata: Optional[Dict[str, Any]] = None) -> None
```

**Parameters**:
- `message`: Log message
- `metadata`: Additional structured metadata

**Example**:
```python
logger.warning("Cache near capacity", metadata={"usage_percent": 85})
```

##### `error()`

Log error message with optional exception info.

```python
def error(
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
    exc_info: Optional[Exception] = None
) -> None
```

**Parameters**:
- `message`: Log message
- `metadata`: Additional structured metadata
- `exc_info`: Exception information

**Example**:
```python
try:
    result = risky_operation()
except ValueError as e:
    logger.error("Operation failed", metadata={"operation": "validation"}, exc_info=e)
```

##### `critical()`

Log critical message with optional exception info.

```python
def critical(
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
    exc_info: Optional[Exception] = None
) -> None
```

**Parameters**:
- `message`: Log message
- `metadata`: Additional structured metadata
- `exc_info`: Exception information

**Example**:
```python
logger.critical("System failure", metadata={"component": "database"}, exc_info=e)
```

### Convenience Functions

#### `get_logger()`

Factory function to create structured logger.

```python
def get_logger(name: str, component: Optional[str] = None) -> StructuredLogger
```

**Parameters**:
- `name`: Logger name (typically __name__)
- `component`: Component identifier

**Returns**: StructuredLogger instance

**Example**:
```python
from lib.structured_logger import get_logger

logger = get_logger(__name__, component="agent-researcher")
```

#### `set_global_correlation_id()`

Set correlation ID in global context.

```python
def set_global_correlation_id(correlation_id: UUID | str) -> None
```

**Parameters**:
- `correlation_id`: Correlation ID

**Example**:
```python
from lib.structured_logger import set_global_correlation_id
from uuid import uuid4

set_global_correlation_id(uuid4())
```

#### `set_global_session_id()`

Set session ID in global context.

```python
def set_global_session_id(session_id: UUID | str) -> None
```

**Parameters**:
- `session_id`: Session ID

**Example**:
```python
from lib.structured_logger import set_global_session_id

set_global_session_id(uuid4())
```

#### `get_correlation_id()`

Get current correlation ID from context.

```python
def get_correlation_id() -> Optional[str]
```

**Returns**: Current correlation ID or None

**Example**:
```python
from lib.structured_logger import get_correlation_id

corr_id = get_correlation_id()
if corr_id:
    print(f"Current correlation ID: {corr_id}")
```

#### `get_session_id()`

Get current session ID from context.

```python
def get_session_id() -> Optional[str]
```

**Returns**: Current session ID or None

**Example**:
```python
from lib.structured_logger import get_session_id

sess_id = get_session_id()
```

### Data Classes

#### `LogRecord`

Structured log record for JSON serialization.

```python
@dataclass
class LogRecord:
    timestamp: str
    level: str
    logger_name: str
    message: str
    correlation_id: Optional[str] = None
    session_id: Optional[str] = None
    component: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
```

### Enums

#### `LogLevel`

Standard logging levels.

```python
class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
```

### JSON Output Format

All logs are output as JSON with the following structure:

```json
{
  "timestamp": "2025-01-15T10:30:45.123456+00:00",
  "level": "INFO",
  "logger_name": "agent_researcher",
  "message": "Research task completed",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "component": "agent-researcher",
  "metadata": {
    "task_id": "123",
    "duration_ms": 1234,
    "results_count": 42
  }
}
```

### Performance Characteristics

- **Log entry overhead**: <1ms per log
- **Context setup**: <0.1ms
- **JSON serialization**: <0.5ms
- **Thread-safe**: Uses context variables

---

## Integration Examples

### Complete Workflow Example

```python
from uuid import uuid4
from lib.structured_logger import get_logger
from lib.template_cache import TemplateCache
from lib.parallel_generator import ParallelGenerator, GenerationJob
from lib.mixin_learner import MixinLearner
from lib.pattern_feedback import PatternFeedbackCollector, PatternFeedback
from lib.event_optimizer import EventOptimizer
from lib.monitoring import get_monitoring_system, MetricType

# Initialize logger with correlation ID
correlation_id = uuid4()
logger = get_logger(__name__, component="codegen-workflow")
logger.set_correlation_id(correlation_id)

# Initialize monitoring
monitoring = get_monitoring_system()

# Initialize template cache
cache = TemplateCache(max_templates=100, ttl_seconds=3600)
cache.warmup(templates_dir=Path("/templates"), template_types=["EFFECT", "COMPUTE"])

logger.info("Template cache warmed up", metadata=cache.get_stats())

# Initialize mixin learner
learner = MixinLearner(auto_train=True)
if not learner.is_trained():
    metrics = await learner.train_model()
    logger.info("Mixin model trained", metadata={
        "accuracy": metrics.accuracy,
        "samples": metrics.training_samples
    })

# Generate nodes in parallel
generator = ParallelGenerator(max_workers=3)

jobs = [
    GenerationJob(
        job_id=uuid4(),
        node_type="EFFECT",
        microservice_name="UserService",
        domain="authentication",
        analysis_result=prd_analysis,
        output_directory="/output"
    )
]

results = await generator.generate_nodes_parallel(jobs, session_id=correlation_id)

# Record metrics
for result in results:
    await monitoring.record_metric(
        name="generation_duration_ms",
        value=result.duration_ms,
        metric_type=MetricType.HISTOGRAM,
        labels={"node_type": result.node_type, "success": str(result.success)}
    )

# Record pattern feedback
feedback_collector = PatternFeedbackCollector()
feedback = PatternFeedback(
    session_id=correlation_id,
    detected_pattern="auth_effect",
    detected_confidence=0.92,
    actual_pattern="auth_effect",
    feedback_type="correct"
)
await feedback_collector.record_feedback(feedback)

# Publish events
optimizer = EventOptimizer(bootstrap_servers="localhost:9092")
events = [create_event(r) for r in results]
await optimizer.publish_batch(events)

# Collect final metrics
final_metrics = await monitoring.collect_all_metrics(time_window_minutes=60)
logger.info("Workflow completed", metadata=final_metrics)

# Cleanup
await generator.cleanup()
await feedback_collector.cleanup()
await optimizer.cleanup()
```

---

## Error Codes and Exceptions

### Common Exceptions

- `ValueError`: Invalid parameters or configuration
- `OnexError`: ONEX framework errors (from omnibase_core)
- `RuntimeError`: Circuit breaker open, system failures
- `TimeoutError`: Operation timeout in parallel generation
- `Exception`: Generic errors (always logged with full context)

### Error Handling Best Practices

1. **Always use structured logging for errors**:
```python
try:
    result = risky_operation()
except ValueError as e:
    logger.error("Validation failed", metadata={"operation": "validate"}, exc_info=e)
    raise
```

2. **Use correlation IDs for request tracing**:
```python
logger.set_correlation_id(correlation_id)
# All subsequent logs include correlation_id
```

3. **Record metrics for failures**:
```python
await monitoring.record_metric(
    name="operation_failures",
    value=1,
    metric_type=MetricType.COUNTER,
    labels={"operation": "template_load", "error": type(e).__name__}
)
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-10-15 | Initial agent framework API documentation |

---

## See Also

- [User Guide](./USER_GUIDE.md)
- [Architecture](./ARCHITECTURE.md)
- [Operations Guide](./OPERATIONS_GUIDE.md)
- [Integration Guide](./INTEGRATION_GUIDE.md)
- [Summary](./SUMMARY.md)
