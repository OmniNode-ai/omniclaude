#!/bin/bash
# Entrypoint script for routing adapter service
# Validates environment, starts service, handles graceful shutdown

set -e  # Exit on error
set -u  # Exit on undefined variable

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Graceful shutdown handler
shutdown_handler() {
    log_info "Received shutdown signal, stopping routing adapter service..."
    if [ -n "${SERVICE_PID:-}" ]; then
        kill -TERM "$SERVICE_PID" 2>/dev/null || true
        wait "$SERVICE_PID" 2>/dev/null || true
    fi
    log_info "Routing adapter service stopped"
    exit 0
}

# Register shutdown handler
trap shutdown_handler SIGTERM SIGINT

# Validate required environment variables
log_info "Validating environment configuration..."

REQUIRED_VARS=(
    "KAFKA_BOOTSTRAP_SERVERS"
    "POSTGRES_HOST"
    "POSTGRES_PORT"
    "POSTGRES_DATABASE"
    "POSTGRES_USER"
    "POSTGRES_PASSWORD"
    "AGENT_REGISTRY_PATH"
    "AGENT_DEFINITIONS_PATH"
)

VALIDATION_FAILED=0

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        log_error "Required environment variable $var is not set"
        VALIDATION_FAILED=1
    else
        # Don't log password values
        if [[ "$var" == *"PASSWORD"* ]]; then
            log_info "  ✓ $var: [REDACTED]"
        else
            log_info "  ✓ $var: ${!var}"
        fi
    fi
done

if [ $VALIDATION_FAILED -eq 1 ]; then
    log_error "Environment validation failed. Exiting."
    exit 1
fi

# Validate registry file exists
if [ ! -f "${AGENT_REGISTRY_PATH}" ]; then
    log_error "Agent registry file not found: ${AGENT_REGISTRY_PATH}"
    exit 1
fi

log_info "Registry file found: ${AGENT_REGISTRY_PATH}"

# Check Kafka connectivity (optional, with timeout)
log_info "Checking Kafka connectivity..."
if timeout 5 bash -c "echo > /dev/tcp/${KAFKA_BOOTSTRAP_SERVERS%:*}/${KAFKA_BOOTSTRAP_SERVERS#*:}" 2>/dev/null; then
    log_info "  ✓ Kafka is reachable at ${KAFKA_BOOTSTRAP_SERVERS}"
else
    log_warn "  ⚠ Kafka connectivity check failed (service will retry on startup)"
fi

# Check PostgreSQL connectivity (optional, with timeout)
log_info "Checking PostgreSQL connectivity..."
if timeout 5 bash -c "echo > /dev/tcp/${POSTGRES_HOST}/${POSTGRES_PORT}" 2>/dev/null; then
    log_info "  ✓ PostgreSQL is reachable at ${POSTGRES_HOST}:${POSTGRES_PORT}"
else
    log_warn "  ⚠ PostgreSQL connectivity check failed (service will retry on startup)"
fi

# Display service configuration
log_info "Routing adapter service configuration:"
log_info "  - Kafka Group: ${KAFKA_GROUP_ID:-agent-routing-service}"
log_info "  - Request Topic: ${KAFKA_REQUEST_TOPIC:-agent.routing.requested.v1}"
log_info "  - Completed Topic: ${KAFKA_COMPLETED_TOPIC:-agent.routing.completed.v1}"
log_info "  - Failed Topic: ${KAFKA_FAILED_TOPIC:-agent.routing.failed.v1}"
log_info "  - Health Check Port: ${HEALTH_CHECK_PORT:-8070}"
log_info "  - Log Level: ${LOG_LEVEL:-INFO}"
log_info "  - Routing Timeout: ${ROUTING_TIMEOUT_MS:-5000}ms"
log_info "  - Cache TTL: ${CACHE_TTL_SECONDS:-3600}s"
log_info "  - Max Recommendations: ${MAX_RECOMMENDATIONS:-5}"

# Start routing adapter service (Phase 2 implementation)
log_info "Starting routing adapter service..."

# Run Phase 2 service as module (RouterEventHandler with event-driven architecture)
# Use -m flag to run as module so relative imports work correctly
python -m service.routing_adapter_service &
SERVICE_PID=$!

log_info "Routing adapter service started (PID: $SERVICE_PID)"

# Wait for service to exit
wait "$SERVICE_PID"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log_info "Routing adapter service exited normally"
else
    log_error "Routing adapter service exited with code $EXIT_CODE"
fi

exit $EXIT_CODE
