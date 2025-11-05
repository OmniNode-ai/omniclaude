# Docker Compose Quick Start

## TL;DR

```bash
# Setup (current single-environment configuration)
cp .env.example .env
nano .env  # Set passwords and API keys
./scripts/validate-env.sh .env
docker-compose up -d

# Future: For multiple environments (when .env.dev, .env.test, .env.prod are added):
# cp .env.example .env.dev
# nano .env.dev
# docker-compose --env-file .env.dev up -d
```

## Required Configuration

Before first run, set these in your `.env` file:

```bash
# MUST CHANGE
POSTGRES_PASSWORD="your-secure-password"
APP_POSTGRES_PASSWORD="your-app-db-password"
SECRET_KEY="$(openssl rand -base64 32)"
GRAFANA_ADMIN_PASSWORD="your-grafana-password"

# VERIFY these match your infrastructure
KAFKA_BOOTSTRAP_SERVERS="192.168.86.200:29092"
POSTGRES_HOST="192.168.86.200"
```

## Common Commands

```bash
# Start services (uses .env automatically)
docker-compose up -d

# View logs
docker-compose logs -f app

# Stop services
docker-compose down

# Restart single service
docker-compose restart app

# Rebuild and restart
docker-compose up -d --build app

# Check status
docker-compose ps

# Validate configuration
./scripts/validate-env.sh .env
```

## Current Configuration

**Single Environment Setup** (current):
- Kafka: Remote (192.168.86.200:29092)
- PostgreSQL: Remote (192.168.86.200:5436)
- Monitoring: Optional (--profile monitoring)
- Log Level: Configurable in `.env`

**Future: Multi-Environment Support** (when .env.dev, .env.test, .env.prod are added):

| Feature | Development | Test | Production |
|---------|-------------|------|------------|
| Kafka | Remote (192.168.86.200) | Local (redpanda) | Configure |
| PostgreSQL | Remote (192.168.86.200) | Local (postgres) | Configure |
| Monitoring | Full stack | Minimal | Full stack |
| Resources | Medium | Low | High |
| Log Level | info | DEBUG | warning |

## Troubleshooting

```bash
# Validation failed?
./scripts/validate-env.sh .env

# Service won't start?
docker-compose config

# Database connection issues?
source .env && psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}

# View service logs
docker-compose logs -f app

# View full documentation
cat deployment/README.md
```

## Files

**Current**:
- `.env.example` - Environment template (copy to `.env`)
- `.env` - Your local configuration (gitignored)
- `deployment/docker-compose.yml` - Consolidated compose
- `deployment/README.md` - Full documentation
- `scripts/validate-env.sh` - Configuration validator

**Future** (for multi-environment support):
- `.env.dev`, `.env.test`, `.env.prod` - Environment-specific templates

## Security Checklist

- [ ] Copy `.env.example` to `.env`
- [ ] Change all passwords from placeholders
- [ ] Generate strong `SECRET_KEY` (use `openssl rand -base64 32`)
- [ ] Never commit `.env` to git (already in .gitignore)
- [ ] Validate with `./scripts/validate-env.sh .env`
- [ ] Use separate credentials per environment (when multi-env is needed)

## Help

Full documentation: `deployment/README.md`
Summary: `DOCKER_COMPOSE_CONSOLIDATION_SUMMARY.md`
