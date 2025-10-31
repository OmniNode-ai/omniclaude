# OmniClaude Intelligence System Optimization Plan

**Repository**: OmniNode-ai/omniclaude
**Status**: Phase 1 Complete ✅ | Phase 2-3 Pending
**Created**: 2025-10-30
**Updated**: 2025-10-31
**Target**: Fix query performance (7.5s → <2s) and enable pattern quality scoring

## Implementation Status

**✅ Phase 1: Valkey Caching** - COMPLETED (2025-10-31)
- Commit: `75fc706` on branch `fix/consumer-hardcoded-localhost`
- Files: `agents/lib/intelligence_cache.py`, `agents/lib/manifest_injector.py`, `.env.example`
- Status: Pushed to remote, ready for testing

**⏳ Phase 2: Pattern Quality Scoring** - PENDING

**⏳ Phase 3: Query Optimization** - PENDING

## Overview

This document outlines optimizations we can implement in OmniClaude to improve intelligence system performance and quality, independent of external service changes.

**Related Docs**:
- External requests: `ARCHON_INTELLIGENCE_ENHANCEMENT_REQUESTS.md`
- Architecture: `EVENT_BUS_INTELLIGENCE_IMPLEMENTATION.md`

---

## Problem Statement

### Issue 1: Empty Pattern Quality Metrics
- **Table**: `pattern_quality_metrics` has 0 rows
- **Impact**: No quality-based pattern filtering
- **Root Cause**: Scoring system not implemented

### Issue 2: Slow Intelligence Queries
- **Current**: 7,500ms average query time
- **Target**: <2,000ms
- **Impact**: 34% of manifest injections have degraded results

---

## Implementation Plan

### Phase 1: Valkey Caching Layer ✅ COMPLETED

**Status**: ✅ Implemented and pushed (2025-10-31)
**Commit**: `75fc706` - "feat: implement Phase 1 intelligence optimization with Valkey caching"
**Branch**: `fix/consumer-hardcoded-localhost`

**Objective**: Cache intelligence query results using existing Valkey service

**Implementation Delivered**:

#### 1.1 Create Valkey Client Wrapper

**New File**: `agents/lib/intelligence_cache.py`

```python
"""
Intelligence Cache - Valkey-backed caching for pattern queries

Caches:
- Pattern discovery results (TTL: 5 min)
- Infrastructure topology (TTL: 1 hour)
- Database schemas (TTL: 30 min)
- Model information (TTL: 1 hour)

Performance targets:
- Cache hit rate: >60%
- Cache lookup: <10ms p95
- Reduces Archon load by 60%+
"""

import hashlib
import json
from typing import Any, Dict, List, Optional
from redis.asyncio import Redis
import os

class IntelligenceCache:
    """Valkey-backed cache for intelligence queries"""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        enabled: bool = True,
    ):
        """
        Initialize cache client.

        Args:
            redis_url: Valkey connection URL (default: from env)
            enabled: Enable/disable caching (default: True)
        """
        self.enabled = enabled and os.getenv("ENABLE_INTELLIGENCE_CACHE", "true").lower() == "true"

        if not self.enabled:
            return

        # Valkey is already running at archon-valkey:6379
        self.redis_url = redis_url or os.getenv(
            "VALKEY_URL",
            "redis://archon-valkey:6379/0"  # Use existing service
        )
        self._client: Optional[Redis] = None

    async def connect(self):
        """Establish connection to Valkey"""
        if not self.enabled:
            return

        self._client = await Redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

    async def close(self):
        """Close connection"""
        if self._client:
            await self._client.close()

    def _generate_cache_key(self, operation_type: str, params: Dict[str, Any]) -> str:
        """Generate deterministic cache key from query parameters"""
        # Sort params for consistent hashing
        sorted_params = json.dumps(params, sort_keys=True)
        params_hash = hashlib.md5(sorted_params.encode()).hexdigest()[:12]

        return f"intelligence:{operation_type}:{params_hash}"

    async def get(
        self,
        operation_type: str,
        params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Get cached result if available"""
        if not self.enabled or not self._client:
            return None

        cache_key = self._generate_cache_key(operation_type, params)

        try:
            cached_json = await self._client.get(cache_key)
            if cached_json:
                return json.loads(cached_json)
        except Exception as e:
            # Log but don't fail on cache errors
            logger.warning(f"Cache get failed: {e}")

        return None

    async def set(
        self,
        operation_type: str,
        params: Dict[str, Any],
        result: Dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ):
        """Cache query result with TTL"""
        if not self.enabled or not self._client:
            return

        cache_key = self._generate_cache_key(operation_type, params)

        # Default TTLs by operation type
        if ttl_seconds is None:
            ttl_seconds = {
                "pattern_discovery": 300,      # 5 minutes
                "infrastructure_query": 3600,  # 1 hour
                "schema_query": 1800,          # 30 minutes
                "model_query": 3600,           # 1 hour
            }.get(operation_type, 300)

        try:
            result_json = json.dumps(result)
            await self._client.setex(cache_key, ttl_seconds, result_json)
        except Exception as e:
            logger.warning(f"Cache set failed: {e}")

    async def invalidate_pattern(self, pattern: str):
        """Invalidate cache entries matching pattern"""
        if not self.enabled or not self._client:
            return

        try:
            keys = await self._client.keys(f"intelligence:*{pattern}*")
            if keys:
                await self._client.delete(*keys)
        except Exception as e:
            logger.warning(f"Cache invalidation failed: {e}")

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self.enabled or not self._client:
            return {"enabled": False}

        try:
            info = await self._client.info("stats")
            return {
                "enabled": True,
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "hit_rate": (
                    info["keyspace_hits"] / (info["keyspace_hits"] + info["keyspace_misses"])
                    if (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0)) > 0
                    else 0.0
                ),
            }
        except Exception:
            return {"enabled": True, "error": "Stats unavailable"}
```

