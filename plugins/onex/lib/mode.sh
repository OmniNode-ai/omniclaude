#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# mode.sh - OMNICLAUDE_MODE resolution [OMN-5396, OMN-5397]
#
# Resolves the current plugin operating mode.  Sourced by hook scripts to
# decide whether to run (full mode) or exit early (lite mode).
#
# Resolution order:
#   1. OMNICLAUDE_MODE env var (explicit override)
#   2. ~/.config/omniclaude/mode  (persistent user preference)
#   3. Auto-detect: cwd under omni_home or omni_worktrees → full
#   4. Auto-detect: omnibase_core importable as local dev install → full
#   5. Default: "lite" (graceful degradation for external repos)
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

    # 3. Auto-detect: cwd is under omni_home or omni_worktrees → full
    local cwd="${PWD}"
    if [[ "$cwd" == */omni_home ]] || [[ "$cwd" == */omni_home/* ]] || [[ "$cwd" == */omni_worktrees ]] || [[ "$cwd" == */omni_worktrees/* ]]; then
        echo "full"
        return 0
    fi

    # 4. Auto-detect: omnibase_core importable as local dev install → full
    local loc=""
    local plugin_python="${CLAUDE_PLUGIN_ROOT:-}/lib/.venv/bin/python3"
    if [[ -x "$plugin_python" ]]; then
        loc=$("$plugin_python" -c "import omnibase_core; print(omnibase_core.__file__)" 2>/dev/null || true)
    elif command -v python3 &>/dev/null; then
        loc=$(python3 -c "import omnibase_core; print(omnibase_core.__file__)" 2>/dev/null || true)
    fi
    if [[ -n "$loc" ]] && { [[ "$loc" == */omni_home/* ]] || [[ "$loc" == */omni_worktrees/* ]]; }; then
        echo "full"
        return 0
    fi

    # 5. Default: lite (graceful degradation for external repos)
    echo "lite"
}
