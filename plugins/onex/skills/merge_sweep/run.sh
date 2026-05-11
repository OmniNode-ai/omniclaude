#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# run.sh — thin wrapper for /onex:merge_sweep.
# Delegates to _lib/run.py which dispatches through the runtime ingress
# (SSH socket → HTTP → Kafka) instead of calling onex run-node directly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Use the plugin Python interpreter if set, otherwise fall back to the brew
# canonical Python (required for macOS LAN access — see omniclaude/CLAUDE.md §11).
PYTHON_BIN="${PLUGIN_PYTHON_BIN:-/opt/homebrew/bin/python3.13}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 2>/dev/null || echo "")"
  if [[ -z "${PYTHON_BIN}" ]]; then
    echo "No Python interpreter found. Set PLUGIN_PYTHON_BIN to the correct path." >&2
    exit 1
  fi
fi

# Forward all CLI args to the Python entry point.
exec env -u PYTHONPATH \
  PYTHONPATH="${PLUGIN_ROOT}/../../src:${PLUGIN_ROOT}/hooks/lib" \
  "${PYTHON_BIN}" "${SCRIPT_DIR}/_lib/run.py" "$@"