#### 1.2 Integrate with Manifest Injector

**Modify**: `agents/lib/manifest_injector.py`

```python
# Add at top
from agents.lib.intelligence_cache import IntelligenceCache

class ManifestInjector:
    def __init__(self):
        # Existing init...
        self.cache = IntelligenceCache()

    async def _query_patterns_with_cache(self, collection_name: str, limit: int):
        """Query patterns with caching"""
        params = {"collection": collection_name, "limit": limit}

        # Try cache first
        cached = await self.cache.get("pattern_discovery", params)
        if cached:
            logger.debug(f"Cache hit for pattern query: {collection_name}")
            return cached

        # Cache miss - query intelligence service
        result = await self._intelligence_client.request_intelligence(
            operation_type="PATTERN_EXTRACTION",
            collection_name=collection_name,
            options={"limit": limit},
        )

        # Cache successful result
        if result.get("success"):
            await self.cache.set("pattern_discovery", params, result)

        return result
```

#### 1.3 Add Caching Configuration

**Modify**: `.env.example`

```bash
# Valkey Caching Configuration
ENABLE_INTELLIGENCE_CACHE=true
VALKEY_URL=redis://archon-valkey:6379/0

# Cache TTLs (seconds)
CACHE_TTL_PATTERNS=300        # 5 minutes
CACHE_TTL_INFRASTRUCTURE=3600 # 1 hour
CACHE_TTL_SCHEMAS=1800        # 30 minutes
```

**Expected Impact**:
- Query time: 7,500ms → 1,500ms (60% cache hit rate)
- Archon load: -60% (fewer duplicate queries)
- Cost: Near zero (Valkey already running)

**Actual Implementation** (2025-10-31):

