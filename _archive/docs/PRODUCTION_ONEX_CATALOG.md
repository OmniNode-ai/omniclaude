# Production ONEX Node Catalog & Refactoring Reference

**Generated**: 2025-10-21
**Source Repositories**: omniarchon
**Purpose**: Reference library for code refinement and ONEX pattern compliance

---

## Executive Summary

### Node Inventory (omniarchon)

| Node Type | Count | Production Examples |
|-----------|-------|---------------------|
| **Effect** | 16 | Database, Qdrant vector, Kafka consumers, pattern storage |
| **Compute** | 12 | Intent classifiers, keyword extractors, analyzers, scorers |
| **Reducer** | 1 | Usage analytics aggregator |
| **Orchestrator** | 5 | Pattern assemblers, quality gates, consensus validators, feedback loops |
| **Total** | 34 | Fully production-ready ONEX nodes |

### Key Repositories

1. **omniarchon** (`../omniarchon`): 34 production nodes
2. **omninode_bridge** (`../omninode_bridge`): No ONEX nodes found (legacy patterns)

---

## Best Production Examples by Node Type

### 1. Effect Nodes (16 total)

**Best Examples**:

#### 🌟 Qdrant Search Effect
**File**: `../omniarchon/services/intelligence/onex/effects/node_qdrant_search_effect.py`

**Why This Example**:
- Production-proven vector search (<100ms for 10K vectors)
- Clean transaction management with `transaction_manager.begin()`
- Comprehensive metrics tracking (`_record_metric`)
- Proper error handling with context logging
- Strong typing throughout

**Key Patterns**:
```python
class NodeQdrantSearchEffect(NodeBaseEffect):
    """
    Performs semantic vector search in a Qdrant collection.

    Performance Targets:
    - <100ms search latency for 10K vectors
    - Configurable HNSW search parameters for speed/accuracy trade-off
    """

    def __init__(
        self,
        qdrant_client: AsyncQdrantClient,
        openai_client: AsyncOpenAI,
    ):
        super().__init__()
        self.qdrant_client = qdrant_client
        self.openai_client = openai_client

    async def execute_effect(
        self, contract: ModelContractQdrantSearchEffect
    ) -> ModelQdrantSearchResult:
        """Execute semantic similarity search in Qdrant."""
        logger.info(f"Executing Qdrant search effect...")
        start_time = time.perf_counter()

        async with self.transaction_manager.begin():
            try:
                # 1. Generate query embedding
                query_vector = await self._get_query_embedding(contract.query_text)

                # 2. Perform search
                search_result = await self.qdrant_client.search(
                    collection_name=contract.collection_name,
                    query_vector=query_vector,
                    limit=contract.limit,
                    # ... more params
                )

                # 3. Format results
                hits = [
                    ModelQdrantHit(id=point.id, score=point.score, payload=point.payload)
                    for point in search_result
                ]

                # 4. Record metrics
                self._record_metric("search_duration_ms", search_duration_ms)

                return ModelQdrantSearchResult(hits=hits, ...)

            except Exception as e:
                logger.error(f"Error during Qdrant search: {e}", exc_info=True)
                raise
```

**Other Production Effect Nodes**:
- `node_qdrant_vector_index_effect.py` - Batch vector indexing
- `node_qdrant_update_effect.py` - Point updates
- `node_qdrant_health_effect.py` - Health checks
- `node_pattern_storage_effect.py` - Pattern persistence
- `node_pattern_query_effect.py` - Pattern retrieval
- `node_pattern_update_effect.py` - Pattern updates
- `node_archon_kafka_consumer_effect.py` - Event consumption
- `node_intelligence_adapter_effect.py` - Intelligence integration

---

### 2. Compute Nodes (12 total)

**Best Examples**:

#### 🌟 Intent Classifier Compute
**File**: `../omniarchon/services/intelligence/src/services/pattern_learning/phase1_foundation/extraction/node_intent_classifier_compute.py`

**Why This Example**:
- Pure functional compute (no side effects)
- Deterministic results for same inputs
- Strong Pydantic models for input/output
- TF-IDF algorithm with pattern matching
- Performance optimized (<50ms target)

