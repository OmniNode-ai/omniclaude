#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${HOME}/.claude/logs"
mkdir -p "${LOG_DIR}"

# Generate high-precision timestamp with collision-resistant unique identifier
# - Uses microseconds via Python (macOS date doesn't support %N nanoseconds)
# - Combines PID + multiple random values for uniqueness
# - Uses /dev/urandom for cryptographic randomness when available

# Get microsecond-precision timestamp (Python is standard on macOS)
# Uses timezone-aware API to avoid deprecation warnings in Python 3.12+
if command -v python3 >/dev/null 2>&1; then
    TS="$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H_%M_%S_%f"))' 2>/dev/null)" || \
    TS="$(python3 -c 'import datetime; print(datetime.datetime.utcnow().strftime("%Y-%m-%dT%H_%M_%S_%f"))')"
elif command -v python >/dev/null 2>&1; then
    TS="$(python -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H_%M_%S_%f"))' 2>/dev/null)" || \
    TS="$(python -c 'import datetime; print(datetime.datetime.utcnow().strftime("%Y-%m-%dT%H_%M_%S_%f"))')"
else
    # Fallback to second precision if Python unavailable
    TS="$(date -u +"%Y-%m-%dT%H_%M_%S_000000")"
fi

# Generate unique identifier using multiple entropy sources
# Format: PID_RANDOM1_RANDOM2_URANDOM (8 hex chars from /dev/urandom)
if [ -r /dev/urandom ]; then
    UNIQUE_ID="${$}_${RANDOM}_${RANDOM}_$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n')"
else
    # Fallback: use multiple RANDOM calls and current nanoseconds if available
    UNIQUE_ID="${$}_${RANDOM}_${RANDOM}_${RANDOM}"
fi

LOG_FILE="${LOG_DIR}/pre_tool_use_${TS}_${UNIQUE_ID}.json"

# Atomic file creation: write to temp file, then rename
# This prevents partial writes from being visible
# Note: macOS mktemp doesn't expand template patterns, so use default temp directory
TEMP_FILE="$(mktemp)"

# Ensure temp file is cleaned up on any exit (script failure, signal, etc.)
cleanup() {
    [ -f "${TEMP_FILE}" ] && rm -f "${TEMP_FILE}" 2>/dev/null || true
}
trap cleanup EXIT

# Copy stdin to both temp file and stdout, then atomically move to final location
tee "${TEMP_FILE}"
mv -f "${TEMP_FILE}" "${LOG_FILE}"

# Disable cleanup trap since file was successfully moved
trap - EXIT
