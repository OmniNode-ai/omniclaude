# Docker Compose Quick Start

## TL;DR

```bash
# Development
cp .env.dev .env.dev.local
nano .env.dev.local  # Set passwords
docker-compose --env-file .env.dev.local up -d

# Test
cp .env.test .env.test.local
nano .env.test.local  # Set password
docker-compose --env-file .env.test.local up -d --profile test

# Production
cp .env.prod .env.prod.local
nano .env.prod.local  # Configure everything
./scripts/validate-env.sh .env.prod.local
docker-compose --env-file .env.prod.local up -d
```

## Required Configuration

Before first run, set these in your `.env.X.local` file:

```bash
# MUST CHANGE
POSTGRES_PASSWORD="your-secure-password"
APP_POSTGRES_PASSWORD="your-app-db-password"
SECRET_KEY="$(openssl rand -base64 32)"
GRAFANA_ADMIN_PASSWORD="your-grafana-password"

# Verify
KAFKA_BOOTSTRAP_SERVERS="192.168.86.200:29092"  # Dev
POSTGRES_HOST="192.168.86.200"                   # Dev
```

## Common Commands

```bash
# Start services
docker-compose --env-file .env.dev.local up -d

# View logs
docker-compose --env-file .env.dev.local logs -f app

# Stop services
docker-compose --env-file .env.dev.local down

# Restart single service
docker-compose --env-file .env.dev.local restart app

# Rebuild and restart
docker-compose --env-file .env.dev.local up -d --build app

# Check status
docker-compose --env-file .env.dev.local ps

# Validate before deploy
./scripts/validate-env.sh .env.dev.local
```

## Environment Differences

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
./scripts/validate-env.sh .env.dev.local

# Service won't start?
docker-compose --env-file .env.dev.local config

# Database connection issues?
docker exec -it omniclaude_dev_postgres psql -U omniclaude

# View full documentation
cat deployment/README.md
```

## Files

- `.env.dev` - Development template
- `.env.test` - Test template
- `.env.prod` - Production template
- `deployment/docker-compose.yml` - Consolidated compose
- `deployment/README.md` - Full documentation
- `scripts/validate-env.sh` - Configuration validator

## Security Checklist

- [ ] Copy `.env.X` to `.env.X.local`
- [ ] Change all passwords from placeholders
- [ ] Generate strong `SECRET_KEY`
- [ ] Never commit `.env.X.local` to git
- [ ] Validate with `./scripts/validate-env.sh`
- [ ] Use separate credentials per environment

## Help

Full documentation: `deployment/README.md`
Summary: `DOCKER_COMPOSE_CONSOLIDATION_SUMMARY.md`