**Key Patterns**:
```python
# Input/Output Models with Pydantic
class ModelIntentClassificationInput(BaseModel):
    """Input state for intent classification."""
    request_text: str = Field(..., description="Text to classify for intent")
    correlation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Correlation ID for tracing",
    )
    confidence_threshold: float = Field(
        default=0.5, description="Minimum confidence threshold", ge=0.0, le=1.0
    )

class ModelIntentClassificationOutput(BaseModel):
    """Output state for intent classification."""
    intent: str = Field(..., description="Classified intent type")
    confidence: float = Field(..., description="Classification confidence (0.0-1.0)")
    keywords: List[str] = Field(default_factory=list)
    all_scores: Dict[str, float] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(...)

# Node Implementation
class NodeIntentClassifierCompute:
    """
    ONEX-Compliant Compute Node for Intent Classification.

    ONEX Patterns:
    - Pure functional computation (no side effects)
    - Deterministic results for same inputs
    - Correlation ID propagation
    - Performance optimized (<50ms target)
    """

    # Business logic constants
    INTENT_PATTERNS: Dict[str, List[str]] = {
        "code_generation": ["generate", "create", "implement", ...],
        "debugging": ["debug", "fix", "error", ...],
        # ... more patterns
    }

    async def execute_compute(
        self, input_state: ModelIntentClassificationInput
    ) -> ModelIntentClassificationOutput:
        """Execute intent classification (ONEX NodeCompute interface)."""
        start_time = time.time()

        try:
            # Validate input
            if not input_state.request_text.strip():
                return ModelIntentClassificationOutput(
                    intent="unknown",
                    confidence=0.0,
                    # ... error result
                )

            # Classify intent using pure functional algorithm
            classification_result = self._classify_intent(
                text=input_state.request_text,
                confidence_threshold=input_state.confidence_threshold,
            )

            # Build output
            return ModelIntentClassificationOutput(
                intent=classification_result["intent"],
                confidence=classification_result["confidence"],
                keywords=classification_result["keywords"],
                correlation_id=input_state.correlation_id,
            )

        except Exception as e:
            # Graceful error handling
            return ModelIntentClassificationOutput(
                intent="unknown",
                confidence=0.0,
                metadata={"error": str(e)},
                correlation_id=input_state.correlation_id,
            )
```

**Other Production Compute Nodes**:
- `node_keyword_extractor_compute.py` - TF-IDF keyword extraction
- `node_execution_analyzer_compute.py` - Execution trace analysis
- `node_success_scorer_compute.py` - Success metric computation
- `node_onex_validator_compute.py` - ONEX compliance validation
- `node_pattern_similarity_compute.py` - Pattern matching
- `node_hybrid_scorer_compute.py` - Hybrid scoring algorithms

---

### 3. Reducer Nodes (1 total)

**Best Example**:

#### 🌟 Usage Analytics Reducer
**File**: `../omniarchon/services/intelligence/src/services/pattern_learning/phase4_traceability/node_usage_analytics_reducer.py`

**Why This Example**:
- Pure data aggregation (no external I/O)
- Comprehensive analytics (usage, success, performance, trends)
- Stateless operations
- Efficient percentile calculations
- Strong contract models using dataclasses

