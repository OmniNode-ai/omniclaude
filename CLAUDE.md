# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **📋 Documentation Restructured**: See specialized docs:
> - **Shared Infrastructure** → `~/.claude/CLAUDE.md` (PostgreSQL, Kafka, remote topology)
> - **Type-Safe Configuration** → `config/README.md` (Pydantic Settings, 90+ variables)
> - **Docker Deployment** → `deployment/README.md` (Consolidated docker-compose)
> - **Agent Framework** → `agents/polymorphic-agent.md` (ONEX compliance)
> - **Test Coverage** → `TEST_COVERAGE_PLAN.md`
> - **Security** → `SECURITY_KEY_ROTATION.md`

## Overview

OmniClaude enhances Claude Code with:
- **Multi-provider AI model support** with dynamic switching
- **Intelligence infrastructure** for real-time pattern discovery
- **Event-driven architecture** using Kafka for distributed intelligence
- **Polymorphic agent framework** with ONEX compliance
- **Complete observability** with manifest injection traceability

## Intelligence Infrastructure

### Architecture Overview

**Event-Driven Intelligence**:
- **Kafka Event Bus** (192.168.86.200:9092) - Central message broker
- **Request-Response Pattern** - Async queries with correlation tracking
- **Graceful Degradation** - Falls back on timeout

**Key Services**:

| Service | Purpose | Port |
|---------|---------|------|
| **archon-intelligence** | Intelligence coordinator | 8053 |
| **archon-qdrant** | Vector DB (15,689+ patterns) | 6333 |
| **archon-bridge** | PostgreSQL connector (34 tables) | 5436 |
| **archon-search** | Full-text/semantic search | 8054 |
| **archon-memgraph** | Graph database | 7687 |

### Pattern Discovery

**15,689+ patterns** from Qdrant:
- `archon_vectors` (7,118) - ONEX templates/execution patterns
- `code_generation_patterns` (8,571) - Python implementations

**Database**: 34 tables tracking agent routing, manifest injections, execution logs, performance metrics.

---

## Environment Configuration

> **🎯 New**: Type-Safe Configuration Framework with Pydantic Settings
> See `config/README.md` for complete documentation.

### Quick Setup

```bash
cp .env.example .env
nano .env
source .env
./scripts/validate-env.sh .env
```

### Key Variables

```bash
# API Keys
GEMINI_API_KEY=your_key
ZAI_API_KEY=your_key

# PostgreSQL (source .env before use)
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_PASSWORD=<set_in_env>

# Kafka
KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092  # Docker
# KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092         # Host scripts

# Qdrant
QDRANT_URL=http://localhost:6333
```

**Collections**:
- `archon_vectors` (7,118 vectors) - Active
- `code_generation_patterns` (8,571 vectors) - Active
- `archon-intelligence`, `quality_vectors` - Planned (empty)

---

## Type-Safe Configuration Framework

**Location**: `config/` directory

### Quick Start

```python
from config import settings

# Access with full type safety
print(settings.postgres_host)              # str: "192.168.86.200"
print(settings.postgres_port)              # int: 5436

# Get connection strings
dsn = settings.get_postgres_dsn()
async_dsn = settings.get_postgres_dsn(async_driver=True)

# Validation
errors = settings.validate_required_services()
```

**90+ type-safe variables** organized into:
1. External Service Discovery (Archon services)
2. Shared Infrastructure (PostgreSQL, Kafka)
3. AI Provider API Keys
4. Local Services (Qdrant, Valkey)
5. Feature Flags & Optimization

**📚 Complete Documentation**: See `config/README.md` and `docs/configuration/` for:
- STANDARDIZATION_GUIDE.md - Complete migration guide
- QUICK_REFERENCE.md - Quick lookup reference
- MIGRATION_TEMPLATE.py - Working code template

---

## Deployment

**Location**: `deployment/` directory
**Guide**: See `deployment/README.md` for complete procedures.

### Quick Start

