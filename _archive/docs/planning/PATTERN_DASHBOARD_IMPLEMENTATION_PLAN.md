# Pattern Dashboard Implementation Plan

**Date**: 2025-10-28
**Correlation ID**: a06eb29a-8922-4fdf-bb27-96fc40fae415
**Dependencies**: See [PATTERN_DASHBOARD_REPOSITORY_BOUNDARIES.md](./PATTERN_DASHBOARD_REPOSITORY_BOUNDARIES.md)

## Overview

This document maps the Pattern Learning Dashboard backend features to specific repositories, files, and implementation tasks.

**Primary Repository**: omniarchon (90% of work)
**Secondary Repository**: omniclaude (10% - client updates)

## Task Mapping

### Task 1: Pattern Quality Metrics Collection

**Repository**: omniarchon
**Status**: ✅ Partially exists, needs enhancement

**Existing Infrastructure**:
- Quality scoring: `services/intelligence/scoring/quality_scorer.py`
- Pattern analytics API: `services/intelligence/src/api/pattern_analytics/`
- Success rate tracking: Already implemented in `service.py`

**Implementation Required**:
1. **Enhance Quality Metrics Collection**:
   - File: `services/intelligence/src/services/pattern_learning/phase1_foundation/storage/node_pattern_storage_effect.py`
   - Add: Quality score calculation on pattern storage
   - Add: Quality trend tracking over time

2. **Create Quality Metrics API Endpoint**:
   - File: `services/intelligence/src/api/pattern_analytics/routes.py`
   - Add: `GET /api/pattern-analytics/quality-metrics`
   - Response: Pattern quality scores with confidence, trends

3. **Database Schema** (if not exists):
   - Table: `pattern_quality_metrics`
   - Columns: pattern_id, quality_score, measurement_timestamp, version

**Dependencies**:
- QualityScorer (already exists)
- Pattern storage effect (already exists)

**Estimated Effort**: 4 hours

---

### Task 2: Pattern Success Rate Analytics

**Repository**: omniarchon
**Status**: ✅ Already implemented

**Existing Implementation**:
- Service: `services/intelligence/src/api/pattern_analytics/service.py`
  - Method: `get_pattern_success_rates()`
  - Success rate calculation with sample size adjustment
  - Confidence scoring based on sample count

- API Endpoint: `services/intelligence/src/api/pattern_analytics/routes.py`
  - `GET /api/pattern-analytics/success-rates`
  - Filters: pattern_type, min_samples
  - Response: Success rates with confidence, summary stats

**No Work Required** ✅

**Usage Example**:
```bash
curl http://localhost:8053/api/pattern-analytics/success-rates?pattern_type=architectural&min_samples=5
```

**Response**:
```json
{
  "patterns": [
    {
      "pattern_id": "uuid",
      "pattern_name": "CRUD Effect Pattern",
      "success_rate": 0.92,
      "confidence": 0.87,
      "total_executions": 45,
      "successful_executions": 41,
      "pattern_type": "architectural"
    }
  ],
  "summary": {
    "total_patterns": 23,
    "average_success_rate": 0.85,
    "high_confidence_count": 12
  }
}
```

---

### Task 3: Pattern Usage Tracking Backend

**Repository**: omniarchon
**Status**: ✅ Partially exists, needs enhancement

**Existing Infrastructure**:
- Pattern traceability API: `services/intelligence/src/api/phase4_traceability/`
- Lineage tracker: `services/intelligence/src/services/pattern_learning/phase4_traceability/node_pattern_lineage_tracker_effect.py`
- Pattern metrics model: `model_pattern_metrics.py`

**Implementation Required**:
1. **Usage Tracking Enhancement**:
   - File: `services/intelligence/src/services/pattern_learning/phase4_traceability/node_pattern_lineage_tracker_effect.py`
   - Add: Real-time usage counting
   - Add: Usage frequency per time period (hourly, daily, weekly)

2. **Usage Analytics API**:
   - File: `services/intelligence/src/api/pattern_analytics/routes.py`
   - Add: `GET /api/pattern-analytics/usage-stats`
   - Response: Usage counts, trends, popular patterns

3. **Kafka Consumer for Real-Time Updates** (omniclaude side):
   - File: `omniclaude/agents/lib/pattern_feedback.py`
   - Ensure: Feedback events published to Kafka
   - Topic: `pattern-usage-events`

**Database Schema**:
```sql
-- Likely already exists, verify:
pattern_usage_stats (
  pattern_id UUID,
  usage_count INTEGER,
  last_used TIMESTAMP,
  period_start TIMESTAMP,
  period_end TIMESTAMP
)
```

**Dependencies**:
- Pattern feedback events from omniclaude (already publishing)
- Kafka consumer in archon-intelligence (already exists)

