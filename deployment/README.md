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
