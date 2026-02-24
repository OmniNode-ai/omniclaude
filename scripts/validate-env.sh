#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# ==============================================================================
# Environment Variable Validation Script
# ==============================================================================
# Validates that all required environment variables are set
# Usage: ./scripts/validate-env.sh [env-file]
# ==============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default env file
ENV_FILE="${1:-.env}"

# Check if file exists
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}❌ Error: Environment file not found: $ENV_FILE${NC}"
    echo "Usage: $0 [env-file]"
    exit 1
fi

echo "=================================================="
echo "Validating Environment File: $ENV_FILE"
echo "=================================================="

# Required variables for all environments
REQUIRED_VARS=(
    "ENVIRONMENT"
    "CONTAINER_PREFIX"
    "KAFKA_BOOTSTRAP_SERVERS"
    "POSTGRES_HOST"
    "POSTGRES_PORT"
    "POSTGRES_DATABASE"
    "POSTGRES_USER"
    "POSTGRES_PASSWORD"
    "APP_POSTGRES_PASSWORD"
    "SECRET_KEY"
    "GRAFANA_ADMIN_PASSWORD"
)

# Variables that should NOT be placeholders
PLACEHOLDER_CHECKS=(
    "POSTGRES_PASSWORD:<set_password>:<set_test_db_password>:<CHANGE_ME"
    "APP_POSTGRES_PASSWORD:<set_password>:<set_app_db_password>:<CHANGE_ME"
    "SECRET_KEY:<set_secret_key>:<CHANGE_ME"
    "GRAFANA_ADMIN_PASSWORD:<set_password>:<CHANGE_ME"
)

# Load environment file
# Temporarily disable errexit for sourcing (handles command substitutions)
set +e
set -a
source "$ENV_FILE" 2>/dev/null
SOURCE_EXIT=$?
set +a
set -e

if [ $SOURCE_EXIT -ne 0 ]; then
    echo -e "${RED}❌ Error: Failed to source environment file${NC}"
    exit 1
fi

# Check each required variable
MISSING_VARS=()
PLACEHOLDER_VARS=()
EMPTY_VARS=()

for var in "${REQUIRED_VARS[@]}"; do
    value="${!var}"

    if [ -z "$value" ]; then
        EMPTY_VARS+=("$var")
    else
        # Check for placeholder values
        for check in "${PLACEHOLDER_CHECKS[@]}"; do
            var_name="${check%%:*}"
            placeholders="${check#*:}"

            if [ "$var" == "$var_name" ]; then
                IFS=':' read -ra PLACEHOLDERS <<< "$placeholders"
                for placeholder in "${PLACEHOLDERS[@]}"; do
                    if [[ "$value" == *"$placeholder"* ]]; then
                        PLACEHOLDER_VARS+=("$var (value: $placeholder)")
                        break
                    fi
                done
            fi
        done
    fi
done

# Additional validation checks
echo ""
echo "Running validation checks..."
echo ""

# Check 1: Environment value
case "$ENVIRONMENT" in
    development|test|production)
        echo -e "${GREEN}✅ Environment: $ENVIRONMENT${NC}"
        ;;
    *)
        echo -e "${RED}❌ Invalid ENVIRONMENT value: $ENVIRONMENT${NC}"
        echo "   Must be: development, test, or production"
        MISSING_VARS+=("ENVIRONMENT (invalid value)")
        ;;
esac

# Check 2: Kafka configuration
if [[ "$KAFKA_BOOTSTRAP_SERVERS" == *"<"*">"* ]] || [[ "$KAFKA_BOOTSTRAP_SERVERS" == *"CHANGE_ME"* ]]; then
    echo -e "${RED}❌ Kafka bootstrap servers not configured${NC}"
    PLACEHOLDER_VARS+=("KAFKA_BOOTSTRAP_SERVERS")
else
    echo -e "${GREEN}✅ Kafka: $KAFKA_BOOTSTRAP_SERVERS${NC}"
fi

# Check 3: PostgreSQL configuration
if [[ "$POSTGRES_HOST" == *"<"*">"* ]] || [[ "$POSTGRES_HOST" == *"production-"* ]]; then
    echo -e "${RED}❌ PostgreSQL host not configured${NC}"
    PLACEHOLDER_VARS+=("POSTGRES_HOST")
else
    echo -e "${GREEN}✅ PostgreSQL: $POSTGRES_HOST:$POSTGRES_PORT${NC}"
fi

# Check 4: Secret key strength (minimum 32 characters)
if [ ${#SECRET_KEY} -lt 32 ]; then
    echo -e "${YELLOW}⚠️  Warning: SECRET_KEY should be at least 32 characters${NC}"
    echo "   Generate with: openssl rand -base64 32"
fi

# Check 5: Test for hardcoded production passwords
if [ "$ENVIRONMENT" == "production" ]; then
    if [ "$GRAFANA_ADMIN_PASSWORD" == "admin" ]; then
        echo -e "${RED}❌ Using default Grafana password in production!${NC}"
        PLACEHOLDER_VARS+=("GRAFANA_ADMIN_PASSWORD (default password)")
    fi
fi

# Report results
echo ""
echo "=================================================="
echo "Validation Results"
echo "=================================================="

ERROR_COUNT=0

if [ ${#EMPTY_VARS[@]} -gt 0 ]; then
    echo -e "${RED}❌ Empty Variables (${#EMPTY_VARS[@]})${NC}"
    for var in "${EMPTY_VARS[@]}"; do
        echo "   - $var"
    done
    ERROR_COUNT=$((ERROR_COUNT + ${#EMPTY_VARS[@]}))
    echo ""
fi

if [ ${#PLACEHOLDER_VARS[@]} -gt 0 ]; then
    echo -e "${RED}❌ Placeholder Values Detected (${#PLACEHOLDER_VARS[@]})${NC}"
    for var in "${PLACEHOLDER_VARS[@]}"; do
        echo "   - $var"
    done
    ERROR_COUNT=$((ERROR_COUNT + ${#PLACEHOLDER_VARS[@]}))
    echo ""
fi

if [ $ERROR_COUNT -eq 0 ]; then
    echo -e "${GREEN}✅ All required variables are set and validated${NC}"
    echo ""
    echo "Summary:"
    echo "  - Environment: $ENVIRONMENT"
    echo "  - Container Prefix: $CONTAINER_PREFIX"
    echo "  - Kafka: $KAFKA_BOOTSTRAP_SERVERS"
    echo "  - PostgreSQL: $POSTGRES_HOST:$POSTGRES_PORT"
    echo "  - App Database: ${APP_POSTGRES_USER}@${APP_POSTGRES_HOST}"
    echo ""
    echo -e "${GREEN}Ready to deploy!${NC}"
    exit 0
else
    echo -e "${RED}❌ Validation failed with $ERROR_COUNT error(s)${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Copy the .env file: cp $ENV_FILE ${ENV_FILE}.local"
    echo "  2. Edit and set missing values: nano ${ENV_FILE}.local"
    echo "  3. Re-run validation: $0 ${ENV_FILE}.local"
    echo ""
    exit 1
fi
