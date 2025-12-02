#!/bin/bash
#
# publish_sample_events.sh
# Publishes sample events to Redpanda for dashboard development testing
#
# Usage:
#   ./scripts/publish_sample_events.sh              # Publish to localhost:9092
#   ./scripts/publish_sample_events.sh --count 50   # Publish 50 events (default: 10)
#   ./scripts/publish_sample_events.sh --broker localhost:29092  # Custom broker
#
# Prerequisites:
#   - Redpanda running locally (docker-compose up -d redpanda)
#   - rpk or kafkacat/kcat installed
#
# Topics:
#   - agent.routing.requested.v1
#   - agent.routing.completed.v1
#   - agent-routing-decisions
#   - agent-transformation-events

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Defaults
BROKER="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
COUNT=10

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --broker)
            BROKER="$2"
            shift 2
            ;;
        --count)
            COUNT="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--broker BROKER] [--count N]"
            echo ""
            echo "Options:"
            echo "  --broker  Kafka broker address (default: localhost:9092)"
            echo "  --count   Number of events to publish (default: 10)"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Detect available Kafka CLI tool
detect_kafka_tool() {
    if command -v rpk &> /dev/null; then
        echo "rpk"
    elif command -v kcat &> /dev/null; then
        echo "kcat"
    elif command -v kafkacat &> /dev/null; then
        echo "kafkacat"
    else
        echo ""
    fi
}

# Generate a random UUID
generate_uuid() {
    if command -v uuidgen &> /dev/null; then
        uuidgen | tr '[:upper:]' '[:lower:]'
    else
        # Fallback using /dev/urandom
        cat /proc/sys/kernel/random/uuid 2>/dev/null || \
            python3 -c "import uuid; print(uuid.uuid4())"
    fi
}

# Generate sample routing requested event
generate_routing_requested() {
    local correlation_id=$(generate_uuid)
    local session_id=$(generate_uuid)
    local requests=(
        "Help me refactor the authentication module"
        "Fix the bug in payment processing"
        "Create a new API endpoint for users"
        "Write unit tests for the order service"
        "Optimize database queries"
        "Add logging to notification service"
        "Review the PR for feature branch"
        "Debug memory leak in background worker"
        "Implement caching for product catalog"
        "Set up CI/CD pipeline"
    )
    local request="${requests[$((RANDOM % ${#requests[@]}))]}"
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")

    cat <<EOF
{
  "event_type": "routing.requested",
  "version": "1.0",
  "correlation_id": "${correlation_id}",
  "session_id": "${session_id}",
  "timestamp": "${timestamp}",
  "payload": {
    "user_request": "${request}",
    "context": {
      "source": "claude-code",
      "environment": "development"
    },
    "options": {
      "max_recommendations": 3,
      "include_reasoning": true
    }
  }
}
EOF
}

# Generate sample routing completed event
generate_routing_completed() {
    local correlation_id=$(generate_uuid)
    local session_id=$(generate_uuid)
    local agents=("polymorphic-agent" "python-fastapi-expert" "debug-intelligence" "testing-agent" "pr-review-agent")
    local selected_agent="${agents[$((RANDOM % ${#agents[@]}))]}"
    local confidence=$(echo "scale=4; 0.75 + ($RANDOM % 25) / 100" | bc)
    local routing_time=$((5 + RANDOM % 15))
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")

    cat <<EOF
{
  "event_type": "routing.completed",
  "version": "1.0",
  "correlation_id": "${correlation_id}",
  "session_id": "${session_id}",
  "timestamp": "${timestamp}",
  "payload": {
    "selected_agent": "${selected_agent}",
    "confidence_score": ${confidence},
    "routing_strategy": "enhanced_fuzzy_matching",
    "routing_time_ms": ${routing_time},
    "alternatives": [
      {"agent": "debug-intelligence", "confidence": 0.72},
      {"agent": "testing-agent", "confidence": 0.65}
    ],
    "reasoning": "Selected based on trigger match and historical success rate"
  }
}
EOF
}

# Generate sample routing decision event (for agent-routing-decisions topic)
generate_routing_decision() {
    local correlation_id=$(generate_uuid)
    local agents=("polymorphic-agent" "python-fastapi-expert" "debug-intelligence" "testing-agent" "pr-review-agent")
    local selected_agent="${agents[$((RANDOM % ${#agents[@]}))]}"
    local confidence=$(echo "scale=4; 0.75 + ($RANDOM % 25) / 100" | bc)
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")

    cat <<EOF
{
  "correlation_id": "${correlation_id}",
  "selected_agent": "${selected_agent}",
  "confidence_score": ${confidence},
  "routing_strategy": "enhanced_fuzzy_matching",
  "cache_hit": $((RANDOM % 2 == 0 ? 1 : 0)),
  "timestamp": "${timestamp}"
}
EOF
}

