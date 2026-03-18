#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# mode.sh - OMNICLAUDE_MODE resolution [OMN-5396]
#
# Resolves the current plugin operating mode.  Sourced by hook scripts to
# decide whether to run (full mode) or exit early (lite mode).
#
# Resolution order:
#   1. OMNICLAUDE_MODE env var (explicit override)
#   2. ~/.config/omniclaude/mode  (persistent user preference)
#   3. Default: "full"
#
# Valid values: "full" | "lite"

omniclaude_mode() {
    # 1. Env var (highest priority)
    if [[ -n "${OMNICLAUDE_MODE:-}" ]]; then
        case "$OMNICLAUDE_MODE" in
            full|lite) echo "$OMNICLAUDE_MODE"; return 0 ;;
        esac
    fi

    # 2. Persistent config file
    local config_file="${HOME}/.config/omniclaude/mode"
    if [[ -f "$config_file" ]]; then
        local val
        val=$(<"$config_file")
        val="${val%%[[:space:]]*}"  # trim trailing whitespace/newlines
        case "$val" in
            full|lite) echo "$val"; return 0 ;;
        esac
    fi

    # 3. Default
    echo "full"
}
