# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **📚 Specialized Documentation:**
> - **Shared Infrastructure** → `~/.claude/CLAUDE.md` (PostgreSQL, Kafka, remote server topology)
> - **Type-Safe Configuration** → `config/README.md` (Pydantic Settings, 90+ validated variables)
> - **Docker Deployment** → `deployment/README.md` (docker-compose, environment setup)
> - **Agent Framework** → `agents/polymorphic-agent.md` (ONEX compliance)
> - **Testing** → `docs/testing/INTEGRATION_TESTS_GUIDE.md` (CI/CD, integration tests)
> - **Security** → `SECURITY_KEY_ROTATION.md` (API key management)

## Overview

OmniClaude is a comprehensive toolkit for enhancing Claude Code capabilities with:
- **Multi-provider AI model support** with dynamic switching
- **Intelligence infrastructure** for real-time pattern discovery
- **Event-driven architecture** using Kafka for distributed intelligence
- **Polymorphic agent framework** with ONEX compliance
- **Complete observability** with manifest injection traceability

---

## Intelligence Infrastructure

**Event-Driven Intelligence**:
- **Kafka Event Bus** (192.168.86.200:9092) - Central message broker
- **Request-Response Pattern** - Async intelligence queries with correlation tracking
- **Graceful Degradation** - Falls back to minimal manifest on timeout

**Key Services**:

| Service | Purpose | Port |
|---------|---------|------|
| archon-intelligence | Intelligence coordinator | 8053 |
| archon-qdrant | Vector database (120+ patterns) | 6333 |
| archon-bridge | PostgreSQL connector (34 tables) | 5436 |
| archon-search | Full-text/semantic search | 8054 |
| archon-memgraph | Graph database | 7687 |

**Manifest Intelligence System**:
- Queries Qdrant, Memgraph, PostgreSQL via event bus
- Parallel query execution (<2000ms total)
- 120+ patterns from Qdrant (execution_patterns + code_patterns)
- Complete traceability with correlation IDs

**Database Schemas** (34 tables in `omninode_bridge`):
- `agent_manifest_injections` - Complete manifest snapshots
- `agent_routing_decisions` - Agent selection with confidence scores
- `agent_transformation_events` - Polymorphic transformations
- `router_performance_metrics` - Routing analytics

---

## Environment Configuration

**Quick Setup**:
```bash
cp .env.example .env
nano .env
source .env
./scripts/validate-env.sh .env
```

**Critical Variables**:
- **PostgreSQL**: `POSTGRES_HOST=192.168.86.200`, `POSTGRES_PORT=5436`, `POSTGRES_PASSWORD` (in .env)
- **Kafka**: `KAFKA_BOOTSTRAP_SERVERS` (omninode-bridge-redpanda:9092 for Docker, 192.168.86.200:29092 for host)
- **AI Providers**: `GEMINI_API_KEY`, `ZAI_API_KEY`, `OPENAI_API_KEY`
- **Qdrant**: `QDRANT_URL=http://localhost:6333`

**⚠️ SECURITY**: Always use `source .env` before running psql/kafka commands. Never hardcode passwords.

**Type-Safe Configuration** (Pydantic Settings):
```python
from config import settings
dsn = settings.get_postgres_dsn()  # Type-safe, validated
errors = settings.validate_required_services()  # Startup validation
```

See `config/README.md` for complete configuration reference.

---

## Deployment

**Location**: `deployment/docker-compose.yml`

**Quick Start**:
```bash
# From deployment directory
cd deployment && docker-compose up -d

# OR from project root
docker-compose -f deployment/docker-compose.yml up -d

# With monitoring
cd deployment && docker-compose --profile monitoring up -d
```

**Service Profiles**:
- **default**: Core services (app, routing-adapter, consumers, postgres, valkey)
- **monitoring**: Add prometheus, grafana, jaeger, otel-collector
- **test**: Add test infrastructure

**Key Services**:
- `app` (8000) - Main FastAPI application
- `routing-adapter` (8070) - Agent routing
- `postgres` (5432) - Application database
- `valkey` (6379) - Cache layer

**Network Architecture**:
- External networks: `omninode-bridge-network` (cross-repo communication)
- Local networks: `app_network`, `monitoring_network`

See `deployment/README.md` for complete deployment guide.

---

## CI/CD & Automated Testing

**4 Integration Test Suites**:
1. Database Integration - Schema, operations, UUID handling
2. Kafka Integration - Event bus connectivity
3. Agent Observability - Logging completeness
4. Full Pipeline - End-to-end workflows

**PR Requirements**: Tests must pass, coverage >80%, no schema errors.

**Quick Local Testing**:
```bash
docker-compose -f deployment/docker-compose.yml up -d postgres redis
poetry run pytest -m integration -v --cov
docker-compose -f deployment/docker-compose.yml down
```

