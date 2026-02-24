#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

#
# Agent Actions Consumer Startup Script
#
# This script properly loads environment variables from .env and starts the consumer.
# It ensures all required variables are available before starting the Python consumer.
#

set -e          # Exit on error
set -o pipefail # Propagate pipe failures

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Create tmp directory and set log file location
mkdir -p "$PROJECT_ROOT/tmp"
LOG_FILE="$PROJECT_ROOT/tmp/agent_actions_consumer.log"

echo "========================================" | tee -a "$LOG_FILE"
echo "Agent Actions Consumer Startup" | tee -a "$LOG_FILE"
echo "Started at: $(date)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Load environment variables from .env
ENV_FILE="$PROJECT_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env file not found at $ENV_FILE" | tee -a "$LOG_FILE"
    exit 1
fi

echo "Loading environment from: $ENV_FILE" | tee -a "$LOG_FILE"

# Source the .env file
set -a  # Automatically export all variables
source "$ENV_FILE"
set +a

# Verify required environment variables
REQUIRED_VARS=(
    "KAFKA_BOOTSTRAP_SERVERS"
    "POSTGRES_HOST"
    "POSTGRES_PORT"
    "POSTGRES_DATABASE"
    "POSTGRES_USER"
    "POSTGRES_PASSWORD"
)

echo "" | tee -a "$LOG_FILE"
echo "Verifying required environment variables:" | tee -a "$LOG_FILE"

MISSING_VARS=()
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo "  ✗ $var - NOT SET" | tee -a "$LOG_FILE"
        MISSING_VARS+=("$var")
    else
        # Mask password for display
        if [ "$var" == "POSTGRES_PASSWORD" ]; then
            echo "  ✓ $var - SET (masked)" | tee -a "$LOG_FILE"
        else
            echo "  ✓ $var - ${!var}" | tee -a "$LOG_FILE"
        fi
    fi
done

if [ ${#MISSING_VARS[@]} -ne 0 ]; then
    echo "" | tee -a "$LOG_FILE"
    echo "ERROR: Missing required environment variables:" | tee -a "$LOG_FILE"
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var" | tee -a "$LOG_FILE"
    done
    echo "" | tee -a "$LOG_FILE"
    echo "Please set these variables in $ENV_FILE" | tee -a "$LOG_FILE"
    exit 1
fi

echo "" | tee -a "$LOG_FILE"
echo "All required environment variables are set" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Export environment variables explicitly (belt and suspenders approach)
export KAFKA_BOOTSTRAP_SERVERS="$KAFKA_BOOTSTRAP_SERVERS"
export POSTGRES_HOST="$POSTGRES_HOST"
export POSTGRES_PORT="$POSTGRES_PORT"
export POSTGRES_DATABASE="$POSTGRES_DATABASE"
export POSTGRES_USER="$POSTGRES_USER"
export POSTGRES_PASSWORD="$POSTGRES_PASSWORD"

# Set additional defaults
export KAFKA_GROUP_ID="${KAFKA_GROUP_ID:-agent-observability-postgres}"
export BATCH_SIZE="${BATCH_SIZE:-100}"
export BATCH_TIMEOUT_MS="${BATCH_TIMEOUT_MS:-1000}"
export HEALTH_CHECK_PORT="${HEALTH_CHECK_PORT:-8080}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

echo "Configuration:" | tee -a "$LOG_FILE"
echo "  Project Root: $PROJECT_ROOT" | tee -a "$LOG_FILE"
echo "  Consumer Script: $SCRIPT_DIR/agent_actions_consumer.py" | tee -a "$LOG_FILE"
echo "  Kafka Bootstrap: $KAFKA_BOOTSTRAP_SERVERS" | tee -a "$LOG_FILE"
echo "  PostgreSQL: $POSTGRES_USER@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DATABASE" | tee -a "$LOG_FILE"
echo "  Consumer Group: $KAFKA_GROUP_ID" | tee -a "$LOG_FILE"
echo "  Batch Size: $BATCH_SIZE" | tee -a "$LOG_FILE"
echo "  Health Check Port: $HEALTH_CHECK_PORT" | tee -a "$LOG_FILE"
echo "  Log Level: $LOG_LEVEL" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Change to consumer directory
cd "$SCRIPT_DIR"

echo "Starting consumer..." | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Start the consumer with output to both console and log file
# Note: Using command substitution with pipefail to ensure failures propagate
python3 agent_actions_consumer.py 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -ne 0 ]; then
    echo "" >&2
    echo "========================================" >&2
    echo "ERROR: Consumer failed with exit code $EXIT_CODE" >&2
    echo "Timestamp: $(date)" >&2
    echo "========================================" >&2
    echo "" >&2
    echo "ERROR: Consumer failed with exit code $EXIT_CODE" >> "$LOG_FILE"
    exit $EXIT_CODE
fi

echo "" | tee -a "$LOG_FILE"
echo "Consumer exited successfully" | tee -a "$LOG_FILE"
exit 0
