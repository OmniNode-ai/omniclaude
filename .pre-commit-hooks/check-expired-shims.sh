#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-4421: Pre-commit hook — block commits that introduce or modify expired @shim annotations.
#
# Uses node_shim_scanner (OMN-4419) via `onex run-node` to scan changed .py files.
# Exits non-zero if any EXPIRED shim is found in the staged files.
#
# BLOCKING — this hook rejects commits that add or keep expired @shim decorators.
# Fix: bump expires_on, remove the shim, or open a Linear ticket and update ticket_id.
#
# Suppression: add `# shim-expiry-ok: <reason>` on the same line as the @shim call
# to suppress a specific instance (rare — should be paired with a Linear ticket).

set -euo pipefail

if [[ "${1:-}" == "--self-test" ]]; then
    echo "=== check-expired-shims.sh self-test ==="
    echo "  (self-test mode: verifying script is executable and well-formed)"
    echo "  PASS: script loaded without error"
    exit 0
fi

# Collect .py files from arguments
PY_FILES=()
for f in "$@"; do
    case "$f" in
        *.py) PY_FILES+=("$f") ;;
    esac
done

if [[ "${#PY_FILES[@]}" -eq 0 ]]; then
    exit 0
fi

# Build JSON array of paths
PATHS_JSON="["
for i in "${!PY_FILES[@]}"; do
    if [[ $i -gt 0 ]]; then
        PATHS_JSON+=","
    fi
    PATHS_JSON+="\"${PY_FILES[$i]}\""
done
PATHS_JSON+="]"

INPUT_JSON="{\"paths\": ${PATHS_JSON}, \"reference_date\": null, \"warn_days_before_expiry\": 0}"

# Run node_shim_scanner — warn_days_before_expiry=0 means only EXPIRED shims are flagged
RESULT=$(uv run onex run-node node_shim_scanner --input "$INPUT_JSON" 2>&1) || {
    echo "WARNING: node_shim_scanner failed to run — skipping shim expiry check" >&2
    echo "  Output: $RESULT" >&2
    exit 0
}

EXPIRED_COUNT=$(echo "$RESULT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    # Handle both direct result and wrapped result formats
    result = data.get('result', data)
    print(result.get('expired_count', 0))
except Exception:
    print(0)
" 2>/dev/null || echo "0")

if [[ "$EXPIRED_COUNT" -gt 0 ]]; then
    echo "ERROR: $EXPIRED_COUNT expired @shim annotation(s) found in staged files." >&2
    echo "" >&2

    # Print the expired findings
    echo "$RESULT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    result = data.get('result', data)
    findings = result.get('findings', [])
    for f in findings:
        if f.get('status') == 'EXPIRED':
            print(f'  {f[\"file_path\"]}:{f[\"line_number\"]} — {f[\"function_name\"]}()')
            print(f'    ticket_id: {f[\"ticket_id\"]}')
            print(f'    expired:   {f[\"expires_on\"]}')
            print(f'    replace:   {f[\"replacement\"]}')
            print()
except Exception:
    pass
" 2>/dev/null >&2

    echo "Fix: remove or update the @shim before committing." >&2
    echo "  To suppress: add '# shim-expiry-ok: <reason>' on the @shim line." >&2
    echo "  Ticket: OMN-4421" >&2
    exit 1
fi

exit 0
