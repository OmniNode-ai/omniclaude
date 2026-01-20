# OmniClaude Deployment Guide

This directory contains a consolidated Docker Compose configuration following 12-factor app principles.

## Overview

**Architecture**: Single `docker-compose.yml` with environment configuration via `.env`

**Benefits**:
- ✅ One source of truth for service definitions
- ✅ Configuration via environment variables
- ✅ No hardcoded values
- ✅ Easy to add new environments when needed
- ✅ Follows 12-factor app methodology

## Prerequisites

### Required Tools

**kcat** (Kafka command-line consumer/producer):

kcat is required for Kafka diagnostics, topic inspection, and skills that interact with the event bus.

**Installation**:
- **macOS**: `brew install kcat`
- **Ubuntu/Debian**: `sudo apt-get install kafkacat` (kcat is symlinked as kafkacat)
- **Alpine/Docker**: `apk add kafkacat`
- **From Source**: https://github.com/edenhill/kcat

**Verify Installation**:
```bash
kcat -V
# Expected: kcat - Apache Kafka producer and consumer tool
```

**Note**: Some skills in `skills/_shared/kafka_helper.py` will fail silently if kcat is not installed. The error message will indicate the missing dependency.

### External Dependencies

**⚠️ REQUIRED**: The `omninode_bridge` repository must be running before starting OmniClaude services.

OmniClaude connects to external Docker networks created by `omninode_bridge` for cross-repository communication. Without these networks, Docker Compose will fail to start with "network not found" errors.

#### Verify External Networks Exist

Before starting OmniClaude, verify the required networks are available:

```bash
# Check for required external networks
docker network ls | grep omninode-bridge
```

**Expected output**:
```
<network-id>   omninode-bridge-network                      bridge    local
<network-id>   omninode_bridge_omninode-bridge-network      bridge    local
```

If you see both networks listed, you're ready to start OmniClaude services. If networks are missing, see troubleshooting below.

#### Required Networks

| Network Name | Created By | Purpose |
|--------------|------------|---------|
| `omninode-bridge-network` | omninode_bridge | Primary cross-repository communication |
| `omninode_bridge_omninode-bridge-network` | omninode_bridge | Secondary cross-repository network |

These networks enable:
- ✅ Native service-to-service connectivity across repositories
- ✅ Direct access to shared PostgreSQL and Kafka/Redpanda
- ✅ Automatic DNS resolution within Docker network
- ✅ No manual `/etc/hosts` configuration required (for Docker services)

### Troubleshooting: "Network Not Found"

#### Problem: Docker Compose Fails with Network Error

If you see this error when running `docker-compose up`:

```
ERROR: Network omninode-bridge-network declared as external, but could not be found
```

This means the external networks from `omninode_bridge` are not available.

#### Solution: Start omninode_bridge First

**Step 1**: Navigate to omninode_bridge repository and start services:

```bash
# Navigate to omninode_bridge (adjust path as needed)
cd ../omninode_bridge

# Start omninode_bridge services
docker-compose up -d
```

**Step 2**: Verify networks were created:

```bash
# Check that both networks now exist
docker network ls | grep omninode-bridge

# Should show:
# omninode-bridge-network
# omninode_bridge_omninode-bridge-network
```

**Step 3**: Return to OmniClaude and retry:

```bash
# Navigate back to omniclaude deployment
cd ../omniclaude/deployment

# Start services (networks should now be available)
docker-compose up -d
```

#### Alternative: Disable Cross-Repository Communication

If you don't need cross-repository communication and want to run OmniClaude in isolation:

**Option 1**: Comment out external networks in `docker-compose.yml`:

```yaml
# networks:
#   omninode-bridge-network:
#     external: true
#     name: omninode-bridge-network
#   omninode_bridge_omninode-bridge-network:
#     external: true
#     name: omninode_bridge_omninode-bridge-network
```

**Option 2**: Update service network assignments to remove external network references.

**⚠️ Warning**: Disabling external networks means:
- ❌ No access to shared PostgreSQL on 192.168.86.200:5436
- ❌ No access to Kafka/Redpanda event bus
- ❌ Limited agent observability and intelligence features
- ❌ Some services may not function correctly

Only use this approach for isolated testing or development without shared infrastructure.

#### Verify External Network Connectivity