```bash
# Setup
cp .env.example .env
nano .env
./scripts/validate-env.sh .env

# Start services
cd deployment && docker-compose up -d

# With monitoring
cd deployment && docker-compose --profile monitoring up -d

# View logs
cd deployment && docker-compose logs -f
```

### Services

**Core**: `app` (8000), `routing-adapter` (8070)
**Consumers**: `agent-consumer`, `router-consumer`, `intelligence-consumer`
**Infrastructure**: `postgres` (5432), `valkey` (6379)
**Monitoring**: `prometheus` (9090), `grafana` (3000), `jaeger` (16686)

**External** (omninode_bridge): Kafka (192.168.86.200:29092), PostgreSQL (192.168.86.200:5436), Qdrant (192.168.86.101:6333)

---

## Diagnostic Tools

### Health Check

```bash
./scripts/health_check.sh  # Comprehensive system check
```

Checks: Docker services, Kafka, Qdrant, PostgreSQL, manifest injection quality, intelligence collection.

### Agent History Browser

```bash
python3 agents/lib/agent_history_browser.py
python3 agents/lib/agent_history_browser.py --agent test-agent
python3 agents/lib/agent_history_browser.py --correlation-id <id> --export manifest.json
```

### System Functional Tests

```bash
./scripts/test_system_functionality.sh  # 44+ functional tests
```

Tests: Kafka (15 tests), PostgreSQL (9), Intelligence (8), Routing (12)

Individual suites:
```bash
./scripts/tests/test_kafka_functionality.sh
./scripts/tests/test_postgres_functionality.sh
./scripts/tests/test_intelligence_functionality.sh
./scripts/tests/test_routing_functionality.sh
```

---

## Agent Observability

Three-layer traceability via `correlation_id`:
- `agent_routing_decisions` - Agent selection with confidence
- `agent_manifest_injections` - Complete manifest snapshots
- `agent_execution_logs` - Execution lifecycle

```python
from agents.lib.agent_execution_logger import log_agent_execution
logger = await log_agent_execution(agent_name="...", user_prompt="...", correlation_id=...)
await logger.progress(stage="...", percent=50)
await logger.complete(status=EnumOperationStatus.SUCCESS, quality_score=0.92)
```

---

## Container Management

**Location**: `deployment/docker-compose.yml`

### Common Operations

```bash
# View services
docker-compose ps
docker ps --format "table {{.Names}}\t{{.Status}}"

# Service management (from deployment/)
cd deployment
docker-compose restart app
docker-compose logs -f app
docker-compose up -d --build app

# Or from project root
docker-compose -f deployment/docker-compose.yml restart app

# Shell access
docker exec -it archon-intelligence bash
docker exec -it archon-qdrant sh
```

### Networking

**Local**: `app_network`, `monitoring_network`
**External** (omninode_bridge): `omninode-bridge-network`

Benefits: Native cross-repo communication, no manual `/etc/hosts` for Docker services.

---

## Agent Router Service

Event-driven routing via Kafka: ~7-8ms routing, <500ms total latency, 100+ req/s throughput.

**Service**: `archon-router-consumer` (pure Kafka consumer)
**Topics**: `agent.routing.{requested,completed,failed}.v1`

```python
from agents.lib.routing_event_client import route_via_events
recommendations = await route_via_events(user_request="...", max_recommendations=3)
```

```bash
# Management
cd deployment && docker-compose up -d router-consumer
docker logs -f omniclaude_archon_router_consumer

# Query decisions
source .env && psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT * FROM agent_routing_decisions ORDER BY created_at DESC LIMIT 10;"
```

---

## Provider Management

```bash
./toggle-claude-provider.sh claude|zai|together|openrouter|gemini-pro|gemini-flash|gemini-2.5-flash
./toggle-claude-provider.sh status
./toggle-claude-provider.sh list
```

**Providers**: Anthropic, Z.ai (GLM), Together AI, OpenRouter, Google Gemini (Pro/Flash/2.5)
**Config**: `claude-providers.json`, `~/.claude/settings.json`, `.env`

---