See `docs/testing/INTEGRATION_TESTS_GUIDE.md` for complete testing guide.

---

## Diagnostic Tools

**Health Check**:
```bash
./scripts/health_check.sh  # Checks all services, Kafka, Qdrant, PostgreSQL
```

**Agent History Browser**:
```bash
python3 agents/lib/agent_history_browser.py                     # Interactive mode
python3 agents/lib/agent_history_browser.py --agent test-agent  # Filter by agent
```

**Performance Indicators**:
- Query time: <2000ms excellent | 2000-5000ms acceptable | >5000ms issue
- Agent name "unknown" → Check `AGENT_NAME` env var

---

## Agent Observability & Traceability

Three-layer traceability: routing decisions → manifest injections → execution logs, linked by correlation_id.

**Database Tables**:
- `agent_routing_decisions` - Agent selection with confidence scores
- `agent_manifest_injections` - Complete manifest snapshots
- `agent_execution_logs` - Execution lifecycle

**Usage**:
```python
from agents.lib.agent_execution_logger import log_agent_execution
logger = await log_agent_execution(agent_name="...", user_prompt="...", correlation_id=...)
await logger.progress(stage="...", percent=50)
await logger.complete(status=EnumOperationStatus.SUCCESS, quality_score=0.92)
```

**Analytical Views**:
```sql
SELECT * FROM v_agent_execution_trace WHERE correlation_id = '...';
SELECT * FROM v_manifest_injection_performance ORDER BY avg_query_time_ms DESC;
```

See `docs/observability/` for detailed schemas and debugging guides.

---

## Container Management

**List Containers**:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
docker-compose ps  # OmniClaude services only
```

**Service Management**:
```bash
# Docker Compose (recommended)
cd deployment && docker-compose restart app
cd deployment && docker-compose up -d --build app

# Docker CLI
docker restart archon-intelligence
docker logs -f archon-intelligence
```

**Port Mappings** (Local Services):
- app: 8000 | routing-adapter: 8070 | postgres: 5432 | valkey: 6379
- prometheus: 9090 | grafana: 3000 | jaeger: 16686

**External Services** (192.168.86.101/200):
- archon-intelligence: 8053 | archon-qdrant: 6333 | archon-search: 8055
- Kafka/Redpanda: 29092 (ext) / 9092 (int) | PostgreSQL: 5436

---

## Agent Router Service

Event-driven agent routing via Kafka with ~7-8ms routing time.

**Service**: `archon-router-consumer` (pure Kafka consumer, no HTTP)
**Performance**: 7-8ms routing, <500ms total latency, 100+ req/s throughput

**Kafka Topics**:
- `agent.routing.requested.v1` - Routing requests
- `agent.routing.completed.v1` - Successful routing
- `agent.routing.failed.v1` - Errors

**Usage**:
```python
from agents.lib.routing_event_client import route_via_events
recommendations = await route_via_events(user_request="...", max_recommendations=3)
```

**Management**:
```bash
cd deployment && docker-compose up -d router-consumer
docker logs -f omniclaude_archon_router_consumer
python3 agents/services/test_router_service.py -v
```

---

## Provider Management

**Switch AI Providers**:
```bash
./toggle-claude-provider.sh claude         # Anthropic Claude
./toggle-claude-provider.sh zai            # Z.ai GLM models
./toggle-claude-provider.sh gemini-flash   # Google Gemini Flash
./toggle-claude-provider.sh status         # Check current provider
```

**Configuration Files**:
- `claude-providers.json` - Provider definitions
- `~/.claude/settings.json` - Modified by toggle script
- `.env` - API keys (never commit!)

---

## Polymorphic Agent Framework

**Core Components**:
- **Agent Workflow Coordinator**: Routing, parallel execution, dynamic transformation
- **Enhanced Router System**: Fuzzy matching and confidence scoring
- **Manifest Injector**: Dynamic context via event bus intelligence
- **ONEX Compliance**: 4-node architecture (Effect, Compute, Reducer, Orchestrator)

**Manifest Injection Flow**:
```
1. Agent spawns with correlation ID
2. ManifestInjector queries archon-intelligence via Kafka
3. Parallel queries: patterns, infrastructure, models, schemas, debug_intelligence
4. Results formatted into structured manifest
5. Manifest injected into agent prompt
6. Complete record stored in agent_manifest_injections table
```

**ONEX Node Types**:
- **Effect**: External I/O, APIs, side effects (`Node<Name>Effect`)
- **Compute**: Pure transforms/algorithms (`Node<Name>Compute`)
- **Reducer**: Aggregation, persistence, state (`Node<Name>Reducer`)
- **Orchestrator**: Workflow coordination (`Node<Name>Orchestrator`)

**Development Commands**:
```bash
ls ~/.claude/agent-definitions/                    # View agent configs
python3 agents/lib/test_manifest_traceability.py  # Test manifest injection
python3 agents/lib/agent_history_browser.py        # Browse execution history
```

See `agents/polymorphic-agent.md` for complete framework documentation.

---

## Event Bus Architecture

**Event-Driven Intelligence**:
```
Agent Request → Kafka: intelligence.requests → archon-intelligence-adapter
→ Qdrant + Memgraph + PostgreSQL → Kafka: intelligence.responses → Agent
```

**Key Topics**:
- Intelligence: `dev.archon-intelligence.intelligence.code-analysis-*`
- Router: `agent.routing.requested/completed/failed.v1`
- Tracking: `agent-routing-decisions`, `agent-transformation-events`, `router-performance-metrics`

**Performance**:
- Request-Response Latency: <5ms publish + <2000ms processing
- Event Durability: Kafka persistent storage
- Replay Capability: Complete event history

---

## Universal Agent Router (Planned)

> **⚠️ STATUS**: Planning phase - Blocked by PR #22
>
> Framework-agnostic, multi-protocol routing with GPU-accelerated inference (vLLM on RTX 5090), 4-tier caching (Valkey L1), and 99.87% cost savings vs all-Anthropic baseline.
>
> **Docs**: [`docs/architecture/UNIVERSAL_AGENT_ROUTER.md`](docs/architecture/UNIVERSAL_AGENT_ROUTER.md), [`docs/planning/ROUTER_IMPLEMENTATION_PLAN.md`](docs/planning/ROUTER_IMPLEMENTATION_PLAN.md)

---

## Troubleshooting Guide

| Issue | Quick Fix |
|-------|-----------|
| Agent name "unknown" | Set `AGENT_NAME` env var |
| 0 patterns discovered | Verify Qdrant collections: `curl http://localhost:6333/collections` |
| Long query times (>10s) | Check Qdrant performance, reduce pattern limit |
| DB connection failed | `source .env` and verify `POSTGRES_PASSWORD` |
| Intelligence unavailable | `docker start archon-intelligence` |

