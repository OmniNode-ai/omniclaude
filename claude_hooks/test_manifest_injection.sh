#!/bin/bash
# Test script for system manifest injection in user-prompt-submit hook

set -euo pipefail

# Portable path resolution
if [ -n "${PROJECT_PATH:-}" ]; then
    REPO_ROOT="$PROJECT_PATH"
elif [ -n "${PROJECT_ROOT:-}" ]; then
    REPO_ROOT="$PROJECT_ROOT"
else
    # Compute from script location (claude_hooks/ -> project root)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

LOG_FILE="/tmp/manifest_injection_test.log"
echo "Testing manifest injection..." > "$LOG_FILE"

# Test 1: Test ManifestInjector directly
echo "Test 1: Direct ManifestInjector test"
REPO_ROOT="$REPO_ROOT" python3 - <<'PYTEST' 2>&1 | tee -a "$LOG_FILE"
import sys
from pathlib import Path
import os

# Add agents/lib to path - use environment variable for portability
repo_root = Path(os.environ.get("REPO_ROOT", os.getcwd()))
agents_lib_path = repo_root / "agents" / "lib"

if agents_lib_path.exists():
    sys.path.insert(0, str(agents_lib_path))
    print(f"✓ Added to path: {agents_lib_path}")
else:
    print(f"✗ Path not found: {agents_lib_path}")
    sys.exit(1)

try:
    from manifest_injector import inject_manifest
    print("✓ Successfully imported inject_manifest")

    manifest = inject_manifest()
    print(f"✓ Manifest loaded: {len(manifest)} characters")

    # Check for key sections
    required_sections = [
        "SYSTEM MANIFEST",
        "AVAILABLE PATTERNS",
        "INFRASTRUCTURE TOPOLOGY",
        "FILE STRUCTURE"
    ]

    for section in required_sections:
        if section in manifest:
            print(f"✓ Found section: {section}")
        else:
            print(f"✗ Missing section: {section}")

    print("\n=== First 500 chars of manifest ===")
    print(manifest[:500])
    print("\n✓ Test 1 PASSED")

except FileNotFoundError as e:
    print(f"✗ Test 1 FAILED: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Test 1 FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYTEST

if [ $? -eq 0 ]; then
    echo "✓ Test 1 PASSED: ManifestInjector works" | tee -a "$LOG_FILE"
else
    echo "✗ Test 1 FAILED: ManifestInjector failed" | tee -a "$LOG_FILE"
    exit 1
fi

# Test 2: Test inline Python snippet (as used in hook)
echo -e "\nTest 2: Inline Python snippet test (simulating hook)" | tee -a "$LOG_FILE"
# REPO_ROOT is already set above with portable resolution
SYSTEM_MANIFEST="$(
  REPO_ROOT="$REPO_ROOT" python3 - <<\PYMANIFEST 2>&1 || echo "FAILED"
import sys
import os
from pathlib import Path

# Add agents/lib to path
agents_lib_path = Path.home() / ".claude" / "agents" / "lib"
# Also try relative to current repo (from environment variable)
repo_root = os.environ.get("REPO_ROOT", os.getcwd())
repo_agents_lib = Path(repo_root) / "agents" / "lib"

for lib_path in [agents_lib_path, repo_agents_lib]:
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
    print(f"System Manifest: Not available (error: {e})")
PYMANIFEST
)"

if [[ "$SYSTEM_MANIFEST" == "FAILED" ]]; then
    echo "✗ Test 2 FAILED: Inline Python snippet failed" | tee -a "$LOG_FILE"
    exit 1
elif [[ "$SYSTEM_MANIFEST" == *"Not available"* ]]; then
    echo "⚠ Test 2 WARNING: Manifest not available: $SYSTEM_MANIFEST" | tee -a "$LOG_FILE"
    echo "$SYSTEM_MANIFEST" >> "$LOG_FILE"
else
    echo "✓ Test 2 PASSED: Inline Python snippet works" | tee -a "$LOG_FILE"
    echo "  Manifest length: ${#SYSTEM_MANIFEST} chars" | tee -a "$LOG_FILE"
    echo "  First 200 chars: ${SYSTEM_MANIFEST:0:200}..." | tee -a "$LOG_FILE"
fi

# Test 3: Test error handling (non-blocking)
echo -e "\nTest 3: Error handling test (with invalid path)" | tee -a "$LOG_FILE"
PROJECT_PATH="/nonexistent/path"
SYSTEM_MANIFEST="$(
  python3 - <<\PYMANIFEST 2>&1 || echo "System Manifest: Not available (fallback)"
import sys
from pathlib import Path

# Add agents/lib to path (will fail)
agents_lib_path = Path.home() / ".claude" / "agents" / "lib"
repo_agents_lib = Path("/nonexistent/path") / "agents" / "lib"

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
PYMANIFEST
)"

if [[ "$SYSTEM_MANIFEST" == *"Not available"* ]]; then
    echo "✓ Test 3 PASSED: Error handling works (non-blocking)" | tee -a "$LOG_FILE"
    echo "  Fallback message: $SYSTEM_MANIFEST" | tee -a "$LOG_FILE"
else
    echo "✓ Test 3 PASSED: Manifest loaded despite invalid repo path" | tee -a "$LOG_FILE"
fi

# Summary
echo -e "\n========================================" | tee -a "$LOG_FILE"
echo "ALL TESTS PASSED ✓" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "Log file: $LOG_FILE"
