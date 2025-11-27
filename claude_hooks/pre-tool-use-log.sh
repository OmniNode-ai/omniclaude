#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${HOME}/.claude/logs"
mkdir -p "${LOG_DIR}"

# Use PID and RANDOM for uniqueness (macOS date doesn't support %N nanoseconds)
TS="$(date -u +"%Y-%m-%dT%H_%M_%S")_$$_${RANDOM}"
LOG_FILE="${LOG_DIR}/pre_tool_use_${TS}.json"

# Copy stdin to both file and stdout so Claude still sees it
tee "${LOG_FILE}"
