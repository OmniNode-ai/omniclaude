#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Run all local validation checks in CI order.
# Usage: ./scripts/validate-local.sh [--quick]
#
# --quick: skip slow checks (full test suite, pyright)
set -euo pipefail

QUICK="${1:-}"
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
PASS=0
FAIL=0

run_check() {
    local name="$1"
    shift
    printf "%-45s " "$name"
    if "$@" > /dev/null 2>&1; then
        echo -e "${GREEN}PASS${NC}"
        PASS=$((PASS + 1))
    else
        echo -e "${RED}FAIL${NC}"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== omniclaude local validation ==="
echo ""

# Quality
run_check "ruff format" uv run ruff format --check src/ tests/
run_check "ruff lint" uv run ruff check src/ tests/
run_check "mypy" uv run mypy src/ --ignore-missing-imports

if [ "$QUICK" != "--quick" ]; then
    run_check "pyright" uv run pyright src/omniclaude/
fi

# Architecture
run_check "exports validation" uv run python scripts/validation/validate_exports.py
run_check "enum governance" uv run python scripts/validation/validate_enum_governance.py
run_check "no hardcoded IPs" uv run python scripts/validation/validate_no_hardcoded_ip.py
run_check "no DB in orchestrator" uv run python scripts/validation/validate_no_db_in_orchestrator.py
run_check "no git outside effects" uv run python scripts/validation/validate_no_git_outside_effects.py
run_check "no direct Kafka producer" uv run python scripts/validation/validate_no_direct_kafka_producer.py
run_check "topic naming" uv run python scripts/validation/validate_topic_naming.py
run_check "no hardcoded Kafka broker" uv run python scripts/validation/validate_no_hardcoded_kafka_broker.py

# Tests
if [ "$QUICK" != "--quick" ]; then
    run_check "unit tests" uv run pytest tests/ -m unit -q --tb=no
fi

echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}Local validation failed. Fix issues before pushing.${NC}"
    exit 1
else
    echo -e "${GREEN}All checks passed.${NC}"
    exit 0
fi
