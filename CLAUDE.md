# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

OmniClaude is a comprehensive toolkit for enhancing Claude Code capabilities with:
- **Multi-provider AI model support** with dynamic switching
- **Intelligence infrastructure** for real-time pattern discovery
- **Event-driven architecture** using Kafka for distributed intelligence
- **Polymorphic agent framework** with ONEX compliance
- **Complete observability** with manifest injection traceability

## Table of Contents

1. [Intelligence Infrastructure](#intelligence-infrastructure)
2. [Environment Configuration](#environment-configuration)
3. [Diagnostic Tools](#diagnostic-tools)
4. [Agent Observability & Traceability](#agent-observability--traceability)
5. [Container Management](#container-management)
6. [Provider Management](#provider-management)
7. [Polymorphic Agent Framework](#polymorphic-agent-framework)
8. [Event Bus Architecture](#event-bus-architecture)
9. [Troubleshooting Guide](#troubleshooting-guide)
10. [Quick Reference](#quick-reference)

---

## Intelligence Infrastructure

OmniClaude features a sophisticated intelligence infrastructure that provides agents with real-time system awareness and pattern discovery.

### Architecture Overview

**Event-Driven Intelligence**:
- **Kafka Event Bus** (192.168.86.200:9092) - Central message broker for all intelligence events
- **No MCP** - All services communicate via Kafka events, not MCP protocol
- **Request-Response Pattern** - Async intelligence queries with correlation tracking
- **Graceful Degradation** - Falls back to minimal manifest on timeout

**Key Services**:

| Service | Purpose | Port | Health Check |
|---------|---------|------|--------------|
| **archon-intelligence** | Intelligence coordinator and event processor | 8053 | `curl http://localhost:8053/health` |
| **archon-qdrant** | Vector database for pattern storage (120+ patterns) | 6333 | `curl http://localhost:6333/collections` |
| **archon-bridge** | PostgreSQL connector (34 tables in omninode_bridge) | 5436 | `psql -h localhost -p 5436 -U postgres` |
| **archon-search** | Full-text and semantic search | 8054 | `curl http://localhost:8054/health` |
| **archon-memgraph** | Graph database for relationships | 7687 | Bolt protocol check |
| **archon-kafka-consumer** | Event consumer for intelligence processing | N/A | Check logs |
| **archon-server** | Main Archon MCP server | 8150 | `curl http://localhost:8150/health` |

### Manifest Intelligence System

**Dynamic Manifest Generation** (`agents/lib/manifest_injector.py`):
- Queries Qdrant, Memgraph, PostgreSQL via event bus
- Parallel query execution (<2000ms total)
- Complete system context injected into agent prompts
- Full traceability with correlation IDs

**Pattern Discovery**:
- **120+ patterns** from Qdrant (execution_patterns + code_patterns collections)
- ONEX architectural templates
- Real Python implementations
- Debug intelligence (successful/failed workflows)

**Database Schemas** (34 tables in `omninode_bridge`):
- `agent_manifest_injections` - Complete manifest injection records
- `agent_routing_decisions` - Agent selection and confidence scores
- `agent_transformation_events` - Polymorphic agent transformations
- `router_performance_metrics` - Routing performance analytics
- `workflow_events` - Debug intelligence and workflow history

---

## Environment Configuration

### Required Environment Variables

All environment variables are configured in `.env` (copy from `.env.example`):

```bash
# Setup
cp .env.example .env
nano .env
source .env
```

### Complete Variable Reference

#### Google Gemini API
```bash
# Primary API key
GEMINI_API_KEY=your_gemini_api_key_here

# Pydantic AI compatibility
GOOGLE_API_KEY=your_gemini_api_key_here
```

**Get your key**: https://console.cloud.google.com/apis/credentials
**Enable**: Generative Language API
**Used by**: Multi-provider support, AI quorum validation

#### Z.ai API
```bash
ZAI_API_KEY=your_zai_api_key_here
```

**Get your key**: https://z.ai/dashboard
**Used by**: GLM models (GLM-4.5-Air, GLM-4.5, GLM-4.6)
**Rate limits**: 5-20 concurrent requests depending on model

#### PostgreSQL Configuration

**⚠️ IMPORTANT: ALL CREDENTIALS ARE IN `.env` FILE**

The `.env` file contains the correct PostgreSQL password for all services. **You MUST source it before running any commands**:

```bash
# Load credentials from .env
source .env

# Or use PGPASSWORD directly from .env
export PGPASSWORD="omninode_remote_2024_secure"
```

**Environment Variables in `.env`**:
```bash
# Hook intelligence database (required)
DB_PASSWORD=omninode_remote_2024_secure

# Docker deployment (required for containers)
OMNINODE_BRIDGE_POSTGRES_PASSWORD=omninode_remote_2024_secure

# PostgreSQL password for psql commands (REQUIRED for agents/tests)
POSTGRES_PASSWORD=omninode_remote_2024_secure
```

**Connection details**:
- Host: `192.168.86.200` (remote) or `localhost` (local)
- Port: `5436`
- Database: `omninode_bridge`
- User: `postgres`
- Password: `omninode_remote_2024_secure` (available in `.env`)

**Connecting to PostgreSQL**:

```bash
# Method 1: Source .env first (RECOMMENDED)
source .env
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge

# Method 2: Use PGPASSWORD environment variable
PGPASSWORD="omninode_remote_2024_secure" psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge

# Method 3: Connection string
psql "postgresql://postgres:omninode_remote_2024_secure@192.168.86.200:5436/omninode_bridge"
```

**For Polymorphic Agents & Tests**:

All agents and tests automatically read credentials from `.env`. If you see authentication errors:

1. ✅ Verify `.env` exists: `ls -la .env`
2. ✅ Verify password in `.env`: `grep POSTGRES_PASSWORD .env`
3. ✅ Source `.env` in your shell: `source .env`
4. ✅ Test connection: `PGPASSWORD="omninode_remote_2024_secure" psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"`

**⚠️ SECURITY WARNING**: Change default password in production!

#### Kafka Configuration
```bash
# REQUIRED: Set based on your deployment environment (no default)
# See .env.example for detailed port selection guide
KAFKA_BOOTSTRAP_SERVERS=

# Common configurations:
# - Docker internal: omninode-bridge-redpanda:9092
# - Host to Docker (production): localhost:29102 or 192.168.86.200:29102
# - Host to Docker (test): localhost:29092

# Documentation hooks
KAFKA_DOC_TOPIC=documentation-changed
GIT_HOOK_VALIDATE_DOCS=false

# Event-based intelligence (PRIMARY)
KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS=  # Same as KAFKA_BOOTSTRAP_SERVERS
KAFKA_ENABLE_INTELLIGENCE=true
ENABLE_EVENT_BASED_DISCOVERY=true
ENABLE_FILESYSTEM_FALLBACK=true
PREFER_EVENT_PATTERNS=true
KAFKA_REQUEST_TIMEOUT_MS=5000
```

**Topics**:
- `dev.archon-intelligence.intelligence.code-analysis-requested.v1`
- `dev.archon-intelligence.intelligence.code-analysis-completed.v1`
- `dev.archon-intelligence.intelligence.code-analysis-failed.v1`
- `documentation-changed`

**Port Reference**:
- **Port 9092**: Internal Docker network (service-to-service communication)
- **Port 29092**: External host access (test environment)
- **Port 29102**: External host access (production environment - RECOMMENDED)
- **Admin UI**: `http://localhost:8080`

**Port Selection**:
- Use `omninode-bridge-redpanda:9092` for containers within Docker network
- Use `localhost:29102` or `192.168.86.200:29102` for external access from host (production)
- Use `localhost:29092` for external access in test environment

#### Qdrant Configuration
```bash
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_URL=http://localhost:6333
```

**Collections**:
- `code_patterns` - Real Python implementations
- `execution_patterns` - ONEX architectural templates
- `workflow_events` - Debug intelligence data

### Environment File Locations

1. **Primary**: `/Volumes/PRO-G40/Code/omniclaude/.env`
2. **Hooks**: `~/.claude/hooks/.env` (legacy)
3. **Agents**: `agents/configs/.env` (agent-specific overrides)

---

## Diagnostic Tools

### Health Check Script

**Location**: `scripts/health_check.sh`

**Usage**:
```bash
./scripts/health_check.sh
```

**What it checks**:
- ✅ Docker services (archon-*, omninode-*)
- ✅ Kafka connectivity (topics, broker health)
- ✅ Qdrant collections (vector counts)
- ✅ PostgreSQL connectivity (table counts)
- ✅ Recent manifest injection quality
- ✅ Intelligence collection status (last 5 min)

**Output**:
```
=== System Health Check ===
Timestamp: 2025-10-27 14:30:00

Services:
  ✅ archon-intelligence (healthy)
  ✅ archon-qdrant (healthy)
  ✅ archon-bridge (healthy)
  ✅ archon-search (healthy)
  ✅ archon-memgraph (healthy)
  ✅ archon-kafka-consumer (healthy)
  ✅ archon-server (healthy)

Infrastructure:
  ✅ Kafka: 192.168.86.200:9092 (connected, 15 topics)
  ✅ Qdrant: http://localhost:6333 (connected, 3 collections)
  📊 Collections: code_patterns (856 vectors), execution_patterns (229 vectors)
  ✅ PostgreSQL: 192.168.86.200:5436/omninode_bridge (connected)
  📊 Tables: 34 in public schema
  📊 Manifest Injections (24h): 142

Intelligence Collection (Last 5 min):
  ✅ Pattern Discovery: 12 manifest injections with patterns
  📊 Avg Query Time: 1842ms

=== Summary ===
✅ All systems healthy
```

**Output Files**:
- `/tmp/health_check_latest.txt` - Latest check results
- `/tmp/health_check_history.log` - Appended history

**Exit Codes**:
- `0` - All systems healthy
- `1` - Issues found (see summary)

### Agent History Browser

**Location**: `agents/lib/agent_history_browser.py`

Interactive CLI tool to browse complete agent execution history with manifest injection traceability.

**Usage**:
```bash
# Interactive mode
python3 agents/lib/agent_history_browser.py

# Filter by agent
python3 agents/lib/agent_history_browser.py --agent test-agent

# Show more results
python3 agents/lib/agent_history_browser.py --limit 100

# View specific execution
python3 agents/lib/agent_history_browser.py --correlation-id a2f33abd-34c2-4d63-bfe7-2cb14ded13fd

# Export manifest JSON
python3 agents/lib/agent_history_browser.py --correlation-id <id> --export manifest.json
```

**Features**:
- 📊 List recent agent executions with performance metrics
- 🔍 Drill down into complete manifest details
- 🧠 View debug intelligence (what worked/failed)
- 🔎 Search and filter by agent, date range, correlation ID
- 💾 Export manifest JSON for analysis
- 🎨 Rich terminal UI with fallback to basic formatting

**Interactive Commands**:
- `[number]` - View detailed history for agent run
- `search [name]` - Filter by agent name (partial match)
- `clear` - Clear filter
- `limit [N]` - Set list limit
- `export [number]` - Export manifest JSON
- `h, help` - Show help
- `q, quit` - Quit browser

**Example Session**:
```
Recent Agent Runs
┌────┬──────────────────────────────────────┬─────────────────────────┬──────────────────────┬──────────┬────────────┬──────────────┐
│ #  │ Correlation ID                       │ Agent Name              │ Time                 │ Patterns │ Query Time │ Debug Intel  │
├────┼──────────────────────────────────────┼─────────────────────────┼──────────────────────┼──────────┼────────────┼──────────────┤
│ 1  │ 8b57ec39-45b5-467b-939c-dd1439219f69 │ agent-devops-infra      │ 2h ago               │      120 │     1842ms │ ✓12/✗3       │
│ 2  │ 7a44dc28-34a1-456c-8ef6-1cb03ded02ad │ agent-test-generator    │ 3h ago               │       95 │     1523ms │ ✓8/✗1        │
│ 3  │ 6c33cb17-23b0-345b-7de5-0ba92cdc91bc │ polymorphic-agent       │ 4h ago               │      108 │     1678ms │ ✓15/✗2       │
└────┴──────────────────────────────────────┴─────────────────────────┴──────────────────────┴──────────┴────────────┴──────────────┘

Commands:
  [number]           View detailed history for agent run
  search [name]      Filter by agent name
  clear              Clear filter
  limit [N]          Set list limit (current: 50)
  export [number]    Export manifest JSON
  h, help            Show help
  q, quit            Quit browser

Command [q]: 1
```

**Detail View Shows**:
- Complete correlation ID and agent information
- Performance metrics breakdown (query times per section)
- Content summary (patterns, infrastructure, models, schemas)
- Debug intelligence with successful/failed approaches
- Formatted manifest preview (first 20 lines)

**Interpreting Agent Names**:
- **Agent name = "unknown"** → Check `manifest_loader.py` reads `AGENT_NAME` env var
- **Agent name with marker "⚠"** → Fallback manifest (intelligence unavailable)
- **Agent name in green** → Full manifest with intelligence

**Interpreting Query Times**:
- **<2000ms** → Excellent performance
- **2000-5000ms** → Acceptable performance
- **>5000ms** → Performance issue (check logs, Qdrant connectivity)
- **>10000ms** → Critical issue (check archon-intelligence service)

---

## Agent Observability & Traceability

OmniClaude provides complete observability for agent executions with three-layer traceability: routing decisions → manifest injections → execution logs.

### Architecture

**Three-Layer Traceability**:
```
USER REQUEST
  ↓
LAYER 1: Routing Decision (agent_routing_decisions)
  - Which agent?
  - Why selected?
  - Confidence score?
  ↓
LAYER 2: Manifest Injection (agent_manifest_injections)
  - What context?
  - Which patterns?
  - Debug intelligence?
  ↓
LAYER 3: Execution Log (agent_execution_logs)
  - Start/progress/completion
  - Quality score
  - Error details
```

**Key Features**:
- **Correlation ID Tracking**: Complete trace from user prompt to execution outcome
- **Dual-Path Logging**: PostgreSQL primary, JSON file fallback
- **Kafka Event Bus**: All intelligence queries flow through Kafka
- **Complete Replay**: Full manifest snapshots enable exact reproduction
- **Debug Intelligence**: Learn from past successes and failures

### AgentExecutionLogger

Every agent execution uses `AgentExecutionLogger` for comprehensive logging:

```python
from agents.lib.agent_execution_logger import log_agent_execution
from omnibase_core.enums.enum_operation_status import EnumOperationStatus

# Start logging
logger = await log_agent_execution(
    agent_name="agent-researcher",
    user_prompt="Research ONEX patterns",
    correlation_id=correlation_id,
    project_path="/path/to/project"
)

# Log progress
await logger.progress(stage="gathering_intelligence", percent=25)
await logger.progress(stage="analyzing_results", percent=75)

# Complete with success
await logger.complete(
    status=EnumOperationStatus.SUCCESS,
    quality_score=0.92
)
```

**Features**:
- Non-blocking (never fails agent execution)
- Exponential backoff retry (1m, 2m, 5m, 10m)
- Platform-aware fallback (uses `tempfile.gettempdir()`)
- Quality score tracking
- Project context capture

### Database Tables

#### agent_routing_decisions

Tracks routing decisions with confidence scoring:
- `correlation_id` - Links to manifest and execution
- `selected_agent` - Which agent was chosen
- `confidence_score` - Overall confidence (0.0-1.0)
- `routing_strategy` - enhanced_fuzzy_matching, explicit, fallback
- `alternatives` - Other agents considered (JSONB)
- `reasoning` - Why this agent was selected

#### agent_manifest_injections

Complete manifest snapshots for replay:
- `correlation_id` - Links to routing and execution
- `full_manifest_snapshot` - Complete manifest data (JSONB)
- `formatted_manifest_text` - Exact text injected into prompt
- `patterns_count` - Number of patterns included
- `debug_intelligence_successes/failures` - Similar past workflows
- `query_times` - Performance breakdown per section (JSONB)
- `total_query_time_ms` - Total manifest generation time

#### agent_execution_logs

Execution lifecycle tracking:
- `execution_id` - Unique execution identifier
- `correlation_id` - Links to routing and manifest
- `agent_name` - Agent that executed
- `status` - in_progress, success, failed, cancelled
- `quality_score` - Output quality (0.0-1.0)
- `duration_ms` - Execution time
- `error_message/error_type` - Error details if failed

### Analytical Views

```sql
-- Complete execution trace
SELECT * FROM v_agent_execution_trace
WHERE correlation_id = '8b57ec39-45b5-467b-939c-dd1439219f69';

-- Manifest injection performance
SELECT * FROM v_manifest_injection_performance
ORDER BY avg_query_time_ms DESC;

-- Routing decision accuracy
SELECT * FROM v_routing_decision_accuracy
ORDER BY accuracy_percent DESC;
```

### Event Flow

```
1. Agent spawns with correlation_id
2. AgentExecutionLogger.start() → PostgreSQL INSERT
3. ManifestInjector queries archon-intelligence via Kafka:
   - Publish: intelligence.code-analysis-requested.v1
   - Wait: intelligence.code-analysis-completed.v1
   - Store: agent_manifest_injections table
4. Agent executes with injected context
5. AgentExecutionLogger.progress() → PostgreSQL UPDATE
6. AgentExecutionLogger.complete() → PostgreSQL UPDATE
7. Complete trace available via correlation_id
```

### Fallback Mechanism

When PostgreSQL is unavailable, logs are written to structured JSON files:

```
{temp}/omniclaude_logs/
├── 2025-10-29/
│   ├── 8b57ec39-45b5-467b-939c-dd1439219f69.jsonl
│   └── 7a44dc28-34a1-456c-8ef6-1cb03ded02ad.jsonl
└── 2025-10-28/
    └── ...
```

**JSONL Format** (one JSON object per line):
```jsonl
{"timestamp": "2025-10-29T14:30:00Z", "event_type": "start", "agent_name": "agent-researcher", ...}
{"timestamp": "2025-10-29T14:30:15Z", "event_type": "progress", "stage": "gathering_intelligence", ...}
{"timestamp": "2025-10-29T14:30:45Z", "event_type": "complete", "status": "success", "quality_score": 0.92}
```

### Performance Targets

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| Routing decision time | <100ms | >200ms | >500ms |
| Manifest query time | <2000ms | >3000ms | >5000ms |
| Log write latency | <50ms | >100ms | >500ms |
| Fallback activation | <1% | >5% | >10% |
| Intelligence availability | >95% | <90% | <80% |

### Comprehensive Documentation

**Detailed Guides**:
- [docs/observability/AGENT_TRACEABILITY.md](docs/observability/AGENT_TRACEABILITY.md) - Architecture, database schemas, query examples
- [docs/observability/DIAGNOSTIC_SCRIPTS.md](docs/observability/DIAGNOSTIC_SCRIPTS.md) - Tool usage, troubleshooting workflows
- [docs/observability/LOGGING_PIPELINE.md](docs/observability/LOGGING_PIPELINE.md) - Event flow, integration guide, debugging

**Quick Start**:

```bash
# Browse agent execution history
python3 agents/lib/agent_history_browser.py

# Filter by agent
python3 agents/lib/agent_history_browser.py --agent agent-researcher

# View specific execution
python3 agents/lib/agent_history_browser.py \
    --correlation-id 8b57ec39-45b5-467b-939c-dd1439219f69

# Export manifest JSON
python3 agents/lib/agent_history_browser.py \
    --correlation-id 8b57ec39... \
    --export manifest.json

# Check system health
./scripts/health_check.sh

# Direct database queries
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge
```

---

## Container Management

### List All Containers

```bash
# View all running containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# View with health status
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "(archon|omninode)"
```

### Access Container Shell

```bash
# Archon Intelligence (Python/FastAPI)
docker exec -it archon-intelligence bash

# Qdrant (Vector database)
docker exec -it archon-qdrant sh

# PostgreSQL Bridge
docker exec -it archon-bridge bash

# Kafka Consumer
docker exec -it archon-kafka-consumer bash
```

### View Container Logs

```bash
# Real-time logs
docker logs -f archon-intelligence

# Last 100 lines
docker logs --tail 100 archon-intelligence

# Logs with timestamps
docker logs -t archon-intelligence

# Search logs
docker logs archon-intelligence 2>&1 | grep "ERROR"
```

### Service Management

```bash
# Restart service (preserves container state)
docker restart archon-intelligence

# Stop service
docker stop archon-intelligence

# Start service
docker start archon-intelligence

# Rebuild and restart (required for code changes)
docker-compose up -d --build archon-intelligence

# View service health
docker inspect archon-intelligence --format='{{.State.Health.Status}}'
```

### Port Mappings

| Service | Internal Port | External Port | Protocol |
|---------|---------------|---------------|----------|
| archon-intelligence | 8053 | 8053 | HTTP |
| archon-qdrant | 6333 | 6333 | HTTP |
| archon-bridge (PostgreSQL) | 5432 | 5436 | PostgreSQL |
| archon-search | 8054 | 8054 | HTTP |
| archon-memgraph | 7687 | 7687 | Bolt |
| archon-kafka-consumer | N/A | N/A | Internal |
| archon-server | 8150 | 8150 | HTTP |
| Kafka/Redpanda | 9092 | 9092 | Kafka |
| Redpanda Admin | 8080 | 8080 | HTTP |

### Network Configuration

All services run on `omninode-bridge-network` Docker network.

**External connectivity**:
- Host machine: `192.168.86.200` (remote services)
- Localhost: `localhost` or `127.0.0.1` (local services)
- Docker internal: `<service-name>` (e.g., `archon-intelligence`)

---

## Provider Management

### Switch AI Providers

```bash
# Switch between AI providers
./toggle-claude-provider.sh claude        # Use Anthropic Claude models
./toggle-claude-provider.sh zai           # Use Z.ai GLM models
./toggle-claude-provider.sh together      # Use Together AI models
./toggle-claude-provider.sh openrouter    # Use OpenRouter models
./toggle-claude-provider.sh gemini-pro      # Use Google Gemini Pro models
./toggle-claude-provider.sh gemini-flash    # Use Google Gemini Flash models
./toggle-claude-provider.sh gemini-2.5-flash # Use Google Gemini 2.5 Flash models

# Check current provider status
./toggle-claude-provider.sh status

# List all available providers
./toggle-claude-provider.sh list
```

### Provider Configuration

**Provider Support**:
- **Anthropic**: Native Claude models with standard rate limits
- **Z.ai**: GLM-4.5-Air, GLM-4.5, GLM-4.6 with high concurrency (35 total)
- **Together AI**: Llama-3.1 variants with variable limits
- **OpenRouter**: Model marketplace with OpenRouter-specific limits
- **Google Gemini Pro**: Gemini 1.5 Flash/Pro with quality focus
- **Google Gemini Flash**: Gemini 1.5 Flash optimized for speed
- **Google Gemini 2.5 Flash**: Gemini 2.5 Flash/Pro with latest capabilities

**Configuration Files**:
- `claude-providers.json` - Provider definitions
- `~/.claude/settings.json` - Modified by toggle script
- `.env` - API keys (never commit!)

**Notes**:
- Requires Claude Code restart after provider changes
- Modifies `~/.claude/settings.json` (creates backups)
- Requires `jq` for JSON manipulation

---

## Polymorphic Agent Framework

The `agents/` directory contains a comprehensive polymorphic agent framework built on ONEX architecture principles.

### Architecture

**Core Components**:
- **Agent Workflow Coordinator**: Unified orchestration with routing, parallel execution, dynamic transformation
- **Enhanced Router System**: Intelligent agent selection with fuzzy matching and confidence scoring
- **Manifest Injector**: Dynamic system context via event bus intelligence
- **ONEX Compliance**: 4-node architecture (Effect, Compute, Reducer, Orchestrator)
- **Multi-Agent Coordination**: Parallel execution with shared state and dependency tracking

### Intelligence Context Injection

**Manifest Injection Flow**:
```
1. Agent spawns with correlation ID
2. ManifestInjector queries archon-intelligence via Kafka
3. Parallel queries executed:
   - patterns (execution_patterns + code_patterns)
   - infrastructure (PostgreSQL, Kafka, Qdrant, Docker)
   - models (AI providers, ONEX models, quorum config)
   - database_schemas (table definitions)
   - debug_intelligence (similar workflows - successes/failures)
4. Results formatted into structured manifest
5. Manifest injected into agent prompt
6. Complete record stored in agent_manifest_injections table
```

**Example Manifest Section**:
```
======================================================================
SYSTEM MANIFEST - Dynamic Context via Event Bus
======================================================================

Version: 2.0.0
Generated: 2025-10-27T14:30:00Z
Source: archon-intelligence-adapter

AVAILABLE PATTERNS:
  Collections: execution_patterns (120), code_patterns (856)

  • Node State Management Pattern (95% confidence)
    File: node_state_manager_effect.py
    Node Types: EFFECT, REDUCER

  • Async Event Bus Communication (92% confidence)
    File: node_event_publisher_effect.py
    Node Types: EFFECT

  ... and 118 more patterns

  Total: 120 patterns available

DEBUG INTELLIGENCE (Similar Workflows):
  Total Similar: 12 successes, 3 failures

  ✅ SUCCESSFUL APPROACHES (what worked):
    • Read: Successfully read file before editing
    • Bash: Used parallel tool calls for independent operations
    • Edit: Preserved exact indentation from Read output

  ❌ FAILED APPROACHES (avoid retrying):
    • Write: Attempted to write without reading first (permission error)
    • Bash: Sequential commands caused timeout (use parallel instead)
```

### Mandatory Functions (47 across 11 categories)

- **Intelligence Capture** (4): Pre-execution intelligence gathering
- **Execution Lifecycle** (5): Agent lifecycle management
- **Debug Intelligence** (3): Debug pattern capture and analysis
- **Context Management** (4): Context inheritance and preservation
- **Coordination Protocols** (5): Multi-agent communication
- **Performance Monitoring** (4): Real-time performance tracking
- **Quality Validation** (5): ONEX compliance and quality gates
- **Parallel Coordination** (4): Synchronization and result aggregation
- **Knowledge Capture** (4): UAKS framework implementation
- **Error Handling** (5): Graceful degradation and retry logic
- **Framework Integration** (4): Template system and @include references

### Quality Gates (23 across 8 validation types)

- Sequential validation: Input/process/output validation
- Parallel validation: Distributed coordination validation
- Intelligence validation: RAG intelligence application
- Coordination validation: Multi-agent context inheritance
- Quality compliance: ONEX standards validation
- Performance validation: Threshold compliance (<200ms per gate)
- Knowledge validation: Learning pattern validation
- Framework validation: Lifecycle integration

### ONEX Architecture Patterns

**Node Types**:
- **Effect**: External I/O, APIs, side effects (`Node<Name>Effect`)
- **Compute**: Pure transforms/algorithms (`Node<Name>Compute`)
- **Reducer**: Aggregation, persistence, state (`Node<Name>Reducer`)
- **Orchestrator**: Workflow coordination (`Node<Name>Orchestrator`)

**File Patterns**:
- Models: `model_<name>.py` → `Model<Name>`
- Contracts: `model_contract_<type>.py` → `ModelContract<Type>`
- Node files: `node_*_<type>.py` → `Node<Name><Type>`

**Method Signatures**:
```python
# Effect
async def execute_effect(self, contract: ModelContractEffect) -> Any

# Compute
async def execute_compute(self, contract: ModelContractCompute) -> Any

# Reducer
async def execute_reduction(self, contract: ModelContractReducer) -> Any

# Orchestrator
async def execute_orchestration(self, contract: ModelContractOrchestrator) -> Any
```

### Agent Registry

**Location**: `~/.claude/agent-definitions/`

**Configuration**:
- Central registry for all agent definitions
- YAML-based configuration with metadata
- Dynamic agent loading and transformation

**Performance Targets**:
- Routing accuracy: >95%
- Average query time: <100ms
- Cache hit rate: >60%
- Quality gate execution: <200ms per gate

### Development Commands

```bash
# View agent configurations
ls ~/.claude/agent-definitions/

# Check framework requirements
cat agents/core-requirements.yaml     # 47 mandatory functions
cat agents/quality-gates-spec.yaml    # 23 quality gates

# Test manifest injection
python3 agents/lib/test_manifest_traceability.py

# Browse agent execution history
python3 agents/lib/agent_history_browser.py
```

---

## Event Bus Architecture

OmniClaude uses **Kafka/Redpanda** for all distributed intelligence communication.

### Event-Driven Intelligence

**No MCP Services** - All intelligence queries flow through Kafka event bus:
```
Agent Request
  ↓ (publish)
Kafka Topic: intelligence.requests
  ↓ (consume)
archon-intelligence-adapter
  ↓ (queries)
Qdrant + Memgraph + PostgreSQL
  ↓ (publish)
Kafka Topic: intelligence.responses
  ↓ (consume)
Agent receives manifest
```

### Kafka Topics

**Intelligence Topics**:
- `dev.archon-intelligence.intelligence.code-analysis-requested.v1`
- `dev.archon-intelligence.intelligence.code-analysis-completed.v1`
- `dev.archon-intelligence.intelligence.code-analysis-failed.v1`

**Documentation Topics**:
- `documentation-changed`

**Agent Tracking Topics**:
- `agent-routing-decisions`
- `agent-transformation-events`
- `router-performance-metrics`
- `agent-actions`

### Event Flow Examples

**Pattern Discovery Request**:
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

**Pattern Discovery Response**:
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

### Communication with OnexTree and Metadata Stamping

**OnexTree Filesystem Events**:
- File creation → Published to `filesystem.events` topic
- Metadata stamping service subscribes
- ONEX compliance metadata attached
- Result published back to `filesystem.results` topic

**Metadata Stamping Flow**:
```
1. File created in OnexTree
2. Event published to Kafka
3. Metadata stamping service consumes event
4. ONEX compliance validation performed
5. Metadata stamped to file
6. Confirmation published to Kafka
7. OnexTree receives confirmation
```

### Performance Characteristics

- **Request-Response Latency**: <5ms publish + <2000ms processing
- **Event Durability**: Kafka persistent storage
- **Replay Capability**: Complete event history available
- **Fault Tolerance**: Services continue even if consumers temporarily fail
- **Scalability**: Horizontal scaling via Kafka partitions

---

## Troubleshooting Guide

### Common Issues

#### Issue: Intelligence showing "unknown"

**Symptoms**:
- Agent name appears as "unknown" in browser
- Manifest shows minimal fallback content
- 0 patterns discovered

**Diagnosis**:
```bash
# Check archon-intelligence service
docker logs --tail 50 archon-intelligence

# Check Qdrant connectivity
curl http://localhost:6333/collections

# Check Kafka connectivity
./scripts/health_check.sh
```

**Solutions**:
1. **Service not running**: `docker start archon-intelligence`
2. **Qdrant empty**: Verify collections have vectors
3. **Kafka unreachable**: Check `KAFKA_BOOTSTRAP_SERVERS` in `.env`
4. **Timeout**: Increase `KAFKA_REQUEST_TIMEOUT_MS` (default: 5000)

#### Issue: Agent name = "unknown"

**Symptoms**:
- All agent executions show "unknown" as agent name
- Cannot filter by agent in history browser

**Diagnosis**:
```bash
# Check manifest_loader.py reads AGENT_NAME
grep "AGENT_NAME" agents/lib/manifest_loader.py

# Check environment variable set
echo $AGENT_NAME
```

**Solutions**:
1. **Missing env var**: Set `AGENT_NAME` before agent execution
2. **Hook not setting var**: Update git hooks to set `AGENT_NAME`
3. **manifest_loader.py issue**: Verify it reads `os.environ.get("AGENT_NAME")`

#### Issue: 0 patterns discovered

**Symptoms**:
- Manifest shows "Total: 0 patterns available"
- Debug intelligence empty

**Diagnosis**:
```bash
# Check Qdrant collections
curl http://localhost:6333/collections | jq '.result.collections[].name'

# Check vector counts
curl http://localhost:6333/collections/code_patterns | jq '.result.points_count'
curl http://localhost:6333/collections/execution_patterns | jq '.result.points_count'

# Check archon-intelligence logs for query failures
docker logs archon-intelligence 2>&1 | grep "PATTERN_EXTRACTION"
```

**Solutions**:
1. **Collections empty**: Run pattern ingestion process
2. **Query failing**: Check archon-intelligence can reach Qdrant
3. **Wrong collection name**: Verify `collection_name` in manifest_injector.py
4. **Network issue**: Check Docker network connectivity

#### Issue: Long query times (>10s)

**Symptoms**:
- Manifest injection takes >10 seconds
- Timeout warnings in logs
- Fallback manifests frequently

**Diagnosis**:
```bash
# Check recent query times
python3 agents/lib/agent_history_browser.py --limit 20

# Check archon-intelligence performance
docker logs archon-intelligence 2>&1 | grep "query_time_ms"

# Check Qdrant performance
curl http://localhost:6333/metrics
```

**Solutions**:
1. **Qdrant slow**: Optimize vector indexes
2. **Too many patterns**: Reduce `limit` in query options
3. **Network latency**: Check network between services
4. **Timeout too low**: Increase `KAFKA_REQUEST_TIMEOUT_MS`
5. **Sequential queries**: Ensure parallel query execution

#### Issue: Database connection failed

**Symptoms**:
- "Failed to connect to database" errors
- Browser cannot load history
- Health check shows PostgreSQL connection failed

**Diagnosis**:
```bash
# Test connection manually
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge

# Check password in .env
grep POSTGRES_PASSWORD .env

# Check service running
docker ps | grep archon-bridge
```

**Solutions**:
1. **Wrong password**: Verify `POSTGRES_PASSWORD` in `.env`
2. **Service not running**: `docker start archon-bridge`
3. **Wrong host/port**: Verify connection details in `.env`
4. **Network issue**: Check firewall rules for port 5436

### Verification Steps

**1. Verify Service Connectivity**:
```bash
# Run comprehensive health check
./scripts/health_check.sh

# Check specific services
curl http://localhost:6333/collections  # Qdrant
curl http://localhost:8053/health       # archon-intelligence
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"
```

**2. Verify Event Bus**:
```bash
# List Kafka topics (requires kafkacat/kcat)
kcat -L -b 192.168.86.200:9092

# Check consumer groups
docker exec -it omninode-bridge-redpanda rpk group list
```

**3. Verify Pattern Discovery**:
```bash
# Test manifest injection directly
python3 -c "
from agents.lib.manifest_injector import inject_manifest
manifest = inject_manifest()
print(manifest)
"
```

**4. Verify Database Queries**:
```bash
# Check recent manifest injections
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
SELECT
  agent_name,
  patterns_count,
  total_query_time_ms,
  created_at
FROM agent_manifest_injections
ORDER BY created_at DESC
LIMIT 5;
"
```

### Debug Intelligence Decision Tree

```
Start: Agent execution needs intelligence
  │
  ├─→ Check archon-intelligence service running?
  │    ├─ NO → Start service: docker start archon-intelligence
  │    └─ YES → Continue
  │
  ├─→ Check Qdrant has patterns?
  │    ├─ NO → Run pattern ingestion
  │    └─ YES → Continue
  │
  ├─→ Check Kafka connectivity?
  │    ├─ NO → Verify KAFKA_BOOTSTRAP_SERVERS in .env
  │    └─ YES → Continue
  │
  ├─→ Check query timeout reasonable?
  │    ├─ NO → Increase KAFKA_REQUEST_TIMEOUT_MS
  │    └─ YES → Continue
  │
  ├─→ Check recent executions in browser?
  │    ├─ agent_name = "unknown" → Set AGENT_NAME env var
  │    ├─ patterns_count = 0 → Check Qdrant collections
  │    ├─ query_time > 10000ms → Optimize queries
  │    └─ All good → Success!
  │
  └─→ Still failing?
       └─ Check archon-intelligence logs for specific errors
```

---

## Quick Reference

### 🔑 Credentials & Authentication

**⚠️ CRITICAL: All credentials are in `.env` file - source it before running any commands!**

```bash
# ALWAYS load credentials first
source .env

# PostgreSQL password (for all psql commands)
export PGPASSWORD="omninode_remote_2024_secure"
```

**If you see authentication errors:**
1. Source `.env`: `source .env`
2. Verify password: `grep POSTGRES_PASSWORD .env`
3. Test connection: `PGPASSWORD="omninode_remote_2024_secure" psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"`

**All passwords in `.env`:**
- `POSTGRES_PASSWORD=omninode_remote_2024_secure` ← **Use this for psql**
- `DB_PASSWORD=omninode_remote_2024_secure`
- `OMNINODE_BRIDGE_POSTGRES_PASSWORD=omninode_remote_2024_secure`

---

### Service URLs

```bash
# Intelligence Services
http://localhost:8053/health          # archon-intelligence
http://localhost:6333/collections     # archon-qdrant
http://localhost:8054/health          # archon-search
http://localhost:8150/health          # archon-server

# Infrastructure
http://localhost:8080                 # Redpanda Admin UI
http://192.168.86.200:9092           # Kafka Bootstrap Servers
postgresql://192.168.86.200:5436/omninode_bridge  # PostgreSQL
```

### Common Commands

```bash
# Health checks
./scripts/health_check.sh
docker ps --format "table {{.Names}}\t{{.Status}}"
curl http://localhost:6333/collections

# Browse agent history
python3 agents/lib/agent_history_browser.py
python3 agents/lib/agent_history_browser.py --agent test-agent
python3 agents/lib/agent_history_browser.py --correlation-id <id>

# View logs
docker logs -f archon-intelligence
docker logs --tail 100 archon-qdrant
docker logs archon-kafka-consumer 2>&1 | grep ERROR

# Service management
docker restart archon-intelligence
docker-compose up -d --build archon-intelligence
docker stop archon-intelligence && docker start archon-intelligence

# Database queries (MUST source .env first or use PGPASSWORD)
source .env && psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge
# OR with inline password:
PGPASSWORD="omninode_remote_2024_secure" psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge

# Provider management
./toggle-claude-provider.sh status
./toggle-claude-provider.sh gemini-flash

# Observability and traceability
python3 agents/lib/agent_history_browser.py                 # Interactive history browser
python3 agents/lib/agent_history_browser.py --agent <name>  # Filter by agent
python3 agents/lib/agent_history_browser.py --limit 100     # Show more results
python3 agents/lib/agent_history_browser.py --correlation-id <id>  # Specific execution
python3 agents/lib/agent_history_browser.py --correlation-id <id> --export manifest.json  # Export

# Observability queries (SQL) - Use PGPASSWORD from .env
PGPASSWORD="omninode_remote_2024_secure" psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT * FROM v_agent_execution_trace LIMIT 10;"
PGPASSWORD="omninode_remote_2024_secure" psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT * FROM v_manifest_injection_performance;"
PGPASSWORD="omninode_remote_2024_secure" psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT * FROM v_routing_decision_accuracy;"
```

### Database Connection Strings

```bash
# PostgreSQL (remote)
postgresql://postgres:${POSTGRES_PASSWORD}@192.168.86.200:5436/omninode_bridge

# PostgreSQL (local via Docker)
postgresql://postgres:${POSTGRES_PASSWORD}@localhost:5436/omninode_bridge

# Environment variable
export POSTGRES_PASSWORD="omninode_remote_2024_secure"
```

### Key Files

```bash
# Configuration
.env                                    # Environment variables (copy from .env.example)
claude-providers.json                   # AI provider configurations
~/.claude/settings.json                 # Claude Code settings (modified by toggle script)

# Intelligence Infrastructure
agents/lib/manifest_injector.py         # Dynamic manifest generation
agents/lib/intelligence_event_client.py # Kafka event client
agents/lib/agent_history_browser.py     # Interactive history browser
scripts/health_check.sh                 # System health checker

# Documentation
CLAUDE.md                               # This file
SECURITY_KEY_ROTATION.md               # API key management
agents/lib/MANIFEST_TRACEABILITY_GUIDE.md  # Manifest system guide
agents/lib/AGENT_HISTORY_BROWSER_DEMO.md   # Browser usage examples

# Observability Documentation (NEW)
docs/observability/AGENT_TRACEABILITY.md    # Architecture, database schemas, correlation tracking
docs/observability/DIAGNOSTIC_SCRIPTS.md    # Tool usage, troubleshooting workflows
docs/observability/LOGGING_PIPELINE.md      # Event flow, integration guide, debugging
```

### Performance Targets

| Metric | Target | Critical |
|--------|--------|----------|
| Manifest query time | <2000ms | >5000ms |
| Pattern discovery | 100+ patterns | <10 patterns |
| Routing decision | <100ms | >500ms |
| Quality gate execution | <200ms | >1000ms |
| Cache hit rate | >60% | <30% |
| Intelligence availability | >95% | <80% |
| Log write latency | <50ms | >500ms |
| Fallback activation rate | <1% | >10% |

### Environment Variable Quick Check

```bash
# Required variables
echo "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-(not set)}"
echo "KAFKA_BOOTSTRAP_SERVERS: ${KAFKA_BOOTSTRAP_SERVERS:-(not set)}"
echo "QDRANT_HOST: ${QDRANT_HOST:-(not set)}"
echo "GEMINI_API_KEY: ${GEMINI_API_KEY:+(set)}${GEMINI_API_KEY:-(not set)}"

# Load from .env if not set
source .env
```

---

## Security

**Important**: This repository uses environment variables for API key management.

### Security Best Practices

1. **Never commit API keys** to version control
2. **Use `.env.example`** as a template for your local `.env` file
3. **Rotate keys regularly** (every 30-90 days recommended)
4. **Use separate keys** for development and production
5. **Enable IP restrictions** in provider dashboards
6. **Set usage quotas** to limit damage from leaks
7. **Monitor API usage** regularly
8. **Change default passwords** in production (especially PostgreSQL)

**See [SECURITY_KEY_ROTATION.md](SECURITY_KEY_ROTATION.md)** for:
- Obtaining API keys from provider dashboards
- Step-by-step rotation procedures
- Testing new keys
- Troubleshooting common issues

---

## Notes

- Requires `jq` for JSON manipulation in provider toggle
- Requires `psql` for database health checks (optional but recommended)
- Requires `kafkacat` or `kcat` for Kafka diagnostics (optional but recommended)
- Agent framework requires ONEX compliance for all implementations
- Quality gates provide automated validation with <200ms execution target
- All services communicate via Kafka event bus (no MCP)
- Complete observability with manifest injection traceability
- Pattern discovery yields 120+ patterns from Qdrant
- Database contains 34 tables with complete agent execution history

---

**Last Updated**: 2025-10-29
**Documentation Version**: 2.1.0
**Intelligence Infrastructure**: Event-driven via Kafka
**Pattern Count**: 120+ (execution_patterns + code_patterns)
**Database Tables**: 34 in omninode_bridge
**Observability**: Complete traceability with correlation ID tracking