✅ **Created Files**:
- `agents/lib/intelligence_cache.py` (268 lines)
  - IntelligenceCache class with Valkey connection management
  - MD5-based cache key generation
  - Configurable TTLs per operation type
  - Graceful error handling (cache failures don't break queries)
  - get_stats() for monitoring

✅ **Modified Files**:
- `agents/lib/manifest_injector.py`
  - Integrated IntelligenceCache with two-tier caching
  - Cache-first strategy (Valkey → in-memory → backend)
  - Non-blocking cache operations
- `.env.example`
  - Added Valkey configuration with password authentication
  - TTL configuration: patterns (5min), infrastructure (1hr), schemas (30min)

✅ **Configuration**:
```bash
ENABLE_INTELLIGENCE_CACHE=true
VALKEY_URL=redis://:archon_cache_2025@archon-valkey:6379/0
CACHE_TTL_PATTERNS=300
CACHE_TTL_INFRASTRUCTURE=3600
CACHE_TTL_SCHEMAS=1800
```

✅ **Testing Status**:
- Unit tests: Pending (Valkey auth connection needs verification)
- Integration: Ready for live testing
- Performance: Target <10ms cache lookup, 60%+ hit rate

**Next Steps for Phase 1**:
1. Test Valkey caching in live environment
2. Monitor cache hit rates
3. Verify performance improvements
4. Adjust TTLs based on real usage patterns

---

### Phase 2: Pattern Quality Scoring ⏳ PENDING

**Objective**: Implement quality scoring and populate `pattern_quality_metrics` table

#### 2.1 Create Pattern Quality Scorer

**New File**: `agents/lib/pattern_quality_scorer.py`

```python
"""
Pattern Quality Scorer - Evaluates and stores pattern quality metrics

Scoring Dimensions:
1. Code Completeness (0-1.0): Has meaningful code vs stubs
2. Documentation Quality (0-1.0): Docstrings, comments, type hints
3. ONEX Compliance (0-1.0): Follows ONEX architecture patterns
4. Metadata Richness (0-1.0): Use cases, examples, node types
5. Complexity Appropriateness (0-1.0): Complexity matches use case

Composite Score: Weighted average of dimensions
"""

from typing import Dict, Optional
import re
from dataclasses import dataclass

@dataclass
class PatternQualityScore:
    """Quality score breakdown"""
    pattern_id: str
    pattern_name: str
    composite_score: float  # 0.0-1.0
    completeness_score: float
    documentation_score: float
    onex_compliance_score: float
    metadata_richness_score: float
    complexity_score: float
    confidence: float  # From Archon Intelligence
    measurement_timestamp: datetime
    version: str = "1.0.0"

class PatternQualityScorer:
    """Evaluate pattern quality across multiple dimensions"""

    # Quality thresholds
    EXCELLENT_THRESHOLD = 0.9
    GOOD_THRESHOLD = 0.7
    FAIR_THRESHOLD = 0.5

    def score_pattern(self, pattern: Dict) -> PatternQualityScore:
        """
        Calculate composite quality score for a pattern.

        Args:
            pattern: Pattern data from Qdrant/Archon Intelligence

        Returns:
            PatternQualityScore with dimension breakdown
        """
        # Extract pattern fields
        code = pattern.get("code", "")
        text = pattern.get("text", "")
        pattern_name = pattern.get("pattern_name", "")
        metadata = pattern.get("metadata", {})
        node_type = pattern.get("node_type")
        use_cases = pattern.get("use_cases", [])
        examples = pattern.get("code_examples", [])
        confidence = pattern.get("confidence", 0.0)

        # Score each dimension
        completeness = self._score_completeness(code, text)
        documentation = self._score_documentation(code, text)
        onex_compliance = self._score_onex_compliance(code, node_type, pattern_name)
        metadata_rich = self._score_metadata_richness(use_cases, examples, metadata)
        complexity = self._score_complexity(code, pattern.get("complexity"))

        # Weighted composite score
        composite = (
            completeness * 0.30 +      # Most important
            documentation * 0.25 +
            onex_compliance * 0.20 +
            metadata_rich * 0.15 +
            complexity * 0.10
        )

        return PatternQualityScore(
            pattern_id=pattern.get("pattern_id", ""),
            pattern_name=pattern_name,
            composite_score=composite,
            completeness_score=completeness,
            documentation_score=documentation,
            onex_compliance_score=onex_compliance,
            metadata_richness_score=metadata_rich,
            complexity_score=complexity,
            confidence=confidence,
            measurement_timestamp=datetime.now(UTC),
        )

    def _score_completeness(self, code: str, text: str) -> float:
        """Score code completeness (0-1.0)"""
        if not code:
            return 0.0

        # Penalties for incomplete code
        stub_indicators = ["pass", "TODO", "NotImplemented", "...", "raise NotImplementedError"]
        stub_count = sum(1 for indicator in stub_indicators if indicator in code)

        # Bonus for meaningful implementation
        has_logic = bool(re.search(r"(if|for|while|async def|class)", code))
        has_imports = bool(re.search(r"^import |^from .* import", code, re.MULTILINE))
        line_count = len([l for l in code.split("\n") if l.strip()])

        base_score = max(0.0, 1.0 - (stub_count * 0.2))
        bonus = (0.1 if has_logic else 0) + (0.05 if has_imports else 0) + min(0.15, line_count / 100)

        return min(1.0, base_score + bonus)

    def _score_documentation(self, code: str, text: str) -> float:
        """Score documentation quality (0-1.0)"""
        score = 0.0

        # Docstrings
        if '"""' in code or "'''" in code:
            score += 0.4

        # Inline comments
        comment_lines = len([l for l in code.split("\n") if "#" in l])
        score += min(0.2, comment_lines / 20)

        # Type hints
        if re.search(r":\s*\w+|\s*->\s*\w+", code):
            score += 0.2

        # Descriptive text/summary
        if len(text) > 100:
            score += 0.2

        return min(1.0, score)

    def _score_onex_compliance(self, code: str, node_type: Optional[str], pattern_name: str) -> float:
        """Score ONEX architecture compliance (0-1.0)"""
        if not node_type:
            # Try to infer from pattern name
            if re.search(r"(Effect|Compute|Reducer|Orchestrator)", pattern_name):
                score = 0.5  # Partial compliance
            else:
                return 0.3  # Low score for non-ONEX patterns

        score = 0.7  # Has node type

        # Check for proper naming
        expected_suffix = f"{node_type.capitalize()}"
        if expected_suffix in pattern_name:
            score += 0.15

        # Check for ONEX method signatures
        onex_methods = {
            "effect": "async def execute_effect",
            "compute": "async def execute_compute",
            "reducer": "async def execute_reduction",
            "orchestrator": "async def execute_orchestration",
        }

        if node_type and onex_methods.get(node_type.lower(), "") in code:
            score += 0.15

        return min(1.0, score)

    def _score_metadata_richness(self, use_cases: List, examples: List, metadata: Dict) -> float:
        """Score metadata richness (0-1.0)"""
        score = 0.0

        if use_cases and len(use_cases) > 0:
            score += min(0.4, len(use_cases) / 3 * 0.4)

        if examples and len(examples) > 0:
            score += min(0.3, len(examples) / 2 * 0.3)

        if metadata and len(metadata) > 3:
            score += 0.3

        return min(1.0, score)

    def _score_complexity(self, code: str, declared_complexity: Optional[str]) -> float:
        """Score complexity appropriateness (0-1.0)"""
        # Measure actual complexity
        cyclomatic_indicators = code.count("if ") + code.count("for ") + code.count("while ") + code.count("except ")
        actual_complexity = "low" if cyclomatic_indicators < 3 else "medium" if cyclomatic_indicators < 8 else "high"

        # Compare with declared
        if declared_complexity:
            if declared_complexity.lower() == actual_complexity:
                return 1.0  # Perfect match
            else:
                return 0.6  # Mismatch but has declaration

        return 0.4  # No complexity declaration

    async def store_quality_metrics(
        self,
        score: PatternQualityScore,
        db_connection_string: Optional[str] = None
    ):
        """Store quality metrics in pattern_quality_metrics table"""
        import psycopg2

        conn = psycopg2.connect(db_connection_string or os.getenv("DATABASE_URL"))
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO pattern_quality_metrics (
                    pattern_id,
                    quality_score,
                    confidence,
                    measurement_timestamp,
                    version,
                    metadata
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (pattern_id, measurement_timestamp)
                DO UPDATE SET
                    quality_score = EXCLUDED.quality_score,
                    confidence = EXCLUDED.confidence,
                    metadata = EXCLUDED.metadata
                """,
                (
                    score.pattern_id,
                    score.composite_score,
                    score.confidence,
                    score.measurement_timestamp,
                    score.version,
                    json.dumps({
                        "pattern_name": score.pattern_name,
                        "completeness_score": score.completeness_score,
                        "documentation_score": score.documentation_score,
                        "onex_compliance_score": score.onex_compliance_score,
                        "metadata_richness_score": score.metadata_richness_score,
                        "complexity_score": score.complexity_score,
                    })
                )
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()
```

#### 2.2 Backfill Script for Existing Patterns

**New File**: `scripts/backfill_pattern_quality.py`

```python
"""
Backfill Pattern Quality Metrics

One-time script to score all existing patterns in Qdrant
and populate pattern_quality_metrics table.

Usage:
    python3 scripts/backfill_pattern_quality.py --dry-run
    python3 scripts/backfill_pattern_quality.py
"""

import asyncio
import argparse
from agents.lib.pattern_quality_scorer import PatternQualityScorer
# ... implementation ...
```

#### 2.3 Integrate with Manifest Injection

**Modify**: `agents/lib/manifest_injector.py`

```python
from agents.lib.pattern_quality_scorer import PatternQualityScorer

class ManifestInjector:
    def __init__(self):
        # ...
        self.quality_scorer = PatternQualityScorer()
        self.enable_quality_filtering = os.getenv("ENABLE_PATTERN_QUALITY_FILTER", "true").lower() == "true"
        self.min_quality_threshold = float(os.getenv("MIN_PATTERN_QUALITY", "0.5"))

    async def _filter_by_quality(self, patterns: List[Dict]) -> List[Dict]:
        """Filter patterns by quality score"""
        if not self.enable_quality_filtering:
            return patterns

        filtered = []
        for pattern in patterns:
            score = self.quality_scorer.score_pattern(pattern)

            # Score and store (async, non-blocking)
            asyncio.create_task(
                self.quality_scorer.store_quality_metrics(score)
            )

            # Filter by threshold
            if score.composite_score >= self.min_quality_threshold:
                filtered.append(pattern)

        logger.info(f"Quality filter: {len(filtered)}/{len(patterns)} patterns passed (threshold: {self.min_quality_threshold})")
        return filtered
```

**Expected Impact**:
- Pattern quality table: 0 rows → 1,065 rows (full coverage)
- Pattern filtering: Remove low-quality stub patterns
- Manifest quality: Higher relevance of suggested patterns

---

### Phase 3: Query Optimization ⏳ PENDING

**Status**: Not started - depends on Phase 1 performance data

**Objective**: Optimize client-side query patterns and timeouts

#### 3.1 Parallel Query Verification

**Modify**: `agents/lib/manifest_injector.py`

```python
async def generate_dynamic_manifest(self) -> Dict[str, Any]:
    """Generate manifest with verified parallel queries"""

    # CRITICAL: Verify these run in parallel, not sequential
    start_time = time.time()

    results = await asyncio.gather(
        self._query_patterns_with_cache("code_patterns", 50),
        self._query_patterns_with_cache("execution_patterns", 20),
        self._query_infrastructure(),
        self._query_models(),
        self._query_schemas(),
        self._query_debug_intelligence(),
        return_exceptions=True  # Graceful degradation
    )

    total_time = (time.time() - start_time) * 1000
    logger.info(f"Parallel query completed in {total_time:.0f}ms")

    # Validate parallelism (should be <2x slowest individual query)
    if total_time > 5000:  # 5s threshold
        logger.warning(f"Query time exceeded threshold: {total_time}ms (likely sequential execution)")

    return self._build_manifest(results)
```

#### 3.2 Smarter Timeout Configuration

**Modify**: `agents/lib/intelligence_event_client.py`

```python
# Reduce default timeout from 10s to 5s
DEFAULT_REQUEST_TIMEOUT_MS = 5000  # Fail faster

# Add per-operation timeout configuration
OPERATION_TIMEOUTS = {
    "PATTERN_EXTRACTION": 2000,      # 2s for pattern queries
    "INFRASTRUCTURE_QUERY": 1000,    # 1s for infrastructure
    "SCHEMA_QUERY": 1000,            # 1s for schemas
    "MODEL_QUERY": 1000,             # 1s for models
    "DEBUG_INTELLIGENCE": 2000,      # 2s for debug intel
}

async def request_intelligence(self, operation_type: str, **kwargs):
    """Request with operation-specific timeout"""
    timeout_ms = OPERATION_TIMEOUTS.get(operation_type, DEFAULT_REQUEST_TIMEOUT_MS)

    try:
        return await asyncio.wait_for(
            self._request_with_correlation(operation_type, **kwargs),
            timeout=timeout_ms / 1000
        )
    except asyncio.TimeoutError:
        logger.warning(f"{operation_type} timed out after {timeout_ms}ms")
        raise
```

#### 3.3 Connection Reuse

**Modify**: `agents/lib/intelligence_event_client.py`

```python
class IntelligenceEventClient:
    """Reuse producer/consumer connections across requests"""

    # Class-level connection pool
    _shared_producer: Optional[AIOKafkaProducer] = None
    _shared_consumer: Optional[AIOKafkaConsumer] = None
    _connection_lock = asyncio.Lock()

    async def start(self):
        """Start with connection pooling"""
        async with self._connection_lock:
            if self._shared_producer is None:
                # Create shared producer (reused across all clients)
                self._shared_producer = AIOKafkaProducer(...)
                await self._shared_producer.start()

            if self._shared_consumer is None:
                # Create shared consumer
                self._shared_consumer = AIOKafkaConsumer(...)
                await self._shared_consumer.start()

            self._producer = self._shared_producer
            self._consumer = self._shared_consumer
```

**Expected Impact**:
- Connection overhead: -200ms (reuse instead of reconnect)
- Parallel execution verified: Catch sequential bottlenecks
- Timeout failures: Fail in 5s instead of 10s

---

## Testing & Validation

### Test Suite

**New File**: `agents/tests/test_intelligence_optimization.py`

```python
"""Test intelligence optimization improvements"""

async def test_cache_hit_rate():
    """Verify cache achieves >60% hit rate"""
    # Run 100 duplicate queries
    # Assert cache hit rate > 60%

async def test_query_performance():
    """Verify query time <2s with cache"""
    # Run manifest injection 10 times
    # Assert p95 < 2000ms

async def test_pattern_quality_scoring():
    """Verify quality scoring accuracy"""
    # Score sample patterns
    # Assert scores match expected ranges

async def test_graceful_degradation():
    """Verify partial results on component failure"""
    # Simulate Qdrant timeout
    # Assert manifest still returns infrastructure/schemas
```

### Performance Benchmarks

```bash
# Before optimization
python3 scripts/benchmark_manifest_injection.py --iterations 50
# Expected: p95 = 7500ms, 66% success rate

# After Phase 1 (caching)
python3 scripts/benchmark_manifest_injection.py --iterations 50
# Expected: p95 = 1500ms, 90% success rate (60% cache hits)

# After Phase 2 (quality filtering)
# Expected: Higher quality patterns, faster manifest generation

# After Phase 3 (query optimization)
# Expected: p95 = 1200ms, 95% success rate
```

### Monitoring Dashboard

**Grafana Metrics to Track**:
- Manifest injection time (p50, p95, p99)
- Cache hit rate (target: >60%)
- Pattern quality distribution
- Failed query rate (target: <5%)

---

## Implementation Checklist

### Phase 1: Caching (Day 1)
- [ ] Create `agents/lib/intelligence_cache.py`
- [ ] Integrate with `manifest_injector.py`
- [ ] Add configuration to `.env.example`
- [ ] Test cache hit/miss scenarios
- [ ] Verify Valkey connectivity
- [ ] Monitor cache hit rate (target: >60%)

### Phase 2: Quality Scoring (Day 2)
- [ ] Create `agents/lib/pattern_quality_scorer.py`
- [ ] Create `scripts/backfill_pattern_quality.py`
- [ ] Run backfill for existing patterns
- [ ] Integrate quality filtering with manifest injection
- [ ] Verify `pattern_quality_metrics` table populated
- [ ] Test quality-based pattern filtering

### Phase 3: Query Optimization (Day 3)
- [ ] Verify parallel query execution
- [ ] Implement per-operation timeouts
- [ ] Add connection pooling/reuse
- [ ] Test graceful degradation
- [ ] Benchmark performance improvements
- [ ] Document configuration options

### Phase 4: Testing & Validation
- [ ] Write integration tests
- [ ] Run performance benchmarks
- [ ] Set up monitoring dashboards
- [ ] Document findings and metrics

---

## Configuration Reference

### Environment Variables

```bash
# Caching Configuration
ENABLE_INTELLIGENCE_CACHE=true
VALKEY_URL=redis://archon-valkey:6379/0
CACHE_TTL_PATTERNS=300        # 5 minutes
CACHE_TTL_INFRASTRUCTURE=3600 # 1 hour
CACHE_TTL_SCHEMAS=1800        # 30 minutes

# Quality Filtering
ENABLE_PATTERN_QUALITY_FILTER=true
MIN_PATTERN_QUALITY=0.5       # 0.0-1.0 threshold

# Query Optimization
INTELLIGENCE_REQUEST_TIMEOUT_MS=5000
ENABLE_CONNECTION_POOLING=true
```

---

## Success Metrics

### Performance Targets

| Metric | Before | After Phase 1 | Target | Expected Final |
|--------|--------|---------------|--------|----------------|
| Query time (p95) | 7,500ms | 1,500ms* | <2,000ms | 1,200ms |
| Success rate | 66% | TBD | >90% | 95% |
| Cache hit rate | 0% | TBD | >60% | 70% |
| Pattern quality coverage | 0% | 0% (Phase 2) | 100% | 100% |
| Timeout failures | 34% | TBD | <5% | 3% |

*Projected based on 60% cache hit rate assumption - requires live testing to confirm

### Quality Targets

| Metric | Before | Target | Expected |
|--------|--------|--------|----------|
| Pattern quality metrics rows | 0 | 1,065 | 1,065 |
| High-quality patterns (>0.7) | Unknown | >70% | 75% |
| Low-quality patterns filtered | N/A | <30% | 25% |

---

## Rollback Plan

If issues arise:

```bash
# Disable caching
export ENABLE_INTELLIGENCE_CACHE=false

# Disable quality filtering
export ENABLE_PATTERN_QUALITY_FILTER=false

# Revert timeout changes
export INTELLIGENCE_REQUEST_TIMEOUT_MS=10000

# Check logs
docker logs -f archon-intelligence
tail -f agents/logs/manifest_injection.log
```

---

## Next Steps

### ✅ Completed (2025-10-31)
1. ~~Implement Phase 1 (Caching) for quick wins~~ → **DONE**
2. ~~Move enhancement requests to Archon Intelligence repo~~ → **DONE** (commit `07f10c8` in omniarchon)

### 🔄 Current Priority
1. **Test Phase 1 in live environment**
   - Verify Valkey caching works with authentication
   - Monitor cache hit rates (target: >60%)
   - Measure performance improvements (target: 7.5s → 1.5s)

### ⏭️ Next Up
2. **Implement Phase 2** (Pattern Quality Scoring) - Est. 6 hours
   - Create pattern quality scorer
   - Backfill existing patterns
   - Integrate with manifest injection

3. **Implement Phase 3** (Query Optimization) - Est. 4 hours
   - Verify parallel query execution
   - Implement per-operation timeouts
   - Add connection pooling

**Related Commits**:
- OmniClaude Phase 1: `75fc706` on `fix/consumer-hardcoded-localhost`
- Archon Enhancement Requests: `07f10c8` in `omniarchon/docs/planning/`

---

**Last Updated**: 2025-10-31
**Status**: Phase 1 Complete ✅ | Testing & Phase 2 Next
**Owner**: OmniClaude Team

**Phase 1 Commit**: `75fc706` - Valkey caching implementation
**Archon Enhancement Doc**: `07f10c8` in omniarchon repository
