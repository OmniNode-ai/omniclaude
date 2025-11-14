#!/bin/bash
# Functional Test: Intelligence Integration
# Tests actual Qdrant queries, pattern retrieval, and manifest injection
# Author: OmniClaude Intelligence Testing Suite
# Version: 1.0.0

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

# Load environment variables
if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
else
    echo -e "${RED}❌ .env file not found at $PROJECT_ROOT/.env${NC}"
    exit 1
fi

echo "=== Intelligence Functional Test ==="
echo "Project Root: $PROJECT_ROOT"
echo "Timestamp: $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
echo ""

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

# Helper function for test results
pass_test() {
    echo -e "${GREEN}✅ $1${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

fail_test() {
    echo -e "${RED}❌ $1${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

warn_test() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# ============================================
# TEST 1: Qdrant Connectivity
# ============================================
echo "TEST 1: Qdrant Connectivity"
echo "----------------------------"

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
echo "Testing connection to: $QDRANT_URL"

if curl -sf "$QDRANT_URL/collections" > /dev/null; then
    pass_test "Qdrant is accessible"
else
    fail_test "Qdrant is not accessible at $QDRANT_URL"
    echo "  Hint: Check if Qdrant container is running: docker ps | grep qdrant"
    exit 1
fi

# Test health endpoint (optional - some Qdrant versions don't have this)
set +e  # Temporarily disable exit on error for health checks
curl -sf "$QDRANT_URL/healthz" > /dev/null 2>&1
HEALTHZ_CODE=$?
curl -sf "$QDRANT_URL/" > /dev/null 2>&1
ROOT_CODE=$?
set -e  # Re-enable exit on error

if [ $HEALTHZ_CODE -eq 0 ]; then
    pass_test "Qdrant health check passed (/healthz)"
elif [ $ROOT_CODE -eq 0 ]; then
    pass_test "Qdrant root endpoint responding"
else
    warn_test "Qdrant health endpoints not available (using /collections as health check)"
fi

echo ""

# ============================================
# TEST 2: Collection Verification
# ============================================
echo "TEST 2: Collection Verification"
echo "--------------------------------"

# Get repo root and create tmp directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
mkdir -p "$REPO_ROOT/tmp"

# Active collections (should have data)
ACTIVE_COLLECTIONS=("archon_vectors" "code_generation_patterns")
# Planned collections (expected to be empty)
PLANNED_COLLECTIONS=("archon-intelligence" "quality_vectors")
COLLECTION_STATS_FILE="$REPO_ROOT/tmp/qdrant_collection_stats.json"

echo "Active Collections (should have data):"
for collection in "${ACTIVE_COLLECTIONS[@]}"; do
    echo -n "  Checking collection: $collection... "

    if curl -sf "$QDRANT_URL/collections/$collection" > "$COLLECTION_STATS_FILE" 2>&1; then
        if jq -e '.result' "$COLLECTION_STATS_FILE" > /dev/null 2>&1; then
            POINTS_COUNT=$(jq -r '.result.points_count' "$COLLECTION_STATS_FILE")
            VECTORS_COUNT=$(jq -r '.result.vectors_count // .result.points_count' "$COLLECTION_STATS_FILE")

            if [ "$POINTS_COUNT" -gt 0 ]; then
                pass_test "$collection exists with $POINTS_COUNT vectors"
            else
                warn_test "$collection exists but is empty (0 vectors) - should be populated!"
            fi
        else
            fail_test "$collection - invalid response"
        fi
    else
        fail_test "$collection does not exist - required for pattern discovery!"
    fi
done

echo ""
echo "Planned Collections (reserved for future use):"
for collection in "${PLANNED_COLLECTIONS[@]}"; do
    echo -n "  Checking collection: $collection... "

    if curl -sf "$QDRANT_URL/collections/$collection" > "$COLLECTION_STATS_FILE" 2>&1; then
        if jq -e '.result' "$COLLECTION_STATS_FILE" > /dev/null 2>&1; then
            POINTS_COUNT=$(jq -r '.result.points_count' "$COLLECTION_STATS_FILE")
            VECTORS_COUNT=$(jq -r '.result.vectors_count // .result.points_count' "$COLLECTION_STATS_FILE")

            if [ "$POINTS_COUNT" -gt 0 ]; then
                echo -e "${GREEN}✅ $collection has $POINTS_COUNT vectors (populated)${NC}"
            else
                echo -e "${GREEN}ℹ️  $collection exists and is empty (as expected - planned for future use)${NC}"
            fi
        else
            echo -e "${YELLOW}⚠️  $collection - invalid response${NC}"
        fi
    else
        echo -e "${GREEN}ℹ️  $collection does not exist yet (will be created when needed)${NC}"
    fi
done

rm -f "$COLLECTION_STATS_FILE"
echo ""

# ============================================
# TEST 3: Pattern Retrieval
# ============================================
echo "TEST 3: Pattern Retrieval from Qdrant"
echo "--------------------------------------"

echo "Testing pattern retrieval via Python..."

python3 << EOF
import sys
import json
from pathlib import Path

# Add project paths
project_root = Path("$PROJECT_ROOT")
sys.path.insert(0, str(project_root / "agents" / "lib"))

try:
    from qdrant_client import QdrantClient

    client = QdrantClient(host="localhost", port=6333)

    # Test archon_vectors collection (main pattern collection)
    print("Querying archon_vectors collection...")
    results = client.scroll(
        collection_name="archon_vectors",
        limit=5,
        with_payload=True
    )

    points, next_offset = results

    if len(points) > 0:
        print(f"✅ Retrieved {len(points)} patterns from archon_vectors")

        # Show first pattern
        first_pattern = points[0]
        payload = first_pattern.payload

        print(f"   Example pattern:")
        print(f"   - Name: {payload.get('name', 'N/A')}")
        print(f"   - File: {payload.get('file_path', 'N/A')}")
        print(f"   - Confidence: {payload.get('confidence', 'N/A')}")

        # Exit code 0 for success
        sys.exit(0)
    else:
        print("❌ No patterns found in archon_vectors")
        sys.exit(1)

except ImportError as e:
    print(f"❌ Failed to import required modules: {e}")
    print("   Hint: Install qdrant-client: pip install qdrant-client")
    sys.exit(1)
except Exception as e:
    print(f"❌ Pattern retrieval failed: {e}")
    sys.exit(1)
EOF

if [ $? -eq 0 ]; then
    pass_test "Pattern retrieval successful"
else
    fail_test "Pattern retrieval failed"
fi

echo ""

# ============================================
# TEST 4: Manifest Injection (Async)
# ============================================
echo "TEST 4: Manifest Injection (Async Test)"
echo "-----------------------------------------------"

echo "Testing async manifest injection with real intelligence gathering..."

python3 << EOF
import sys
import os
import asyncio
from pathlib import Path
from datetime import datetime, UTC

# Add project paths
project_root = Path("$PROJECT_ROOT")
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agents" / "lib"))

# Set required environment variables
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("POSTGRES_HOST", "192.168.86.200")
os.environ.setdefault("POSTGRES_PORT", "5436")

async def test_manifest_injection():
    try:
        from manifest_injector import inject_manifest_async

        # Generate test correlation ID
        correlation_id = f"test-intelligence-{datetime.now(UTC).isoformat()}"

        print(f"Testing manifest injection...")
        print(f"Correlation ID: {correlation_id}")

        # Run manifest injection
        import time
        start = time.time()
        manifest = await inject_manifest_async(correlation_id)
        elapsed_ms = (time.time() - start) * 1000

        # Validate results
        if not manifest or len(manifest) < 100:
            print(f"❌ Manifest generation failed (length: {len(manifest) if manifest else 0})")
            sys.exit(1)

        print(f"✅ Manifest generated: {len(manifest)} characters")
        print(f"✅ Query time: {elapsed_ms:.0f}ms", end="")

        if elapsed_ms < 2000:
            print(" (excellent)")
        elif elapsed_ms < 5000:
            print(" (acceptable)")
        else:
            print(" (slow but functional)")

        # Check for patterns in manifest
        pattern_count = manifest.count("pattern") + manifest.count("Pattern")
        if pattern_count > 0:
            print(f"✅ Patterns found in manifest: ~{pattern_count} references")

        sys.exit(0)

    except Exception as e:
        print(f"❌ Manifest injection test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

asyncio.run(test_manifest_injection())
EOF

if [ $? -eq 0 ]; then
    pass_test "Manifest injection test passed"
else
    fail_test "Manifest injection test failed"
fi

echo ""

# ============================================
# TEST 5: Intelligence Query Performance
# ============================================
echo "TEST 5: Intelligence Query Performance"
echo "---------------------------------------"

echo "Testing query response times..."

python3 << EOF
import sys
import time
from pathlib import Path

# Add project paths
project_root = Path("$PROJECT_ROOT")
sys.path.insert(0, str(project_root / "agents" / "lib"))

try:
    from qdrant_client import QdrantClient

    client = QdrantClient(host="localhost", port=6333)

    # Perform 3 test queries and measure time
    query_times = []

    for i in range(3):
        start = time.time()
        results = client.scroll(
            collection_name="archon_vectors",
            limit=10
        )
        elapsed_ms = (time.time() - start) * 1000
        query_times.append(elapsed_ms)

    avg_time = sum(query_times) / len(query_times)
    min_time = min(query_times)
    max_time = max(query_times)

    print(f"Query Performance (3 runs):")
    print(f"  - Average: {avg_time:.0f}ms")
    print(f"  - Min: {min_time:.0f}ms")
    print(f"  - Max: {max_time:.0f}ms")

    # Performance thresholds
    if avg_time < 100:
        print("✅ Excellent performance (<100ms)")
        sys.exit(0)
    elif avg_time < 500:
        print("✅ Good performance (<500ms)")
        sys.exit(0)
    elif avg_time < 2000:
        print("⚠️  Acceptable performance (<2000ms)")
        sys.exit(0)
    else:
        print(f"❌ Slow performance (>{avg_time:.0f}ms)")
        sys.exit(1)

except Exception as e:
    print(f"❌ Performance test failed: {e}")
    sys.exit(1)
EOF

if [ $? -eq 0 ]; then
    pass_test "Query performance test passed"
else
    fail_test "Query performance test failed"
fi

echo ""

# ============================================
# TEST 6: Cache Availability (Optional)
# ============================================
echo "TEST 6: Cache Availability (Optional)"
echo "--------------------------------------"

VALKEY_URL="${VALKEY_URL:-redis://localhost:6379}"

# Parse Redis URL (handles both redis://host:port and redis://:password@host:port/db)
if echo "$VALKEY_URL" | grep -q "@"; then
    # URL has authentication: redis://:password@host:port/db
    REDIS_PASSWORD=$(echo "$VALKEY_URL" | sed 's|redis://:\([^@]*\)@.*|\1|')
    REDIS_HOST=$(echo "$VALKEY_URL" | sed 's|.*@\([^:]*\):.*|\1|')
    REDIS_PORT=$(echo "$VALKEY_URL" | sed 's|.*:\([0-9][0-9]*\)/.*|\1|; s|.*:\([0-9][0-9]*\)$|\1|')
else
    # URL has no authentication: redis://host:port
    REDIS_PASSWORD=""
    REDIS_HOST=$(echo "$VALKEY_URL" | sed 's|redis://\([^:]*\):.*|\1|')
    REDIS_PORT=$(echo "$VALKEY_URL" | sed 's|.*:\([0-9][0-9]*\).*|\1|')
fi

# Override Docker internal hostnames for host scripts (same pattern as PostgreSQL test)
if [ "$REDIS_HOST" = "archon-valkey" ]; then
    REDIS_HOST="localhost"
fi

echo "Testing cache at: $REDIS_HOST:$REDIS_PORT"

if command -v redis-cli &> /dev/null; then
    # Build redis-cli command with optional password
    REDIS_CMD="redis-cli -h $REDIS_HOST -p $REDIS_PORT"
    if [ -n "$REDIS_PASSWORD" ]; then
        REDIS_CMD="$REDIS_CMD -a $REDIS_PASSWORD"
    fi

    if $REDIS_CMD PING > /dev/null 2>&1; then
        pass_test "Cache (Valkey/Redis) is available"

        # Check cache keys
        KEY_COUNT=$($REDIS_CMD DBSIZE 2>/dev/null | awk '{print $2}')
        echo "   Cache keys: ${KEY_COUNT:-0}"
    else
        warn_test "Cache (Valkey/Redis) not available (this is optional)"
    fi
else
    warn_test "redis-cli not installed (skipping cache test)"
fi

echo ""

# ============================================
# TEST SUMMARY
# ============================================
echo "=========================================="
echo "TEST SUMMARY"
echo "=========================================="
echo "Passed: $TESTS_PASSED"
echo "Failed: $TESTS_FAILED"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ ALL TESTS PASSED${NC}"
    echo ""
    echo "Intelligence infrastructure is functional!"
    echo ""
    echo "Next steps:"
    echo "  - Run agent with manifest injection enabled"
    echo "  - Check agent_manifest_injections table for records"
    echo "  - Monitor query times in production"
    exit 0
else
    echo -e "${RED}❌ SOME TESTS FAILED${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check Qdrant container: docker ps | grep qdrant"
    echo "  2. Check Qdrant logs: docker logs archon-qdrant"
    echo "  3. Verify collections: curl http://localhost:6333/collections"
    echo "  4. Check .env configuration"
    exit 1
fi
