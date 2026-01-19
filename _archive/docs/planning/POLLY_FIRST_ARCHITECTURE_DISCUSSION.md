# Polly-First Architecture Discussion

**Date**: 2025-10-30
**Correlation ID**: 6e30ba1f-a80f-4ec8-ac3c-d007b4f7c362
**Status**: Discussion Only - No Implementation

**📊 Implementation Status**: Database event-driven architecture partially implemented
**🔗 Current Progress**: See [docs/EVENT_DRIVEN_DATABASE_IMPLEMENTATION_STATUS.md](docs/EVENT_DRIVEN_DATABASE_IMPLEMENTATION_STATUS.md)

## Executive Summary

This document analyzes the proposed architectural shift to a "Polly-first" routing model where the polymorphic agent handles all work except simple Q&A, all API interactions flow through Claude Code skills, and all database queries use event bus communication.

**Key Findings**:
- ✅ Skills infrastructure exists with Kafka integration
- ✅ Event bus already handles intelligence queries
- ⚠️ No PostgreSQL adapter service currently exists
- ⚠️ Some API calls still direct HTTP (MCP, Quorum)
- ⚠️ Polly-first routing requires significant router changes

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Polly-First Routing Design](#polly-first-routing-design)
3. [Skills Architecture Status](#skills-architecture-status)
4. [Database Query Event Bus](#database-query-event-bus)
5. [API Audit Results](#api-audit-results)
6. [Event Bus Patterns](#event-bus-patterns)
7. [Performance Impact Analysis](#performance-impact-analysis)
8. [Migration Strategy](#migration-strategy)
9. [Trade-offs and Recommendations](#trade-offs-and-recommendations)

---

## 1. Current State Analysis

### Infrastructure Discovered

**Event Bus** (Kafka/Redpanda):
- Bootstrap servers: `192.168.86.200:9092`
- Admin UI: `http://localhost:8080`
- Topics in use:
  - `dev.archon-intelligence.intelligence.code-analysis-requested.v1`
  - `dev.archon-intelligence.intelligence.code-analysis-completed.v1`
  - `dev.archon-intelligence.intelligence.code-analysis-failed.v1`
  - `agent-routing-decisions`
  - `agent-transformation-events`
  - `router-performance-metrics`
  - `agent-actions`
  - `documentation-changed`

**Services Running**:
- `archon-intelligence` - Intelligence coordinator (HTTP: 8053)
- `archon-qdrant` - Vector database (HTTP: 6333)
- `archon-bridge` - **Health check proxy only** (NOT PostgreSQL adapter)
- `archon-search` - Full-text search (HTTP: 8054)
- `archon-memgraph` - Graph database (Bolt: 7687)
- `archon-kafka-consumer` - Event consumer
- `archon-server` - Archon MCP server (HTTP: 8150)
- `omniclaude_agent_consumer` - Agent tracking consumer
- PostgreSQL - `omninode_bridge` database (Port: 5436)

**Database Access** (34 tables in `omninode_bridge`):
- `agent_routing_decisions`
- `agent_transformation_events`
- `router_performance_metrics`
- `agent_manifest_injections`
- `agent_execution_logs`
- 29 other tables (ONEX patterns, workflows, quality metrics, etc.)

### Current Routing Logic

**File**: `agents/lib/agent_router.py`

**Flow**:
1. Check cache (5ms on hit)
2. Extract explicit agent request (`@agent-X`, `use agent-X`)
3. Fuzzy trigger matching with confidence scoring
4. Sort by confidence
5. Return top N recommendations
6. Cache results

**Performance**:
- Explicit request: ~5ms
- Cache hit: ~5ms
- Cache miss (fuzzy matching): ~50-100ms
- Confidence scoring: 4 components (trigger, context, capability, historical)

**Self-Transformation Validation** (Step 1.5):
- Validates polymorphic-agent self-selection
- Requires orchestration keywords or detailed reasoning
- Blocks low-confidence self-transformation (<0.7)
- Target: <10% self-transformation rate (currently 45.5% - critical issue)

### Skills Infrastructure

**Location**: `/Volumes/PRO-G40/Code/omniclaude/skills` → symlinked to `~/.claude/skills/`

**Categories**:
- `agent-tracking/` - Routing decisions, transformations, performance metrics
- `agent-observability/` - Health checks, diagnostics, reports
- `intelligence/` - Intelligence gathering requests
- `log-execution/` - Agent execution logging
- `_shared/` - Database helpers, utilities

**Execution Models**:
1. **Direct PostgreSQL** (`execute.py`):
   - Uses `asyncpg` connection pooling
   - Blocking database writes
   - ~10-50ms latency
   - Fallback for Kafka failures

2. **Kafka Event Bus** (`execute_kafka.py`):
   - Non-blocking publish
   - <5ms publish latency
   - Multiple consumers (DB, analytics, dashboards)
   - **Preferred approach**

**Example Skills**:
```bash
# Agent tracking (Kafka versions available)
~/.claude/skills/agent-tracking/log-routing-decision/execute_kafka.py
~/.claude/skills/agent-tracking/log-transformation/execute_kafka.py
~/.claude/skills/agent-tracking/log-performance-metrics/execute_kafka.py
~/.claude/skills/agent-tracking/log-agent-action/execute_kafka.py

# Intelligence gathering
~/.claude/skills/intelligence/request-intelligence/execute.py

# Observability
~/.claude/skills/agent-observability/check-health/execute.py
~/.claude/skills/agent-observability/generate-report/execute.py
```

**Skill Format** (SKILL.md):
```yaml
---
name: log-routing-decision
description: Log agent routing decisions to Kafka
---

# Log Routing Decision

## Usage
```bash
python3 ~/.claude/skills/agent-tracking/log-routing-decision/execute_kafka.py \
  --agent "agent-performance" \
  --confidence 0.92 \
  --strategy "enhanced_fuzzy_matching" \
  --latency-ms 45 \
  --correlation-id "uuid"
```
```

### Database Access Patterns

**Files with Direct DB Connections** (14 total):
```
agents/lib/db.py                              ← Connection pooling
agents/lib/manifest_injector.py               ← Manifest storage
agents/lib/agent_history_browser.py           ← History queries
agents/lib/kafka_agent_action_consumer.py     ← Kafka→DB consumer
agents/lib/intelligence_gatherer.py           ← Intelligence queries
agents/lib/router_metrics_logger.py           ← Metrics logging
agents/lib/persistence.py                     ← General persistence
agents/parallel_execution/observability_report.py  ← Reports
agents/parallel_execution/db_connection_pool.py    ← Connection pool
agents/parallel_execution/database_integration.py  ← DB integration
agents/tests/test_business_logic_generator.py      ← Tests
agents/migrations/validate_002_migration.py        ← Migrations
```

**Connection Pattern** (`agents/lib/db.py`):
```python
# Environment-based DSN
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<set_in_env>

# asyncpg connection pooling
pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
```

### API Calls Audit

**HTTP Client Usage** (6 files):

1. **`agents/lib/intelligence_event_client.py`**:
   - ✅ **Already event bus!**
   - Uses Kafka for intelligence queries
   - Request-response pattern with correlation tracking
   - Topics: `code-analysis-requested`, `code-analysis-completed`, `code-analysis-failed`

2. **`agents/parallel_execution/mcp_client.py`**:
   - ❌ Direct HTTP to Archon MCP server
   - Endpoint: `http://localhost:8051/mcp`
   - Methods: `assess_code_quality`, `perform_rag_query`, `search_code_examples`
   - Uses `httpx.AsyncClient`
   - Circuit breaker protection

3. **`agents/parallel_execution/quorum_validator.py`**:
   - ❌ Direct HTTP to Gemini and Z.ai APIs
   - Gemini endpoint: `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent`
   - Z.ai endpoint: `https://api.z.ai/api/anthropic/v1/messages`
   - Models: Gemini Flash, GLM-4.5-Air, GLM-4.5, GLM-4.6
   - Used for AI quorum consensus validation

4. **`agents/parallel_execution/code_extractor.py`**:
   - Minimal HTTP usage (likely for external code fetching)

5. **`agents/lib/test_intelligence_event_client.py`**:
   - Test file (not production code)

6. **`agents/tests/test_framework_integration.py`**:
   - Test file (not production code)

---

## 2. Polly-First Routing Design

### Proposed Model

**Current**:
```
User Request → Router → Trigger Matching → Specialized Agent
                  ↓
            (Confidence Scoring)
```

**Proposed**:
```
User Request → Simple Q&A Detector
                  ↓
            Is simple question?
                  ↓
              YES → Direct Response
                  ↓
               NO → Polymorphic Agent
                        ↓
                  Task Analysis & Delegation
                        ↓
                  Specialized Agents (as sub-tasks)
                        ↓
                  Validation & Response
```

### Decision Tree for Simple Q&A Detection

**Method 1: Heuristic-Based** (Fast, ~5ms):
```python
def is_simple_question(request: str) -> bool:
    """
    Heuristic detection of simple questions.

    Returns True if request is likely a simple question that can be
    answered directly from context without multi-step work.
    """
    request_lower = request.lower().strip()

    # Short length threshold
    if len(request.split()) > 50:
        return False  # Long requests likely need work

    # Question patterns
    question_patterns = [
        r'^what (is|are|does|do)',
        r'^how (does|do|can|is)',
        r'^why (is|are|does|do)',
        r'^when (is|are|does|do)',
        r'^where (is|are|does|do)',
        r'^who (is|are|does|do)',
        r'^explain ',
        r'^describe ',
        r'^tell me about',
    ]

    has_question_pattern = any(
        re.match(pattern, request_lower)
        for pattern in question_patterns
    )

    # Action verbs indicate work needed
    action_verbs = [
        'create', 'build', 'implement', 'generate', 'write',
        'add', 'update', 'modify', 'fix', 'debug',
        'refactor', 'optimize', 'test', 'deploy',
        'analyze', 'investigate', 'audit', 'review',
    ]

    has_action_verb = any(verb in request_lower for verb in action_verbs)

    # Simple question if:
    # - Has question pattern AND no action verbs
    # - Short length AND no action verbs
    return (has_question_pattern or len(request.split()) < 10) and not has_action_verb
```

**Method 2: LLM Classification** (Slow, ~500ms):
```python
async def is_simple_question_llm(request: str) -> bool:
    """
    LLM-based classification using fast Claude Haiku.

    More accurate but adds latency.
    """
    prompt = f"""
    Classify this user request:

    Request: {request}

    Answer with ONLY "SIMPLE" or "COMPLEX":
    - SIMPLE: Can be answered with existing knowledge, no code changes needed
    - COMPLEX: Requires multi-step work, code changes, or coordination
    """

    # Quick Claude Haiku call
    response = await claude_haiku_classify(prompt)
    return response.strip().upper() == "SIMPLE"
```

**Method 3: Hybrid** (Balanced, ~10-100ms):
```python
async def is_simple_question_hybrid(request: str) -> tuple[bool, float]:
    """
    Hybrid approach: heuristics first, LLM for edge cases.

    Returns (is_simple, confidence).
    """
    # Quick heuristic check
    heuristic_simple = is_simple_question(request)

    # High confidence cases - no LLM needed
    if len(request.split()) < 5:
        return True, 1.0  # Very short = simple

    if any(verb in request.lower() for verb in ['create', 'build', 'implement']):
        return False, 1.0  # Clear action verbs = complex

    # Ambiguous cases - use LLM
    if heuristic_simple and len(request.split()) > 15:
        # Heuristic says simple but longer text - verify with LLM
        llm_simple = await is_simple_question_llm(request)
        return llm_simple, 0.8

    return heuristic_simple, 0.9
```

**Recommendation**: **Method 3 (Hybrid)** for best balance of accuracy and performance.

### Polly Delegation Model

**Polymorphic Agent as Orchestrator**:

```python
class PolymorphicAgentOrchestrator:
    """
    Polymorphic agent in orchestrator role.

    Responsibilities:
    1. Analyze user request complexity
    2. Break down into sub-tasks
    3. Delegate to specialized agents
    4. Coordinate parallel/sequential execution
    5. Validate results
    6. Synthesize final response
    """

    async def handle_request(self, user_request: str) -> Response:
        # 1. Analyze task complexity
        task_analysis = await self.analyze_task(user_request)

        # 2. Break down into sub-tasks
        sub_tasks = await self.decompose_task(task_analysis)

        # 3. Route sub-tasks to specialized agents
        agent_assignments = []
        for sub_task in sub_tasks:
            # Use existing router for specialized agent selection
            recommendations = self.router.route(sub_task.description)
            assigned_agent = recommendations[0].agent_name
            agent_assignments.append((sub_task, assigned_agent))

        # 4. Execute (parallel when possible)
        results = await self.execute_delegated_tasks(agent_assignments)

        # 5. Validate results
        validation = await self.validate_results(results)

        # 6. Synthesize response
        response = await self.synthesize_response(results, validation)

        return response
```

**Example Flow**:

```
User: "Add tests to the user service"

Polly Analysis:
  - Task type: Testing
  - Complexity: Medium
  - Sub-tasks:
    1. Read user service code
    2. Generate test cases
    3. Write test files
    4. Validate test coverage

Polly Delegation:
  Sub-task 1 → agent-code-reader
  Sub-task 2 → agent-test-generator
  Sub-task 3 → agent-code-writer
  Sub-task 4 → agent-quality-checker

Polly Coordination:
  - Execute 1-2 sequentially (need code before generating tests)
  - Execute 3-4 sequentially (need tests before validating)
  - Validate results
  - Report back to user

Final Response:
  "✅ Added 23 unit tests to user service
     Coverage: 87% (up from 45%)
     Files created:
       - tests/test_user_service.py (15 tests)
       - tests/test_user_models.py (8 tests)
     All tests passing ✓"
```

### Performance Impact

**Current Direct Routing**:
- Cache hit: ~5ms
- Cache miss: ~50-100ms
- Total: ~5-100ms to get to specialized agent

**Proposed Polly-First**:
- Simple Q&A detection: ~5-10ms (heuristic) or ~500ms (LLM)
- Polly invocation: ~50ms (task analysis)
- Delegation decision: ~50-100ms (router call per sub-task)
- Total: ~105-160ms overhead + sub-task execution time

**Impact**:
- ✅ Better task decomposition (worth the latency)
- ✅ Improved coordination (parallel execution)
- ⚠️ +100ms latency for all complex tasks
- ⚠️ +500ms if using LLM classification

**Mitigation**:
- Use heuristic-first hybrid approach
- Cache delegation patterns
- Parallelize sub-task routing

---

## 3. Skills Architecture Status

### Current State

**Skills Exist**: ✅ Located at `/Volumes/PRO-G40/Code/omniclaude/skills`

**Skill Categories**:
- ✅ `agent-tracking/` - 5 skills (routing, transformation, performance, actions, detection)
- ✅ `agent-observability/` - 4 skills (health, diagnostics, reports, checks)
- ✅ `intelligence/` - 1 skill (intelligence gathering)
- ✅ `log-execution/` - Agent execution logging
- ✅ `_shared/` - Database helpers, utilities

**Kafka Integration**: ✅ Available
- All agent-tracking skills have `execute_kafka.py` versions
- Non-blocking publish to Kafka topics
- Multiple consumers (PostgreSQL, analytics, dashboards)

### Skills Requiring Updates

**1. Agent Tracking Skills** - ✅ Already Updated

All agent-tracking skills have Kafka versions:
```bash
log-routing-decision/execute_kafka.py
log-transformation/execute_kafka.py
log-performance-metrics/execute_kafka.py
log-agent-action/execute_kafka.py
```

**Status**: No updates needed, already use event bus only.

**2. Intelligence Skills** - ⚠️ Mixed State

`intelligence/request-intelligence/execute.py`:
- Currently uses direct API calls to Archon MCP
- **Should use**: Event bus intelligence client (`agents/lib/intelligence_event_client.py`)
- **Update needed**: Replace MCP HTTP calls with event bus

**3. Observability Skills** - ⚠️ Direct DB

`agent-observability/check-health/execute.py`:
`agent-observability/generate-report/execute.py`:
- Currently use direct PostgreSQL queries
- **Should use**: Database query event bus (when available)
- **Update needed**: Wait for PostgreSQL adapter service

### Skills to Create

**Skill Category**: `external-api/`

**Needed Skills**:

1. **`call-archon-mcp/`** - Archon MCP tool calls via event bus
2. **`validate-quorum/`** - AI quorum validation via event bus
3. **`query-qdrant/`** - Qdrant vector search via event bus
4. **`query-memgraph/`** - Memgraph graph queries via event bus
5. **`query-database/`** - PostgreSQL queries via event bus

**Example Structure**:
```
skills/external-api/call-archon-mcp/
  ├── SKILL.md           ← Instructions for Claude
  ├── execute_kafka.py   ← Kafka event bus version
  └── execute.py         ← Direct API fallback
```

**SKILL.md Template**:
```yaml
---
name: call-archon-mcp
description: Call Archon MCP tools via event bus
---

# Call Archon MCP Tool

## When to Use
- When you need to call Archon MCP intelligence tools
- For code quality assessment, RAG queries, pattern search

## Usage
```bash
python3 ~/.claude/skills/external-api/call-archon-mcp/execute_kafka.py \
  --tool "assess_code_quality" \
  --params '{"content": "...", "language": "python"}' \
  --correlation-id "uuid" \
  --timeout 5000
```

## Event Flow
1. Publish to `archon-mcp.tool-call-requested.v1`
2. Wait for `archon-mcp.tool-call-completed.v1`
3. Return result or timeout
```

---

## 4. Database Query Event Bus

### Current State: No PostgreSQL Adapter

**Discovery**:
- ❌ No dedicated PostgreSQL adapter service found
- `archon-bridge` container is NOT a database adapter (just health check proxy)
- No Kafka topics for database queries:
  ```bash
  $ docker exec omninode-bridge-redpanda rpk topic list | grep -i postgres
  # (no results)
  ```

**Current Database Access**:
- All agents use direct `asyncpg` connections
- Connection pooling via `agents/lib/db.py`
- 14 files with direct database access
- Skills use `_shared/db_helper.py`

### Proposed PostgreSQL Adapter Service

**Architecture**:

```
Agent → Skill → Kafka Event Bus → PostgreSQL Adapter → PostgreSQL
                                          ↓
                                    Connection Pool
                                    Query Validation
                                    Error Handling
```

**Service Specification**:

**Name**: `omniclaude-postgres-adapter`
**Port**: 8060 (HTTP health), N/A (Kafka only)
**Topics**:
- Subscribe: `postgres.query.requested.v1`
- Publish: `postgres.query.completed.v1`, `postgres.query.failed.v1`

**Event Schema**:

```json
// Request Event (postgres.query.requested.v1)
{
  "event_id": "uuid",
  "event_type": "POSTGRES_QUERY_REQUESTED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T...",
  "service": "omniclaude",
  "payload": {
    "query": "SELECT * FROM agent_routing_decisions WHERE correlation_id = $1",
    "params": ["uuid"],
    "operation_type": "SELECT",  // SELECT, INSERT, UPDATE, DELETE
    "timeout_ms": 5000,
    "read_only": true,
    "options": {
      "return_format": "json",  // json, csv, raw
      "max_rows": 1000
    }
  }
}

// Response Event (postgres.query.completed.v1)
{
  "event_id": "uuid",
  "event_type": "POSTGRES_QUERY_COMPLETED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T...",
  "service": "omniclaude-postgres-adapter",
  "payload": {
    "rows": [...],
    "row_count": 42,
    "columns": ["id", "agent_name", "confidence"],
    "execution_time_ms": 23,
    "query_plan": "..."  // Optional for debugging
  }
}

// Error Event (postgres.query.failed.v1)
{
  "event_id": "uuid",
  "event_type": "POSTGRES_QUERY_FAILED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T...",
  "service": "omniclaude-postgres-adapter",
  "payload": {
    "error_code": "SYNTAX_ERROR",
    "error_message": "syntax error at or near 'SELCT'",
    "query": "SELCT * FROM ...",
    "suggestions": ["Did you mean 'SELECT'?"]
  }
}
```

**Skill Implementation**:

```python
#!/usr/bin/env python3
"""
Query Database Skill - Kafka Version

Executes PostgreSQL queries via event bus.
"""

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4
from kafka import KafkaProducer, KafkaConsumer

# Kafka configuration
KAFKA_BROKERS = "192.168.86.200:9092"
TOPIC_REQUEST = "postgres.query.requested.v1"
TOPIC_COMPLETED = "postgres.query.completed.v1"
TOPIC_FAILED = "postgres.query.failed.v1"

def query_database_kafka(query: str, params: list, timeout_ms: int = 5000) -> dict:
    """
    Execute PostgreSQL query via Kafka event bus.

    Args:
        query: SQL query string
        params: Query parameters
        timeout_ms: Timeout in milliseconds

    Returns:
        Query results or error
    """
    correlation_id = str(uuid4())

    # Build event
    event = {
        "event_id": str(uuid4()),
        "event_type": "POSTGRES_QUERY_REQUESTED",
        "correlation_id": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "omniclaude",
        "payload": {
            "query": query,
            "params": params,
            "operation_type": query.strip().split()[0].upper(),
            "timeout_ms": timeout_ms,
            "read_only": query.strip().upper().startswith("SELECT"),
            "options": {
                "return_format": "json",
                "max_rows": 1000
            }
        }
    }

    # Publish request
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKERS.split(","),
        value_serializer=lambda v: json.dumps(v).encode("utf-8")
    )
    producer.send(TOPIC_REQUEST, value=event)
    producer.flush()

    # Wait for response
    consumer = KafkaConsumer(
        TOPIC_COMPLETED,
        TOPIC_FAILED,
        bootstrap_servers=KAFKA_BROKERS.split(","),
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        group_id=f"query-skill-{correlation_id}",
        auto_offset_reset="latest"
    )

    # Poll for response with timeout
    timeout_seconds = timeout_ms / 1000.0
    start_time = time.time()

    for message in consumer:
        response = message.value

        if response.get("correlation_id") != correlation_id:
            continue  # Not our response

        if message.topic == TOPIC_COMPLETED:
            return {
                "success": True,
                "rows": response["payload"]["rows"],
                "row_count": response["payload"]["row_count"],
                "execution_time_ms": response["payload"]["execution_time_ms"]
            }

        if message.topic == TOPIC_FAILED:
            return {
                "success": False,
                "error": response["payload"]["error_message"],
                "error_code": response["payload"]["error_code"]
            }

        # Check timeout
        if time.time() - start_time > timeout_seconds:
            return {
                "success": False,
                "error": f"Query timeout after {timeout_ms}ms",
                "error_code": "TIMEOUT"
            }

    consumer.close()
    producer.close()
```

### Benefits of Database Event Bus

**1. Security**:
- ✅ No direct credentials in agent code
- ✅ Centralized access control
- ✅ Query validation and sanitization
- ✅ Audit trail of all queries

**2. Performance**:
- ✅ Connection pooling at adapter level
- ✅ Query caching (for read-only queries)
- ✅ Load balancing across read replicas
- ✅ Query optimization hints

**3. Observability**:
- ✅ All queries logged to Kafka (audit trail)
- ✅ Query performance metrics
- ✅ Slow query detection
- ✅ Error rate monitoring

**4. Resilience**:
- ✅ Graceful degradation (fallback to cached data)
- ✅ Circuit breaker protection
- ✅ Automatic retry with exponential backoff
- ✅ Dead letter queue for failed queries

**5. Flexibility**:
- ✅ Easy to switch database backends
- ✅ Multiple consumers (analytics, caching, archival)
- ✅ Query transformation (e.g., SQL → NoSQL)
- ✅ A/B testing of query optimizations

### Implementation Priority

**Phase 1**: Core Adapter Service
- PostgreSQL connection pooling
- Basic query execution (SELECT, INSERT, UPDATE, DELETE)
- Kafka event handling
- Error handling and timeouts

**Phase 2**: Query Validation & Security
- SQL injection prevention
- Query complexity limits (prevent DOS)
- Read-only enforcement
- Access control (which agents can query which tables)

**Phase 3**: Performance Optimization
- Query result caching
- Read replica load balancing
- Query plan analysis
- Slow query logging

**Phase 4**: Advanced Features
- Transaction support (BEGIN, COMMIT, ROLLBACK)
- Batch query execution
- Streaming large result sets
- Query debugging tools

---

## 5. API Audit Results

### APIs Currently Using Direct HTTP

**1. Archon MCP** (`agents/parallel_execution/mcp_client.py`):

**Current**:
```python
class ArchonMCPClient:
    def __init__(self, base_url="http://localhost:8051"):
        self.mcp_url = f"{base_url}/mcp"
        self.client = httpx.AsyncClient()

    async def assess_code_quality(self, content, source_path, language):
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "assess_code_quality", "arguments": {...}}
        }
        response = await self.client.post(self.mcp_url, json=request)
        return response.json()
```

**Proposed Event Bus**:
```python
# Skill: call-archon-mcp
python3 ~/.claude/skills/external-api/call-archon-mcp/execute_kafka.py \
  --tool "assess_code_quality" \
  --params '{"content": "...", "language": "python"}' \
  --correlation-id "uuid"
```

**Topics**:
- `archon-mcp.tool-call-requested.v1`
- `archon-mcp.tool-call-completed.v1`
- `archon-mcp.tool-call-failed.v1`

**Adapter Service**: `omniclaude-mcp-adapter`
- Subscribes to tool call requests
- Forwards to Archon MCP HTTP endpoint
- Publishes results back to Kafka

**2. AI Quorum** (`agents/parallel_execution/quorum_validator.py`):

**Current**:
```python
class QuorumValidator:
    async def validate_intent(self, user_prompt, task_breakdown):
        # Direct HTTP calls to Gemini API
        response = await httpx.post(
            "https://generativelanguage.googleapis.com/v1beta/...",
            headers={"x-goog-api-key": self.gemini_api_key},
            json={...}
        )

        # Direct HTTP calls to Z.ai API
        response = await httpx.post(
            "https://api.z.ai/api/anthropic/v1/messages",
            headers={"x-api-key": self.zai_api_key},
            json={...}
        )

        # Aggregate responses
        return quorum_result
```

**Proposed Event Bus**:
```python
# Skill: validate-quorum
python3 ~/.claude/skills/external-api/validate-quorum/execute_kafka.py \
  --user-prompt "Implement user authentication" \
  --task-breakdown '{"tasks": [...]}' \
  --correlation-id "uuid"
```

**Topics**:
- `ai-quorum.validation-requested.v1`
- `ai-quorum.validation-completed.v1`
- `ai-quorum.validation-failed.v1`

**Adapter Service**: `omniclaude-quorum-adapter`
- Subscribes to validation requests
- Fans out to multiple AI providers (Gemini, Z.ai, local models)
- Aggregates responses with consensus algorithm
- Publishes quorum result back to Kafka

**Benefits**:
- ✅ Parallel model queries (faster consensus)
- ✅ Fault tolerance (continue if 1 model fails)
- ✅ Model selection flexibility (configure via Kafka)
- ✅ Rate limiting at adapter level

**3. Qdrant** (Currently via HTTP in `intelligence_event_client.py`):

**Current**: Event bus already! ✅
- `intelligence_event_client.py` uses Kafka
- Queries sent to `archon-intelligence` service
- `archon-intelligence` queries Qdrant via HTTP internally

**No changes needed** - intelligence queries already use event bus.

**4. PostgreSQL** (Direct `asyncpg` connections):

**Current**: 14 files with direct connections
**Proposed**: Database query event bus (see Section 4)

### Migration Candidates Summary

| API | Current Method | Event Bus Ready? | Adapter Needed? | Priority |
|-----|----------------|------------------|-----------------|----------|
| Intelligence (Qdrant) | Kafka ✅ | Yes | No | - |
| Agent Tracking | Kafka ✅ | Yes | No | - |
| Archon MCP | HTTP ❌ | No | Yes | High |
| AI Quorum | HTTP ❌ | No | Yes | Medium |
| PostgreSQL | Direct ❌ | No | Yes | High |
| Memgraph | Direct ❌ | No | Yes | Low |

---

## 6. Event Bus Patterns

### Standard Event Schema

**Base Event Structure**:
```json
{
  "event_id": "uuid-v4",              // Unique event identifier
  "event_type": "OPERATION_ACTION",   // e.g., "CODE_ANALYSIS_REQUESTED"
  "correlation_id": "uuid-v4",        // Request correlation for tracing
  "timestamp": "2025-10-30T...",      // ISO 8601 timestamp
  "service": "service-name",          // Originating service
  "payload": {
    // Operation-specific data
  }
}
```

### Request-Response Pattern

**1. Request Event**:
```json
{
  "event_id": "uuid-1",
  "event_type": "DATABASE_QUERY_REQUESTED",
  "correlation_id": "uuid-correlation",
  "timestamp": "2025-10-30T14:30:00Z",
  "service": "omniclaude-agent",
  "payload": {
    "query": "SELECT * FROM agent_routing_decisions",
    "params": [],
    "timeout_ms": 5000
  }
}
```

**2. Success Response Event**:
```json
{
  "event_id": "uuid-2",
  "event_type": "DATABASE_QUERY_COMPLETED",
  "correlation_id": "uuid-correlation",  // Same correlation ID!
  "timestamp": "2025-10-30T14:30:00.123Z",
  "service": "omniclaude-postgres-adapter",
  "payload": {
    "rows": [...],
    "row_count": 42,
    "execution_time_ms": 23
  }
}
```

**3. Error Response Event**:
```json
{
  "event_id": "uuid-3",
  "event_type": "DATABASE_QUERY_FAILED",
  "correlation_id": "uuid-correlation",  // Same correlation ID!
  "timestamp": "2025-10-30T14:30:00.050Z",
  "service": "omniclaude-postgres-adapter",
  "payload": {
    "error_code": "SYNTAX_ERROR",
    "error_message": "syntax error near 'SELCT'",
    "query": "SELCT * FROM ...",
    "suggestions": ["Did you mean 'SELECT'?"]
  }
}
```

### Timeout Handling

**Client-Side**:
```python
async def wait_for_response(correlation_id: str, timeout_ms: int) -> dict:
    """
    Wait for response event with timeout.

    Returns response payload or raises TimeoutError.
    """
    timeout_seconds = timeout_ms / 1000.0
    start_time = time.time()

    async for message in consumer:
        response = message.value

        # Check correlation ID
        if response.get("correlation_id") != correlation_id:
            continue

        # Check event type
        if response.get("event_type").endswith("_COMPLETED"):
            return response["payload"]

        if response.get("event_type").endswith("_FAILED"):
            raise RuntimeError(response["payload"]["error_message"])

        # Check timeout
        if time.time() - start_time > timeout_seconds:
            raise TimeoutError(f"Request timeout after {timeout_ms}ms")
```

**Server-Side**:
```python
async def process_request(request_event: dict):
    """
    Process request event with timeout protection.

    Publishes FAILED event if processing exceeds timeout.
    """
    correlation_id = request_event["correlation_id"]
    timeout_ms = request_event["payload"].get("timeout_ms", 5000)

    try:
        # Process with timeout
        result = await asyncio.wait_for(
            do_work(request_event["payload"]),
            timeout=timeout_ms / 1000.0
        )

        # Publish success
        await publish_event({
            "event_type": "OPERATION_COMPLETED",
            "correlation_id": correlation_id,
            "payload": result
        })

    except asyncio.TimeoutError:
        # Publish timeout error
        await publish_event({
            "event_type": "OPERATION_FAILED",
            "correlation_id": correlation_id,
            "payload": {
                "error_code": "TIMEOUT",
                "error_message": f"Processing timeout after {timeout_ms}ms"
            }
        })

    except Exception as e:
        # Publish general error
        await publish_event({
            "event_type": "OPERATION_FAILED",
            "correlation_id": correlation_id,
            "payload": {
                "error_code": "PROCESSING_ERROR",
                "error_message": str(e)
            }
        })
```

### Error Handling Patterns

**1. Retry with Exponential Backoff**:
```python
async def publish_with_retry(event: dict, topic: str, max_retries: int = 3):
    """
    Publish event with exponential backoff retry.

    Retries on transient failures (network errors, broker unavailable).
    Does NOT retry on validation errors (bad event schema).
    """
    retry_delays = [1, 2, 5]  # seconds

    for attempt in range(max_retries):
        try:
            await producer.send(topic, value=event)
            return  # Success

        except KafkaConnectionError as e:
            if attempt < max_retries - 1:
                delay = retry_delays[attempt]
                await asyncio.sleep(delay)
            else:
                raise  # Final attempt failed

        except KafkaValidationError:
            # Don't retry validation errors
            raise
```

**2. Dead Letter Queue**:
```python
async def process_with_dlq(message, processor_fn):
    """
    Process message with dead letter queue fallback.

    Failed messages are sent to DLQ for manual investigation.
    """
    try:
        await processor_fn(message)

    except Exception as e:
        # Log error
        logger.error(f"Message processing failed: {e}", extra={
            "message": message,
            "error": str(e)
        })

        # Send to dead letter queue
        await publish_event({
            "event_type": "MESSAGE_PROCESSING_FAILED",
            "correlation_id": message.get("correlation_id"),
            "payload": {
                "original_message": message,
                "error": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }, topic="dead-letter-queue")
```

**3. Circuit Breaker**:
```python
class EventBusCircuitBreaker:
    """
    Circuit breaker for event bus operations.

    Opens circuit after N consecutive failures.
    Half-open after timeout to test recovery.
    Closes after M consecutive successes.
    """

    def __init__(self, failure_threshold=5, timeout_seconds=30, success_threshold=2):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.success_threshold = success_threshold

        self.failure_count = 0
        self.success_count = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.opened_at = None

    async def call(self, fn, *args, **kwargs):
        """Execute function with circuit breaker protection."""

        # Check circuit state
        if self.state == "OPEN":
            # Check if timeout elapsed
            if time.time() - self.opened_at > self.timeout_seconds:
                self.state = "HALF_OPEN"
                self.success_count = 0
            else:
                raise RuntimeError("Circuit breaker OPEN - service unavailable")

        try:
            # Execute function
            result = await fn(*args, **kwargs)

            # Success - update counts
            self.failure_count = 0
            if self.state == "HALF_OPEN":
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    self.state = "CLOSED"

            return result

        except Exception as e:
            # Failure - update counts
            self.success_count = 0
            self.failure_count += 1

            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                self.opened_at = time.time()

            raise
```

### Event Versioning

**Topic Naming Convention**:
```
{environment}.{service}.{domain}.{event-name}.{version}

Examples:
- dev.archon-intelligence.intelligence.code-analysis-requested.v1
- prod.omniclaude.postgres.query-requested.v2
- test.omniclaude.mcp.tool-call-completed.v1
```

**Version Migration**:
```python
class EventVersionAdapter:
    """
    Adapter for handling multiple event versions.

    Allows gradual migration from v1 to v2 without breaking changes.
    """

    def subscribe_multiple_versions(self, base_topic: str, versions: list):
        """Subscribe to multiple versions of the same event."""
        topics = [f"{base_topic}.{v}" for v in versions]
        return KafkaConsumer(*topics, ...)

    def normalize_event(self, event: dict, from_version: str, to_version: str):
        """
        Normalize event from one version to another.

        Example:
          v1: {"user_request": "..."}
          v2: {"request": {"user_input": "...", "context": {...}}}
        """
        if from_version == "v1" and to_version == "v2":
            return {
                "request": {
                    "user_input": event.get("user_request"),
                    "context": {}
                }
            }

        return event  # No transformation needed
```

---

## 7. Performance Impact Analysis

### Current System Performance

**Direct API Calls**:
- Archon MCP: ~100-500ms (tool-dependent)
- AI Quorum: ~1000-3000ms (multi-model)
- Qdrant (via event bus): ~50-200ms
- PostgreSQL (direct): ~10-50ms

**Routing**:
- Cache hit: ~5ms
- Cache miss: ~50-100ms
- Self-transformation validation: ~10ms

### Proposed System Performance

**Polly-First Routing**:
- Simple Q&A detection: ~5-10ms (heuristic) or ~500ms (LLM)
- Polly invocation: ~50ms (task analysis)
- Delegation to specialized agent: ~50-100ms (router)
- **Total overhead: +105-160ms** (or +650ms with LLM classification)

**Event Bus Migration**:
- Kafka publish latency: ~5ms
- Event processing: ~10-50ms (depends on adapter)
- Response latency: ~10-50ms
- **Total round-trip: +25-105ms per API call**

**Database Queries via Event Bus**:
- Current (direct asyncpg): ~10-50ms
- Proposed (event bus + adapter): ~25-105ms
- **Overhead: +15-55ms per query**

### Mitigation Strategies

**1. Caching**:
```python
# Cache delegation patterns
@lru_cache(maxsize=1000)
def get_delegation_plan(user_request_hash: str) -> List[SubTask]:
    """Cache delegation patterns for similar requests."""
    pass

# Cache event bus responses
@lru_cache(maxsize=5000)
def get_cached_query_result(query_hash: str) -> dict:
    """Cache database query results."""
    pass
```

**2. Parallel Execution**:
```python
# Execute sub-tasks in parallel
async def execute_delegated_tasks(assignments: List[Tuple[SubTask, str]]):
    """Execute independent sub-tasks in parallel."""
    tasks = [
        execute_agent(agent, sub_task)
        for sub_task, agent in assignments
        if sub_task.can_run_parallel
    ]
    results = await asyncio.gather(*tasks)
    return results
```

**3. Adaptive Timeouts**:
```python
class AdaptiveTimeout:
    """
    Adjust timeouts based on historical performance.

    Starts with conservative timeout, reduces as service proves reliable.
    """

    def __init__(self, initial_timeout_ms=5000):
        self.timeout_ms = initial_timeout_ms
        self.performance_history = []

    def get_timeout(self) -> int:
        """Get current adaptive timeout."""
        if not self.performance_history:
            return self.timeout_ms

        # Use p95 of recent performance
        recent = self.performance_history[-100:]
        p95 = sorted(recent)[int(len(recent) * 0.95)]

        # Add 50% buffer
        return int(p95 * 1.5)

    def record_performance(self, duration_ms: int):
        """Record operation duration."""
        self.performance_history.append(duration_ms)
        if len(self.performance_history) > 1000:
            self.performance_history.pop(0)
```

**4. Prefetching**:
```python
async def prefetch_intelligence(context: dict):
    """
    Prefetch likely-needed intelligence based on context.

    Example: If user is working in Python codebase, prefetch Python patterns.
    """
    # Identify likely patterns
    language = context.get("language", "python")
    domain = context.get("domain", "general")

    # Prefetch in background
    asyncio.create_task(
        intelligence_client.request_pattern_discovery(
            source_path=f"*.{language}",
            language=language
        )
    )
```

### Performance Budget

**Target Latencies**:
- Simple Q&A detection: <10ms (heuristic-first hybrid)
- Polly task analysis: <100ms
- Event bus round-trip: <100ms
- Database query (event bus): <100ms
- Total request overhead: <300ms

**Acceptable Latencies**:
- Polly-first total: <500ms (vs current ~100ms)
- Event bus API call: <200ms (vs current ~100ms)
- Database query: <150ms (vs current ~50ms)

**Critical Latencies** (must not exceed):
- Total request: >1000ms
- Event bus round-trip: >500ms
- Database query: >300ms

---

## 8. Migration Strategy

### Phased Approach

**Phase 0: Preparation** (1 week)
- ✅ Document current API usage (this document)
- ✅ Design event schemas (Section 6)
- ✅ Performance baseline measurements
- ⬜ Stakeholder alignment on trade-offs

**Phase 1: Database Event Bus** (2 weeks)
- ⬜ Implement PostgreSQL adapter service
- ⬜ Create Kafka topics (postgres.query.*)
- ⬜ Implement query-database skill
- ⬜ Migrate 1-2 low-risk files (e.g., test files)
- ⬜ Monitor performance and errors
- ⬜ Rollout to all database access

**Phase 2: Archon MCP Event Bus** (2 weeks)
- ⬜ Implement MCP adapter service
- ⬜ Create Kafka topics (archon-mcp.tool-call.*)
- ⬜ Implement call-archon-mcp skill
- ⬜ Migrate mcp_client.py
- ⬜ Monitor performance and errors

**Phase 3: AI Quorum Event Bus** (2 weeks)
- ⬜ Implement Quorum adapter service
- ⬜ Create Kafka topics (ai-quorum.validation.*)
- ⬜ Implement validate-quorum skill
- ⬜ Migrate quorum_validator.py
- ⬜ Monitor performance and errors

**Phase 4: Polly-First Routing** (3 weeks)
- ⬜ Implement simple Q&A detection (hybrid approach)
- ⬜ Update router to call polly-first
- ⬜ Implement polly delegation logic
- ⬜ Add delegation pattern caching
- ⬜ A/B test polly-first vs direct routing (10% traffic)
- ⬜ Monitor task completion rates and quality
- ⬜ Gradual rollout (10% → 50% → 100%)

**Phase 5: Optimization** (ongoing)
- ⬜ Optimize event bus latency
- ⬜ Implement adaptive timeouts
- ⬜ Add prefetching for common patterns
- ⬜ Cache delegation plans
- ⬜ Performance tuning based on metrics

### Rollback Plan

**Event Bus Migration**:
- All skills maintain fallback to direct API
- Environment variable to disable event bus
- Monitoring alerts on event bus failures
- Automatic fallback to direct API on circuit breaker OPEN

```python
# Skill with fallback
async def call_api_with_fallback(tool_name: str, params: dict):
    """
    Call API via event bus with automatic fallback to direct HTTP.

    Enables gradual migration without breaking existing functionality.
    """
    # Try event bus first
    if os.getenv("ENABLE_EVENT_BUS", "true").lower() == "true":
        try:
            return await call_api_event_bus(tool_name, params)
        except (TimeoutError, RuntimeError) as e:
            logger.warning(f"Event bus call failed, falling back to direct API: {e}")

    # Fallback to direct API
    return await call_api_direct(tool_name, params)
```

**Polly-First Routing**:
- Feature flag: `ENABLE_POLLY_FIRST_ROUTING`
- A/B testing framework (10% → 50% → 100%)
- Monitoring: task completion rate, quality score, latency
- Automatic rollback if metrics degrade >10%

```python
# Router with feature flag
def route(user_request: str) -> AgentRecommendation:
    """Route with optional polly-first logic."""

    # Feature flag check
    polly_first_enabled = os.getenv("ENABLE_POLLY_FIRST_ROUTING", "false")
    polly_first_percentage = float(os.getenv("POLLY_FIRST_ROLLOUT_PERCENT", "0"))

    # A/B testing
    if polly_first_enabled == "true" and random.random() < polly_first_percentage / 100.0:
        # Polly-first routing
        if is_simple_question(user_request):
            return direct_response(user_request)
        else:
            return route_to_polly(user_request)
    else:
        # Original routing
        return route_direct(user_request)
```

### Risk Mitigation

**Risk 1: Event Bus Latency**
- **Impact**: High (user-facing latency)
- **Likelihood**: Medium
- **Mitigation**:
  - Caching at skill level
  - Adaptive timeouts
  - Parallel execution
  - Fallback to direct API
- **Monitoring**: p50/p95/p99 latency metrics

**Risk 2: Event Bus Reliability**
- **Impact**: Critical (service unavailable)
- **Likelihood**: Low (Kafka is battle-tested)
- **Mitigation**:
  - Circuit breaker protection
  - Automatic fallback to direct API
  - Kafka cluster redundancy
  - Health checks and alerts
- **Monitoring**: Event bus availability, circuit breaker state

**Risk 3: Adapter Service Bugs**
- **Impact**: High (incorrect query results)
- **Likelihood**: Medium (new code)
- **Mitigation**:
  - Comprehensive test suite
  - Gradual rollout (1 file at a time)
  - Side-by-side validation (compare event bus vs direct results)
  - Extensive logging and debugging
- **Monitoring**: Result comparison mismatches, error rates

**Risk 4: Polly-First Routing Quality**
- **Impact**: High (incorrect agent selection)
- **Likelihood**: Medium (new logic)
- **Mitigation**:
  - A/B testing framework
  - Quality metrics (task completion, user satisfaction)
  - Human-in-the-loop validation
  - Easy rollback via feature flag
- **Monitoring**: Task completion rate, quality scores, user feedback

**Risk 5: Performance Degradation**
- **Impact**: Medium (slower responses)
- **Likelihood**: High (additional hops)
- **Mitigation**:
  - Performance budget enforcement
  - Caching at multiple levels
  - Parallel execution
  - Adaptive timeouts
- **Monitoring**: p95 latency, SLO compliance

---

## 9. Trade-offs and Recommendations

### Polly-First Routing

**Pros**:
- ✅ Better task decomposition and coordination
- ✅ Improved multi-step workflows
- ✅ Specialized agents as sub-tasks (cleaner architecture)
- ✅ Easier to add new specialized agents (just delegation logic)
- ✅ Natural parallel execution of independent sub-tasks

**Cons**:
- ⚠️ +100-600ms latency overhead (depending on Q&A detection method)
- ⚠️ Additional complexity in delegation logic
- ⚠️ Risk of incorrect simple Q&A detection (false positives/negatives)
- ⚠️ Polly becomes single point of failure (mitigated by fallback)

**Recommendation**: ✅ **Implement with Hybrid Q&A Detection**

Use heuristic-first hybrid approach (Method 3):
- Fast heuristic for obvious cases (<10ms)
- LLM classification only for ambiguous cases (~500ms)
- A/B test with 10% → 50% → 100% rollout
- Monitor task completion and quality metrics
- Easy rollback via feature flag

**Expected Impact**:
- 80% of requests: heuristic only (+10ms)
- 15% of requests: hybrid (heuristic + LLM) (+500ms)
- 5% of requests: direct response (no polly overhead)
- Net impact: +50-100ms average (acceptable for better quality)

### Event Bus for All APIs

**Pros**:
- ✅ Consistent architecture (all external calls via event bus)
- ✅ Better observability (all API calls logged to Kafka)
- ✅ Fault tolerance (circuit breaker, retry, fallback)
- ✅ Security (centralized credentials, access control)
- ✅ Flexibility (multiple consumers, easy to swap backends)

**Cons**:
- ⚠️ +25-105ms latency per API call
- ⚠️ Additional complexity (adapter services)
- ⚠️ More infrastructure to maintain (Kafka, adapters)
- ⚠️ Risk of event bus becoming bottleneck

**Recommendation**: ✅ **Implement for Database and MCP**

**Priority Order**:
1. **Database queries** (high impact, reusable pattern)
2. **Archon MCP** (frequently used, benefits from caching)
3. **AI Quorum** (low frequency, can wait)

**Rationale**:
- Database queries are ubiquitous (14 files)
- Centralizing DB access improves security and performance
- MCP calls benefit from caching and circuit breaker
- Quorum validation is infrequent (can use direct API for now)

### Simple Q&A Detection Method

**Method 1: Heuristic-Based**
- ⚡ Fast: ~5ms
- ⚠️ Lower accuracy: ~70-80%
- ✅ Good for obvious cases

**Method 2: LLM Classification**
- ⚠️ Slow: ~500ms
- ✅ Higher accuracy: ~90-95%
- ⚠️ Adds latency to every request

**Method 3: Hybrid**
- ⚡ Fast for obvious cases: ~5ms
- 🎯 Accurate for ambiguous: ~500ms
- ✅ Best of both worlds: 80% requests <10ms, 95% accuracy

**Recommendation**: ✅ **Hybrid Approach (Method 3)**

**Implementation**:
```python
async def detect_simple_qa(request: str) -> tuple[bool, float]:
    """
    Hybrid Q&A detection.

    Returns (is_simple, confidence).
    """
    # Fast heuristic check
    if len(request.split()) < 5:
        return True, 1.0  # Very short = simple

    if any(verb in request.lower() for verb in ACTION_VERBS):
        return False, 1.0  # Action verb = complex

    # Ambiguous - use LLM
    if len(request.split()) > 15:
        llm_result = await llm_classify(request)
        return llm_result, 0.9

    # Heuristic confidence
    heuristic_result = heuristic_classify(request)
    return heuristic_result, 0.8
```

### PostgreSQL Adapter Service

**Build In-House vs Use Existing**:

**Option A: Build Custom Adapter**
- ✅ Full control over features
- ✅ Optimized for our use case
- ⚠️ Development time (2-3 weeks)
- ⚠️ Maintenance burden

**Option B: Use Debezium or Similar**
- ✅ Battle-tested
- ✅ Rich feature set
- ⚠️ Overkill for our needs
- ⚠️ Steep learning curve

**Recommendation**: ✅ **Build Custom Adapter**

**Rationale**:
- Simple use case (query execution, not CDC)
- Full control over event schema
- Easier to optimize for our patterns
- Learning opportunity for team

**Scope**:
- Core query execution (SELECT, INSERT, UPDATE, DELETE)
- Connection pooling
- Timeout handling
- Error handling
- Basic caching (read-only queries)
- **No transactions** in Phase 1 (add later if needed)

### Migration Timeline

**Conservative Estimate**:
- Phase 1 (Database): 2 weeks
- Phase 2 (MCP): 2 weeks
- Phase 3 (Quorum): 2 weeks (optional)
- Phase 4 (Polly-first): 3 weeks
- Total: **7-9 weeks**

**Aggressive Estimate**:
- Phase 1 (Database): 1 week
- Phase 2 (MCP): 1 week
- Phase 4 (Polly-first): 2 weeks (skip Quorum)
- Total: **4 weeks**

**Recommendation**: ✅ **Conservative Timeline**

**Rationale**:
- Avoid rushing critical infrastructure changes
- Time for proper testing and monitoring
- Gradual rollout reduces risk
- Buffer for unexpected issues

---

## Summary and Next Steps

### Key Decisions Needed

1. **Approve polly-first routing approach?**
   - ✅ Recommended: Yes, with hybrid Q&A detection
   - ⬜ Decision: _____________

2. **Approve event bus for database queries?**
   - ✅ Recommended: Yes, build custom adapter
   - ⬜ Decision: _____________

3. **Approve event bus for Archon MCP?**
   - ✅ Recommended: Yes, Phase 2 priority
   - ⬜ Decision: _____________

4. **Approve migration timeline?**
   - ✅ Recommended: 7-9 weeks (conservative)
   - ⬜ Decision: _____________

### Immediate Next Steps

**If Approved**:

1. **Week 1-2: Database Event Bus**
   - Design PostgreSQL adapter service
   - Define Kafka topics and event schemas
   - Implement adapter (Docker container)
   - Create query-database skill
   - Test with 1 low-risk file

2. **Week 3: Database Migration**
   - Migrate all 14 files to event bus
   - Monitor performance and errors
   - Document patterns and best practices

3. **Week 4-5: MCP Event Bus**
   - Design MCP adapter service
   - Implement adapter
   - Create call-archon-mcp skill
   - Migrate mcp_client.py

4. **Week 6-9: Polly-First Routing**
   - Implement hybrid Q&A detection
   - Add polly delegation logic
   - A/B testing framework
   - Gradual rollout (10% → 50% → 100%)

**If Not Approved**:
- Maintain current architecture
- Optimize existing routing logic
- Focus on other priorities

---

## Appendix

### A. Infrastructure Map

```
┌─────────────────────────────────────────────────────────────┐
│                        USER REQUEST                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  POLYMORPHIC AGENT (Polly)                   │
│  - Simple Q&A detection (hybrid)                             │
│  - Task analysis & decomposition                             │
│  - Delegation to specialized agents                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Agent Router │  │    Skills    │  │  Event Bus   │
│  (existing)  │  │  (enhanced)  │  │   (Kafka)    │
└──────────────┘  └──────────────┘  └──────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  PostgreSQL  │  │  Archon MCP  │  │ Intelligence │
│   Adapter    │  │   Adapter    │  │   (existing) │
│    (new)     │  │    (new)     │  │              │
└──────────────┘  └──────────────┘  └──────────────┘
          │                │                │
          ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  PostgreSQL  │  │ Archon MCP   │  │   Qdrant     │
│  (existing)  │  │  (existing)  │  │  Memgraph    │
└──────────────┘  └──────────────┘  └──────────────┘
```

### B. Event Topics Summary

**Existing**:
- `dev.archon-intelligence.intelligence.code-analysis-requested.v1`
- `dev.archon-intelligence.intelligence.code-analysis-completed.v1`
- `dev.archon-intelligence.intelligence.code-analysis-failed.v1`
- `agent-routing-decisions`
- `agent-transformation-events`
- `router-performance-metrics`
- `agent-actions`
- `documentation-changed`

**Proposed**:
- `postgres.query.requested.v1`
- `postgres.query.completed.v1`
- `postgres.query.failed.v1`
- `archon-mcp.tool-call.requested.v1`
- `archon-mcp.tool-call.completed.v1`
- `archon-mcp.tool-call.failed.v1`
- `ai-quorum.validation.requested.v1`
- `ai-quorum.validation.completed.v1`
- `ai-quorum.validation.failed.v1`

### C. Performance Metrics Baseline

**Current System** (pre-migration):
- Router (cache hit): ~5ms
- Router (cache miss): ~50-100ms
- Database query (direct): ~10-50ms
- MCP call (direct): ~100-500ms
- Intelligence query (event bus): ~50-200ms

**Target System** (post-migration):
- Simple Q&A detection: <10ms (p95)
- Polly task analysis: <100ms (p95)
- Database query (event bus): <100ms (p95)
- MCP call (event bus): <200ms (p95)
- Total request overhead: <300ms (p95)

### D. Skills to Create/Update

**Create**:
- `external-api/call-archon-mcp/` - MCP tool calls
- `external-api/validate-quorum/` - AI quorum validation
- `external-api/query-database/` - PostgreSQL queries
- `external-api/query-qdrant/` - Qdrant vector search (optional)
- `external-api/query-memgraph/` - Memgraph graph queries (optional)

**Update**:
- `intelligence/request-intelligence/` - Use event bus client directly

**No Changes**:
- `agent-tracking/*` - Already use Kafka
- `agent-observability/*` - Direct DB is OK for now (low frequency)

---

**End of Document**

For questions or clarifications, contact:
- Architecture decisions: [team lead]
- Event bus design: [infrastructure team]
- Performance concerns: [performance team]
