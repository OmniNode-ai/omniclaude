#!/bin/bash
# Kafka Setup Validation Script
# Verifies Kafka/Redpanda and PostgreSQL connectivity for agent logging

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
KAFKA_BROKER=${KAFKA_BROKERS:-"localhost:29092"}
KAFKA_TOPIC="agent-actions"
POSTGRES_HOST=${POSTGRES_HOST:-"localhost"}
POSTGRES_PORT=${POSTGRES_PORT:-"5436"}
POSTGRES_USER=${POSTGRES_USER:-"postgres"}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-"omninode-bridge-postgres-dev-2024"}
POSTGRES_DB=${POSTGRES_DATABASE:-"omninode_bridge"}

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🔍 Kafka Agent Logging Setup Validator${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to print status
print_status() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ $1${NC}"
    else
        echo -e "${RED}❌ $1${NC}"
        exit 1
    fi
}

# 1. Check required tools
echo -e "${YELLOW}1. Checking required tools...${NC}"

if command_exists docker; then
    print_status "Docker installed"
else
    echo -e "${RED}❌ Docker not found. Please install Docker.${NC}"
    exit 1
fi

if command_exists docker-compose; then
    DOCKER_COMPOSE_CMD="docker-compose"
elif command_exists docker compose; then
    DOCKER_COMPOSE_CMD="docker compose"
else
    echo -e "${RED}❌ docker-compose not found. Please install docker-compose.${NC}"
    exit 1
fi
print_status "docker-compose installed"

if command_exists psql; then
    print_status "PostgreSQL client (psql) installed"
else
    echo -e "${YELLOW}⚠️  PostgreSQL client (psql) not found - skipping direct DB checks${NC}"
fi

echo ""

# 2. Check Docker containers
echo -e "${YELLOW}2. Checking Docker containers...${NC}"

# Check if Redpanda container is running
if docker ps | grep -q "omniclaude_test_redpanda"; then
    print_status "Redpanda container running"
else
    echo -e "${RED}❌ Redpanda container not running${NC}"
    echo -e "${YELLOW}   Run: docker-compose -f deployment/docker-compose.test.yml up -d redpanda${NC}"
    exit 1
fi

# Check if PostgreSQL container is running
if docker ps | grep -q "omniclaude_test_postgres"; then
    print_status "PostgreSQL container running"
else
    echo -e "${RED}❌ PostgreSQL container not running${NC}"
    echo -e "${YELLOW}   Run: docker-compose -f deployment/docker-compose.test.yml up -d postgres${NC}"
    exit 1
fi

echo ""

# 3. Check Kafka connectivity
echo -e "${YELLOW}3. Checking Kafka connectivity...${NC}"

# Wait for Kafka to be ready
echo -e "${BLUE}   Waiting for Kafka to be ready...${NC}"
KAFKA_READY=false
for i in {1..30}; do
    if docker exec omniclaude_test_redpanda rpk cluster health >/dev/null 2>&1; then
        KAFKA_READY=true
        break
    fi
    sleep 1
done

if [ "$KAFKA_READY" = true ]; then
    print_status "Kafka broker is healthy"
else
    echo -e "${RED}❌ Kafka broker not ready after 30 seconds${NC}"
    exit 1
fi

# Check if topic exists, create if not
if docker exec omniclaude_test_redpanda rpk topic list 2>/dev/null | grep -q "$KAFKA_TOPIC"; then
    print_status "Topic '$KAFKA_TOPIC' exists"
else
    echo -e "${YELLOW}   Topic '$KAFKA_TOPIC' not found, creating...${NC}"
    docker exec omniclaude_test_redpanda rpk topic create "$KAFKA_TOPIC" --partitions 3 --replicas 1
    print_status "Topic '$KAFKA_TOPIC' created"
fi

echo ""

# 4. Check PostgreSQL connectivity
echo -e "${YELLOW}4. Checking PostgreSQL connectivity...${NC}"

# Check if PostgreSQL is ready
PG_READY=false
for i in {1..30}; do
    if docker exec omniclaude_test_postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
        PG_READY=true
        break
    fi
    sleep 1
done

