#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Read the declared agent host off a hook's own command line (OMN-18704).
#
# This does no validation on purpose. The allowlist lives in exactly one place
# -- hooks/lib/hook_actor.py -- so a second copy here could drift from it and
# would be the harder of the two to test. The shell half only lifts the raw
# value out of argv; hook_emit_append.py resolves and validates it.
#
# Codex runs hook commands through a shell, so both forms below work and both
# reach this function or the environment it falls back to:
#
#     "command": ".../post_tool_use_bus_mirror.sh --actor codex"
#     "command": "ONEX_HOOK_ACTOR=codex .../post_tool_use_bus_mirror.sh"
#
# Fail-open like everything on this path: an odd argv yields an empty string,
# which downstream resolves to the Claude default.

# Echo the value that follows `--actor` (or `--actor=<value>`) in the caller's
# argv, or nothing when it is absent. Unknown flags are skipped, not fatal.
onex_hook_actor_arg() {
    while (($# > 0)); do
        case "$1" in
            --actor)
                printf '%s' "${2:-}"
                return 0
                ;;
            --actor=*)
                printf '%s' "${1#--actor=}"
                return 0
                ;;
            *)
                shift
                ;;
        esac
    done
    return 0
}