**Estimated Effort**: 6 hours

---

### Task 4: Dashboard API Endpoints

**Repository**: omniarchon
**Status**: ⚠️  New endpoints required

**Implementation Required**:

1. **Dashboard Summary Endpoint**:
   - File: `services/intelligence/src/api/pattern_analytics/routes.py`
   - Add: `GET /api/pattern-analytics/dashboard-summary`
   - Response: Aggregated dashboard data
   - Content:
     - Total patterns count
     - Average success rate
     - Most used patterns (top 10)
     - Quality distribution
     - Recent trends

2. **Pattern Detail Endpoint** (may exist):
   - Add: `GET /api/pattern-analytics/patterns/{pattern_id}`
   - Response: Complete pattern details with analytics

3. **Time-Series Data Endpoint**:
   - Add: `GET /api/pattern-analytics/time-series`
   - Params: pattern_id, metric_type, time_range
   - Response: Time-series data for charts

**Service Layer**:
- File: `services/intelligence/src/api/pattern_analytics/service.py`
- Add: `get_dashboard_summary()` method
- Add: `get_pattern_time_series()` method

**Models**:
- File: `services/intelligence/src/api/pattern_analytics/models.py`
- Add: `DashboardSummaryResponse`
- Add: `TimeSeriesDataResponse`

**Estimated Effort**: 8 hours

---

### Task 5: Historical Trend Analysis

**Repository**: omniarchon
**Status**: ⚠️  New analysis logic required

**Implementation Required**:

1. **Trend Analysis Service**:
   - File: `services/intelligence/src/services/pattern_learning/phase4_traceability/pattern_trend_analyzer.py` (NEW)
   - Class: `PatternTrendAnalyzer`
   - Methods:
     - `analyze_quality_trends(pattern_id, time_range)`
     - `analyze_usage_trends(pattern_id, time_range)`
     - `detect_emerging_patterns(time_window)`
     - `identify_declining_patterns(threshold)`

2. **Trend Analysis API**:
   - File: `services/intelligence/src/api/pattern_analytics/routes.py`
   - Add: `GET /api/pattern-analytics/trends`
   - Params: trend_type, time_range, pattern_id (optional)
   - Response: Trend data with direction, velocity, predictions

3. **Database Queries**:
   - Add aggregation queries for time-series analysis
   - Use PostgreSQL window functions for trend calculation

**Statistical Analysis**:
- Linear regression for trend direction
- Moving averages for smoothing
- Standard deviation for volatility

**Estimated Effort**: 10 hours

---

### Task 6: Pattern Comparison & Benchmarking

**Repository**: omniarchon
**Status**: ⚠️  New feature

**Implementation Required**:

1. **Comparison Service**:
   - File: `services/intelligence/src/services/pattern_learning/phase2_matching/pattern_comparator.py` (NEW)
   - Class: `PatternComparator`
   - Methods:
     - `compare_patterns(pattern_ids: List[UUID])`
     - `benchmark_pattern(pattern_id, category)`

2. **Comparison API**:
   - File: `services/intelligence/src/api/pattern_analytics/routes.py`
   - Add: `POST /api/pattern-analytics/compare`
   - Body: `{"pattern_ids": ["uuid1", "uuid2", ...]}`
   - Response: Side-by-side comparison matrix

3. **Benchmarking Logic**:
   - Compare against category averages
   - Percentile ranking
   - Relative performance metrics

**Estimated Effort**: 8 hours

---

### Task 7: Real-Time Pattern Metrics Dashboard Data

**Repository**: Both (omniarchon primary, omniclaude secondary)

**Implementation Required**:

**omniarchon**:
1. **WebSocket Support** (optional):
   - File: `services/intelligence/app.py`
   - Add: WebSocket endpoint for real-time updates
   - Endpoint: `ws://localhost:8053/ws/pattern-metrics`

2. **Server-Sent Events** (simpler alternative):
   - File: `services/intelligence/src/api/pattern_analytics/routes.py`
   - Add: `GET /api/pattern-analytics/stream` (SSE endpoint)
   - Stream: Real-time metric updates

3. **Event Aggregation**:
   - File: `services/intelligence/src/handlers/pattern_analytics_handler.py`
   - Add: Real-time event aggregation from Kafka
   - Publish updates to connected clients

**omniclaude** (if real-time needed):
- File: `agents/lib/pattern_feedback.py`
- Ensure: Low-latency Kafka event publishing
- Add: Batch optimization for high-frequency updates

**Estimated Effort**: 12 hours

---

## Summary Table

