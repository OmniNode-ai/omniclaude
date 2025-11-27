#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${HOME}/.claude/logs"
mkdir -p "${LOG_DIR}"

TS="$(date -Iseconds | tr ':' '_')"
LOG_FILE="${LOG_DIR}/pre_tool_use_${TS}.json"

# Copy stdin to both file and stdout so Claude still sees it
tee "${LOG_FILE}"
