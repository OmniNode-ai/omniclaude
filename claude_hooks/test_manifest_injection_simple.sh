#!/bin/bash
# Simplified test script for system manifest injection

set -euo pipefail

echo "=========================================="
echo "Testing Manifest Injection"
echo "=========================================="

# Test 1: Direct Python import
echo -e "\nTest 1: Direct ManifestInjector import"
python3 <<'PYTEST'
import sys
from pathlib import Path

agents_lib = Path("/Volumes/PRO-G40/Code/omniclaude/agents/lib")
sys.path.insert(0, str(agents_lib))

from manifest_injector import inject_manifest

manifest = inject_manifest()
print(f"✓ Manifest loaded: {len(manifest)} characters")

required_sections = ["SYSTEM MANIFEST", "AVAILABLE PATTERNS", "INFRASTRUCTURE TOPOLOGY"]
for section in required_sections:
    if section in manifest:
        print(f"✓ Found section: {section}")
    else:
        print(f"✗ Missing section: {section}")

print("\n=== Manifest Preview (first 400 chars) ===")
print(manifest[:400])
print("...")
PYTEST

if [ $? -eq 0 ]; then
    echo -e "\n✓ Test 1 PASSED"
else
    echo -e "\n✗ Test 1 FAILED"
    exit 1
fi

# Test 2: Test the exact snippet used in the hook
echo -e "\nTest 2: Hook inline snippet"
cd /Volumes/PRO-G40/Code/omniclaude

# Create a temporary test file
cat > /tmp/test_manifest_inline.py <<'PYCODE'
import sys
from pathlib import Path

# Add agents/lib to path (exactly as in hook)
agents_lib_path = Path.home() / ".claude" / "agents" / "lib"
repo_agents_lib = Path("/Volumes/PRO-G40/Code/omniclaude") / "agents" / "lib"

for lib_path in [agents_lib_path, repo_agents_lib]:
    if lib_path.exists():
        sys.path.insert(0, str(lib_path))
        break

try:
    from manifest_injector import inject_manifest
    manifest = inject_manifest()
    print(manifest)
except FileNotFoundError:
    print("System Manifest: Not available (file not found)")
except Exception as e:
    print(f"System Manifest: Not available (error: {e})")
PYCODE

MANIFEST_OUTPUT="$(python3 /tmp/test_manifest_inline.py)"

if [[ "$MANIFEST_OUTPUT" == *"Not available"* ]]; then
    echo "⚠  Warning: Manifest not available"
    echo "   Message: $MANIFEST_OUTPUT"
    exit 1
elif [[ -n "$MANIFEST_OUTPUT" ]]; then
    echo "✓ Manifest loaded: ${#MANIFEST_OUTPUT} characters"
    echo "✓ First 200 chars: ${MANIFEST_OUTPUT:0:200}..."
else
    echo "✗ Empty output"
    exit 1
fi

echo -e "\n✓ Test 2 PASSED"

# Test 3: Verify it works from hook directory
echo -e "\nTest 3: From hook directory context"
cd /Volumes/PRO-G40/Code/omniclaude/claude_hooks

python3 /tmp/test_manifest_inline.py > /tmp/manifest_test_output.txt 2>&1

if grep -q "SYSTEM MANIFEST" /tmp/manifest_test_output.txt; then
    echo "✓ Manifest contains expected content"
else
    echo "✗ Manifest missing expected content"
    cat /tmp/manifest_test_output.txt
    exit 1
fi

echo -e "\n✓ Test 3 PASSED"

# Summary
echo -e "\n=========================================="
echo "ALL TESTS PASSED ✓"
echo "=========================================="

# Cleanup
rm -f /tmp/test_manifest_inline.py /tmp/manifest_test_output.txt
