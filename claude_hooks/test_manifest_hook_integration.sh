#!/bin/bash
# Test manifest injection as used in actual hook

set -euo pipefail

echo "=========================================="
echo "Testing Hook Manifest Integration"
echo "=========================================="

PROJECT_PATH="/Volumes/PRO-G40/Code/omniclaude"

# Test the exact code snippet from the hook
echo "Test: Manifest loading (exact hook code)"

SYSTEM_MANIFEST="$(
  PROJECT_PATH="$PROJECT_PATH" python3 - <<'PYMANIFEST' 2>&1 || echo ""
import sys
import os
from pathlib import Path

# Add agents/lib to path - try multiple locations
project_path = os.environ.get("PROJECT_PATH", "")
search_paths = [
    Path.home() / ".claude" / "agents" / "lib",
]

# Add project path if available
if project_path:
    search_paths.append(Path(project_path) / "agents" / "lib")

# Add current working directory as fallback
search_paths.append(Path.cwd() / "agents" / "lib")

for lib_path in search_paths:
    if lib_path.exists():
        sys.path.insert(0, str(lib_path))
        break

try:
    from manifest_injector import inject_manifest
    manifest = inject_manifest()
    print(manifest)
except FileNotFoundError:
    # Manifest file doesn't exist - non-blocking
    print("System Manifest: Not available (file not found)")
except Exception as e:
    # Any other error - non-blocking
    print(f"System Manifest: Not available (error: {str(e)})")
PYMANIFEST
)"

# Check result
if [[ -z "$SYSTEM_MANIFEST" ]]; then
    echo "✗ FAILED: Empty manifest"
    exit 1
elif [[ "$SYSTEM_MANIFEST" == *"Not available"* ]]; then
    echo "✗ FAILED: Manifest not available"
    echo "   Error: $SYSTEM_MANIFEST"
    exit 1
else
    echo "✓ PASSED: Manifest loaded successfully"
    echo "   Length: ${#SYSTEM_MANIFEST} characters"

    # Verify key sections
    if [[ "$SYSTEM_MANIFEST" == *"SYSTEM MANIFEST"* ]]; then
        echo "   ✓ Contains 'SYSTEM MANIFEST'"
    else
        echo "   ✗ Missing 'SYSTEM MANIFEST'"
        exit 1
    fi

    if [[ "$SYSTEM_MANIFEST" == *"AVAILABLE PATTERNS"* ]]; then
        echo "   ✓ Contains 'AVAILABLE PATTERNS'"
    else
        echo "   ✗ Missing 'AVAILABLE PATTERNS'"
        exit 1
    fi

    if [[ "$SYSTEM_MANIFEST" == *"INFRASTRUCTURE TOPOLOGY"* ]]; then
        echo "   ✓ Contains 'INFRASTRUCTURE TOPOLOGY'"
    else
        echo "   ✗ Missing 'INFRASTRUCTURE TOPOLOGY'"
        exit 1
    fi

    # Show preview
    echo ""
    echo "=== Manifest Preview (first 400 chars) ==="
    echo "${SYSTEM_MANIFEST:0:400}..."
fi

echo ""
echo "=========================================="
echo "ALL TESTS PASSED ✓"
echo "=========================================="