| Task | Repository | Status | Effort | Files to Modify/Create |
|------|-----------|--------|--------|----------------------|
| 1. Quality Metrics | omniarchon | Partial | 4h | pattern_analytics/routes.py, node_pattern_storage_effect.py |
| 2. Success Rates | omniarchon | ✅ Done | 0h | Already implemented |
| 3. Usage Tracking | omniarchon | Partial | 6h | node_pattern_lineage_tracker_effect.py, routes.py |
| 4. Dashboard APIs | omniarchon | New | 8h | pattern_analytics/routes.py, service.py, models.py |
| 5. Trend Analysis | omniarchon | New | 10h | pattern_trend_analyzer.py (new), routes.py |
| 6. Comparison/Benchmarking | omniarchon | New | 8h | pattern_comparator.py (new), routes.py |
| 7. Real-Time Metrics | Both | New | 12h | app.py, pattern_analytics/routes.py, pattern_feedback.py |
| **TOTAL** | - | - | **48h** | ~15 files |

## Repository Breakdown

### omniarchon Work (90%)

**Total Effort**: ~48 hours

**Primary Files**:
1. `services/intelligence/src/api/pattern_analytics/routes.py` (5 new endpoints)
2. `services/intelligence/src/api/pattern_analytics/service.py` (6 new methods)
3. `services/intelligence/src/api/pattern_analytics/models.py` (8 new response models)
4. `services/intelligence/src/services/pattern_learning/phase4_traceability/pattern_trend_analyzer.py` (NEW)
5. `services/intelligence/src/services/pattern_learning/phase2_matching/pattern_comparator.py` (NEW)
6. `services/intelligence/src/services/pattern_learning/phase1_foundation/storage/node_pattern_storage_effect.py` (enhancement)
7. `services/intelligence/app.py` (WebSocket support - optional)

**Database Migrations**:
- New table: `pattern_quality_metrics` (if not exists)
- Index: `pattern_usage_stats` by timestamp for trend queries
- Index: `pattern_feedback` for aggregation queries

### omniclaude Work (10%)

**Total Effort**: ~4 hours

**Primary Files**:
1. `agents/lib/pattern_feedback.py` (ensure Kafka publishing)
2. `agents/lib/patterns/pattern_storage.py` (client updates if API changes)
3. `scripts/ingest_all_repositories.py` (may need updates)

**Work**:
- Verify Kafka event publishing works correctly
- Add any new client methods for dashboard APIs
- Test integration with new endpoints

---

## Implementation Phases

### Phase 1: Foundation (Tasks 1, 3)
**Duration**: 1.5 days
**Goal**: Quality metrics and usage tracking enhancements

1. Enhance pattern storage quality metrics
2. Implement usage tracking APIs
3. Test with existing patterns

### Phase 2: Dashboard APIs (Task 4)
**Duration**: 1 day
**Goal**: Core dashboard endpoints

1. Create dashboard summary endpoint
2. Implement time-series data endpoint
3. Add pattern detail endpoint
4. Test API responses

### Phase 3: Analytics (Tasks 5, 6)
**Duration**: 2 days
**Goal**: Advanced analytics features

1. Implement trend analysis service
2. Add pattern comparison logic
3. Create benchmarking APIs
4. Test statistical calculations

### Phase 4: Real-Time (Task 7)
**Duration**: 1.5 days
**Goal**: Real-time updates

1. Add SSE/WebSocket support
2. Implement event aggregation
3. Test real-time updates
4. Optimize latency

### Phase 5: Integration & Testing
**Duration**: 1 day
**Goal**: End-to-end validation

1. Integration tests for all endpoints
2. Performance testing
3. Load testing
4. Documentation

**Total Duration**: ~7 working days (56 hours)

---

## Dependencies & Blockers

### External Dependencies
- ✅ Qdrant running (localhost:6333)
- ✅ PostgreSQL running (localhost:5436)
- ✅ Kafka running (localhost:9092)
- ✅ archon-intelligence service (localhost:8053)

### Code Dependencies
- ✅ Pattern storage nodes (phase1_foundation)
- ✅ Pattern analytics service (existing)
- ✅ Quality scorer (existing)
- ⚠️  Pattern feedback events from omniclaude (verify)

