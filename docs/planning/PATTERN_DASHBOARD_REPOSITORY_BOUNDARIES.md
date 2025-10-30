# Pattern Dashboard Repository Boundaries

**Investigation Date**: 2025-10-28
**Correlation ID**: a06eb29a-8922-4fdf-bb27-96fc40fae415

## Executive Summary

The Pattern Learning Dashboard backend work is split across **two repositories** with clear ownership boundaries:

- **omniarchon**: Backend services, APIs, database operations, analytics collection
- **omniclaude**: Client utilities, ingestion scripts, agent-level feedback tracking

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         OMNICLAUDE                              │
│  (Client-side pattern consumption & feedback)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐        ┌─────────────────────┐          │
│  │ Ingestion Script │───────▶│ Intelligence Event  │          │
│  │ ingest_all_*.py  │        │ Client (Kafka)      │          │
│  └──────────────────┘        └─────────────────────┘          │
│           │                            │                        │
│           │ HTTP                       │ Kafka                  │
│           ▼                            ▼                        │
└───────────┼────────────────────────────┼────────────────────────┘
            │                            │
            │                            │
┌───────────▼────────────────────────────▼────────────────────────┐
│                       OMNIARCHON                                │
│  (Backend services & intelligence infrastructure)               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │         archon-intelligence (FastAPI Service)            │ │
│  │                 Port: 8053                                │ │
│  │                                                           │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │ │
│  │  │  Pattern     │  │   Pattern    │  │  Phase 4      │ │ │
│  │  │  Learning    │  │  Analytics   │  │ Traceability  │ │ │
│  │  │  API         │  │  API         │  │  API          │ │ │
│  │  └──────────────┘  └──────────────┘  └───────────────┘ │ │
│  │         │                  │                  │         │ │
│  │         ▼                  ▼                  ▼         │ │
│  │  ┌──────────────────────────────────────────────────┐ │ │
│  │  │     Pattern Services Layer                       │ │ │
│  │  │  - Storage (Qdrant integration)                  │ │ │
│  │  │  - Analytics (success rate calculation)          │ │ │
│  │  │  - Traceability (usage tracking)                 │ │ │
│  │  │  - Quality metrics collection                    │ │ │
│  │  └──────────────────────────────────────────────────┘ │ │
│  │         │                                              │ │
│  │         ▼                                              │ │
│  │  ┌──────────────────────────────────────────────────┐ │ │
│  │  │     Data Layer                                    │ │ │
│  │  │  - Qdrant (vectors & embeddings)                 │ │ │
│  │  │  - PostgreSQL (metadata & analytics)             │ │ │
│  │  │  - Memgraph (relationships)                      │ │ │
│  │  └──────────────────────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## omniclaude Responsibilities

### What Lives Here

**Client-Side Pattern Consumption**:
- **Pattern Storage Client**: `agents/lib/patterns/pattern_storage.py`
  - Client wrapper around archon-intelligence APIs
  - In-memory fallback for testing
  - Pattern retrieval and similarity queries

- **Pattern Reuse**: `agents/lib/patterns/pattern_reuse.py`
  - Agent-level pattern application
  - Pattern matching for code generation
  - Integration with quality gates

**Ingestion & Data Collection**:
- **Ingestion Script**: `scripts/ingest_all_repositories.py`
  - Multi-repository Python file ingestion
  - Calls archon-intelligence `/assess/code` API
  - Pattern extraction from codebases

**Agent-Level Feedback**:
- **Pattern Feedback**: `agents/lib/pattern_feedback.py`
  - Collects feedback during agent execution
  - Tracks pattern usage success/failure
  - Publishes to Kafka for analytics

**Intelligence Integration**:
- **Event Client**: `agents/lib/intelligence_event_client.py`
  - Kafka-based intelligence queries
  - Async pattern discovery requests
  - Manifest injection support

**Models & Utilities**:
- **Pattern Models**: `agents/lib/models/model_code_pattern.py`
- **Pattern Library**: `agents/lib/pattern_library.py`
- **Pattern Tuner**: `agents/lib/pattern_tuner.py`

### File Paths Summary

```
omniclaude/
├── agents/
│   ├── lib/
│   │   ├── patterns/
│   │   │   ├── pattern_storage.py          # Client for archon APIs
│   │   │   ├── pattern_reuse.py            # Pattern application
│   │   │   ├── pattern_extractor.py        # Local extraction
│   │   │   └── test_patterns.py            # Tests
│   │   ├── pattern_feedback.py             # Feedback collection
│   │   ├── pattern_library.py              # Pattern catalog
│   │   ├── pattern_tuner.py                # Pattern optimization
│   │   ├── intelligence_event_client.py    # Kafka client
│   │   └── models/
│   │       └── model_code_pattern.py       # Pattern data models
│   └── examples/
│       └── pattern_storage_demo.py         # Usage examples
└── scripts/
    ├── ingest_all_repositories.py          # Ingestion script
    └── validate_pattern_integration.py     # Validation
```

### What Does NOT Live Here