# Generate sample transformation event
generate_transformation_event() {
    local correlation_id=$(generate_uuid)
    local agents=("polymorphic-agent" "python-fastapi-expert" "debug-intelligence" "testing-agent")
    local source_agent="polymorphic-agent"
    local target_agent="${agents[$((1 + RANDOM % 3))]}"
    local confidence=$(echo "scale=4; 0.75 + ($RANDOM % 25) / 100" | bc)
    local duration=$((10 + RANDOM % 50))
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")

    cat <<EOF
{
  "event_type": "agent_transformation",
  "correlation_id": "${correlation_id}",
  "source_agent": "${source_agent}",
  "target_agent": "${target_agent}",
  "routing_confidence": ${confidence},
  "transformation_duration_ms": ${duration},
  "success": true,
  "timestamp": "${timestamp}"
}
EOF
}

# Publish event using detected tool
publish_event() {
    local topic="$1"
    local event="$2"
    local tool="$3"

    case $tool in
        rpk)
            echo "$event" | rpk topic produce "$topic" --brokers "$BROKER" 2>/dev/null
            ;;
        kcat|kafkacat)
            echo "$event" | $tool -P -b "$BROKER" -t "$topic" 2>/dev/null
            ;;
    esac
}

# Create topics if they don't exist (rpk only)
create_topics() {
    local tool="$1"
    local topics=("agent.routing.requested.v1" "agent.routing.completed.v1" "agent-routing-decisions" "agent-transformation-events")

    if [ "$tool" = "rpk" ]; then
        print_info "Ensuring topics exist..."
        for topic in "${topics[@]}"; do
            rpk topic create "$topic" --brokers "$BROKER" 2>/dev/null || true
        done
    fi
}

# Main
main() {
    print_info "Publishing sample events to Redpanda"
    print_info "Broker: $BROKER"
    print_info "Count: $COUNT events per topic"
    echo ""

    # Detect Kafka tool
    KAFKA_TOOL=$(detect_kafka_tool)
    if [ -z "$KAFKA_TOOL" ]; then
        print_error "No Kafka CLI tool found. Please install rpk, kcat, or kafkacat."
        print_info "Install rpk: https://docs.redpanda.com/current/get-started/rpk-install/"
        print_info "Install kcat: apt-get install kafkacat (or brew install kcat)"
        exit 1
    fi
    print_success "Using $KAFKA_TOOL"

    # Test broker connectivity
    print_info "Testing broker connectivity..."
    if [ "$KAFKA_TOOL" = "rpk" ]; then
        if ! rpk cluster info --brokers "$BROKER" &>/dev/null; then
            print_error "Cannot connect to broker at $BROKER"
            print_info "Make sure Redpanda is running: docker-compose up -d redpanda"
            exit 1
        fi
    fi
    print_success "Connected to broker"

    # Create topics
    create_topics "$KAFKA_TOOL"

    echo ""
    print_info "Publishing events..."

    # Publish routing requested events
    for ((i=1; i<=COUNT; i++)); do
        event=$(generate_routing_requested)
        publish_event "agent.routing.requested.v1" "$event" "$KAFKA_TOOL"
    done
    print_success "Published $COUNT events to agent.routing.requested.v1"

    # Publish routing completed events
    for ((i=1; i<=COUNT; i++)); do
        event=$(generate_routing_completed)
        publish_event "agent.routing.completed.v1" "$event" "$KAFKA_TOOL"
    done
    print_success "Published $COUNT events to agent.routing.completed.v1"

    # Publish routing decision events
    for ((i=1; i<=COUNT; i++)); do
        event=$(generate_routing_decision)
        publish_event "agent-routing-decisions" "$event" "$KAFKA_TOOL"
    done
    print_success "Published $COUNT events to agent-routing-decisions"

    # Publish transformation events
    for ((i=1; i<=COUNT; i++)); do
        event=$(generate_transformation_event)
        publish_event "agent-transformation-events" "$event" "$KAFKA_TOOL"
    done
    print_success "Published $COUNT events to agent-transformation-events"

    echo ""
    print_success "Done! Published $((COUNT * 4)) total events"
    echo ""
    print_info "To consume events:"
    if [ "$KAFKA_TOOL" = "rpk" ]; then
        echo "  rpk topic consume agent.routing.completed.v1 --brokers $BROKER -n 5"
    else
        echo "  $KAFKA_TOOL -C -b $BROKER -t agent.routing.completed.v1 -c 5"
    fi
}

main "$@"
