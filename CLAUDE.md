# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **📋 Documentation Restructured (Phase 2)**: This file was reorganized for clarity and enhanced with new infrastructure sections.
>
> **Specialized Documentation**:
> - **Shared Infrastructure** → `~/.claude/CLAUDE.md` (PostgreSQL, Kafka, remote server topology)
> - **Type-Safe Configuration** → `config/README.md` (Pydantic Settings framework, 90+ validated variables)
> - **Docker Deployment** → `deployment/README.md` (Consolidated docker-compose, environment setup)
> - **Agent Framework** → `agents/polymorphic-agent.md` (ONEX compliance, mandatory functions)
> - **Memory Management** → `docs/guides/MEMORY_MANAGEMENT_USER_GUIDE.md` (Hook-based persistent context)
> - **Test Coverage** → `TEST_COVERAGE_PLAN.md` (Testing strategy and plans)
> - **Security** → `SECURITY_KEY_ROTATION.md` (API key management and rotation)
>
> **Recent Infrastructure Changes (Phase 2)**:
> - ✅ Type-safe configuration framework with Pydantic Settings
> - ✅ Consolidated Docker Compose (single file with profiles)
> - ✅ External network references for cross-repo communication
> - ✅ Simplified environment configuration (.env approach)
> - ✅ Environment validation script for safety
> - ✅ **NEW**: Hook-based memory management with intent-driven retrieval
> - ✅ **NEW**: Integration with Anthropic's Context Management API Beta
> - ✅ **NEW**: Cross-session persistent context (75-80% token savings)

> **📚 Shared Infrastructure**: For common OmniNode infrastructure (PostgreSQL, Kafka/Redpanda, remote server topology, Docker networking, environment variables), see **`~/.claude/CLAUDE.md`**. This file contains OmniClaude-specific architecture, agents, and services only.

## Overview

OmniClaude is a comprehensive toolkit for enhancing Claude Code capabilities with:
- **Multi-provider AI model support** with dynamic switching
- **Intelligence infrastructure** for real-time pattern discovery
- **Event-driven architecture** using Kafka for distributed intelligence
- **Polymorphic agent framework** with ONEX compliance
- **Hook-based memory management** with intent-driven context retrieval
- **Complete observability** with manifest injection traceability

## Table of Contents