- ❌ Pattern API endpoint definitions
- ❌ Pattern analytics calculation logic
- ❌ Qdrant integration code (beyond client calls)
- ❌ Pattern quality metrics collection
- ❌ Pattern usage tracking backend
- ❌ Success rate calculation

## omniarchon Responsibilities

### What Lives Here

**Backend Services (archon-intelligence)**:
- **Main Service**: `services/intelligence/app.py`
  - FastAPI application on port 8053
  - All pattern-related API routes
  - Service orchestration and lifecycle

**API Layer**:
- **Pattern Learning API**: `services/intelligence/src/api/pattern_learning/routes.py`
  - Pattern similarity matching
  - Hybrid scoring (semantic + structural)
  - Semantic analysis integration
  - Cache management

- **Pattern Analytics API**: `services/intelligence/src/api/pattern_analytics/routes.py`
  - Pattern success rates
  - Top performing patterns by node type
  - Emerging patterns detection
  - Pattern history and evolution

- **Phase 4 Traceability API**: `services/intelligence/src/api/phase4_traceability/routes.py`
  - Pattern usage tracking
  - Lineage tracking
  - Feedback analysis
  - Execution logs

**Service Layer**:
- **Pattern Storage**: `services/intelligence/src/services/pattern_learning/phase1_foundation/storage/`
  - `node_pattern_storage_effect.py` - ONEX Effect node for pattern storage
  - `node_qdrant_vector_index_effect.py` - Qdrant vector operations
  - `model_contract_pattern_storage.py` - Storage contracts
  - Direct Qdrant integration (15 files using QdrantClient)

- **Pattern Analytics**: `services/intelligence/src/api/pattern_analytics/service.py`
  - Success rate calculation logic
  - Confidence scoring with sample size adjustment
  - Top patterns ranking by weighted score
  - Emerging patterns detection

- **Pattern Traceability**: `services/intelligence/src/services/pattern_learning/phase4_traceability/`
  - `node_pattern_lineage_tracker_effect.py` - Usage tracking
  - `model_pattern_metrics.py` - Metrics models
  - `model_pattern_feedback.py` - Feedback aggregation

- **Pattern Matching**: `services/intelligence/src/services/pattern_learning/phase2_matching/`
  - `node_pattern_similarity_compute.py` - Similarity calculations
  - `node_hybrid_scorer_compute.py` - Hybrid scoring
  - `monitoring_hybrid_patterns.py` - Performance monitoring

**Data Layer Integration**:
- **Qdrant Integration**: 15 files with direct QdrantClient usage
  - Vector indexing and search
  - Embedding storage
  - Similarity queries

- **PostgreSQL Integration**:
  - Pattern metadata storage
  - Analytics data persistence
  - Usage statistics

- **Memgraph Integration**:
  - Pattern relationship graphs
  - Lineage tracking

### File Paths Summary

```
omniarchon/
└── services/
    └── intelligence/
        ├── app.py                          # Main FastAPI application
        ├── src/
        │   ├── api/
        │   │   ├── pattern_learning/
        │   │   │   ├── routes.py           # Pattern learning endpoints
        │   │   │   └── models.py           # API models
        │   │   ├── pattern_analytics/
        │   │   │   ├── routes.py           # Analytics endpoints
        │   │   │   ├── service.py          # Analytics logic
        │   │   │   └── models.py           # Response models
        │   │   └── phase4_traceability/
        │   │       └── routes.py           # Traceability endpoints
        │   ├── services/
        │   │   └── pattern_learning/
        │   │       ├── phase1_foundation/  # Storage & models
        │   │       │   ├── storage/
        │   │       │   │   ├── node_pattern_storage_effect.py
        │   │       │   │   └── node_qdrant_vector_index_effect.py
        │   │       │   └── models/
        │   │       │       ├── model_pattern.py
        │   │       │       └── model_pattern_provenance.py
        │   │       ├── phase2_matching/    # Similarity & scoring
        │   │       │   ├── node_pattern_similarity_compute.py
        │   │       │   ├── node_hybrid_scorer_compute.py
        │   │       │   └── monitoring_hybrid_patterns.py
        │   │       ├── phase3_validation/  # Quality validation
        │   │       ├── phase4_traceability/ # Usage tracking
        │   │       │   ├── node_pattern_lineage_tracker_effect.py
        │   │       │   └── models/
        │   │       │       ├── model_pattern_metrics.py
        │   │       │       └── model_pattern_feedback.py
        │   │       └── phase5_autonomous/  # Autonomous learning
        │   ├── effects/
        │   │   └── qdrant_indexer_effect.py  # Qdrant operations
        │   ├── handlers/
        │   │   ├── pattern_learning_handler.py
        │   │   ├── pattern_analytics_handler.py
        │   │   └── pattern_traceability_handler.py
        │   └── schemas/
        │       └── qdrant_schemas.py        # Qdrant models
        └── tests/
            ├── integration/
            │   ├── test_api_pattern_learning.py
            │   └── test_api_pattern_analytics.py
            └── unit/
                └── pattern_learning/
```

