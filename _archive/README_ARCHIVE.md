# Archived Code

This directory contains the original OmniClaude implementation archived on 2025-01-19.

**Why archived**: Resetting to use proper omnibase ecosystem dependencies (omnibase-core, spi, infra).

## Contents

- `agents/` - Old 52-agent polymorphic framework
- `claude/` - Old hooks implementation
- `config/` - Old Pydantic config
- `deployment/` - Old docker-compose
- `docs/` - Old documentation
- `scripts/` - Old utility scripts
- `app/` - Old FastAPI application
- `cli/` - Old CLI interface
- `consumers/` - Old Kafka consumers
- `contracts/` - Old contract definitions
- `examples/` - Old example code
- `grafana/` - Old Grafana dashboards
- `migrations/` - Old database migrations
- `monitoring/` - Old monitoring config
- `omniclaude/` - Old package structure
- `schemas/` - Old Pydantic schemas
- `services/` - Old service layer
- `shared_lib/` - Old shared library code
- `skills/` - Old skills definitions
- `sql/` - Old SQL scripts
- `tests/` - Old test suite
- `tools/` - Old utility tools
- `validation/` - Old validation logic

## Important Notes

**Reference only** - Do not import or resurrect without explicit approval.

The new implementation uses:
- `src/omniclaude/` - New package structure with ONEX-compatible schemas
- `plugins/onex/` - Claude Code plugin architecture with hooks
- omnibase-core, omnibase-spi, omnibase-infra dependencies

## Migration Context

This archive was created as part of OMN-1399 to:
1. Reset OmniClaude to a clean slate
2. Implement ONEX-compatible event schemas for Claude Code hooks
3. Properly integrate with the omnibase ecosystem