if [ "$PG_READY" = true ]; then
    print_status "PostgreSQL is ready"
else
    echo -e "${RED}❌ PostgreSQL not ready after 30 seconds${NC}"
    exit 1
fi

# Check if agent_actions table exists
TABLE_EXISTS=$(docker exec omniclaude_test_postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='agent_actions');")

if [ "$TABLE_EXISTS" = "t" ]; then
    print_status "Table 'agent_actions' exists"
else
    echo -e "${RED}❌ Table 'agent_actions' does not exist${NC}"
    echo -e "${YELLOW}   Run: docker exec omniclaude_test_postgres psql -U postgres -d omninode_bridge -f /docker-entrypoint-initdb.d/init-test-db.sql${NC}"
    exit 1
fi

echo ""

# 5. Test Kafka publish/consume
echo -e "${YELLOW}5. Testing Kafka publish/consume...${NC}"

# Generate test message
TEST_MESSAGE='{"correlation_id":"test-validate-'$(date +%s)'","agent_name":"test-agent","action_type":"tool_call","action_name":"validation_test","action_details":{},"debug_mode":true,"timestamp":"'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'"}'

# Publish test message
echo "$TEST_MESSAGE" | docker exec -i omniclaude_test_redpanda rpk topic produce "$KAFKA_TOPIC" >/dev/null 2>&1
print_status "Published test message to Kafka"

# Consume test message (check last message)
CONSUMED=$(docker exec omniclaude_test_redpanda rpk topic consume "$KAFKA_TOPIC" --num 1 --offset end --format '%v' 2>/dev/null | tail -1)

if [ -n "$CONSUMED" ]; then
    print_status "Consumed test message from Kafka"
else
    echo -e "${RED}❌ Failed to consume message from Kafka${NC}"
    exit 1
fi

echo ""

# 6. Test database write (optional)
echo -e "${YELLOW}6. Testing database write...${NC}"

TEST_CORRELATION_ID="test-validate-$(date +%s)"
docker exec omniclaude_test_postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
    "INSERT INTO agent_actions (correlation_id, agent_name, action_type, action_name, action_details, debug_mode) \
     VALUES ('$TEST_CORRELATION_ID', 'test-agent', 'tool_call', 'validation_test', '{}'::jsonb, true);" \
    >/dev/null 2>&1
print_status "Database write successful"

# Verify record exists
RECORD_COUNT=$(docker exec omniclaude_test_postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT COUNT(*) FROM agent_actions WHERE correlation_id='$TEST_CORRELATION_ID';")

if [ "$RECORD_COUNT" -eq "1" ]; then
    print_status "Database read successful"
else
    echo -e "${RED}❌ Database read failed${NC}"
    exit 1
fi

# Cleanup test record
docker exec omniclaude_test_postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
    "DELETE FROM agent_actions WHERE correlation_id='$TEST_CORRELATION_ID';" \
    >/dev/null 2>&1

echo ""

# 7. Summary
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ All validation checks passed!${NC}"
echo -e "${GREEN}========================================${NC}\n"

echo -e "${BLUE}📊 Configuration Summary:${NC}"
echo -e "  Kafka Broker:     $KAFKA_BROKER"
echo -e "  Kafka Topic:      $KAFKA_TOPIC"
echo -e "  PostgreSQL Host:  $POSTGRES_HOST:$POSTGRES_PORT"
echo -e "  Database:         $POSTGRES_DB"
echo ""

echo -e "${BLUE}🚀 Next Steps:${NC}"
echo -e "  1. Run unit tests:         ${YELLOW}pytest tests/test_kafka_logging.py -v${NC}"
echo -e "  2. Run integration tests:  ${YELLOW}pytest tests/test_kafka_consumer.py -v${NC}"
echo -e "  3. Run e2e tests:          ${YELLOW}pytest tests/test_e2e_agent_logging.py -v${NC}"
echo -e "  4. Run performance tests:  ${YELLOW}pytest tests/test_logging_performance.py -v -m performance${NC}"
echo -e "  5. Run all tests:          ${YELLOW}docker-compose -f deployment/docker-compose.test.yml --profile test up test-runner${NC}"
echo ""

exit 0