After starting services, verify connectivity to shared infrastructure:

```bash
# Test PostgreSQL connectivity (requires .env to be sourced)
source ../.env
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -c "SELECT 1"

# Test Kafka connectivity (requires kcat)
kcat -L -b 192.168.86.200:29092

# Expected: Connection successful with broker list
```

## Quick Start

### Development Environment (Current Setup)

```bash
# 1. Copy the template
cp ../.env.example ../.env

# 2. Edit with your actual values
nano ../.env
# Set: POSTGRES_PASSWORD, GEMINI_API_KEY, ZAI_API_KEY, etc.

# 3. Start services
docker-compose up -d

# 4. View logs
docker-compose logs -f

# 5. Check status
docker-compose ps

# 6. Stop services
docker-compose down
```

## Architecture

### Current Services

The `docker-compose.yml` defines all OmniClaude services:

**Core Application**:
- `app` (port 8000) - Main FastAPI application
- `routing-adapter` (port 8070) - Agent routing service

**Consumers**:
- `agent-consumer` - Event-driven agent execution
- `router-consumer` - Event-based routing decisions
- `intelligence-consumer` - Intelligence event processing

**Infrastructure**:
- `postgres` (port 5432) - Application database
- `valkey` (port 6379) - Cache layer

**Monitoring Stack** (profile: `monitoring`):
- `prometheus` (port 9090) - Metrics collection
- `grafana` (port 3000) - Visualization
- `jaeger` (port 16686) - Distributed tracing
- `otel-collector` (port 4317/4318) - Telemetry collection

### Shared Infrastructure

OmniClaude connects to **remote shared services** (configured in `.env`):

| Service | Default Location | Purpose |
|---------|------------------|---------|
| **Kafka/Redpanda** | 192.168.86.200:29092 | Event bus |
| **PostgreSQL** | 192.168.86.200:5436 | Shared database (omninode_bridge) |
| **Qdrant** | 192.168.86.101:6333 | Vector database |
| **Memgraph** | 192.168.86.101:7687 | Knowledge graph |

These services are provided by `omninode_bridge` and `omniarchon` repositories.

## Environment Configuration

### PostgreSQL Environment Variable Convention

**IMPORTANT**: This compose file uses **TWO SETS** of PostgreSQL variables with distinct purposes:

#### 1. APP_POSTGRES_* → Local Application Database

Used by: `app`, `postgres` services

```bash
# Local containerized PostgreSQL database for OmniClaude application
APP_POSTGRES_USER=omniclaude
APP_POSTGRES_PASSWORD=<set_in_env>
APP_POSTGRES_DATABASE=omniclaude
APP_POSTGRES_HOST=postgres
APP_POSTGRES_INTERNAL_PORT=5432
```

**Purpose**: Application-specific data storage, runs as a containerized PostgreSQL service within Docker.

#### 2. POSTGRES_* → Shared Bridge Database

Used by: `agent-observability-consumer`, `routing-adapter`, `archon-router-consumer`, `test-runner`

```bash
# Remote shared database for cross-service observability
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<set_in_env>
```

**Purpose**: Cross-service observability, agent routing decisions, manifest injections, and all event-driven intelligence tracking. This database is shared across all OmniNode repositories.

#### Why Two Sets?

- **Local app database** (`APP_POSTGRES_*`): Isolated application data that doesn't need to be shared
- **Shared bridge database** (`POSTGRES_*`): Centralized observability and intelligence data that multiple services and repositories need to access

This separation ensures:
- ✅ Clear separation of concerns
- ✅ Application data isolation
- ✅ Shared observability across all OmniNode services
- ✅ No naming conflicts between local and shared databases

### Required Variables

See `../.env.example` for complete list. Key variables:

```bash
# Infrastructure (remote services)
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<set_in_env>
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092

# Local application database
APP_POSTGRES_USER=omniclaude
APP_POSTGRES_PASSWORD=<set_in_env>
APP_POSTGRES_DATABASE=omniclaude

# API Keys (get from provider dashboards)
GEMINI_API_KEY=your_key_here
ZAI_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here

# Application
APP_ENV=development
LOG_LEVEL=INFO
```

### Validation

Before deploying, validate your environment:

```bash
../scripts/validate-env.sh ../.env
```

