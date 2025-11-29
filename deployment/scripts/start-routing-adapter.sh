#!/bin/bash
# Build and start routing adapter service
# Usage: ./deployment/scripts/start-routing-adapter.sh

set -e          # Exit on error
set -o pipefail # Propagate pipe failures

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Change to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}Routing Adapter Service - Build & Start${NC}"
echo -e "${BLUE}==========================================${NC}"
echo ""

# Check .env file exists
if [ ! -f ".env" ]; then
    echo -e "${RED}ERROR: .env file not found${NC}"
    echo "Please create .env from .env.example:"
    echo "  cp .env.example .env"
    echo "  nano .env  # Add your credentials"
    exit 1
fi

# Source .env file and export variables for docker-compose
echo -e "${GREEN}Loading environment from .env...${NC}"
set -a  # Automatically export all variables
source .env
set +a  # Stop auto-export

# Explicitly export critical variables for docker-compose
export KAFKA_BOOTSTRAP_SERVERS
export POSTGRES_PASSWORD
export OMNINODE_BRIDGE_POSTGRES_PASSWORD

# Validate required environment variables
REQUIRED_VARS=(
    "KAFKA_BOOTSTRAP_SERVERS"
    "POSTGRES_PASSWORD"
)

VALIDATION_FAILED=0

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo -e "${RED}ERROR: Required environment variable $var is not set in .env${NC}"
        VALIDATION_FAILED=1
    fi
done

if [ $VALIDATION_FAILED -eq 1 ]; then
    echo ""
    echo -e "${YELLOW}Please update .env with required credentials${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Environment validation passed${NC}"
echo ""

# Check if agent registry exists
REGISTRY_PATH="${HOME}/.claude/agents/onex/agent-registry.yaml"
if [ ! -f "$REGISTRY_PATH" ]; then
    echo -e "${RED}ERROR: Agent registry not found: $REGISTRY_PATH${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Agent registry found: $REGISTRY_PATH${NC}"
echo ""

# Stop existing container if running
if docker ps -a --format '{{.Names}}' | grep -q "^omniclaude_routing_adapter$"; then
    echo -e "${YELLOW}Stopping existing routing adapter container...${NC}"
    docker stop omniclaude_routing_adapter >/dev/null 2>&1 || true
    docker rm omniclaude_routing_adapter >/dev/null 2>&1 || true
    echo -e "${GREEN}✓ Stopped and removed existing container${NC}"
    echo ""
fi

# Build image
echo -e "${BLUE}Building routing adapter image...${NC}"
docker-compose -f deployment/docker-compose.yml build routing-adapter

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Build successful${NC}"
    echo ""
else
    echo -e "${RED}ERROR: Build failed${NC}"
    exit 1
fi

# Start service
echo -e "${BLUE}Starting routing adapter service...${NC}"
docker-compose -f deployment/docker-compose.yml up -d routing-adapter

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Service started${NC}"
    echo ""
else
    echo -e "${RED}ERROR: Service failed to start${NC}"
    exit 1
fi

# Wait for health check
echo -e "${BLUE}Waiting for service to be healthy...${NC}"
MAX_WAIT=30
WAIT_COUNT=0

while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if docker ps --filter "name=omniclaude_routing_adapter" --filter "health=healthy" | grep -q "omniclaude_routing_adapter"; then
        echo -e "${GREEN}✓ Service is healthy${NC}"
        break
    fi

    sleep 1
    WAIT_COUNT=$((WAIT_COUNT + 1))

    if [ $WAIT_COUNT -eq $MAX_WAIT ]; then
        echo -e "${YELLOW}⚠ Service health check timed out (still starting)${NC}"
    fi
done

echo ""

# Show service info
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}Service Information${NC}"
echo -e "${BLUE}==========================================${NC}"
docker ps --filter "name=omniclaude_routing_adapter" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""

# Show logs (last 20 lines)
echo -e "${BLUE}Recent Logs:${NC}"
echo -e "${BLUE}==========================================${NC}"
docker logs --tail 20 omniclaude_routing_adapter
echo ""

# Show useful commands
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}Useful Commands${NC}"
echo -e "${BLUE}==========================================${NC}"
echo "View logs:"
echo "  docker logs -f omniclaude_routing_adapter"
echo ""
echo "Check health:"
echo "  curl http://localhost:8070/health"
echo ""
echo "Stop service:"
echo "  docker-compose -f deployment/docker-compose.yml stop routing-adapter"
echo ""
echo "Restart service:"
echo "  docker-compose -f deployment/docker-compose.yml restart routing-adapter"
echo ""
echo "Shell access:"
echo "  docker exec -it omniclaude_routing_adapter bash"
echo ""
echo -e "${GREEN}✓ Routing adapter service ready${NC}"