**Key Patterns**:
```python
# Contract Models using dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID, uuid4

class UsageTrendType(str, Enum):
    """Pattern usage trend classifications"""
    GROWING = "growing"
    STABLE = "stable"
    DECLINING = "declining"
    EMERGING = "emerging"
    ABANDONED = "abandoned"

@dataclass
class UsageFrequencyMetrics:
    """Pattern usage frequency metrics."""
    total_executions: int = 0
    executions_per_day: float = 0.0
    executions_per_week: float = 0.0
    unique_contexts: int = 0
    peak_daily_usage: int = 0
    time_since_last_use: Optional[float] = None

@dataclass
class ModelUsageAnalyticsInput:
    """Input contract for usage analytics reducer node."""
    pattern_id: UUID
    time_window_start: datetime
    time_window_end: datetime
    time_window_type: TimeWindowType = TimeWindowType.DAILY
    execution_data: List[Dict[str, Any]] = field(default_factory=list)
    correlation_id: UUID = field(default_factory=uuid4)

    def __post_init__(self):
        """Validate input contract after initialization."""
        if self.time_window_end <= self.time_window_start:
            raise ValueError("time_window_end must be after time_window_start")

# Node Implementation
class NodeUsageAnalyticsReducer:
    """
    ONEX Reducer node for pattern usage analytics aggregation.

    Features:
    - Pure functional operations (no external I/O)
    - Stateless (no instance state between calls)
    - Performance target: <500ms
    """

    async def execute_reduction(
        self, contract: ModelUsageAnalyticsInput
    ) -> ModelUsageAnalyticsOutput:
        """Execute analytics reduction on pattern usage data."""
        start_time = time.time()

        try:
            # Core metrics (always computed)
            usage_metrics = self._compute_usage_frequency(
                contract.execution_data,
                contract.time_window_start,
                contract.time_window_end
            )

            success_metrics = self._compute_success_metrics(
                contract.execution_data
            )

            # Optional metrics (based on flags)
            performance_metrics = None
            if contract.include_performance:
                performance_metrics = self._compute_performance_metrics(
                    contract.execution_data
                )

            # Build output
            return ModelUsageAnalyticsOutput(
                pattern_id=contract.pattern_id,
                usage_metrics=usage_metrics,
                success_metrics=success_metrics,
                performance_metrics=performance_metrics,
                # ... more fields
            )

        except Exception as e:
            logger.error(f"Analytics computation failed: {e}")
            raise

    def _compute_percentile(
        self, sorted_values: List[float], percentile: int
    ) -> float:
        """Compute percentile from sorted values."""
        if not sorted_values:
            return 0.0

        index = (percentile / 100) * (len(sorted_values) - 1)
        lower = int(index)
        upper = min(lower + 1, len(sorted_values) - 1)
        weight = index - lower

        return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
```

---

### 4. Orchestrator Nodes (5 total)

**Best Example**:

#### 🌟 Pattern Assembler Orchestrator
**File**: `../omniarchon/services/intelligence/src/services/pattern_learning/phase1_foundation/extraction/node_pattern_assembler_orchestrator.py`

**Why This Example**:
- Coordinates multiple compute nodes
- Parallel execution with asyncio
- Correlation ID propagation
- Performance target (<200ms total pipeline)
- Error isolation and graceful degradation

**Key Patterns**:
```python
class NodePatternAssemblerOrchestrator:
    """
    ONEX-Compliant Orchestrator Node for Pattern Assembly.

    Orchestrates the pattern extraction pipeline by coordinating:
    1. Intent Classification (NodeCompute)
    2. Keyword Extraction (NodeCompute)
    3. Execution Analysis (NodeCompute)
    4. Success Scoring (NodeCompute)

    ONEX Patterns:
    - Workflow coordination
    - Correlation ID propagation
    - Parallel execution where possible
    - Performance target: <200ms total pipeline
    """

    def __init__(self) -> None:
        """Initialize orchestrator with compute nodes."""
        self.intent_classifier = NodeIntentClassifierCompute()
        self.keyword_extractor = NodeKeywordExtractorCompute()
        self.execution_analyzer = NodeExecutionAnalyzerCompute()
        self.success_scorer = NodeSuccessScorerCompute()

    async def execute_orchestration(
        self, input_state: ModelPatternExtractionInput
    ) -> ModelPatternExtractionOutput:
        """Execute pattern extraction orchestration."""
        import asyncio
        start_time = time.time()

        try:
            correlation_id = input_state.correlation_id

            # Phase 1: Parallel execution of independent nodes
            intent_task = asyncio.create_task(
                self._classify_intent(
                    request_text=input_state.request_text,
                    correlation_id=correlation_id,
                )
            )

            keyword_task = asyncio.create_task(
                self._extract_keywords(
                    context_text=input_state.request_text,
                    correlation_id=correlation_id,
                )
            )

            execution_task = asyncio.create_task(
                self._analyze_execution(
                    execution_trace=input_state.execution_trace,
                    correlation_id=correlation_id,
                )
            )

            # Wait for all parallel operations
            intent_result, keyword_result, execution_result = await asyncio.gather(
                intent_task, keyword_task, execution_task
            )

            # Phase 2: Success scoring (depends on execution analysis)
            success_result = await self._score_success(...)

            # Phase 3: Pattern Assembly
            assembled_pattern = self._assemble_pattern(
                intent_result, keyword_result, execution_result, success_result
            )

            # Build output
            return ModelPatternExtractionOutput(
                intent=intent_result.intent,
                keywords=keyword_result.keywords,
                assembled_pattern=assembled_pattern,
                correlation_id=correlation_id,
            )

        except Exception as e:
            # Graceful error handling
            return ModelPatternExtractionOutput(
                intent="unknown",
                metadata={"error": str(e), "orchestration_failed": True},
                correlation_id=input_state.correlation_id,
            )
```