This checks:
- ✅ All required variables are set
- ✅ No placeholder values remain
- ✅ Password strength requirements
- ✅ URL format validation
- ✅ Port number ranges

## Database Architecture

OmniClaude uses **two separate PostgreSQL databases** with distinct purposes and connection patterns.

### Overview

| Database Type | Environment Variables | Purpose | Location |
|---------------|----------------------|---------|----------|
| **Local Application Database** | `APP_POSTGRES_*` | Application-specific data storage | Containerized (postgres service) |
| **Shared Bridge Database** | `POSTGRES_*` | Cross-service observability & intelligence | Remote (192.168.86.200:5436) |

### 1. Local Application Database (APP_POSTGRES_*)

**Purpose**: Application-specific data for OmniClaude services

**Configuration Variables**:
```bash
APP_POSTGRES_HOST=postgres
APP_POSTGRES_PORT=5432
APP_POSTGRES_USER=omniclaude
APP_POSTGRES_PASSWORD=<set_in_env>
APP_POSTGRES_DATABASE=omniclaude
APP_POSTGRES_INTERNAL_PORT=5432
```

**Services Using This Database**:
- `app` - Main FastAPI application
- `postgres` - Local PostgreSQL container

**Connection Pattern**:
```bash
# From within Docker network
postgresql://omniclaude:${APP_POSTGRES_PASSWORD}@postgres:5432/omniclaude

# From host (after exposing port)
postgresql://omniclaude:${APP_POSTGRES_PASSWORD}@localhost:5432/omniclaude
```

**Example Access**:
```bash
# Connect to local app database
docker-compose exec postgres psql -U omniclaude -d omniclaude

# Run query
docker-compose exec postgres psql -U omniclaude -d omniclaude \
  -c "SELECT * FROM users LIMIT 10;"
```

### 2. Shared Bridge Database (POSTGRES_*)

**Purpose**: Cross-repository observability, agent routing, manifest injections, and event-driven intelligence tracking

**Configuration Variables**:
```bash
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<set_in_env>
POSTGRES_DATABASE=omninode_bridge
```

**Services Using This Database**:
- `routing-adapter` - Agent routing service
- `agent-observability-consumer` - Observability event consumer
- `archon-router-consumer` - Event-based routing consumer
- `test-runner` - Integration test runner
- External services from other repositories (omniarchon, omninode_bridge)

**Key Tables** (34+ total):
- `agent_routing_decisions` - Agent selection with confidence scores
- `agent_manifest_injections` - Complete manifest snapshots
- `agent_execution_logs` - Agent lifecycle tracking
- `agent_transformation_events` - Polymorphic transformations
- `workflow_steps` - Workflow execution history
- `llm_calls` - LLM API call tracking
- `router_performance_metrics` - Routing analytics
- `error_events` / `success_events` - Event tracking

**Connection Pattern**:
```bash
# From within Docker network (using external network reference)
postgresql://postgres:${POSTGRES_PASSWORD}@192.168.86.200:5436/omninode_bridge

# From host scripts
postgresql://postgres:${POSTGRES_PASSWORD}@192.168.86.200:5436/omninode_bridge
```

**Example Access**:
```bash
# Connect to shared bridge database (requires .env)
source ../.env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}

# Query agent routing decisions
source ../.env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT * FROM agent_routing_decisions ORDER BY created_at DESC LIMIT 10;"

# Query manifest injections
source ../.env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT correlation_id, agent_name, query_time_ms FROM agent_manifest_injections ORDER BY created_at DESC LIMIT 5;"
```

### Why Two Databases?

**Separation of Concerns**:
- **Local app database** (`APP_POSTGRES_*`) contains application-specific data that doesn't need to be shared across services or repositories
- **Shared bridge database** (`POSTGRES_*`) provides centralized observability and intelligence data accessible by multiple services and repositories

**Benefits**:

| Benefit | Description |
|---------|-------------|
| **Isolation** | Application failures don't affect observability data |
| **Scalability** | Shared database can be independently scaled and optimized |
| **Reliability** | Local database issues don't impact cross-service intelligence |
| **Security** | Different access patterns and security requirements |
| **Performance** | Optimized connection pools for different workloads |
| **Data Sovereignty** | Clear ownership and lifecycle management |

**Example Scenarios**:

