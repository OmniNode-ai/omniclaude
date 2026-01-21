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

# Set PostgreSQL environment variables (no fallbacks - must be set in .env)
export PGHOST="${POSTGRES_HOST}"
export PGPORT="${POSTGRES_PORT}"
export PGUSER="${POSTGRES_USER}"
export PGPASSWORD="${POSTGRES_PASSWORD}"
export PGDATABASE="${POSTGRES_DATABASE}"

# Verify required credentials are set
missing_vars=()
[ -z "$PGHOST" ] && missing_vars+=("POSTGRES_HOST")
[ -z "$PGPORT" ] && missing_vars+=("POSTGRES_PORT")
[ -z "$PGUSER" ] && missing_vars+=("POSTGRES_USER")
[ -z "$PGPASSWORD" ] && missing_vars+=("POSTGRES_PASSWORD")
[ -z "$PGDATABASE" ] && missing_vars+=("POSTGRES_DATABASE")

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo "❌ ERROR: Required environment variables not set in .env:" >&2
    for var in "${missing_vars[@]}"; do
        echo "   - $var" >&2
    done
    echo "" >&2
    echo "Please update your .env file with these variables." >&2
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