**Other Production Orchestrator Nodes**:
- `node_quality_gate_orchestrator.py` - Quality validation workflows
- `node_consensus_validator_orchestrator.py` - Multi-validator consensus
- `node_feedback_loop_orchestrator.py` - Feedback processing

---

## Key Patterns for ONEX Compliance

### 1. Pydantic Model Patterns (Fixes G12, G13, G14)

#### ✅ CORRECT: Modern Pydantic v2 with ConfigDict

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4

class ModelIntentClassificationInput(BaseModel):
    """Input state for intent classification."""

    # Use Field with explicit descriptions
    request_text: str = Field(
        ...,
        description="Text to classify for intent"
    )

    correlation_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Correlation ID for tracing",
    )

    confidence_threshold: float = Field(
        default=0.5,
        description="Minimum confidence threshold",
        ge=0.0,
        le=1.0
    )

    # Use specific types instead of Any when possible
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )

    # Modern Pydantic v2 config using ConfigDict
    model_config = ConfigDict(
        extra="forbid",  # or "allow" or "ignore"
        use_enum_values=False,
        validate_assignment=True,
        str_strip_whitespace=True,
    )
```

#### ❌ LEGACY: Old Pydantic v1 Config class (G12 warning)

```python
# DON'T USE THIS - deprecated in Pydantic v2
class Config:
    extra = "forbid"
    use_enum_values = True
```

**Fix**: Replace `class Config` with `model_config = ConfigDict(...)`

---

### 2. Type Hints Patterns (Fixes G13)

#### ✅ CORRECT: Full type hints with proper imports

```python
from typing import Dict, List, Optional, Any, Union
from uuid import UUID
from datetime import datetime

class NodeUsageAnalyticsReducer:
    """Usage analytics reducer with proper type hints."""

    def __init__(self) -> None:
        """Initialize reducer."""
        self.contract = ModelContractUsageAnalytics()

    async def execute_reduction(
        self, contract: ModelUsageAnalyticsInput
    ) -> ModelUsageAnalyticsOutput:
        """Execute analytics reduction with typed parameters."""
        pass

    def _compute_percentile(
        self, sorted_values: List[float], percentile: int
    ) -> float:
        """Compute percentile with typed parameters and return."""
        if not sorted_values:
            return 0.0
        # ... implementation
```

**Key Rules**:
1. **Always** type hint function parameters
2. **Always** type hint return values (including `-> None`)
3. Use specific types: `List[str]`, `Dict[str, Any]`, `Optional[int]`
4. Import types from `typing` module

---

### 3. Dataclass vs Pydantic BaseModel

#### Production Usage Guide

**Use Dataclasses** for:
- Contract models (simple data containers)
- Internal data structures
- Performance-critical code (dataclasses are faster)

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class UsageFrequencyMetrics:
    """Usage frequency metrics using dataclass."""
    total_executions: int = 0
    executions_per_day: float = 0.0
    unique_contexts: int = 0
    time_since_last_use: Optional[float] = None
```

**Use Pydantic BaseModel** for:
- API input/output models (automatic validation)
- Complex validation requirements
- JSON serialization needs

```python
from pydantic import BaseModel, Field, validator

class ModelQdrantSearchResult(BaseModel):
    """Search result with validation using Pydantic."""
    hits: List[ModelQdrantHit]
    search_time_ms: float
    total_results: int

    @validator('search_time_ms')
    def validate_positive_time(cls, v):
        if v < 0:
            raise ValueError('search_time_ms must be positive')
        return v
```

