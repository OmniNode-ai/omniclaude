# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **📚 Shared Infrastructure**: For common OmniNode infrastructure (PostgreSQL, Kafka/Redpanda, remote server topology, Docker networking, environment variables), see **`~/.claude/CLAUDE.md`**. This file contains OmniClaude-specific architecture, agents, and services only.

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
6. [Agent Router Service](#agent-router-service)
7. [Provider Management](#provider-management)
8. [Polymorphic Agent Framework](#polymorphic-agent-framework)
9. [Event Bus Architecture](#event-bus-architecture)
10. [Troubleshooting Guide](#troubleshooting-guide)
11. [Quick Reference](#quick-reference)

---

## Intelligence Infrastructure

OmniClaude features a sophisticated intelligence infrastructure that provides agents with real-time system awareness and pattern discovery.

### Architecture Overview

**Event-Driven Intelligence**:
- **Kafka Event Bus** (192.168.86.200:9092) - Central message broker for all intelligence events
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
| **archon-router-consumer** | Event-based agent routing service | N/A | Check logs |

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

**⚠️ IMPORTANT: Source `.env` before running psql commands**

```bash
source .env  # Loads POSTGRES_PASSWORD=***REDACTED***
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge
```

**Connection Details**:
- Host: `192.168.86.200` | Port: `5436` | Database: `omninode_bridge`
- Password in `.env`: `POSTGRES_PASSWORD=***REDACTED***`

**If auth fails**: Verify `.env` exists and is sourced: `source .env && grep POSTGRES_PASSWORD .env`

#### Kafka Configuration
```bash
# Bootstrap servers (set in .env based on deployment)
KAFKA_BOOTSTRAP_SERVERS=  # Docker internal: omninode-bridge-redpanda:9092
                          # Host access: localhost:29102 (prod) or localhost:29092 (test)

# Event-based intelligence
KAFKA_ENABLE_INTELLIGENCE=true
KAFKA_REQUEST_TIMEOUT_MS=5000
```

**Key Topics**: `intelligence.code-analysis-*`, `agent.routing.*`, `documentation-changed`
**Admin UI**: `http://localhost:8080`

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

Interactive CLI tool at `agents/lib/agent_history_browser.py` for browsing agent execution history.

**Usage**:
```bash
python3 agents/lib/agent_history_browser.py                    # Interactive mode
python3 agents/lib/agent_history_browser.py --agent test-agent # Filter by agent
python3 agents/lib/agent_history_browser.py --correlation-id <id> --export manifest.json
```

**Features**: Performance metrics, debug intelligence (successes/failures), manifest export, rich terminal UI

**Performance Indicators**:
- Query time: <2000ms excellent | 2000-5000ms acceptable | >5000ms issue
- Agent name "unknown" → Check `AGENT_NAME` env var in `manifest_loader.py`

---

## Agent Observability & Traceability

Three-layer traceability: routing decisions → manifest injections → execution logs, all linked by correlation_id.

### Database Tables
- `agent_routing_decisions` - Agent selection with confidence scores
- `agent_manifest_injections` - Complete manifest snapshots for replay
- `agent_execution_logs` - Execution lifecycle (start/progress/complete)

### AgentExecutionLogger Usage

```python
from agents.lib.agent_execution_logger import log_agent_execution
logger = await log_agent_execution(agent_name="...", user_prompt="...", correlation_id=...)
await logger.progress(stage="...", percent=50)
await logger.complete(status=EnumOperationStatus.SUCCESS, quality_score=0.92)
```

**Features**: Non-blocking, exponential backoff retry, PostgreSQL primary + JSON fallback

### Analytical Views
```sql
SELECT * FROM v_agent_execution_trace WHERE correlation_id = '...';
SELECT * FROM v_manifest_injection_performance ORDER BY avg_query_time_ms DESC;
```

**Docs**: See `docs/observability/` for detailed architecture, schemas, and debugging guides

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

# Router Consumer
docker exec -it omniclaude_archon_router_consumer bash
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
| archon-kafka-consumer | N/A | N/A | Kafka |
| archon-router-consumer | N/A | N/A | Kafka |
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

## Agent Router Service

Event-driven agent routing via Kafka with ~7-8ms routing time and complete observability.

### Service: `archon-router-consumer`
- Pure Kafka consumer (no HTTP endpoints)
- Async processing with aiokafka
- Performance: 7-8ms routing, <500ms total latency, 100+ req/s throughput
- Non-blocking DB logging to `agent_routing_decisions` table

### Kafka Topics
- `agent.routing.requested.v1` - Routing requests
- `agent.routing.completed.v1` - Successful routing
- `agent.routing.failed.v1` - Errors

### Usage

```python
from agents.lib.routing_event_client import route_via_events

recommendations = await route_via_events(
    user_request="Help me implement ONEX patterns",
    max_recommendations=3,
)
```

### Service Management

```bash
# Manage service
docker-compose -f deployment/docker-compose.yml up -d archon-router-consumer
docker restart omniclaude_archon_router_consumer
docker logs -f omniclaude_archon_router_consumer

# Query routing decisions
source .env && psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT * FROM agent_routing_decisions ORDER BY created_at DESC LIMIT 10;"

# Test routing
python3 agents/services/test_router_service.py -v
```

### Troubleshooting

| Issue | Quick Fix |
|-------|-----------|
| Service not responding | `docker restart omniclaude_archon_router_consumer` |
| DB logging failures | Verify `POSTGRES_PASSWORD` in `.env` |
| Consumer lag | Check `docker stats omniclaude_archon_router_consumer` |

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

All intelligence queries flow through Kafka event bus:
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

**Router Topics** (Event-Based Routing):
- `agent.routing.requested.v1` - Routing requests from clients
- `agent.routing.completed.v1` - Successful routing with recommendations
- `agent.routing.failed.v1` - Error responses with failure details

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

| Issue | Quick Diagnosis | Quick Fix |
|-------|----------------|-----------|
| Agent name "unknown" | `echo $AGENT_NAME` | Set `AGENT_NAME` env var before execution |
| 0 patterns discovered | `curl http://localhost:6333/collections` | Verify Qdrant collections have vectors |
| Long query times (>10s) | `python3 agents/lib/agent_history_browser.py --limit 20` | Check Qdrant performance, reduce pattern limit |
| DB connection failed | `grep POSTGRES_PASSWORD .env` | Source `.env` and verify `POSTGRES_PASSWORD` |
| Intelligence unavailable | `docker logs archon-intelligence` | `docker start archon-intelligence` |

### Quick Verification

```bash
./scripts/health_check.sh                                    # Comprehensive check
curl http://localhost:6333/collections                       # Qdrant
curl http://localhost:8053/health                            # archon-intelligence
source .env && psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"
```

---

## Quick Reference

### 🔑 Credentials
**⚠️ Always source `.env` first**: `source .env` (contains `POSTGRES_PASSWORD=***REDACTED***`)

### Service URLs
- Intelligence: `http://localhost:8053/health`, `http://localhost:6333/collections`
- Infrastructure: `http://localhost:8080` (Kafka Admin), `postgresql://192.168.86.200:5436/omninode_bridge`

### Common Commands

```bash
# Health & monitoring
./scripts/health_check.sh
python3 agents/lib/agent_history_browser.py --agent <name>

# Service management
docker restart archon-intelligence
docker logs -f omniclaude_archon_router_consumer

# Database (after source .env)
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge
psql ... -c "SELECT * FROM v_agent_execution_trace LIMIT 10;"

# Provider switching
./toggle-claude-provider.sh gemini-flash

# Testing
python3 agents/services/test_router_service.py -v
```

### Key Files
- **Config**: `.env`, `claude-providers.json`
- **Intelligence**: `agents/lib/manifest_injector.py`, `agents/lib/routing_event_client.py`
- **Docs**: `docs/observability/AGENT_TRACEABILITY.md`, `SECURITY_KEY_ROTATION.md`

### Performance Targets
| Metric | Target | Critical |
|--------|--------|----------|
| Manifest query | <2000ms | >5000ms |
| Routing | <10ms | >100ms |
| Intelligence availability | >95% | <80% |

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
- All services communicate via Kafka event bus
- Agent router uses pure event-based architecture (no HTTP endpoints)
- Complete observability with manifest injection traceability
- Pattern discovery yields 120+ patterns from Qdrant
- Database contains 34 tables with complete agent execution history
- Router performance: 7-8ms routing time, 100+ requests/second throughput

---

**Last Updated**: 2025-10-30
**Documentation Version**: 2.2.0
**Intelligence Infrastructure**: Event-driven via Kafka
**Router Architecture**: Event-based (Kafka consumer) - Phase 2 complete
**Pattern Count**: 120+ (execution_patterns + code_patterns)
**Database Tables**: 34 in omninode_bridge
**Observability**: Complete traceability with correlation ID tracking
**Router Performance**: 7-8ms routing time, <500ms total latency