**Quick Verification**:
```bash
./scripts/health_check.sh
curl http://localhost:6333/collections
curl http://localhost:8053/health
source .env && psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT 1"
```

---

## Quick Reference

**Configuration**:
```bash
./scripts/validate-env.sh .env                              # Validate environment
python -c "from config import settings; settings.log_configuration()"  # View config
```

**Service Management**:
```bash
cd deployment && docker-compose up -d                       # Start all services
cd deployment && docker-compose restart app                 # Restart service
docker logs -f archon-intelligence                          # View logs
./scripts/health_check.sh                                   # Health check
```

**Database**:
```bash
source .env  # ALWAYS source first
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}
```

**AI Providers**:
```bash
./toggle-claude-provider.sh gemini-flash                    # Switch provider
./toggle-claude-provider.sh status                          # Check current
```

**Testing**:
```bash
poetry run pytest -m integration -v --cov                   # Run integration tests
python3 agents/services/test_router_service.py -v           # Test router
```

**Key Files**:
- Config: `.env`, `config/settings.py`, `config/README.md`
- Deployment: `deployment/docker-compose.yml`, `deployment/README.md`
- Intelligence: `agents/lib/manifest_injector.py`, `agents/lib/routing_event_client.py`
- Docs: `docs/observability/AGENT_TRACEABILITY.md`, `SECURITY_KEY_ROTATION.md`

**Performance Targets**:
- Manifest query: <2000ms (critical: >5000ms)
- Routing: <10ms (critical: >100ms)
- Intelligence availability: >95% (critical: <80%)

---

## Security

**Best Practices**:
1. Never commit secrets (API keys, passwords, tokens)
2. Never hardcode passwords - use `.env` variables
3. Rotate keys every 30-90 days
4. Use separate credentials for dev/prod
5. Enable IP restrictions and usage quotas
6. Monitor API usage regularly

See [SECURITY_KEY_ROTATION.md](SECURITY_KEY_ROTATION.md) for rotation procedures.

---

## Notes

- Requires `jq`, `psql`, `kafkacat`/`kcat` (optional but recommended)
- Agent framework requires ONEX compliance
- All services communicate via Kafka event bus
- Router: 7-8ms routing, 100+ req/s throughput
- Pattern discovery: 120+ patterns from Qdrant
- Database: 34 tables with complete agent execution history
- Type-safe configuration via Pydantic Settings (90+ variables)
- Consolidated Docker Compose with profiles
- External network references for cross-repo communication

---

**Last Updated**: 2025-11-05
**Documentation Version**: 2.3.0
**Intelligence Infrastructure**: Event-driven via Kafka
**Router Architecture**: Event-based (Kafka consumer)
**Configuration Framework**: Pydantic Settings
**Pattern Count**: 120+ (execution_patterns + code_patterns)
**Database Tables**: 34 in omninode_bridge