---

### 4. Error Handling Patterns

#### Production Pattern: Context-Rich Error Handling

```python
import logging
logger = logging.getLogger(__name__)

async def execute_effect(
    self, contract: ModelContractQdrantSearchEffect
) -> ModelQdrantSearchResult:
    """Execute effect with proper error handling."""
    logger.info(f"Executing Qdrant search effect for '{contract.collection_name}'")
    start_time = time.perf_counter()

    async with self.transaction_manager.begin():
        try:
            # Operation implementation
            result = await self._perform_search(contract)

            # Success logging with metrics
            logger.info(
                f"Search completed in {duration_ms:.2f}ms, "
                f"found {len(result.hits)} results"
            )

            return result

        except Exception as e:
            # Context-rich error logging
            logger.error(
                f"Error during Qdrant search on collection '{contract.collection_name}': {e}",
                exc_info=True  # Include stack trace
            )
            raise  # Re-raise for upstream handling
```

**Key Principles**:
1. Log at operation start (info level)
2. Log success with metrics (info level)
3. Log errors with context and stack trace (error level)
4. Re-raise exceptions for upstream handling

---

### 5. Transaction Management Pattern

#### Production Pattern: Effect Node Transactions

```python
async def execute_effect(
    self, contract: ModelContractEffect
) -> ModelResultEffect:
    """Execute effect within transaction context."""

    # Always use transaction manager for effect nodes
    async with self.transaction_manager.begin():
        try:
            # Perform side effect operations
            result = await self._perform_operation(contract)

            # Transaction commits on successful exit
            return result

        except Exception as e:
            # Transaction automatically rolls back on exception
            logger.error(f"Operation failed: {e}")
            raise
```

**Key Points**:
- Effect nodes **MUST** use `self.transaction_manager.begin()`
- Compute/Reducer nodes **NEVER** use transactions (pure functions)
- Orchestrators delegate transaction management to effect nodes

---

### 6. Metrics Tracking Pattern

#### Production Pattern: Performance Metrics

```python
import time

class NodeQdrantSearchEffect(NodeBaseEffect):
    """Effect node with metrics tracking."""

    async def execute_effect(
        self, contract: ModelContractQdrantSearchEffect
    ) -> ModelQdrantSearchResult:
        """Execute with performance tracking."""
        start_time = time.perf_counter()

        # Operation implementation
        result = await self._perform_search(contract)

        # Calculate metrics
        total_duration_ms = (time.perf_counter() - start_time) * 1000

        # Record metrics (inherited from NodeBaseEffect)
        self._record_metric("search_duration_ms", total_duration_ms)
        self._record_metric("results_count", len(result.hits))

        return result
```

---

### 7. Helper Methods Pattern

#### Production Pattern: Model Serialization

```python
@dataclass
class ModelUsageAnalyticsOutput:
    """Output with serialization helper."""
    pattern_id: UUID
    usage_metrics: UsageFrequencyMetrics
    computed_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert analytics output to dictionary format."""
        result = {
            "pattern_id": str(self.pattern_id),  # UUID to string
            "usage_metrics": {
                "total_executions": self.usage_metrics.total_executions,
                "executions_per_day": self.usage_metrics.executions_per_day,
                # ... more fields
            },
            "computed_at": self.computed_at.isoformat(),  # datetime to ISO string
            "metadata": self.metadata,
        }

        # Add optional fields if present
        if self.performance_metrics:
            result["performance_metrics"] = {
                "avg_execution_time_ms": self.performance_metrics.avg_execution_time_ms,
                # ... more fields
            }

        return result
```

**Common Helper Methods**:
- `to_dict()` - Serialize to dictionary
- `from_dict(data: Dict)` - Deserialize from dictionary
- `from_api_response(response: Any)` - Parse API responses
- `validate()` - Custom validation logic

---

## Naming Convention Reference

### File Naming