### What Does NOT Live Here

- ❌ Agent-level pattern usage (that's in omniclaude agents)
- ❌ Client-side pattern storage wrappers
- ❌ Ingestion scripts (those call the APIs we provide)

## Rationale

### Why This Separation?

**Separation of Concerns**:
- **omniarchon**: Infrastructure services, scalable backends, multi-tenant support
- **omniclaude**: Agent utilities, client tools, local development

**Performance & Scalability**:
- **omniarchon**: Centralized Qdrant/PostgreSQL access, caching, connection pooling
- **omniclaude**: Lightweight clients, minimal dependencies

**Service Boundaries**:
- **archon-intelligence** (omniarchon) is a standalone FastAPI service
- Can be deployed independently, scaled horizontally
- omniclaude agents are clients that consume the service

**Data Ownership**:
- Pattern data stored in Qdrant/PostgreSQL/Memgraph (omniarchon)
- Analytics calculated server-side for consistency
- Clients receive read-only views via APIs

**Development Workflow**:
- Backend changes (APIs, analytics) → omniarchon
- Client changes (agent integration) → omniclaude
- API contract defines the boundary

## Communication Protocol

### omniclaude → omniarchon

**HTTP REST APIs**:
```
POST http://localhost:8053/api/pattern-learning/similarity
POST http://localhost:8053/api/pattern-learning/hybrid-score
GET  http://localhost:8053/api/pattern-analytics/success-rates
GET  http://localhost:8053/api/pattern-analytics/top-patterns
```

**Kafka Event Bus** (async intelligence):
```
Topic: dev.archon-intelligence.intelligence.code-analysis-requested.v1
       → archon-intelligence processes request
Topic: dev.archon-intelligence.intelligence.code-analysis-completed.v1
       → omniclaude receives results
```

### Data Flow Example

1. **Pattern Ingestion**:
   ```
   omniclaude/scripts/ingest_all_repositories.py
     ↓ HTTP POST
   omniarchon/services/intelligence (app.py)
     ↓ /assess/code endpoint
   Pattern extraction + Qdrant indexing
     ↓ Vector storage
   Qdrant database
   ```

2. **Pattern Usage Tracking**:
   ```
   omniclaude/agents/lib/pattern_feedback.py
     ↓ Kafka event
   omniarchon/services/intelligence
     ↓ Pattern traceability handler
   PostgreSQL (usage statistics)
   ```

3. **Analytics Query**:
   ```
   Pattern Dashboard (future)
     ↓ HTTP GET
   omniarchon/api/pattern-analytics/success-rates
     ↓ Query PostgreSQL + Qdrant
   Return aggregated metrics
   ```

## Implementation Implications

### For Pattern Dashboard Backend (7 Tasks)

**Tasks in omniarchon**:
1. ✅ Pattern quality metrics API endpoint
2. ✅ Pattern analytics calculation logic
3. ✅ Usage tracking database schema (already exists)
4. ✅ Qdrant integration for pattern retrieval (already exists)
5. ✅ Success rate calculation (already exists in pattern_analytics)
6. ⚠️  Dashboard API endpoints (new routes in pattern_analytics)
7. ⚠️  Historical trend analysis (new service logic)

**Tasks in omniclaude**:
- Pattern feedback collection (already exists)
- Client utilities for dashboard data (if needed)
- Agent integration updates (if API changes)

**Shared/Cross-Repo**:
- None (clean API boundary)

### Deployment Considerations

**omniarchon deployment**:
- Docker container: `archon-intelligence`
- Rebuild required: `docker-compose up -d --build archon-intelligence`
- Port: 8053

**omniclaude deployment**:
- No service deployment (client-side code)
- Agent updates require git pull on deployment machine

## Dependencies

### omniclaude Dependencies on omniarchon

- archon-intelligence service running on localhost:8053
- Kafka broker for async intelligence queries
- API stability (contract versioning recommended)

### omniarchon Dependencies on omniclaude

- None (services are independent)
- Kafka events from omniclaude agents (optional, for analytics)

## Conclusion

**Clear boundaries established**:

| Component | Repository | Reason |
|-----------|-----------|--------|
| Pattern APIs | omniarchon | Service infrastructure |
| Pattern storage (Qdrant) | omniarchon | Database integration |
| Analytics calculation | omniarchon | Server-side aggregation |
| Usage tracking backend | omniarchon | Data persistence layer |
| Pattern feedback collection | omniclaude | Agent-level instrumentation |
| Ingestion scripts | omniclaude | Client-side tooling |
| Pattern client utilities | omniclaude | Agent consumption |

**For Pattern Dashboard backend work**:
- Primary repository: **omniarchon** (90% of work)
- Secondary repository: **omniclaude** (10% - client updates if needed)

**Next Steps**:
1. Review existing pattern_analytics API endpoints (already extensive)
2. Identify gaps for dashboard requirements
3. Create detailed implementation plan in omniarchon
4. Document any required omniclaude client updates
