# Database Migrations

This directory contains database migration scripts for OmniClaude.

## Running Migrations

### Security Note

⚠️ **Always load credentials from `.env` before running database commands**:

```bash
source .env
```

Never hardcode database credentials in documentation or scripts. All connection details should use environment variables.

### Prerequisites

1. **PostgreSQL Access**: Ensure you have access to the PostgreSQL database
   - Host: `${POSTGRES_HOST}` (default: `192.168.86.200`)
   - Port: `${POSTGRES_PORT}` (default: `5436`)
   - Database: `${POSTGRES_DATABASE}` (default: `omninode_bridge`)
   - User: `${POSTGRES_USER}` (default: `postgres`)

2. **Environment Variables**: Load credentials from `.env` before running migrations

```bash
# Load environment variables (REQUIRED)
source .env

# Verify credentials are loaded
echo "Host: ${POSTGRES_HOST}"
echo "Port: ${POSTGRES_PORT}"
echo "Database: ${POSTGRES_DATABASE}"
echo "User: ${POSTGRES_USER}"

# Run migration using environment variables
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -f migrations/001_debug_loop_core_schema.sql
```

### Alternative: Using Python Config

If you have the Python environment set up:

```bash
python3 -c "
from config import settings
import subprocess
import os

os.environ['PGPASSWORD'] = settings.postgres_password
subprocess.run([
    'psql',
    '-h', settings.postgres_host,
    '-p', str(settings.postgres_port),
    '-U', settings.postgres_user,
    '-d', settings.postgres_database,
    '-f', 'migrations/001_debug_loop_core_schema.sql'
])
"
```

## Migration 001: Debug Loop Core Schema

**File**: `001_debug_loop_core_schema.sql`
**Created**: 2025-11-09
**Part**: Phase 1 - Debug Intelligence Core

Creates 5 tables:

1. **`debug_transform_functions`** - STF registry with quality metrics
   - 14 fields including quality dimensions
   - 6 indexes for performance
   - Auto-calculated quality scores
   - Approval workflow (pending → approved/rejected)

2. **`model_price_catalog`** - LLM model pricing
   - Tracks pricing per 1M tokens
   - Performance characteristics (latency, context window)
   - Capabilities (streaming, function calling, vision)
   - Rate limits
   - Seed data for 15+ models (Anthropic, OpenAI, Google, Z.ai, Together)

3. **`debug_execution_attempts`** - Enhanced correlation tracking
   - Links retries via `parent_attempt_id`
   - Tracks STFs attempted (`stf_ids` array)
   - Cost tracking (tokens, estimated USD)
   - Golden state nomination
   - 8 indexes for query performance

4. **`debug_error_success_mappings`** - Error→success patterns
   - Auto-calculated confidence scores
   - Links to successful/failed attempts
   - Error pattern normalization
   - Success/failure counts

5. **`debug_golden_states`** - Proven solution registry
   - Links to execution attempts
   - Quality, complexity, reusability scores
   - Approval workflow
   - Reuse tracking

### Analytical Views

The migration also creates 3 views for common queries:

- **`v_recommended_stfs`** - High-quality approved STFs (quality ≥ 0.7)
- **`v_error_resolution_patterns`** - High-confidence error patterns (confidence ≥ 0.7)
- **`v_golden_states_full`** - Approved golden states with full context

### Seed Data

The migration includes seed data for **15 LLM models** across 5 providers:
- Anthropic: Claude 3.5 Sonnet, Opus, Haiku
- OpenAI: GPT-4 Turbo, GPT-4, GPT-3.5 Turbo
- Google: Gemini 1.5 Pro/Flash, Gemini 2.5 Flash
- Z.ai: GLM-4.5-Air, GLM-4.5, GLM-4.6, GLM-4-Flash
- Together AI: Llama 3.1 (405B, 70B, 8B)

## Verification

After running the migration, verify success:

```sql
-- Check table creation
SELECT tablename FROM pg_tables WHERE schemaname = 'public'
AND tablename LIKE 'debug_%';

-- Check view creation
SELECT viewname FROM pg_views WHERE schemaname = 'public'
AND viewname LIKE 'v_%';

-- Check seed data
SELECT provider, model_name, model_version FROM model_price_catalog ORDER BY provider, model_name;

-- Verify indexes
SELECT tablename, indexname FROM pg_indexes WHERE schemaname = 'public'
AND tablename LIKE 'debug_%' ORDER BY tablename;
```

Expected output:
- 5 tables created
- 3 views created
- 15 model entries in catalog
- 23 indexes total

## Rollback

To rollback this migration:

```sql
-- Drop tables (cascades to foreign keys)
DROP TABLE IF EXISTS debug_golden_states CASCADE;
DROP TABLE IF EXISTS debug_error_success_mappings CASCADE;
DROP TABLE IF EXISTS debug_execution_attempts CASCADE;
DROP TABLE IF EXISTS model_price_catalog CASCADE;
DROP TABLE IF EXISTS debug_transform_functions CASCADE;

-- Drop views
DROP VIEW IF EXISTS v_recommended_stfs;
DROP VIEW IF EXISTS v_error_resolution_patterns;
DROP VIEW IF EXISTS v_golden_states_full;

-- Drop helper function
DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;
DROP FUNCTION IF EXISTS calculate_error_mapping_confidence() CASCADE;
```

## Next Steps

After migration is complete:

1. **Day 3-5**: Design ONEX v2.0 contracts (11 YAML files)
2. **Week 2**: Generate nodes using node generator
3. **Week 3-4**: Integration and testing

See `docs/planning/DEBUG_LOOP_ONEX_IMPLEMENTATION_PLAN.md` for complete implementation plan.
