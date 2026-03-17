#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Delegation Config Reader
#
# Parses config.yaml once → writes JSON to /tmp/omniclaude-delegation-config.json
# Shell scripts read values via jq from that JSON file.
# Falls back to hardcoded defaults if Python or config unavailable.
#
# Usage (source from consumer scripts):
#   source "${SCRIPT_DIR}/delegation-config.sh"
#   WRITE_WARN=$(_dc_read '.write_warn_threshold' '3')
#
# IMPORTANT: This file is sourced under set -euo pipefail from consumer scripts.
# Every command that can fail MUST have || true or || fallback to prevent killing the parent.

# SCRIPT_DIR must be set by the caller before sourcing this file.
# Consumer scripts resolve it before cd $HOME to avoid relative path breakage.
_DC_SCRIPT_DIR="${SCRIPT_DIR:-}"
if [[ -z "$_DC_SCRIPT_DIR" ]]; then
    _DC_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || _DC_SCRIPT_DIR=""
fi
_DC_HOOKS_DIR=""
if [[ -n "$_DC_SCRIPT_DIR" ]]; then
    _DC_HOOKS_DIR="$(cd "${_DC_SCRIPT_DIR}/.." && pwd)" || _DC_HOOKS_DIR=""
fi
CONFIG_YAML="${_DC_HOOKS_DIR:+${_DC_HOOKS_DIR}/config.yaml}"
CONFIG_JSON="/tmp/omniclaude-delegation-config.json"
CONFIG_STALE_MS=5000  # re-parse if older than 5s

_dc_needs_refresh() {
    [[ ! -f "$CONFIG_JSON" ]] && return 0
    [[ -z "$CONFIG_YAML" ]] && return 1
    # Check file age — use stat instead of python3 for reliability
    local file_mod_epoch now_epoch age_s
    file_mod_epoch=$(stat -f %m "$CONFIG_JSON" 2>/dev/null) || return 0
    now_epoch=$(date +%s 2>/dev/null) || return 0
    age_s=$(( now_epoch - file_mod_epoch ))
    [[ $age_s -gt 5 ]] && return 0
    return 1
}

_dc_parse() {
    [[ -z "$CONFIG_YAML" ]] && return 1
    [[ ! -f "$CONFIG_YAML" ]] && return 1
    python3 -c "
import json,sys
try:
    import yaml
except ImportError:
    json.dump({}, sys.stdout)
    sys.exit(0)
try:
    with open(sys.argv[1]) as f:
        cfg = yaml.safe_load(f) or {}
    de = cfg.get('delegation_enforcement', {})
    json.dump(de, sys.stdout)
except Exception:
    json.dump({}, sys.stdout)
" "$CONFIG_YAML" > "$CONFIG_JSON" 2>/dev/null || return 1
}

_dc_read() {
    # Read a value from the cached JSON. $1=jq path, $2=default
    local val
    val=$(jq -r "$1 // empty" "$CONFIG_JSON" 2>/dev/null) || val=""
    echo "${val:-$2}"
}

_dc_read_array() {
    # Read a JSON array as newline-separated values. $1=jq path
    jq -r "$1[]? // empty" "$CONFIG_JSON" 2>/dev/null || true
}

# Parse if needed (all failures are non-fatal)
if _dc_needs_refresh; then
    _dc_parse || true
fi

# If JSON still missing/empty, use legacy defaults and WARN
if [[ ! -s "$CONFIG_JSON" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [delegation-config] WARNING: config parse failed, falling back to legacy thresholds — read-only enforcement DISABLED" >> "${LOG_FILE:-$HOME/.claude/hooks.log}" 2>/dev/null || true
fi
