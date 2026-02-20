# Service Ownership & Boundaries

**Status**: Active
**Based on**: ADR-001 (Service Ownership Separation)
**Last Updated**: 2025-11-05
**Version**: 1.0.0

## Purpose

This document defines clear service ownership boundaries between **omniclaude** and external services (primarily **omniarchon**). Understanding these boundaries is critical for:

- Preventing cross-repository architectural violations
- Maintaining clean service separation
- Ensuring proper dependency management
- Facilitating independent service deployment and scaling

## Table of Contents

1. [Services Owned by omniclaude](#services-owned-by-omniclaude)
2. [External Service Dependencies](#external-service-dependencies)
3. [Service Discovery Pattern](#service-discovery-pattern)
4. [Communication Patterns](#communication-patterns)
5. [What NOT to Do](#what-not-to-do)
6. [Architecture Diagrams](#architecture-diagrams)
7. [Troubleshooting](#troubleshooting)

---

## Services Owned by omniclaude

These services are **owned, maintained, and deployed** by the omniclaude repository. Any changes to these services should be made in this repository.

### 1. omniclaude CLI

**Purpose**: Primary command-line interface for Claude Code enhancements

**Key Responsibilities**:
- User interaction and command processing
- Agent orchestration and coordination
- Provider management (Claude, Gemini, Z.ai, etc.)
- Multi-agent workflow execution
- Quality gate validation

**Dependencies**:
- External: Archon services (via HTTP), Kafka, PostgreSQL
- Internal: Agent system, Router consumer

**Configuration**:
- Environment variables in `.env`
- Provider configs in `claude-providers.json`
- Settings in `~/.claude/settings.json`

**Ports**: N/A (CLI tool)

---

### 2. omniclaude Agent System

**Purpose**: Polymorphic agent framework with ONEX compliance

**Key Responsibilities**:
- Dynamic agent transformation and routing
- Manifest injection (system context via event bus)
- Parallel multi-agent coordination
- ONEX architecture enforcement (4-node types: Effect, Compute, Reducer, Orchestrator)
- Quality validation (23 quality gates across 8 types)
- Intelligence context integration

**Components**:
- `agents/lib/manifest_injector.py` - Dynamic manifest generation via Kafka
- `agents/lib/routing_event_client.py` - Event-based routing client
- `agents/lib/agent_execution_logger.py` - Execution lifecycle tracking
- `agents/lib/agent_history_browser.py` - Interactive history browser
- `plugins/onex/agents/configs/` - Agent registry (YAML configs)

**Dependencies**:
- External: Archon Intelligence (patterns), Kafka (events), PostgreSQL (logging)
- Internal: Router consumer (for routing)

**Configuration**:
```bash
# .env variables
AGENT_NAME=<agent_name>
KAFKA_ENABLE_INTELLIGENCE=true
KAFKA_REQUEST_TIMEOUT_MS=5000
```

**Ports**: N/A (library/framework)

**Performance Targets**:
- Manifest query time: <2000ms
- Routing accuracy: >95%
- Quality gate execution: <200ms per gate

---

### 3. omniclaude Router Consumer (archon-router-consumer)

**Purpose**: Event-driven agent routing service via Kafka

**Key Responsibilities**:
- Consume routing requests from `agent.routing.requested.v1` topic
- Intelligent agent selection with fuzzy matching and confidence scoring
- Publish routing results to `agent.routing.completed.v1` / `agent.routing.failed.v1`
- Non-blocking database logging to `agent_routing_decisions` table

**Service Type**: Pure Kafka consumer (no HTTP endpoints)

**Docker Container**: `omniclaude_archon_router_consumer`

**Dependencies**:
- External: Kafka (`${KAFKA_BOOTSTRAP_SERVERS}`), PostgreSQL (`${POSTGRES_HOST}:${POSTGRES_PORT}`)
- Internal: Agent registry (`plugins/onex/agents/configs/`)

**Kafka Topics**:
- **Consumes**: `agent.routing.requested.v1`
- **Produces**: `agent.routing.completed.v1`, `agent.routing.failed.v1`

**Configuration**:
```bash
# docker-compose.yml (uses .env variables)
services:
  archon-router-consumer:
    build:
      context: .
      dockerfile: deployment/Dockerfile.router-consumer
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS}  # From .env
      - POSTGRES_HOST=${POSTGRES_HOST}                      # From .env
      - POSTGRES_PORT=${POSTGRES_PORT}                      # From .env
```

**Ports**: N/A (Kafka consumer only)

**Performance**:
- Routing time: 7-8ms
- Total latency: <500ms
- Throughput: 100+ requests/second

**Management**:
```bash
# Restart service
docker restart omniclaude_archon_router_consumer

# View logs
docker logs -f omniclaude_archon_router_consumer

# Query routing decisions
source .env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT * FROM agent_routing_decisions ORDER BY created_at DESC LIMIT 10;"
```

---

## External Service Dependencies

These services are **NOT owned by omniclaude**. They are provided by external systems (primarily **omniarchon**) and should be treated as black-box dependencies.

### 1. Archon Intelligence Service

**Owner**: omniarchon repository
**Endpoint**: `${ARCHON_INTELLIGENCE_URL}` (see `.env.example`)
**Access Pattern**: HTTP REST API

**Purpose**: Intelligence coordination and event processing

**APIs Used by omniclaude**:
- `GET /health` - Health check
- Event-based queries via Kafka (primary)

**What omniclaude Uses It For**:
- Pattern discovery (120+ patterns from Qdrant)
- Debug intelligence (successful/failed workflow analysis)
- System context for manifest injection

**Configuration in omniclaude**:
```bash
# Not directly configured - accessed via Kafka events
# Service discovery via Kafka event bus
```

**DO NOT**:
- ❌ Modify Archon Intelligence service code
- ❌ Add endpoints to Archon Intelligence
- ❌ Change Archon Intelligence configuration
- ❌ Deploy Archon Intelligence from omniclaude

---

### 2. Archon Search Service

**Owner**: omniarchon repository
**Endpoint**: `${ARCHON_SEARCH_URL}` (see `.env.example`)
**Access Pattern**: HTTP REST API

**Purpose**: Full-text and semantic search across patterns and code

**APIs Used by omniclaude**:
- `GET /health` - Health check
- `POST /search` - Pattern search (via Kafka events)

**What omniclaude Uses It For**:
- Code pattern search
- Semantic similarity matching
- ONEX pattern discovery

**Configuration in omniclaude**:
```bash
# Accessed via Kafka - no direct HTTP config needed
```

---

### 3. Archon Bridge Service

**Owner**: omniarchon repository
**Endpoint**: `${ARCHON_BRIDGE_URL}` (see `.env.example`)
**Access Pattern**: HTTP REST API

**Purpose**: PostgreSQL connector with query optimization

**APIs Used by omniclaude**:
- `GET /health` - Health check
- Database queries via Kafka events

**What omniclaude Uses It For**:
- Database schema introspection
- Historical workflow data
- Agent execution history

---

### 4. Kafka/Redpanda Event Bus

**Owner**: Shared infrastructure (deployed separately)
**Endpoint**: `${KAFKA_BOOTSTRAP_SERVERS}` (see `.env` for context-specific value)
**Access Pattern**: Kafka protocol

**Purpose**: Distributed event bus for all intelligence communication

**Topics Used by omniclaude**:

**Intelligence Topics**:
- `dev.archon-intelligence.intelligence.code-analysis-requested.v1` (publish)
- `dev.archon-intelligence.intelligence.code-analysis-completed.v1` (consume)
- `dev.archon-intelligence.intelligence.code-analysis-failed.v1` (consume)

**Router Topics**:
- `agent.routing.requested.v1` (publish from CLI, consume in router consumer)
- `agent.routing.completed.v1` (consume in CLI, publish from router consumer)
- `agent.routing.failed.v1` (consume in CLI, publish from router consumer)

**Tracking Topics**:
- `onex.evt.omniclaude.routing-decision.v1` (publish)
- `agent-transformation-events` (publish)
- `router-performance-metrics` (publish)
- `agent-actions` (publish)

**Configuration in omniclaude**:
```bash
# .env configuration (context-specific)
# For Docker services (internal port)
KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092

# For host scripts (external port)
KAFKA_BOOTSTRAP_SERVERS=${KAFKA_REMOTE_HOST}:29092  # See .env.example

# For remote shell (when SSH'd into server)
KAFKA_BOOTSTRAP_SERVERS=localhost:29092
```

**Admin UI**: See `.env` for `KAFKA_ADMIN_UI_URL` (typically port 8080)

**Port Reference**:
| Context | Bootstrap Servers | Port | Use Case |
|---------|------------------|------|----------|
| **Docker services** | `omninode-bridge-redpanda:9092` | 9092 | Container-to-container (router consumer) |
| **Host scripts** | `${KAFKA_REMOTE_HOST}:29092` | 29092 | Development scripts, testing |
| **Remote shell** | `localhost:29092` | 29092 | SSH'd into remote server |

---

### 5. PostgreSQL Database

**Owner**: Shared infrastructure (deployed separately)
**Endpoint**: `${POSTGRES_HOST}:${POSTGRES_PORT}` (see `.env`)
**Access Pattern**: PostgreSQL protocol (direct connection)

**Purpose**: Persistent storage for agent execution, routing decisions, and observability data

**Database**: `omninode_bridge`

**Tables Used by omniclaude** (subset of 34 total):
- `agent_routing_decisions` - Agent selection and confidence scores
- `agent_manifest_injections` - Complete manifest snapshots
- `agent_execution_logs` - Execution lifecycle tracking
- `agent_transformation_events` - Polymorphic agent transformations
- `router_performance_metrics` - Routing performance analytics
- `workflow_events` - Debug intelligence data

**Configuration in omniclaude**:
```bash
# .env configuration (ALWAYS source before using)
# See .env.example for default values
POSTGRES_HOST=${POSTGRES_HOST}          # Typically: remote server IP
POSTGRES_PORT=${POSTGRES_PORT}          # Typically: 5436 (external) or 5432 (internal)
POSTGRES_DATABASE=${POSTGRES_DATABASE}  # Database name
POSTGRES_USER=${POSTGRES_USER}          # Database user
POSTGRES_PASSWORD=<set_in_env>          # NEVER hardcode - set in .env
```

**Usage**:
```bash
# ALWAYS source .env first to load credentials
source .env

# Connect to database
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}

# Query routing decisions
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT * FROM agent_routing_decisions ORDER BY created_at DESC LIMIT 10;"
```

---

### 6. Qdrant Vector Database

**Owner**: Deployed locally in omniclaude (but patterns managed by omniarchon)
**Endpoint**: `${QDRANT_URL}` (see `.env`)
**Access Pattern**: HTTP REST API

**Purpose**: Vector storage for pattern discovery and semantic search

**Collections Used**:
- `execution_patterns` - ONEX architectural templates (120 patterns)
- `code_patterns` - Real Python implementations (856 patterns)
- `workflow_events` - Debug intelligence data

**Configuration in omniclaude**:
```bash
# .env configuration (see .env.example)
QDRANT_HOST=${QDRANT_HOST}    # Typically: localhost (local deployment)
QDRANT_PORT=${QDRANT_PORT}    # Typically: 6333
QDRANT_URL=${QDRANT_URL}      # Full URL for HTTP access
```

**Note**: While Qdrant runs locally in omniclaude's Docker, the **patterns are populated and managed by omniarchon**. omniclaude only reads from these collections.

---

## Service Discovery Pattern

omniclaude uses **environment-based service discovery** following 12-factor app principles.

### Configuration Hierarchy

1. **Primary**: `.env` file in repository root (highest priority)
2. **Shared**: `~/.claude/.env` (optional, for shared credentials)
3. **Repository-specific**: `agents/configs/.env` (agent-specific overrides)

### Example .env Configuration

```bash
# ============================================
# EXTERNAL SERVICE ENDPOINTS
# ============================================

# Kafka/Redpanda Event Bus
# Docker services use internal port (9092)
# Host scripts use external port (29092)
KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092  # For Docker
# KAFKA_BOOTSTRAP_SERVERS=${KAFKA_REMOTE_HOST}:29092   # For host scripts (see .env.example)

# PostgreSQL Database
POSTGRES_HOST=<see .env.example>       # Remote server IP
POSTGRES_PORT=<see .env.example>       # External port (typically 5436)
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<set_in_env>         # NEVER commit real passwords

# Qdrant Vector Database (local)
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_URL=http://localhost:6333

# ============================================
# ARCHON SERVICES (HTTP APIs)
# ============================================
# Note: Accessed primarily via Kafka events
# Direct HTTP used only for health checks

ARCHON_INTELLIGENCE_URL=<see .env.example>  # Archon server IP and port
ARCHON_SEARCH_URL=<see .env.example>        # Archon server IP and port
ARCHON_BRIDGE_URL=<see .env.example>        # Archon server IP and port

# ============================================
# FEATURE FLAGS
# ============================================

# Enable event-based intelligence
KAFKA_ENABLE_INTELLIGENCE=true

# Intelligence request timeout (ms)
KAFKA_REQUEST_TIMEOUT_MS=5000

# Enable real-time event processing
ENABLE_REAL_TIME_EVENTS=true
```

### Loading Configuration

```bash
# ALWAYS source .env before running database/Kafka operations
source .env

# Verify loaded
echo "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:+(set)}"
echo "KAFKA_BOOTSTRAP_SERVERS: ${KAFKA_BOOTSTRAP_SERVERS}"
```

### DNS Resolution

**For Docker Services**: No `/etc/hosts` configuration required
- External network references enable native service discovery
- Docker network automatically resolves `omninode-bridge-redpanda:9092`, `omninode-bridge-postgres:5432`, etc.
- Services communicate directly via Docker DNS

**For Host Scripts**: `/etc/hosts` entries required

When running scripts/commands on the host machine (outside Docker), add these entries to `/etc/hosts`:

```bash
# /etc/hosts entries (required for host scripts accessing Kafka/PostgreSQL)
# Replace IP address with value from your .env POSTGRES_HOST/KAFKA_REMOTE_HOST
<your_remote_server_ip> omninode-bridge-redpanda
<your_remote_server_ip> omninode-bridge-consul
<your_remote_server_ip> omninode-bridge-postgres

# Example (if remote server is 192.168.86.200):
# 192.168.86.200 omninode-bridge-redpanda
# 192.168.86.200 omninode-bridge-consul
# 192.168.86.200 omninode-bridge-postgres
```

**Why the difference?**
- Docker services use external network references → automatic DNS resolution
- Host scripts run outside Docker network → manual DNS configuration needed
- Kafka uses two-step broker discovery protocol requiring hostname resolution

---

## Communication Patterns

omniclaude uses three communication patterns with external services:

### 1. Synchronous HTTP API Calls

**Used For**: Health checks only (not primary communication)

**Services**:
- Archon Intelligence: `GET /health`
- Archon Search: `GET /health`
- Archon Bridge: `GET /health`
- Qdrant: `GET /collections`

**Example**:
```bash
# Health checks (load .env first to get service URLs)
source .env
curl ${ARCHON_INTELLIGENCE_URL}/health  # Archon Intelligence
curl ${QDRANT_URL}/collections          # Qdrant
```

**NOT USED FOR**: Primary intelligence queries (use Kafka instead)

---

### 2. Asynchronous Kafka Events (PRIMARY)

**Used For**: All intelligence queries, routing requests, and event tracking

**Pattern**: Request-Response via Kafka topics with correlation IDs

**Flow**:
```
omniclaude (CLI/Agent)
  ↓ (publish with correlation_id)
Kafka Topic: intelligence.code-analysis-requested.v1
  ↓ (consume)
Archon Intelligence
  ↓ (queries Qdrant, Memgraph, PostgreSQL)
  ↓ (publish with same correlation_id)
Kafka Topic: intelligence.code-analysis-completed.v1
  ↓ (consume, match correlation_id)
omniclaude receives manifest
```

**Example Request Event**:
```json
{
  "correlation_id": "8b57ec39-45b5-467b-939c-dd1439219f69",
  "operation_type": "PATTERN_EXTRACTION",
  "collection_name": "execution_patterns",
  "options": {
    "limit": 50,
    "include_patterns": true,
    "include_metrics": false
  },
  "timeout_ms": 5000
}
```

**Example Response Event**:
```json
{
  "correlation_id": "8b57ec39-45b5-467b-939c-dd1439219f69",
  "patterns": [
    {
      "name": "Node State Management Pattern",
      "file_path": "node_state_manager_effect.py",
      "confidence": 0.95,
      "node_types": ["EFFECT", "REDUCER"],
      "use_cases": ["State persistence", "Transaction management"]
    }
  ],
  "query_time_ms": 450,
  "total_count": 120
}
```

**Advantages**:
- Non-blocking (async)
- Fault-tolerant (Kafka persistence)
- Traceable (correlation IDs)
- Scalable (horizontal scaling via partitions)
- Replay capability (full event history)

**Timeout Handling**:
- Default timeout: 5000ms
- Graceful degradation: Falls back to minimal manifest on timeout
- Non-blocking: Agent continues with available data

---

### 3. Direct Database Access

**Used For**: Agent execution logging and historical queries

**Services**: PostgreSQL (`${POSTGRES_HOST}:${POSTGRES_PORT}` - see `.env`)

**Access Pattern**: Direct PostgreSQL protocol connection

**Tables Modified by omniclaude**:
- `agent_routing_decisions` - Routing results (via router consumer)
- `agent_manifest_injections` - Manifest snapshots (via manifest injector)
- `agent_execution_logs` - Lifecycle tracking (via execution logger)

**Example**:
```python
from agents.lib.agent_execution_logger import log_agent_execution

# Non-blocking database logging with retry
logger = await log_agent_execution(
    agent_name="polymorphic-agent",
    user_prompt="Implement ONEX pattern",
    correlation_id="8b57ec39-45b5-467b-939c-dd1439219f69"
)

await logger.progress(stage="pattern_discovery", percent=50)
await logger.complete(status=EnumOperationStatus.SUCCESS, quality_score=0.92)
```

**Performance**:
- Non-blocking writes (async)
- Exponential backoff retry
- Fallback to JSON files on DB failure

---

## What NOT to Do

### ❌ Cross-Repository Service Modifications

**DO NOT**:
- Edit `omniarchon/docker-compose.yml` from omniclaude
- Add Archon services to omniclaude's docker-compose
- Modify Archon service configurations
- Deploy Archon services from omniclaude

**WHY**: Violates service ownership boundaries and causes deployment conflicts

**INSTEAD**:
- Use Archon services as black-box dependencies
- Configure endpoints via `.env`
- Request features via Archon team

---

### ❌ Hardcoded URLs and Ports

**DO NOT**:
```python
# BAD: Hardcoded URL
response = requests.get("http://192.168.86.101:8053/health")

# BAD: Hardcoded Kafka bootstrap
producer = KafkaProducer(bootstrap_servers="omninode-bridge-redpanda:9092")

# BAD: Hardcoded database credentials
conn = psycopg2.connect(
    host="192.168.86.200",
    port=5436,
    user="postgres",
    password="mypassword123"  # SECURITY VIOLATION
)
```

**INSTEAD**:
```python
# GOOD: Environment-based configuration
import os

response = requests.get(f"{os.getenv('ARCHON_INTELLIGENCE_URL')}/health")

producer = KafkaProducer(
    bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS')
)

conn = psycopg2.connect(
    host=os.getenv('POSTGRES_HOST'),
    port=os.getenv('POSTGRES_PORT'),
    user=os.getenv('POSTGRES_USER'),
    password=os.getenv('POSTGRES_PASSWORD')
)
```

---

### ❌ Creating Cross-Repository Service Dependencies

**DO NOT**:
- Make Archon services depend on omniclaude services
- Create circular dependencies between repositories
- Share code via git submodules or symlinks

**WHY**: Creates tight coupling and prevents independent deployment

**INSTEAD**:
- Use event-driven communication (Kafka)
- Define clear service contracts
- Use shared infrastructure (PostgreSQL, Kafka) as mediator

---

### ❌ Bypassing Event Bus for Intelligence Queries

**DO NOT**:
```python
# BAD: Direct HTTP call to Qdrant
response = requests.post("http://localhost:6333/collections/execution_patterns/points/search", ...)

# BAD: Direct SQL query to omniarchon tables
cursor.execute("SELECT * FROM archon_specific_table")
```

**INSTEAD**:
```python
# GOOD: Use event-based intelligence via Kafka
from agents.lib.manifest_injector import ManifestInjector

injector = ManifestInjector(correlation_id="...")
manifest = await injector.gather_intelligence()
```

**WHY**:
- Maintains service encapsulation
- Provides traceability via correlation IDs
- Enables graceful degradation
- Allows Archon to optimize queries internally

---

### ❌ Committing Secrets to Version Control

**DO NOT**:
- Commit `.env` files with real passwords
- Hardcode API keys in code or documentation
- Store credentials in CLAUDE.md or comments

**INSTEAD**:
```bash
# In .env.example (committed)
POSTGRES_PASSWORD=<set_in_env>
GEMINI_API_KEY=<your_key_here>

# In .env (gitignored, never committed)
POSTGRES_PASSWORD=actual_password_here
GEMINI_API_KEY=actual_key_here
```

**See**: `SECURITY_KEY_ROTATION.md` for security best practices

---

## Architecture Diagrams

### Service Ownership Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        OMNICLAUDE OWNS                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  omniclaude CLI                                           │  │
│  │    ↓                                                      │  │
│  │  omniclaude Agent System (Polymorphic Framework)         │  │
│  │    ↓                                                      │  │
│  │  archon-router-consumer (Event-based Routing Service)    │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                   (Kafka Events + HTTP Health)
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL DEPENDENCIES                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Kafka/Redpanda (${KAFKA_BOOTSTRAP_SERVERS})             │  │
│  │    - Event bus for all intelligence communication        │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  PostgreSQL (${POSTGRES_HOST}:${POSTGRES_PORT})          │  │
│  │    - Agent execution logging                             │  │
│  │    - Routing decisions                                   │  │
│  │    - Manifest injections                                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Qdrant (${QDRANT_URL}) - LOCALLY DEPLOYED               │  │
│  │    - Pattern storage (managed by omniarchon)             │  │
│  │    - Vector search                                       │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                   (Kafka Events + HTTP APIs)
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      OMNIARCHON OWNS                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Archon Intelligence (${ARCHON_INTELLIGENCE_URL})        │  │
│  │    - Intelligence coordination                           │  │
│  │    - Pattern discovery orchestration                     │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Archon Search (${ARCHON_SEARCH_URL})                    │  │
│  │    - Full-text search                                    │  │
│  │    - Semantic search                                     │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Archon Bridge (${ARCHON_BRIDGE_URL})                    │  │
│  │    - PostgreSQL connector                                │  │
│  │    - Query optimization                                  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

### Communication Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  USER REQUEST                                                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  omniclaude CLI                                                  │
│    - Parse request                                               │
│    - Generate correlation_id                                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
            ┌─────────────────┴──────────────────┐
            ↓                                    ↓
┌──────────────────────────┐      ┌──────────────────────────┐
│  ROUTING REQUEST         │      │  INTELLIGENCE REQUEST    │
│  (Kafka Event)           │      │  (Kafka Event)           │
│                          │      │                          │
│  Topic:                  │      │  Topic:                  │
│  agent.routing.          │      │  intelligence.code-      │
│  requested.v1            │      │  analysis-requested.v1   │
└──────────────────────────┘      └──────────────────────────┘
            ↓                                    ↓
┌──────────────────────────┐      ┌──────────────────────────┐
│  archon-router-consumer  │      │  Archon Intelligence     │
│  (omniclaude service)    │      │  (omniarchon service)    │
│                          │      │                          │
│  - Agent selection       │      │  - Query Qdrant          │
│  - Confidence scoring    │      │  - Query Memgraph        │
│  - DB logging            │      │  - Query PostgreSQL      │
└──────────────────────────┘      └──────────────────────────┘
            ↓                                    ↓
┌──────────────────────────┐      ┌──────────────────────────┐
│  ROUTING RESPONSE        │      │  INTELLIGENCE RESPONSE   │
│  (Kafka Event)           │      │  (Kafka Event)           │
│                          │      │                          │
│  Topic:                  │      │  Topic:                  │
│  agent.routing.          │      │  intelligence.code-      │
│  completed.v1            │      │  analysis-completed.v1   │
└──────────────────────────┘      └──────────────────────────┘
            ↓                                    ↓
            └─────────────────┬──────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  omniclaude Agent System                                         │
│    - Agent transformation (based on routing)                     │
│    - Manifest injection (from intelligence)                      │
│    - Execute with full context                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  PostgreSQL Database (Direct Connection)                         │
│    - Log execution lifecycle                                     │
│    - Store routing decisions                                     │
│    - Record manifest injections                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

### Service Not Available

**Symptom**: Intelligence queries timeout or fail

**Diagnosis**:
```bash
# Load environment variables
source .env

# Check service health (using env vars)
curl ${ARCHON_INTELLIGENCE_URL}/health  # Archon Intelligence
curl ${ARCHON_SEARCH_URL}/health        # Archon Search
curl ${QDRANT_URL}/collections          # Qdrant

# Check Kafka connectivity (using env vars)
kcat -L -b ${KAFKA_BOOTSTRAP_SERVERS}

# Run comprehensive health check
./scripts/health_check.sh
```

**Resolution**:
1. Verify services are running: `docker ps | grep archon`
2. Check network connectivity: `ping ${ARCHON_INTELLIGENCE_URL%%:*}` (extract host from URL)
3. Verify `/etc/hosts` entries (only needed for host scripts, not Docker services)
4. Check service logs: `docker logs archon-intelligence`

---

### Database Connection Failed

**Symptom**: `FATAL: password authentication failed for user "postgres"`

**Diagnosis**:
```bash
# Verify .env exists
ls -la .env

# Verify password is set (don't echo actual value!)
source .env && echo "Password: ${POSTGRES_PASSWORD:+SET}"

# Check .env format
grep POSTGRES_PASSWORD .env  # Should be unquoted
```

**Resolution**:
```bash
# 1. Verify .env file exists
cp .env.example .env

# 2. Edit .env and set POSTGRES_PASSWORD
nano .env

# 3. Source .env before ANY database operation
source .env

# 4. Test connection
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT 1"
```

**See**: `~/.claude/CLAUDE.md` for configuration priority rules

---

### Kafka Consumer Lag

**Symptom**: Router consumer falling behind, slow routing

**Diagnosis**:
```bash
# Check consumer group lag
docker exec omninode-bridge-redpanda rpk group describe omniclaude-router-consumer

# Check container resource usage
docker stats omniclaude_archon_router_consumer

# Check logs for errors
docker logs --tail 100 omniclaude_archon_router_consumer | grep ERROR
```

**Resolution**:
```bash
# Restart consumer
docker restart omniclaude_archon_router_consumer

# Scale horizontally (if supported)
docker-compose up -d --scale archon-router-consumer=2

# Increase consumer resources in docker-compose.yml
resources:
  limits:
    cpus: '2.0'
    memory: 2G
```

---

### Pattern Discovery Returns 0 Patterns

**Symptom**: Manifest injection shows "Total: 0 patterns available"

**Diagnosis**:
```bash
# Load environment variables
source .env

# Check Qdrant collections (using env vars)
curl ${QDRANT_URL}/collections | jq

# Check collection counts
curl ${QDRANT_URL}/collections/execution_patterns | jq '.result.points_count'
curl ${QDRANT_URL}/collections/code_patterns | jq '.result.points_count'

# Check agent history for query times
python3 agents/lib/agent_history_browser.py --limit 20
```

**Resolution**:
1. Verify Qdrant is running: `docker ps | grep qdrant`
2. Check if patterns were populated by omniarchon
3. Verify Kafka intelligence events are flowing
4. Check archon-intelligence logs for errors
5. Restart Qdrant if needed: `docker restart archon-qdrant`

---

## Related Documentation

- **Shared Infrastructure**: `~/.claude/CLAUDE.md` (PostgreSQL, Kafka, remote server topology)
- **omniclaude Architecture**: `/Volumes/PRO-G40/Code/omniclaude/CLAUDE.md` (agents, routing, manifest injection)
- **Event-Driven Routing**: `docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md`
- **Manifest Intelligence**: `docs/architecture/MANIFEST_INTELLIGENCE_EVENT_ARCHITECTURE.md`
- **Agent Traceability**: `docs/observability/AGENT_TRACEABILITY.md`
- **Security**: `SECURITY_KEY_ROTATION.md` (API keys, password rotation)

---

**Document Owner**: omniclaude maintainers
**Review Frequency**: Quarterly or on major architectural changes
**Feedback**: Submit issues to omniclaude repository