- **User Authentication Data** → Local App Database (APP_POSTGRES_*)
  - Reason: Application-specific, no need to share with other repos

- **Agent Routing Decisions** → Shared Bridge Database (POSTGRES_*)
  - Reason: Multiple services and repos need to analyze routing patterns

- **API Request Logs** → Local App Database (APP_POSTGRES_*)
  - Reason: Application-specific logs

- **Manifest Injections** → Shared Bridge Database (POSTGRES_*)
  - Reason: Cross-repo traceability and debugging

### Service-to-Database Mapping

```
┌──────────────────────────────────────────────┐
│         LOCAL APP DATABASE                   │
│         (APP_POSTGRES_*)                     │
│                                              │
│  Services:                                   │
│  • app (FastAPI application)                 │
│  • postgres (database container)             │
│                                              │
│  Data:                                       │
│  • Application state                         │
│  • User data                                 │
│  • API logs                                  │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│      SHARED BRIDGE DATABASE                  │
│      (POSTGRES_*)                            │
│      Location: 192.168.86.200:5436           │
│                                              │
│  Services:                                   │
│  • routing-adapter                           │
│  • agent-observability-consumer              │
│  • archon-router-consumer                    │
│  • test-runner                               │
│  • External services (other repos)           │
│                                              │
│  Data:                                       │
│  • Agent routing decisions (34+ tables)      │
│  • Manifest injections                       │
│  • Execution logs                            │
│  • Performance metrics                       │
│  • Cross-repo intelligence                   │
└──────────────────────────────────────────────┘
```

### Configuration Best Practices

1. **Use Distinct Passwords**: Never reuse passwords between local and shared databases
2. **Source .env Before Queries**: Always run `source ../.env` before database operations
3. **Verify Connection Variables**: Use `echo ${POSTGRES_HOST}` to verify loaded values
4. **Test Connectivity**: Use health checks to verify both databases are accessible
5. **Monitor Separately**: Set up separate monitoring for each database type

### Troubleshooting Database Connectivity

**Issue: Cannot connect to shared database**
```bash
# Verify environment variables are loaded
source ../.env
echo "Host: ${POSTGRES_HOST}"
echo "Port: ${POSTGRES_PORT}"
echo "Database: ${POSTGRES_DATABASE}"
echo "Password set: ${POSTGRES_PASSWORD:+YES}"

# Test connectivity
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -c "SELECT 1"
```

**Issue: Service connecting to wrong database**
```bash
# Check which database your service is configured to use
docker-compose exec <service-name> env | grep POSTGRES

# Services using APP_POSTGRES_* should show "omniclaude"
# Services using POSTGRES_* should show "omninode_bridge"
```

**Issue: Test runner fails with database error**
```bash
# Test runner uses POSTGRES_* (shared database)
# Verify shared database credentials in .env
source ../.env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT 1"

# Check if omninode_bridge database exists
source ../.env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -c "\l" | grep omninode_bridge
```

**Issue: App cannot connect to local database**
```bash
# Verify postgres container is running
docker-compose ps postgres

# Check postgres logs
docker-compose logs postgres

# Connect directly to postgres container
docker-compose exec postgres psql -U omniclaude -d omniclaude -c "SELECT 1"
```

## Service Profiles

The compose file supports profiles for selective service startup:

```bash
# Default: Core services only
docker-compose up -d

# Include monitoring stack
docker-compose --profile monitoring up -d

# Include test infrastructure (when needed)
docker-compose --profile test up -d
```

## Adding More Environments

When you need test/prod environments:

### 1. Create Environment-Specific .env File

```bash
# For test environment
cp ../.env.example ../.env.test
nano ../.env.test
# Update with test-specific values
```

### 2. Deploy with Specific Environment

```bash
docker-compose --env-file ../.env.test up -d --profile test
```

### 3. Update .gitignore

`.gitignore` already excludes `.env.*` files (only `.env.example` is tracked).

## Common Tasks

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f app

# Last 100 lines
docker-compose logs --tail 100 app

# Search logs
docker-compose logs app | grep ERROR
```

### Restart Services

```bash
# Restart specific service
docker-compose restart app

# Rebuild and restart (after code changes)
docker-compose up -d --build app

# Restart all services
docker-compose restart
```

### Database Access

```bash
# Connect to LOCAL application database (APP_POSTGRES_*)
docker-compose exec postgres psql -U omniclaude -d omniclaude