| Pattern | Example | Purpose |
|---------|---------|---------|
| `node_*_effect.py` | `node_qdrant_search_effect.py` | Effect node implementations |
| `node_*_compute.py` | `node_intent_classifier_compute.py` | Compute node implementations |
| `node_*_reducer.py` | `node_usage_analytics_reducer.py` | Reducer node implementations |
| `node_*_orchestrator.py` | `node_pattern_assembler_orchestrator.py` | Orchestrator implementations |
| `model_*.py` | `model_pattern.py` | Data models |
| `model_contract_*.py` | `model_contract_usage_analytics.py` | Contract definitions |
| `enum_*.py` | `enum_node_type.py` | Enumerations |

### Class Naming

| Pattern | Example | Purpose |
|---------|---------|---------|
| `Node<Name>Effect` | `NodeQdrantSearchEffect` | Effect node class |
| `Node<Name>Compute` | `NodeIntentClassifierCompute` | Compute node class |
| `Node<Name>Reducer` | `NodeUsageAnalyticsReducer` | Reducer node class |
| `Node<Name>Orchestrator` | `NodePatternAssemblerOrchestrator` | Orchestrator class |
| `Model<Name>` | `ModelPattern` | Data model class |
| `ModelContract<Type>` | `ModelContractEffect` | Contract class |
| `Enum<Name>` | `EnumNodeType` | Enumeration class |

---

## Common Warning Fixes

### G12: Pydantic Config Deprecation

**Problem**: Using deprecated `class Config` in Pydantic v2

```python
# ❌ WRONG (G12 warning)
class MyModel(BaseModel):
    field: str

    class Config:
        extra = "forbid"
```

**Solution**: Use `model_config = ConfigDict(...)`

```python
# ✅ CORRECT
from pydantic import ConfigDict

class MyModel(BaseModel):
    field: str

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )
```

---

### G13: Missing Type Hints

**Problem**: Missing parameter or return type hints

```python
# ❌ WRONG (G13 warning)
async def execute_compute(self, input_state):
    return result
```

**Solution**: Add full type hints

```python
# ✅ CORRECT
async def execute_compute(
    self, input_state: ModelInput
) -> ModelOutput:
    return result
```

---

### G14: Missing Docstrings

**Problem**: Missing or incomplete docstrings

```python
# ❌ WRONG (G14 warning)
async def execute_compute(self, input_state: ModelInput) -> ModelOutput:
    return result
```

**Solution**: Add comprehensive docstrings

```python
# ✅ CORRECT
async def execute_compute(
    self, input_state: ModelInput
) -> ModelOutput:
    """
    Execute intent classification computation.

    Args:
        input_state: Input state with request text and parameters

    Returns:
        ModelOutput: Classification result with confidence

    Raises:
        ValueError: If input validation fails
    """
    return result
```

---

## Import Patterns

### Standard Import Order

```python
#!/usr/bin/env python3
"""
Module docstring here.
"""

# 1. Standard library imports
import hashlib
import logging
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

# 2. Third-party imports
from pydantic import BaseModel, Field, validator, ConfigDict

# 3. Local imports (relative or absolute)
from .model_contract_base import ModelContractBase
from .node_base_effect import NodeBaseEffect

# Module-level logger
logger = logging.getLogger(__name__)
```

---

## Performance Patterns

### Production Performance Targets

| Node Type | Target | Example |
|-----------|--------|---------|
| Effect (DB) | <100ms | Qdrant search |
| Effect (API) | <200ms | External API calls |
| Compute | <50ms | Intent classification |
| Reducer | <500ms | Analytics aggregation |
| Orchestrator | <200ms | Pattern assembly (parallel) |

### Optimization Techniques

1. **Parallel Execution** (Orchestrators):
```python
import asyncio

# Run independent operations in parallel
results = await asyncio.gather(
    task1(), task2(), task3()
)
```

2. **Efficient Aggregation** (Reducers):
```python
# Pre-sort for percentile calculations
execution_times.sort()
p95 = self._compute_percentile(execution_times, 95)
```

3. **Batch Operations** (Effects):
```python
# Batch insert instead of individual inserts
await self.client.upsert(
    collection_name=collection,
    points=batch_points  # Up to 100 points
)
```

---

## Production File Locations

### omniarchon Repository

