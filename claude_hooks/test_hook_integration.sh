#!/bin/bash
# End-to-end integration test for enhanced metadata in UserPromptSubmit hook

set -euo pipefail

echo "================================================================================"
echo "ENHANCED METADATA HOOK INTEGRATION TEST"
echo "================================================================================"

HOOKS_LIB="$HOME/.claude/hooks/lib"
export PYTHONPATH="${HOOKS_LIB}:${PYTHONPATH:-}"

# Test 1: Verify metadata extractor exists
echo ""
echo "[Test 1] Checking metadata extractor..."
if [[ -f "${HOOKS_LIB}/metadata_extractor.py" ]]; then
    echo "✅ metadata_extractor.py found"
else
    echo "❌ metadata_extractor.py not found"
    exit 1
fi

# Test 2: Test metadata extraction (standalone)
echo ""
echo "[Test 2] Testing standalone metadata extraction..."
METADATA_OUTPUT=$(python3 -c "
import sys
import json
sys.path.insert(0, '${HOOKS_LIB}')

from metadata_extractor import MetadataExtractor

extractor = MetadataExtractor()
metadata = extractor.extract_all('Fix authentication bug in login.py')
print(json.dumps(metadata, indent=2))
" 2>/dev/null)

if [[ -n "$METADATA_OUTPUT" ]]; then
    echo "✅ Metadata extraction working"
else
    echo "❌ Metadata extraction failed"
    exit 1
fi

# Test 3: Performance benchmark
echo ""
echo "[Test 3] Running performance benchmark..."
python3 -c "
import sys
import time
sys.path.insert(0, '${HOOKS_LIB}')

from metadata_extractor import MetadataExtractor

extractor = MetadataExtractor()

# Run 10 iterations
times = []
for _ in range(10):
    start = time.perf_counter()
    metadata = extractor.extract_all('Test prompt')
    elapsed = (time.perf_counter() - start) * 1000
    times.append(elapsed)

avg = sum(times) / len(times)
print(f'Average: {avg:.2f}ms')
print(f'Target: <15ms')
print(f'Status: {\"✅ PASS\" if avg < 15 else \"❌ FAIL\"}')
" 2>/dev/null

echo ""
echo "================================================================================"
echo "✅ INTEGRATION TEST COMPLETE"
echo "================================================================================"
