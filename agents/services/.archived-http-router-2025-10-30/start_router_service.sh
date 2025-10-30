#!/bin/bash
# Start script for Agent Router Service (archon-router)
# Builds Docker image, starts container, waits for health check, and shows logs

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SERVICE_NAME="archon-router"
CONTAINER_NAME="omniclaude_archon_router"
IMAGE_NAME="omniclaude-archon-router"
PORT=8055
HEALTH_ENDPOINT="http://localhost:${PORT}/health"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Agent Router Service Startup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if .env file exists
ENV_FILE="${PROJECT_ROOT}/.env"
if [ ! -f "${ENV_FILE}" ]; then
    echo -e "${YELLOW}⚠️  Warning: .env file not found at ${ENV_FILE}${NC}"
    echo -e "${YELLOW}   Service will use default environment variables${NC}"
    echo ""
fi

# Stop and remove existing container if running
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${YELLOW}🔄 Stopping existing container...${NC}"
    docker stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker rm "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    echo -e "${GREEN}✅ Existing container removed${NC}"
    echo ""
fi

# Build Docker image
echo -e "${BLUE}🔨 Building Docker image...${NC}"
cd "${PROJECT_ROOT}"
docker build \
    -f agents/services/Dockerfile.router \
    -t "${IMAGE_NAME}:latest" \
    --build-arg BUILD_DATE="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
    --build-arg VCS_REF="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')" \
    --build-arg VERSION="${VERSION:-0.1.0}" \
    .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Docker image built successfully${NC}"
    echo ""
else
    echo -e "${RED}❌ Docker build failed${NC}"
    exit 1
fi

# Start container using docker-compose
echo -e "${BLUE}🚀 Starting container...${NC}"
cd "${PROJECT_ROOT}/deployment"

# Load .env if it exists
if [ -f "${ENV_FILE}" ]; then
    export $(grep -v '^#' "${ENV_FILE}" | xargs)
fi

docker-compose up -d "${SERVICE_NAME}"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Container started successfully${NC}"
    echo ""
else
    echo -e "${RED}❌ Failed to start container${NC}"
    exit 1
fi

# Wait for health check
echo -e "${BLUE}⏳ Waiting for health check...${NC}"
MAX_ATTEMPTS=30
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -sf "${HEALTH_ENDPOINT}" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Service is healthy!${NC}"
        echo ""
        break
    fi

    ATTEMPT=$((ATTEMPT + 1))
    if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
        echo -e "${RED}❌ Health check failed after ${MAX_ATTEMPTS} attempts${NC}"
        echo -e "${YELLOW}📋 Showing recent logs:${NC}"
        docker logs --tail 50 "${CONTAINER_NAME}"
        exit 1
    fi

    echo -n "."
    sleep 2
done

# Display service information
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Agent Router Service is running${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${BLUE}Service Information:${NC}"
echo -e "  Container:     ${CONTAINER_NAME}"
echo -e "  Image:         ${IMAGE_NAME}:latest"
echo -e "  Port:          ${PORT}"
echo -e "  Health Check:  ${HEALTH_ENDPOINT}"
echo ""
echo -e "${BLUE}Quick Commands:${NC}"
echo -e "  Logs:          docker logs -f ${CONTAINER_NAME}"
echo -e "  Stop:          docker stop ${CONTAINER_NAME}"
echo -e "  Restart:       docker restart ${CONTAINER_NAME}"
echo -e "  Health:        curl ${HEALTH_ENDPOINT}"
echo ""
echo -e "${BLUE}Agent Definitions:${NC}"
echo -e "  Mounted from:  \${HOME}/.claude/agent-definitions"
echo -e "  Registry:      /agent-definitions/agent-registry.yaml"
echo ""

# Show recent logs
echo -e "${YELLOW}📋 Recent logs (last 20 lines):${NC}"
echo -e "${BLUE}========================================${NC}"
docker logs --tail 20 "${CONTAINER_NAME}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Offer to follow logs
echo -e "${YELLOW}💡 Tip: Run 'docker logs -f ${CONTAINER_NAME}' to follow logs${NC}"
echo ""
