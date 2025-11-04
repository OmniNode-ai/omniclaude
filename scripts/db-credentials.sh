#!/bin/bash
# Database Credentials Helper
# Source this file to get PostgreSQL credentials from .env

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load .env if it exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    # Export variables from .env
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Set PostgreSQL environment variables
export PGHOST="${POSTGRES_HOST:-192.168.86.200}"
export PGPORT="${POSTGRES_PORT:-5436}"
export PGUSER="${POSTGRES_USER:-postgres}"
export PGPASSWORD="${POSTGRES_PASSWORD}"  # Must be set in .env
export PGDATABASE="${POSTGRES_DATABASE:-omninode_bridge}"

# Verify credentials are set
if [ -z "$PGPASSWORD" ]; then
    echo "❌ ERROR: POSTGRES_PASSWORD not found in .env" >&2
    echo "   Please run: source .env" >&2
    return 1 2>/dev/null || exit 1
fi

# Export for scripts
export DB_CONNECTION_STRING="postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${PGDATABASE}"

# Function for easy psql access
db_query() {
    psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"
}

# Export the function
export -f db_query

# Print status (only if not sourced silently)
if [ "${BASH_SOURCE[0]}" = "${0}" ] || [ "$1" != "--silent" ]; then
    echo "✅ Database credentials loaded:"
    echo "   Host: $PGHOST:$PGPORT"
    echo "   Database: $PGDATABASE"
    echo "   User: $PGUSER"
    echo "   Connection: Ready"
fi