## Polymorphic Agent Framework

**Location**: `agents/` directory

### Core Components

- **Agent Workflow Coordinator** - Unified orchestration
- **Enhanced Router** - Fuzzy matching, confidence scoring
- **Manifest Injector** - Dynamic context via event bus
- **ONEX Compliance** - 4-node architecture (Effect/Compute/Reducer/Orchestrator)
- **Multi-Agent Coordination** - Parallel execution

### Manifest Injection Flow

1. Agent spawns with correlation ID
2. ManifestInjector queries via Kafka
3. Parallel queries: patterns, infrastructure, models, schemas, debug intelligence
4. Results formatted into manifest
5. Injected into agent prompt
6. Stored in `agent_manifest_injections`

**Manifest includes**: 15,689+ patterns, infrastructure status, AI models, DB schemas, debug intelligence (successful/failed workflows).

### ONEX Architecture

**Node Types**:
- **Effect**: External I/O, APIs (`Node<Name>Effect`)
- **Compute**: Pure transforms (`Node<Name>Compute`)
- **Reducer**: State/persistence (`Node<Name>Reducer`)
- **Orchestrator**: Workflow coordination (`Node<Name>Orchestrator`)

**Registry**: `~/.claude/agent-definitions/` (YAML configs)

**Performance**: >95% routing accuracy, <100ms query, >60% cache hit, <200ms quality gates

```bash
# Commands
ls ~/.claude/agent-definitions/
cat agents/core-requirements.yaml     # 47 mandatory functions
cat agents/quality-gates-spec.yaml    # 23 quality gates
python3 agents/lib/test_manifest_traceability.py
python3 agents/lib/agent_history_browser.py
```

---

## Event Bus Architecture

**Kafka/Redpanda** for distributed intelligence.

### Topics

**Intelligence**: `dev.archon-intelligence.intelligence.code-analysis-{requested,completed,failed}.v1`
**Router**: `agent.routing.{requested,completed,failed}.v1`
**Tracking**: `agent-routing-decisions`, `agent-transformation-events`, `router-performance-metrics`, `agent-actions`
**Optional**: `documentation-changed` (auto-created)

### Performance

- Latency: <5ms publish + <2000ms processing
- Durability: Kafka persistent storage
- Replay: Complete event history
- Fault Tolerance: Services continue on consumer failure
- Scalability: Horizontal via Kafka partitions

---

## Universal Agent Router (Planned)

> **⚠️ STATUS**: Planning phase - Blocked by PR #22
>
> **Docs**: `docs/architecture/UNIVERSAL_AGENT_ROUTER.md`, `docs/planning/ROUTER_IMPLEMENTATION_PLAN.md`

### Overview

Framework-agnostic, multi-protocol routing with GPU acceleration.

**Features**:
- ⚡ 20-50ms GPU routing (vLLM/RTX 5090)
- 💰 $4 per 1M requests vs $3000 baseline (99.87% savings)
- 🎯 60-70% cache hit rate (Valkey)
- 🌐 Multi-protocol: HTTP, gRPC, Kafka, WebSocket
- 🏗️ Framework-agnostic: Claude Code, LangChain, AutoGPT, CrewAI

### Multi-Tier Architecture

```
TIER 1: VALKEY CACHE    → 60-70% hit, <1ms
TIER 2: vLLM GPU        → 25-35%, 20-50ms
TIER 3: FUZZY FALLBACK  → 3-5%, 5-10ms
TIER 4: REMOTE LLM      → <5%, 200-500ms
Weighted Average: ~36ms
```

### Implementation

**Blocked by**: PR #22 (observability, type-safe config, Docker consolidation, Kafka patterns)

**Phases**:
1. Foundation (Week 1): HTTP API, Valkey, fuzzy fallback
2. GPU Acceleration (Week 2): vLLM integration, 4-tier cascade
3. Multi-Protocol (Week 3): gRPC, Kafka, WebSocket, framework adapters
4. Observability (Week 4): Prometheus, Grafana, OpenTelemetry

