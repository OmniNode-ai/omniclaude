#!/bin/bash
# PostgreSQL Database Initialization Script for OmniClaude
# Runs automatically when the database container starts for the first time
#
# Uses individual POSTGRES_* environment variables (POSTGRES_HOST, POSTGRES_USER,
# POSTGRES_DB / POSTGRES_DATABASE) for connection configuration.
#
# DB-SPLIT-07 (OMN-2058): This script only sets up extensions, schemas, and
# privileges. Session tables are created by sql/migrations/001_create_claude_session_tables.sql.
# Old shared-infrastructure tables (agent_routing_decisions, agent_manifest_injections,
# agent_execution_logs, agent_transformation_events, router_performance_metrics,
# agent_actions) were removed as part of DB-SPLIT-07 -- they belong to the shared
# omninode_bridge database, not the per-service omniclaude database.

set -e

echo "Initializing OmniClaude database..."

# Use POSTGRES_HOST environment variable if set, otherwise default to localhost
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"

# Support both POSTGRES_DB and POSTGRES_DATABASE environment variable names
# Default changed from 'postgres' to 'omniclaude' as part of DB-SPLIT-07 (OMN-2058)
POSTGRES_DB="${POSTGRES_DB:-${POSTGRES_DATABASE:-omniclaude}}"

# Create extensions and schema, then run migrations
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --host="$POSTGRES_HOST" <<-EOSQL
    -- Enable UUID extension for generating UUIDs
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

    -- Enable pg_trgm for fuzzy text search
    CREATE EXTENSION IF NOT EXISTS pg_trgm;

    -- Enable btree_gin for advanced indexing
    CREATE EXTENSION IF NOT EXISTS btree_gin;

    -- Create application schema
    CREATE SCHEMA IF NOT EXISTS omniclaude;

    -- Grant privileges
    GRANT ALL PRIVILEGES ON SCHEMA omniclaude TO $POSTGRES_USER;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA omniclaude TO $POSTGRES_USER;
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA omniclaude TO $POSTGRES_USER;

    -- Set default privileges for future tables
    ALTER DEFAULT PRIVILEGES IN SCHEMA omniclaude GRANT ALL ON TABLES TO $POSTGRES_USER;
    ALTER DEFAULT PRIVILEGES IN SCHEMA omniclaude GRANT ALL ON SEQUENCES TO $POSTGRES_USER;

EOSQL

# Run migrations (session tables)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS_DIR="${SCRIPT_DIR}/../sql/migrations"

if [ -d "$MIGRATIONS_DIR" ]; then
    # Create migration tracking table if it doesn't exist
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --host="$POSTGRES_HOST" <<-EOSQL
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
EOSQL

    echo "Running migrations from ${MIGRATIONS_DIR}..."
    for migration in "$MIGRATIONS_DIR"/*.sql; do
        # Skip rollback (down) migrations — only run forward migrations
        [[ "$migration" == *_down.sql ]] && continue
        if [ -f "$migration" ]; then
            migration_name="$(basename "$migration")"
            # Escape single quotes for safe SQL interpolation (defense-in-depth)
            safe_name="${migration_name//\'/\'\'}"
            # Skip already-applied migrations
            already_applied=$(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --host="$POSTGRES_HOST" -tAc "SELECT 1 FROM schema_migrations WHERE filename = '${safe_name}' LIMIT 1;")
            if [ "$already_applied" = "1" ]; then
                echo "  Skipping ${migration_name} (already applied)"
                continue
            fi
            echo "  Applying ${migration_name}..."
            psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --host="$POSTGRES_HOST" -f "$migration"
            # Record successful migration
            psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --host="$POSTGRES_HOST" -c "INSERT INTO schema_migrations (filename) VALUES ('${safe_name}');"
        fi
    done
else
    echo "No migrations directory found at ${MIGRATIONS_DIR}, skipping."
fi

echo "Database initialization completed successfully!"
