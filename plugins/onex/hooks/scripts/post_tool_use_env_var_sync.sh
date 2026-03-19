#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Env Var Sync Hook
# When docker-compose.infra.yml is edited, extracts all ${VARNAME:?...} patterns
# and appends any missing vars to ~/.omnibase/.env with a placeholder value.
#
# Event:   PostToolUse
# Matcher: ^(Edit|Write)$
# Ticket:  OMN-5132

set -euo pipefail

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

# -----------------------------------------------------------------------
# Kill switch
# -----------------------------------------------------------------------
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi
if [[ "${OMNICLAUDE_HOOK_ENV_SYNC:-1}" == "0" ]]; then
    cat
    exit 0
fi

# -----------------------------------------------------------------------
# Read stdin
# -----------------------------------------------------------------------
INPUT=$(cat)

# Pass through immediately — all logic below is non-blocking
printf '%s\n' "$INPUT"

# Guard: jq required for JSON parsing
if ! command -v jq >/dev/null 2>&1; then
    exit 0
fi

# -----------------------------------------------------------------------
# Extract file path from tool input
# -----------------------------------------------------------------------
FILE_PATH=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null) || FILE_PATH=""

if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# -----------------------------------------------------------------------
# Gate: only docker-compose*infra* files
# -----------------------------------------------------------------------
BASENAME=$(basename "$FILE_PATH")
if [[ "$BASENAME" != *docker-compose*infra* && "$BASENAME" != *docker_compose*infra* ]]; then
    exit 0
fi

if [[ ! -f "$FILE_PATH" ]]; then
    exit 0
fi

# -----------------------------------------------------------------------
# Extract ${VARNAME:?...} patterns from the compose file
# -----------------------------------------------------------------------
# Match both ${VARNAME:?message} and ${VARNAME:-default} style required vars.
# We only care about :? (required/fatal) patterns, not :- (optional defaults).
REQUIRED_VARS=$(grep -oP '\$\{[A-Z][A-Z0-9_]+:\?' "$FILE_PATH" 2>/dev/null \
    | grep -oP '[A-Z][A-Z0-9_]+' \
    || true)

if [[ -z "$REQUIRED_VARS" ]]; then
    exit 0
fi

# -----------------------------------------------------------------------
# Load ~/.omnibase/.env and append any missing vars
# -----------------------------------------------------------------------
ENV_FILE="${HOME}/.omnibase/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    exit 0
fi

ADDED=()

while IFS= read -r VAR; do
    [[ -z "$VAR" ]] && continue

    # Skip if already present (any assignment form: VAR= or VAR=value or export VAR=)
    if grep -qP "^(export\s+)?${VAR}=" "$ENV_FILE" 2>/dev/null; then
        continue
    fi

    # Append placeholder
    printf '\n%s=<set_me>  # auto-added by omniclaude hook\n' "$VAR" >> "$ENV_FILE"
    ADDED+=("$VAR")
done <<< "$REQUIRED_VARS"

# -----------------------------------------------------------------------
# Report what was added
# -----------------------------------------------------------------------
if [[ "${#ADDED[@]}" -gt 0 ]]; then
    echo "[env-var-sync] Added ${#ADDED[@]} missing var(s) to ${ENV_FILE}: ${ADDED[*]}" >&2
fi

exit 0