**Config**: `config/universal_router.yaml.example` (200+ options)

**Monitoring** (post-launch): 5 Grafana dashboards, Prometheus metrics, alerting

---

## Troubleshooting

| Issue | Quick Fix |
|-------|-----------|
| Agent name "unknown" | Set `AGENT_NAME` env var |
| 0 patterns discovered | Verify Qdrant collections: `curl http://localhost:6333/collections` |
| Long query times | Check Qdrant performance, reduce pattern limit |
| DB connection failed | `source .env`, verify `POSTGRES_PASSWORD` |
| Intelligence unavailable | `docker start archon-intelligence` |

### Quick Verification

```bash
./scripts/health_check.sh
curl http://localhost:6333/collections
curl http://localhost:8053/health
source .env && psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT 1"
```

---

## Quick Reference

### Credentials
**⚠️ Always source `.env`**: `source .env` (loads `POSTGRES_PASSWORD`)

### Service URLs
- Intelligence: `http://localhost:8053/health`, `http://localhost:6333/collections`
- Infrastructure: `http://localhost:8080` (Kafka), `postgresql://192.168.86.200:5436/omninode_bridge`

### Common Commands

```bash
# Configuration
./scripts/validate-env.sh .env

# Health & monitoring
./scripts/health_check.sh
./scripts/test_system_functionality.sh
python3 agents/lib/agent_history_browser.py --agent <name>

# Services (docker-compose)
cd deployment && docker-compose up -d
cd deployment && docker-compose restart app
cd deployment && docker-compose logs -f app

# Services (docker CLI)
docker restart archon-intelligence
docker logs -f omniclaude_archon_router_consumer

# Database
source .env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}

# Provider switching
./toggle-claude-provider.sh gemini-flash

# Testing
python3 agents/services/test_router_service.py -v

# Configuration (Pydantic Settings)
python -c "from config import settings; settings.log_configuration()"
```

### Key Files
- **Config**: `.env`, `config/settings.py`, `config/README.md`
- **Deployment**: `deployment/docker-compose.yml`, `deployment/README.md`
- **Intelligence**: `agents/lib/manifest_injector.py`, `agents/lib/routing_event_client.py`
- **Docs**: `docs/observability/`, `docs/configuration/`, `SECURITY_KEY_ROTATION.md`

### Performance Targets
| Metric | Target | Critical |
|--------|--------|----------|
| Manifest query | <2000ms | >5000ms |
| Routing | <10ms | >100ms |
| Intelligence availability | >95% | <80% |

---

## Security

1. Never commit secrets (API keys, passwords)
2. Never hardcode passwords - use `<set_in_env>` placeholders
3. Use `.env.example` as template
4. Rotate keys regularly (30-90 days)
5. Separate dev/prod credentials
6. Enable IP restrictions and usage quotas
7. Monitor API/DB access
8. Change default passwords in production
9. Use environment variables for sensitive values

**See** `SECURITY_KEY_ROTATION.md` for key management procedures.

---

## Notes

- Requires `jq`, `psql`, `kafkacat`/`kcat` (optional but recommended)
- Agent framework requires ONEX compliance
- Quality gates: <200ms execution target
- All services communicate via Kafka event bus
- Complete observability with correlation ID tracking
- 15,689+ patterns from Qdrant (archon_vectors + code_generation_patterns)
- 34 database tables with complete agent history
- Router: 7-8ms routing, 100+ req/s throughput
- **Phase 2 Complete**: Type-safe config (Pydantic Settings), consolidated Docker Compose, external network references, environment validation

---

**Last Updated**: 2025-11-10
**Version**: 2.3.1
**Intelligence**: Event-driven via Kafka
**Router**: Event-based (Kafka consumer)
**Configuration**: Pydantic Settings (ADR-001)
**Docker**: Consolidated with profiles
**Patterns**: 15,689+ (archon_vectors: 7,118 | code_generation_patterns: 8,571)
**Database**: 34 tables
**Performance**: 7-8ms routing, <500ms total latency
