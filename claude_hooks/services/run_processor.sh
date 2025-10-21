#!/bin/bash
# Convenience script to run the Hook Event Processor
# Usage: ./run_processor.sh [--once]

set -e

# Change to script directory
cd "$(dirname "$0")"

# Load environment variables
if [ -f "../../.env" ]; then
    export $(grep -v '^#' ../../.env | xargs)
fi

# Set default environment if not provided
export DB_PASSWORD="${DB_PASSWORD:-omninode-bridge-postgres-dev-2024}"
export POLL_INTERVAL="${POLL_INTERVAL:-1.0}"
export BATCH_SIZE="${BATCH_SIZE:-100}"
export MAX_RETRY_COUNT="${MAX_RETRY_COUNT:-3}"

echo "🚀 Starting Hook Event Processor"
echo "  DB: localhost:5436/omninode_bridge"
echo "  Poll Interval: ${POLL_INTERVAL}s"
echo "  Batch Size: ${BATCH_SIZE}"
echo "  Max Retries: ${MAX_RETRY_COUNT}"
echo ""

# Run processor
if [ "$1" = "--once" ]; then
    echo "Running single batch..."
    timeout 30 python3 hook_event_processor.py || true
else
    echo "Running continuous service (Ctrl+C to stop)..."
    python3 hook_event_processor.py
fi