1. [Intelligence Infrastructure](#intelligence-infrastructure)
2. [Environment Configuration](#environment-configuration)
3. [Type-Safe Configuration Framework](#type-safe-configuration-framework)
4. [Deployment](#deployment)
5. [Diagnostic Tools](#diagnostic-tools)
6. [Agent Observability & Traceability](#agent-observability--traceability)
7. [Container Management](#container-management)
8. [Agent Router Service](#agent-router-service)
9. [Hook-Based Memory Management](#hook-based-memory-management)
10. [Provider Management](#provider-management)
11. [Polymorphic Agent Framework](#polymorphic-agent-framework)
12. [Event Bus Architecture](#event-bus-architecture)
13. [Troubleshooting Guide](#troubleshooting-guide)
14. [Quick Reference](#quick-reference)

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

> **🎯 New in Phase 2**: Type-Safe Configuration Framework with Pydantic Settings
>
> OmniClaude now provides a modern configuration system with 90+ validated variables, automatic type checking, and helper methods. See:
> - [Type-Safe Configuration Framework](#type-safe-configuration-framework) section below
> - [`config/README.md`](config/README.md) for complete documentation
> - **Migration Status**: Legacy `os.getenv()` still supported during gradual migration (82 files identified)

### Quick Setup

All environment variables are configured in `.env` (copy from `.env.example`):

```bash
# Setup
cp .env.example .env
nano .env
source .env

# Validate configuration
./scripts/validate-env.sh .env

# Verify using Pydantic Settings (optional)
python -c "from config import settings; print(settings.validate_required_services())"
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

**🔒 SECURITY WARNING**: Never hardcode passwords in documentation. Always use environment variables from `.env`.

```bash
# REQUIRED: Load credentials from .env first
source .env

# Verify password is loaded
echo "Password loaded: ${POSTGRES_PASSWORD:+YES}"

# Connect to database using environment variables
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}
```

**Connection Details**:
- Host: `192.168.86.200` | Port: `5436` | Database: `omninode_bridge`
- Password in `.env`: `POSTGRES_PASSWORD=<set_in_env>` (NEVER commit real passwords)

**If auth fails**:
1. Verify `.env` exists: `ls -la .env`
2. Verify password is set: `source .env && echo "Password: ${POSTGRES_PASSWORD:+SET}"` (don't echo actual value!)
3. Check `.env` format: `grep POSTGRES_PASSWORD .env` (value should be unquoted)

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
2. **Environment-specific**: `.env.dev`, `.env.test`, `.env.prod` (optional)
3. **Hooks**: `~/.claude/hooks/.env` (legacy)
4. **Agents**: `agents/configs/.env` (agent-specific overrides)

**Environment File Priority** (with Pydantic Settings):
1. System environment variables (highest priority)
2. `.env.{ENVIRONMENT}` file (e.g., `.env.dev`, `.env.prod`)
3. `.env` file (default/fallback)
4. Default values in Settings class (lowest priority)

---

## Type-Safe Configuration Framework

**Location**: `config/` directory

OmniClaude provides a comprehensive type-safe configuration framework using Pydantic Settings, replacing scattered `os.getenv()` calls with validated, documented configuration.

### Overview

**Benefits**:
- ✅ Type safety with IDE autocomplete and type checking
- ✅ Automatic validation on startup with clear error messages
- ✅ Environment file support (`.env`, `.env.dev`, `.env.test`, `.env.prod`)
- ✅ Secure handling of sensitive values (passwords, API keys)
- ✅ Helper methods for DSN generation and validation
- ✅ Legacy compatibility during migration

### Quick Start

```python
from config import settings

# Access configuration with full type safety
print(settings.postgres_host)              # str: "192.168.86.200"
print(settings.postgres_port)              # int: 5436
print(settings.kafka_enable_intelligence)  # bool: True

# Get database connection string
dsn = settings.get_postgres_dsn()
# postgresql://postgres:password@192.168.86.200:5436/omninode_bridge

# Async connection (for asyncpg)
async_dsn = settings.get_postgres_dsn(async_driver=True)
# postgresql+asyncpg://postgres:password@192.168.86.200:5436/omninode_bridge
```

### Configuration Categories

**90+ type-safe configuration variables** organized into:

1. **External Service Discovery** - Archon services (192.168.86.101)
   - `archon_intelligence_url`, `archon_search_url`, `archon_bridge_url`, `archon_mcp_url`

2. **Shared Infrastructure** - PostgreSQL, Kafka/Redpanda (192.168.86.200)
   - `postgres_host`, `postgres_port`, `postgres_database`, `postgres_password`
   - `kafka_bootstrap_servers`, `kafka_enable_intelligence`

3. **AI Provider API Keys**
   - `gemini_api_key`, `zai_api_key`, `openai_api_key`

4. **Local Services** - Qdrant, Valkey
   - `qdrant_host`, `qdrant_port`, `qdrant_url`
   - `valkey_url`, `enable_intelligence_cache`

5. **Feature Flags & Optimization**
   - `enable_pattern_quality_filter`, `min_pattern_quality`
   - `manifest_cache_ttl_seconds`, `cache_ttl_patterns`

### Helper Methods

```python
# PostgreSQL connection strings
settings.get_postgres_dsn(async_driver=False)  # Sync or async driver

# Password handling with legacy aliases
settings.get_effective_postgres_password()     # Handles multiple password env vars

# Kafka bootstrap servers with legacy support
settings.get_effective_kafka_bootstrap_servers()

# Sanitized export (hides passwords/keys)
config_dict = settings.to_dict_sanitized()

# Validation
errors = settings.validate_required_services()
if errors:
    print("Configuration errors:", errors)
    exit(1)

# Logging (with sensitive values masked)
settings.log_configuration(logger)
```

### Migration Guide

**Phase 1: Framework Setup** ✅ (COMPLETE)
- Created `config/settings.py` with comprehensive Settings class
- All 90+ variables from `.env.example` included
- Helper methods and validators implemented

**Phase 2: Gradual Migration** (IN PROGRESS)
- 82 files identified with `os.getenv()` usage
- Migration priorities:
  1. High-frequency files (most `os.getenv()` calls)
  2. Database/Kafka connection files
  3. Service initialization files
  4. Agent framework files

**Migration Pattern**:
```python
# Before (old pattern)
import os
kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))

# After (new pattern)
from config import settings
kafka_servers = settings.kafka_bootstrap_servers  # str, validated
postgres_port = settings.postgres_port            # int, validated
```

### Validation

Validate configuration on application startup:

```python
from config import settings

# Validate required services
errors = settings.validate_required_services()
if errors:
    print("Configuration errors found:")
    for error in errors:
        print(f"  - {error}")
    exit(1)

print("Configuration is valid!")
```

**Validation Script**:
```bash
# Validate .env file
./scripts/validate-env.sh .env

# Checks:
#   ✅ All required variables are set
#   ✅ No placeholder values remain
#   ✅ Password strength requirements
#   ✅ URL format validation
#   ✅ Port number ranges (1-65535)
```

### Documentation

- **Complete reference**: `config/README.md`
- **Environment template**: `.env.example`
- **Type definitions**: `config/settings.py`
- **Security guide**: `SECURITY_KEY_ROTATION.md`

---

## Deployment

**Location**: `deployment/` directory

> **📖 Complete Deployment Guide**: See [`deployment/README.md`](deployment/README.md) for detailed deployment procedures, troubleshooting, and production considerations.

OmniClaude uses a consolidated Docker Compose architecture following 12-factor app principles.

### Docker Compose Architecture

**Single Source of Truth**: One `docker-compose.yml` with environment-based configuration

**Key Changes (Phase 2)**:
- ✅ Consolidated from 2 docker-compose files to 1 unified file
- ✅ Moved all infrastructure to `deployment/` directory
- ✅ All configuration via `.env` (no hardcoded values - 130+ parameterized variables)
- ✅ Simplified environment setup with single `.env.example` template
- ✅ Environment validation script for safety checks

**Benefits**:
- ✅ No hardcoded values (130+ parameterized variables)
- ✅ Configuration via environment variables
- ✅ Profile-based service selection (default, monitoring, test)
- ✅ External network references for cross-repository communication
- ✅ Easy environment switching (.env.dev, .env.test, .env.prod)

### Quick Start

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Edit with your actual values
nano .env

# 3. Validate configuration
./scripts/validate-env.sh .env

# 4. Start services (development)
# Option A: Change to deployment directory
cd deployment && docker-compose up -d

# Option B: Use -f flag from project root
docker-compose -f deployment/docker-compose.yml up -d

# 5. Start with monitoring stack
cd deployment && docker-compose --profile monitoring up -d

# 6. View logs
cd deployment && docker-compose logs -f

# 7. Check status
cd deployment && docker-compose ps

# 8. Stop services
cd deployment && docker-compose down
```

**Note**: The `docker-compose.yml` file is located in the `deployment/` directory. You can either:
- Navigate to `deployment/` directory before running commands, OR
- Use the `-f deployment/docker-compose.yml` flag from the project root

### Service Profiles

```bash
# Default: Core services only (app, routing-adapter, consumers, postgres, valkey)
cd deployment && docker-compose up -d

# Include monitoring stack (prometheus, grafana, jaeger, otel-collector)
cd deployment && docker-compose --profile monitoring up -d

# Include test infrastructure
cd deployment && docker-compose --profile test up -d
```

### Environment-Specific Deployment

```bash
# Development
cd deployment && docker-compose --env-file ../.env.dev up -d

# Test
cd deployment && docker-compose --env-file ../.env.test up -d --profile test

# Production
cd deployment && docker-compose --env-file ../.env.prod up -d
```

### Service Overview

**Core Application**:
- `app` (port 8000) - Main FastAPI application
- `routing-adapter` (port 8070) - Agent routing service

**Consumers**:
- `agent-consumer` - Event-driven agent execution
- `router-consumer` - Event-based routing decisions
- `intelligence-consumer` - Intelligence event processing

**Infrastructure**:
- `postgres` (port 5432) - Application database
- `valkey` (port 6379) - Cache layer (Redis-compatible)

**Monitoring Stack** (profile: `monitoring`):
- `prometheus` (port 9090) - Metrics collection
- `grafana` (port 3000) - Visualization
- `jaeger` (port 16686) - Distributed tracing
- `otel-collector` (port 4317/4318) - Telemetry collection

### Network Architecture

**External Network References**:

OmniClaude connects to external Docker networks created by `omninode_bridge`:

```yaml
networks:
  # Local networks
  app_network:
    driver: bridge
  monitoring_network:
    driver: bridge

  # External networks (created by omninode_bridge)
  omninode-bridge-network:
    external: true
    name: omninode-bridge-network
  omninode_bridge_omninode-bridge-network:
    external: true
    name: omninode_bridge_omninode-bridge-network
```

**Benefits**:
- ✅ Native cross-repository communication
- ✅ No manual `/etc/hosts` configuration required (for Docker services)
- ✅ Direct service-to-service connectivity
- ✅ Shared infrastructure access (PostgreSQL, Kafka/Redpanda)

**Remote Services** (still accessed via IP for host scripts):
- Kafka/Redpanda: `192.168.86.200:29092`
- PostgreSQL: `192.168.86.200:5436`
- Qdrant: `192.168.86.101:6333`
- Memgraph: `192.168.86.101:7687`

### Deployment Documentation

For complete deployment guide, see **`deployment/README.md`**:
- Service configuration
- Environment validation
- Health checks
- Troubleshooting
- Production considerations
- Network architecture diagrams

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

**Deployment Location**: `deployment/docker-compose.yml`

All OmniClaude services are managed through a single consolidated Docker Compose file. See [Deployment](#deployment) section for complete setup.

### List All Containers

```bash
# View all running containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# View OmniClaude services only
docker-compose ps

# View with health status
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "(omniclaude|archon|omninode)"
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

**Using Docker Compose** (recommended):

```bash
# From deployment directory:
cd deployment

# Restart service (preserves container state)
docker-compose restart app

# Stop service
docker-compose stop app

# Start service
docker-compose start app

# Rebuild and restart (required for code changes)
docker-compose up -d --build app

# View service health
docker-compose ps app

# Restart all services
docker-compose restart

# Stop all services
docker-compose down

# Remove all containers and volumes (WARNING: deletes data)
docker-compose down -v

# OR from project root using -f flag:
docker-compose -f deployment/docker-compose.yml restart app
docker-compose -f deployment/docker-compose.yml up -d --build app
```

**Using Docker CLI** (for individual containers):

```bash
# Restart service
docker restart archon-intelligence

# Stop service
docker stop archon-intelligence

# Start service
docker start archon-intelligence

# View service health
docker inspect archon-intelligence --format='{{.State.Health.Status}}'
```

### Port Mappings

**Local OmniClaude Services** (from `deployment/docker-compose.yml`):

| Service | Internal Port | External Port | Protocol |
|---------|---------------|---------------|----------|
| app | 8000 | 8000 | HTTP |
| routing-adapter | 8070 | 8070 | HTTP |
| postgres | 5432 | 5432 | PostgreSQL |
| valkey | 6379 | 6379 | Redis |
| prometheus | 9090 | 9090 | HTTP |
| grafana | 3000 | 3000 | HTTP |
| jaeger | 16686 | 16686 | HTTP |
| otel-collector | 4317/4318 | 4317/4318 | gRPC/HTTP |

**External Services** (from omniarchon/omninode_bridge):

| Service | Host | Port | Protocol |
|---------|------|------|----------|
| archon-intelligence | 192.168.86.101 | 8053 | HTTP |
| archon-qdrant | 192.168.86.101 | 6333 | HTTP |
| archon-search | 192.168.86.101 | 8055 | HTTP |
| archon-bridge | 192.168.86.101 | 8054 | HTTP |
| archon-memgraph | 192.168.86.101 | 7687 | Bolt |
| Kafka/Redpanda | 192.168.86.200 | 29092 (ext) / 9092 (int) | Kafka |
| PostgreSQL (shared) | 192.168.86.200 | 5436 | PostgreSQL |
| Redpanda Admin | 192.168.86.200 | 8080 | HTTP |

### Network Configuration

**Multi-Network Architecture**:

OmniClaude uses multiple Docker networks for isolation and cross-repository communication:

1. **Local Networks** (created by docker-compose):
   - `app_network` - Internal application services
   - `monitoring_network` - Monitoring stack isolation

2. **External Networks** (created by omninode_bridge):
   - `omninode-bridge-network` - Primary cross-repo network
   - `omninode_bridge_omninode-bridge-network` - Secondary cross-repo network

**Service Connectivity**:

```bash
# Within Docker network (container-to-container)
# Use service names:
postgres://postgres:5432
kafka://omninode-bridge-redpanda:9092
http://archon-intelligence:8053

# From host machine (development scripts)
# Use IP addresses:
postgres://192.168.86.200:5436
kafka://192.168.86.200:29092
http://192.168.86.101:8053

# Localhost (local services)
http://localhost:6333  # Qdrant
http://localhost:8000  # App
```

**External Network Benefits**:
- ✅ No manual `/etc/hosts` configuration for Docker services
- ✅ Native service discovery across repositories
- ✅ Direct connectivity to shared PostgreSQL and Kafka
- ✅ Automatic DNS resolution within Docker network

**Network Inspection**:

```bash
# List all networks
docker network ls

# Inspect network details
docker network inspect omninode-bridge-network

# View which services are connected
docker network inspect omninode-bridge-network --format='{{range .Containers}}{{.Name}} {{end}}'
```

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
# Manage service (from project root)
cd deployment && docker-compose up -d router-consumer
docker restart omniclaude_archon_router_consumer
docker logs -f omniclaude_archon_router_consumer

# Alternative: use -f flag from project root
docker-compose -f deployment/docker-compose.yml up -d router-consumer

# Query routing decisions (using environment variables)
source .env && psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
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

## Hook-Based Memory Management

OmniClaude provides an intelligent memory management system that runs through Claude Code hooks, giving Claude persistent context across sessions without requiring agent orchestration.

### Overview

**Key Features**:
- **Intent-Driven Retrieval**: LLM-based intent extraction with 75-80% token savings
- **Cross-Session Persistence**: Memory survives Claude Code restarts
- **Real-Time Updates**: Hooks capture execution patterns, file changes, and workspace state
- **Smart Context Injection**: Relevant memories automatically injected into prompts
- **Graceful Degradation**: Falls back to minimal context on errors

**Integration with Anthropic's Context Management API**:
- Beta header: `anthropic-beta: context-management-2025-06-27`
- Context Editing: `clear_tool_uses_20250919` (automatic stale context cleanup)
- Memory Tool: `memory_20250818` (file-based persistent storage)
- 39% performance improvement over baseline

### Architecture

**Memory Client** (`claude_hooks/lib/memory_client.py`):
```python
from claude_hooks.lib.memory_client import get_memory_client

memory = get_memory_client()

# Store memory
await memory.store_memory(
    key="jwt_implementation",
    value={"pattern": "Bearer token", "location": "auth.py"},
    category="workspace",
    metadata={"updated_by": "user"}
)

# Retrieve memory
jwt_info = await memory.get_memory("jwt_implementation", "workspace")

# Update memory (deep merge for dicts)
await memory.update_memory("jwt_implementation", {"status": "complete"}, "workspace")
```

**Intent Extractor** (`claude_hooks/lib/intent_extractor.py`):
```python
from claude_hooks.lib.intent_extractor import extract_intent

# Extract structured intent from prompt
intent = await extract_intent("Help me implement JWT authentication in auth.py")

# Results:
# - task_type: "authentication"
# - entities: ["JWT", "auth.py"]
# - operations: ["implement"]
# - confidence: 0.9 (LLM) or 0.7 (keyword fallback)
```

### Memory Categories

Memory is organized into 6 categories:

| Category | Purpose | Examples |
|----------|---------|----------|
| **workspace** | Project context, file information | Current branch, modified files, file dependencies |
| **intelligence** | Agent capabilities, patterns | Available agents, ONEX patterns, routing decisions |
| **execution_history** | Tool execution records | Successful Read operations, failed Edit attempts |
| **patterns** | Success/failure patterns | JWT auth implementations, database connection patterns |
| **routing** | Agent routing decisions | Confidence scores, routing history |
| **workspace_events** | File change events | File created/modified/deleted timestamps |

**Storage Location**: `~/.claude/memory/{category}/{key}.json`

### Hook Integration

**Three Hooks Working Together**:

1. **pre-prompt-submit** (Blocking, <100ms):
   - Extracts intent from user prompt
   - Queries relevant memories based on intent
   - Ranks memories by relevance with token budget
   - Injects context into prompt before submission

2. **post-tool-use** (Non-blocking, <50ms):
   - Captures tool execution results
   - Learns success/failure patterns
   - Tracks tool usage sequences
   - Updates execution history

3. **workspace-change** (Background, <20ms/file):
   - Monitors file changes (created/modified/deleted)
   - Analyzes file types and dependencies
   - Updates project context
   - Tracks change history

**Hook Flow Example**:
```
User: "Implement JWT authentication in auth.py"
  ↓
pre-prompt-submit hook:
  1. Extract intent: task_type="authentication", entities=["JWT", "auth.py"]
  2. Query memory for:
     - workspace/file_context_auth_py
     - patterns/success_patterns_authentication
     - execution_history/auth_py_edits
  3. Rank by relevance (token budget: 5000)
  4. Inject context into prompt
  ↓
Claude receives enhanced prompt with relevant context
  ↓
Claude executes: Read auth.py, Edit auth.py
  ↓
post-tool-use hook:
  1. Record Read success (45ms)
  2. Record Edit success (120ms)
  3. Update success_patterns_authentication
  4. Track tool sequence: Read → Edit (successful pattern)
  ↓
workspace-change hook:
  1. Detect auth.py modified
  2. Analyze dependencies (imports jwt, bcrypt)
  3. Update file context
  4. Store change event
```

### Configuration

**Environment Variables** (`.env`):
```bash
# Memory management
ENABLE_MEMORY_CLIENT=true
MEMORY_STORAGE_BACKEND=filesystem
MEMORY_STORAGE_PATH=~/.claude/memory
MEMORY_ENABLE_FALLBACK=true

# Intent extraction
ENABLE_INTENT_EXTRACTION=true
MEMORY_MAX_TOKENS=5000

# Context editing
ENABLE_CONTEXT_EDITING=true
ANTHROPIC_BETA_HEADER=anthropic-beta: context-management-2025-06-27
```

**Pydantic Settings** (`config/settings.py`):
```python
from config import settings

print(settings.enable_memory_client)           # True
print(settings.memory_max_tokens)              # 5000
print(settings.enable_intent_extraction)       # True
```

### Usage Examples

**Query Memory Directly**:
```python
from claude_hooks.lib.memory_client import get_memory_client

memory = get_memory_client()

# List all keys in category
keys = await memory.list_memory("workspace")

# List all categories
categories = await memory.list_categories()

# Get workspace state
workspace = await memory.get_memory("workspace_state", "workspace")
print(f"Branch: {workspace['branch']}")
print(f"Modified files: {workspace['modified_files']}")
```

**Analyze Patterns**:
```python
# Get success patterns for authentication tasks
auth_patterns = await memory.get_memory("success_patterns_authentication", "patterns")
print(f"Success rate: {auth_patterns['success_rate']}")
print(f"Common tools: {auth_patterns['common_tools']}")
```

**Review Execution History**:
```python
# Get execution history for specific file
history = await memory.get_memory("execution_history_auth_py", "execution_history")
for execution in history[-5:]:  # Last 5 executions
    print(f"{execution['tool']}: {execution['status']} ({execution['duration_ms']}ms)")
```

### Performance

**Targets**:
- Pre-prompt hook: <100ms overhead
- Post-tool hook: <50ms overhead
- Workspace-change hook: <20ms per file (background)
- Intent extraction (LLM): 100-200ms
- Intent extraction (keyword): 1-5ms
- Token budget compliance: 2-5K tokens (75-80% savings vs. full memory)

**Monitoring**:
```bash
# View hook performance
python3 agents/lib/agent_history_browser.py --limit 20

# Check memory storage size
du -sh ~/.claude/memory/

# View recent memory operations
ls -lt ~/.claude/memory/*/*.json | head -20
```

### Migration from Correlation Manager

**Automatic Migration**:
```bash
# Dry run (preview migration)
python3 claude_hooks/lib/migrate_to_memory.py --dry-run --verbose

# Perform migration with backup
python3 claude_hooks/lib/migrate_to_memory.py --backup --validate

# Migration converts:
#   ~/.claude/hooks/.state/*.json → ~/.claude/memory/{category}/{key}.json
```

**What Gets Migrated**:
- Correlation context → `routing/correlation_*`
- Agent state → `routing/agent_state_*`
- Generic state → `workspace/legacy_*`

### Troubleshooting

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| No context injected | Check `ENABLE_MEMORY_CLIENT` in `.env` | Set to `true` and restart |
| Slow prompt submission | Check intent extraction performance | Set `ENABLE_INTENT_EXTRACTION=false` for keyword mode |
| Memory not persisting | Check filesystem permissions | `chmod -R 755 ~/.claude/memory` |
| High token usage | Review injected context | Reduce `MEMORY_MAX_TOKENS` (default: 5000) |
| Hook errors | Check hook logs | `cat ~/.claude/hooks/logs/pre_prompt_submit.log` |

**Health Check**:
```bash
# Verify memory client
python3 -c "from claude_hooks.lib.memory_client import get_memory_client; import asyncio; asyncio.run(get_memory_client().list_categories())"

# Verify intent extraction
python3 -c "from claude_hooks.lib.intent_extractor import extract_intent; import asyncio; print(asyncio.run(extract_intent('test prompt')))"

# Run comprehensive tests
pytest tests/claude_hooks/test_memory_client.py -v
pytest tests/claude_hooks/test_intent_extractor.py -v
pytest tests/claude_hooks/test_hooks_integration.py -v
```

### Documentation

- **Architecture**: `docs/planning/HOOK_MEMORY_MANAGEMENT_INTEGRATION.md` (1,494 LOC)
- **Implementation Status**: `docs/planning/HOOK_MEMORY_IMPLEMENTATION_STATUS.md`
- **User Guide**: `docs/guides/MEMORY_MANAGEMENT_USER_GUIDE.md` (created below)
- **API Reference**: Docstrings in `claude_hooks/lib/memory_client.py` and `intent_extractor.py`

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

# Database verification (using environment variables)
source .env && psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT 1"
```

---

## Quick Reference

### 🔑 Credentials
**⚠️ Always source `.env` first**: `source .env` (loads `POSTGRES_PASSWORD` - NEVER hardcode passwords in documentation)

### Service URLs
- Intelligence: `http://localhost:8053/health`, `http://localhost:6333/collections`
- Infrastructure: `http://localhost:8080` (Kafka Admin), `postgresql://192.168.86.200:5436/omninode_bridge`

### Common Commands

```bash
# Configuration validation
./scripts/validate-env.sh .env

# Health & monitoring
./scripts/health_check.sh
python3 agents/lib/agent_history_browser.py --agent <name>

# Service management (docker-compose from deployment/)
cd deployment && docker-compose up -d
cd deployment && docker-compose restart app
cd deployment && docker-compose logs -f app
cd deployment && docker-compose ps

# Alternative: use -f flag from project root
docker-compose -f deployment/docker-compose.yml up -d
docker-compose -f deployment/docker-compose.yml restart app

# Service management (docker CLI)
docker restart archon-intelligence
docker logs -f omniclaude_archon_router_consumer

# Database (ALWAYS source .env first)
source .env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT * FROM v_agent_execution_trace LIMIT 10;"

# Provider switching
./toggle-claude-provider.sh gemini-flash

# Testing
python3 agents/services/test_router_service.py -v

# Configuration (Pydantic Settings)
python -c "from config import settings; settings.log_configuration()"
python -c "from config import settings; print(settings.validate_required_services())"
```

### Key Files
- **Config**: `.env`, `config/settings.py`, `config/README.md`, `claude-providers.json`
- **Deployment**: `deployment/docker-compose.yml`, `deployment/README.md`
- **Intelligence**: `agents/lib/manifest_injector.py`, `agents/lib/routing_event_client.py`
- **Memory Management**: `claude_hooks/lib/memory_client.py`, `claude_hooks/lib/intent_extractor.py`
- **Hooks**: `claude_hooks/pre_prompt_submit.py`, `claude_hooks/post_tool_use.py`, `claude_hooks/workspace_change.py`
- **Docs**: `docs/observability/AGENT_TRACEABILITY.md`, `docs/guides/MEMORY_MANAGEMENT_USER_GUIDE.md`, `SECURITY_KEY_ROTATION.md`
- **Validation**: `scripts/validate-env.sh`

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

1. **Never commit secrets to version control** (API keys, passwords, tokens)
2. **Never hardcode passwords in documentation** - always use placeholders like `<set_in_env>` or `${POSTGRES_PASSWORD}`
3. **Use `.env.example`** as a template for your local `.env` file
4. **Rotate keys and passwords regularly** (every 30-90 days recommended)
5. **Use separate credentials** for development and production
6. **Enable IP restrictions** in provider dashboards and database configs
7. **Set usage quotas** to limit damage from leaks
8. **Monitor API usage** and database access regularly
9. **Change ALL default passwords** immediately in production (especially PostgreSQL)
10. **Use environment variables** for all sensitive configuration values

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
- **Phase 2 Complete**: Type-safe configuration framework (Pydantic Settings) with 90+ validated variables
- **Phase 2 Complete**: Consolidated Docker Compose in `deployment/` directory with environment-based deployment
- **Phase 2 Complete**: External network references for native cross-repository communication
- **Phase 2 Complete**: Simplified environment configuration with single `.env.example` template
- **Phase 2 Complete**: Environment validation script (`scripts/validate-env.sh`) for configuration safety
- **NEW**: Hook-based memory management with intent-driven retrieval (75-80% token savings)
- **NEW**: Cross-session persistent context via filesystem backend (`~/.claude/memory/`)
- **NEW**: Three integrated hooks: pre-prompt-submit, post-tool-use, workspace-change
- **NEW**: Integration with Anthropic's Context Management API Beta (context editing + memory tool)

---

**Last Updated**: 2025-11-06
**Documentation Version**: 2.4.0
**Intelligence Infrastructure**: Event-driven via Kafka
**Router Architecture**: Event-based (Kafka consumer) - Phase 2 complete
**Configuration Framework**: Pydantic Settings - Phase 2 (ADR-001)
**Docker Compose**: Consolidated single file with profiles
**Pattern Count**: 120+ (execution_patterns + code_patterns)
**Database Tables**: 34 in omninode_bridge
**Observability**: Complete traceability with correlation ID tracking
**Router Performance**: 7-8ms routing time, <500ms total latency
**Memory Management**: Hook-based with intent-driven retrieval (75-80% token savings)
**Context Persistence**: Cross-session filesystem backend (~/.claude/memory/)
**Anthropic Integration**: Context Management API Beta (context editing + memory tool)