### Potential Blockers
- Database schema migrations (if pattern_quality_metrics doesn't exist)
- Kafka consumer performance (for real-time updates)
- Query performance on large pattern datasets

---

## Testing Strategy

### Unit Tests
**Repository**: omniarchon
**Location**: `services/intelligence/tests/unit/pattern_learning/`

- Test each new service method independently
- Mock database calls
- Verify calculation logic

### Integration Tests
**Repository**: omniarchon
**Location**: `services/intelligence/tests/integration/`

- Test API endpoints end-to-end
- Verify database queries
- Test Kafka event consumption

### Performance Tests
**Repository**: omniarchon
**Location**: `services/intelligence/tests/performance/`

- Benchmark trend analysis queries
- Test dashboard summary performance
- Measure real-time update latency

### Client Tests
**Repository**: omniclaude
**Location**: `agents/tests/`

- Test pattern feedback publishing
- Verify client API consumption
- Integration with agent workflows

---

## Deployment

### omniarchon Deployment

**Container**: `archon-intelligence`
**Port**: 8053

```bash
# Rebuild and deploy
cd /Volumes/PRO-G40/Code/Omniarchon/deployment
docker-compose up -d --build archon-intelligence

# Verify health
curl http://localhost:8053/health

# Test new endpoints
curl http://localhost:8053/api/pattern-analytics/dashboard-summary
```

**Database Migrations**:
```bash
# Run migrations if schema changes
docker exec -it archon-intelligence alembic upgrade head
```

### omniclaude Updates

**No service deployment** - client-side code only

```bash
# On deployment machine
cd /path/to/omniclaude
git pull origin main

# Test pattern feedback
python3 agents/lib/pattern_feedback.py --test
```

---

## Monitoring & Observability

### Metrics to Track
- API endpoint latency (target: <100ms)
- Dashboard query performance (target: <500ms)
- Real-time update latency (target: <1s)
- Kafka consumer lag (target: <100 messages)

### Logging
- Pattern analytics queries (for optimization)
- Trend calculation errors
- Real-time connection events

### Alerts
- Slow dashboard queries (>1s)
- Failed Kafka event processing
- High consumer lag (>1000 messages)

---

## Documentation Updates Required

1. **API Documentation**:
   - File: `services/intelligence/docs/API.md`
   - Add: All new endpoint documentation
   - Add: Request/response examples

2. **Architecture Documentation**:
   - File: `services/intelligence/docs/ARCHITECTURE.md`
   - Add: Trend analysis component
   - Add: Real-time update flow

3. **Developer Guide**:
   - File: `services/intelligence/docs/DEVELOPER_GUIDE.md`
   - Add: How to add new pattern metrics
   - Add: How to extend trend analysis

---

## Success Criteria

### Functional Requirements
- ✅ Quality metrics API returns accurate scores
- ✅ Success rates match manual calculations
- ✅ Usage tracking updates in real-time
- ✅ Dashboard summary aggregates correctly
- ✅ Trends detect emerging patterns
- ✅ Comparison provides meaningful insights
- ✅ Real-time updates have <1s latency

### Performance Requirements
- ✅ Dashboard loads in <2s
- ✅ Trend analysis completes in <500ms
- ✅ API endpoints respond in <100ms (95th percentile)
- ✅ Real-time updates handle 100 concurrent connections

### Quality Requirements
- ✅ 100% unit test coverage for new code
- ✅ Integration tests for all endpoints
- ✅ Performance benchmarks documented
- ✅ API documentation complete

---

## Next Steps

1. **Review Existing Code**:
   - Audit `pattern_analytics/service.py` for reusable logic
   - Check database schema for pattern_quality_metrics table
   - Verify Kafka consumer handles pattern feedback events

2. **Create Detailed Tickets**:
   - Break down each task into sub-tasks
   - Assign effort estimates
   - Identify dependencies

3. **Set Up Development Environment**:
   - Clone omniarchon repository
   - Verify archon-intelligence builds and runs
   - Set up local Qdrant/PostgreSQL/Kafka

4. **Start with Phase 1**:
   - Begin with quality metrics (Task 1)
   - Then usage tracking (Task 3)
   - Validate with existing patterns

5. **Incremental Deployment**:
   - Deploy after each phase
   - Gather feedback
   - Iterate based on performance

---

## Questions for Clarification

1. **Real-Time Requirements**: Is WebSocket support required, or is polling acceptable?
2. **Historical Data Retention**: How far back should trend analysis go? (30 days? 90 days?)
3. **Dashboard Refresh Rate**: How often should dashboard auto-refresh? (5s? 30s? Manual?)
4. **Pattern Categories**: Are there specific pattern type taxonomies to support?
5. **Performance SLAs**: What are the hard requirements for query performance?

---

## Conclusion

**Clear implementation path established**:
- 90% of work in omniarchon (backend services)
- 10% of work in omniclaude (client utilities)
- ~7 working days total effort
- Phased rollout for incremental value delivery

**Primary focus**: omniarchon intelligence service
**Key files**: pattern_analytics API, trend analyzer, pattern comparator

**See also**:
- [PATTERN_DASHBOARD_REPOSITORY_BOUNDARIES.md](./PATTERN_DASHBOARD_REPOSITORY_BOUNDARIES.md) - Repository ownership
- [PATTERN_DASHBOARD_OMNIARCHON_CHANGES.md](./PATTERN_DASHBOARD_OMNIARCHON_CHANGES.md) - Detailed omniarchon changes