**Effect Nodes**:
- `/services/intelligence/onex/effects/node_qdrant_search_effect.py`
- `/services/intelligence/onex/effects/node_qdrant_vector_index_effect.py`
- `/services/intelligence/onex/effects/node_qdrant_update_effect.py`
- `/services/intelligence/onex/effects/node_qdrant_health_effect.py`
- `/services/intelligence/src/pattern_learning/node_pattern_storage_effect.py`
- `/services/intelligence/src/pattern_learning/node_pattern_query_effect.py`
- `/services/intelligence/src/pattern_learning/node_pattern_update_effect.py`

**Compute Nodes**:
- `/services/intelligence/src/services/pattern_learning/phase1_foundation/extraction/node_intent_classifier_compute.py`
- `/services/intelligence/src/services/pattern_learning/phase1_foundation/extraction/node_keyword_extractor_compute.py`
- `/services/intelligence/src/services/pattern_learning/phase1_foundation/extraction/node_execution_analyzer_compute.py`
- `/services/intelligence/src/services/pattern_learning/phase1_foundation/extraction/node_success_scorer_compute.py`
- `/services/intelligence/src/services/pattern_learning/phase3_validation/node_onex_validator_compute.py`

**Reducer Nodes**:
- `/services/intelligence/src/services/pattern_learning/phase4_traceability/node_usage_analytics_reducer.py`

**Orchestrator Nodes**:
- `/services/intelligence/src/services/pattern_learning/phase1_foundation/extraction/node_pattern_assembler_orchestrator.py`
- `/services/intelligence/src/services/pattern_learning/phase3_validation/node_quality_gate_orchestrator.py`
- `/services/intelligence/src/services/pattern_learning/phase3_validation/reporting/node_consensus_validator_orchestrator.py`
- `/services/intelligence/src/services/pattern_learning/phase4_traceability/node_feedback_loop_orchestrator.py`

**Contract Models**:
- `/services/intelligence/onex/contracts/qdrant_contracts.py`
- `/services/intelligence/src/services/pattern_learning/phase4_traceability/model_contract_usage_analytics.py`
- `/docs/onex/examples/contracts/model_contract_base.py`
- `/docs/onex/examples/contracts/specialized/model_contract_effect.py`

---

## Quick Reference Checklist

### Before Refactoring

- [ ] Read relevant production examples from this catalog
- [ ] Identify node type (Effect/Compute/Reducer/Orchestrator)
- [ ] Review naming conventions for target node type
- [ ] Check contract model patterns

### During Refactoring

- [ ] Use `model_config = ConfigDict(...)` instead of `class Config`
- [ ] Add full type hints to all functions
- [ ] Add comprehensive docstrings
- [ ] Follow import order (stdlib → third-party → local)
- [ ] Use appropriate base class (`NodeBaseEffect`, etc.)
- [ ] Implement proper error handling with context logging
- [ ] Add performance metrics tracking for Effect nodes
- [ ] Use transaction manager for Effect nodes only

### After Refactoring

- [ ] Run type checker (mypy/pyright)
- [ ] Run linter with ONEX rules
- [ ] Verify G12, G13, G14 warnings resolved
- [ ] Test with production-like data
- [ ] Measure performance vs targets
- [ ] Update documentation

---

## Additional Resources

### Related Documentation
- ONEX Architecture Patterns: `/docs/ONEX_ARCHITECTURE_PATTERNS_COMPLETE.md`
- Pydantic v2 Migration Guide: https://docs.pydantic.dev/latest/migration/
- ONEX Node Paradigm: `OMNIBASE_CORE_NODE_PARADIGM.md`

### Production Examples by Feature

**Parallel Execution**:
- `node_pattern_assembler_orchestrator.py` (asyncio.gather)

**Transaction Management**:
- `node_qdrant_search_effect.py` (transaction_manager.begin)

**Metrics Tracking**:
- `node_qdrant_search_effect.py` (_record_metric)

**Percentile Calculations**:
- `node_usage_analytics_reducer.py` (_compute_percentile)

**Validation Patterns**:
- `qdrant_contracts.py` (@validator, @root_validator)

**Serialization Helpers**:
- `model_contract_usage_analytics.py` (to_dict method)

---

**End of Catalog**

*This catalog is a living document. Update as new production patterns emerge.*