# Connect to SHARED bridge database (POSTGRES_*)
# Using .env variables - requires POSTGRES_PASSWORD to be set
source ../.env
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE

# Example: Query agent routing decisions from shared database
source ../.env
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE \
  -c "SELECT * FROM agent_routing_decisions ORDER BY created_at DESC LIMIT 10;"
```

### Kafka Operations

```bash
# List topics (requires kcat)
kcat -L -b 192.168.86.200:29092

# Consume events
kcat -C -b 192.168.86.200:29092 -t agent.routing.requested.v1
```

### Health Checks

```bash
# Run comprehensive health check
../scripts/health_check.sh

# Check specific service
curl http://localhost:8000/health
curl http://localhost:8070/health

# Check all services
docker-compose ps
```

## Troubleshooting

### Services Won't Start

```bash
# Check logs for errors
docker-compose logs

# Verify environment variables
cat ../.env | grep -v "^#" | grep "="

# Validate configuration
../scripts/validate-env.sh ../.env

# Check for port conflicts
docker-compose ps
lsof -i :8000  # Check if port is in use
```

### Cannot Connect to Remote Services

```bash
# Test Kafka connectivity
kcat -L -b 192.168.86.200:29092

# Test PostgreSQL connectivity
source ../.env
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -c "SELECT 1"

# Check /etc/hosts entries
grep omninode /etc/hosts
# Should have: 192.168.86.200 omninode-bridge-redpanda
```

### Service Keeps Restarting

```bash
# Check logs for crash reason
docker-compose logs --tail 100 <service-name>

# Check resource usage
docker stats

# Verify dependencies are running
docker-compose ps
```

### Database Issues

```bash
# Reset application database
docker-compose down -v  # WARNING: Deletes all data
docker-compose up -d

# Check PostgreSQL logs
docker-compose logs postgres
```

## Production Considerations

When deploying to production:

1. **Security**:
   - Change ALL default passwords
   - Use strong passwords (20+ chars)
   - Enable TLS/SSL for database connections
   - Restrict network access via firewall
   - Use secrets management (Vault, etc.)

2. **Resources**:
   - Set resource limits in compose file
   - Monitor memory/CPU usage
   - Scale horizontally for high load

3. **Monitoring**:
   - Enable monitoring profile
   - Configure alerts in Grafana
   - Set up log aggregation
   - Monitor disk usage

4. **Backups**:
   - Regular database backups
   - Backup environment configuration
   - Test restore procedures

5. **Updates**:
   - Use versioned Docker images (not `latest`)
   - Test updates in staging first
   - Have rollback plan

## Network Architecture

```
┌─────────────────────────────────────────────┐
│           LOCAL MACHINE                      │
│  ┌──────────────────────────────────────┐   │
│  │  Docker Network: app-network         │   │
│  │  ┌────────┐  ┌────────┐  ┌────────┐ │   │
│  │  │  app   │  │routing │  │postgres│ │   │
│  │  │  :8000 │  │ :8070  │  │ :5432  │ │   │
│  │  └────────┘  └────────┘  └────────┘ │   │
│  └──────────────────────────────────────┘   │
│                    │                         │
│                    │ Network                 │
│                    ↓                         │
└─────────────────────────────────────────────┘
                     │
                     │
┌─────────────────────────────────────────────┐
│     REMOTE SERVER (192.168.86.200)          │
│  ┌──────────────────────────────────────┐   │
│  │  Kafka/Redpanda (29092)              │   │
│  │  PostgreSQL (5436)                   │   │
│  │  Qdrant (6333)                       │   │
│  │  Memgraph (7687)                     │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

## References

- **Configuration**: See `../.env.example` for all variables
- **Security**: See `../SECURITY_KEY_ROTATION.md` for API key management
- **Architecture**: See `../CLAUDE.md` for system architecture
- **Health Monitoring**: Run `../scripts/health_check.sh`

## Support

For issues:
1. Check logs: `docker-compose logs -f`
2. Run health check: `../scripts/health_check.sh`
3. Validate config: `../scripts/validate-env.sh ../.env`
4. Review this guide

---

**Last Updated**: 2025-11-05
**Docker Compose Version**: 3.8
**Services**: 11 (6 core + 5 monitoring)
