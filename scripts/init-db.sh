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
psql -v ON_ERROR_STOP=1 -v db_user="${POSTGRES_USER}" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --host="$POSTGRES_HOST" <<-EOSQL
    -- Enable UUID extensions for generating UUIDs
    -- uuid-ossp: provides uuid_generate_v4() (legacy, retained for compatibility)
    -- pgcrypto: provides gen_random_uuid() (modern, used by migrations)
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS pgcrypto;

    -- Enable pg_trgm for fuzzy text search
    CREATE EXTENSION IF NOT EXISTS pg_trgm;

    -- Enable btree_gin for advanced indexing
    CREATE EXTENSION IF NOT EXISTS btree_gin;

    -- Create application schema
    CREATE SCHEMA IF NOT EXISTS omniclaude;

    -- Grant privileges (using psql variable binding via -v db_user)
    GRANT ALL PRIVILEGES ON SCHEMA omniclaude TO :"db_user";
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA omniclaude TO :"db_user";
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA omniclaude TO :"db_user";

    -- Set default privileges for future tables
    ALTER DEFAULT PRIVILEGES IN SCHEMA omniclaude GRANT ALL ON TABLES TO :"db_user";
    ALTER DEFAULT PRIVILEGES IN SCHEMA omniclaude GRANT ALL ON SEQUENCES TO :"db_user";

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
            # Use psql variable binding (-v) to avoid SQL injection via filenames.
            # :'varname' is psql's syntax for a string-quoted variable reference.
            already_applied=$(psql -v ON_ERROR_STOP=1 -v migration_name="${migration_name}" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --host="$POSTGRES_HOST" -tAc "SELECT 1 FROM schema_migrations WHERE filename = :'migration_name' LIMIT 1;")
            if [ "$already_applied" = "1" ]; then
                echo "  Skipping ${migration_name} (already applied)"
                continue
            fi
            echo "  Applying ${migration_name}..."
            # Run the migration SQL and record it in schema_migrations atomically.
            #
            # We inject the tracking INSERT *inside* the migration's own transaction
            # (before the final COMMIT;) rather than using --single-transaction.
            # Why: --single-transaction wraps everything in an implicit BEGIN/COMMIT,
            # but migrations with an explicit COMMIT (like 001) terminate the outer
            # transaction early, leaving the tracking INSERT in autocommit mode.
            # By injecting before the migration's COMMIT, both DDL and tracking run
            # in the same transaction. If the migration has no line-anchored COMMIT,
            # we append the INSERT at the end (it will run in autocommit, which is
            # acceptable for migrations that manage their own transaction boundaries).
            #
            # Pattern matching uses ^COMMIT; (start-of-line anchor) via grep/awk
            # to avoid false matches on COMMIT; inside SQL comments or strings.
            migration_content=$(cat "$migration")
            escaped_name="${migration_name//\'/\'\'}"
            tracking_sql="INSERT INTO schema_migrations (filename) VALUES ('${escaped_name}');"
            # Find the LAST line where COMMIT; starts at column 1.
            # Anchoring to ^COMMIT; avoids false matches inside SQL comments
            # (e.g., "-- See COMMIT; behavior") or string literals.
            last_commit_line=$(echo "$migration_content" | grep -n '^COMMIT;' | tail -1 | cut -d: -f1)
            if [ -n "$last_commit_line" ]; then
                # Inject tracking INSERT on the line before the last ^COMMIT;
                modified_content=$(echo "$migration_content" | awk -v line="$last_commit_line" -v sql="$tracking_sql" 'NR==line{print sql} {print}')
            else
                # No line-anchored COMMIT — append tracking INSERT at the end
                modified_content="${migration_content}
${tracking_sql}"
            fi
            echo "$modified_content" | psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --host="$POSTGRES_HOST"
        fi
    done
else
    echo "No migrations directory found at ${MIGRATIONS_DIR}, skipping."
fi

echo "Database initialization completed successfully!"
