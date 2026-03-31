#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# _filter_helpers.sh — Skill tier filtering helpers for deploy-local-plugin (OMN-3453, OMN-5400)
#
# Sourced by deploy.sh; also directly sourceable for unit testing.
# Requires the following variables to be set by the caller:
#   LEVEL_FILTER    — "basic" | "intermediate" | "advanced"
#   INCLUDE_DEBUG   — "true" | "false"
#   _LEVEL_EXPLICIT — "true" | "false"  (true when --level was passed explicitly)
#
# Environment variables read:
#   OMNICLAUDE_MODE — "full" | "lite" (default: "full")
#     When "lite", only skills with mode: both are included.
#     When "full" (or unset), all skills pass mode filtering.

# =============================================================================
# _level_rank <level> → prints integer rank (basic=1, intermediate=2, advanced=3)
# Unknown levels return a sentinel rank (100) that sorts after all valid levels,
# causing the <= comparison in _skill_passes_filter to exclude them.
# =============================================================================
_level_rank() {
    case "$1" in
        basic)        echo 1 ;;
        intermediate) echo 2 ;;
        advanced)     echo 3 ;;
        *)            echo 100 ;;  # unknown — sentinel: excluded by <= comparison
    esac
}

# =============================================================================
# _skill_frontmatter_value <skill_md_path> <key>
# Reads a single scalar YAML value from the opening --- ... --- frontmatter block.
# =============================================================================
_skill_frontmatter_value() {
    local skill_md="$1"
    local key="$2"
    awk -v key="${key}:" '
        /^---$/ { delim++; next }
        delim == 1 && index($0, key) == 1 {
            sub(/^[^:]+:[[:space:]]*/, ""); print; exit
        }
        delim >= 2 { exit }
    ' "$skill_md" 2>/dev/null | tr -d '"'"'"
}

# =============================================================================
# _skill_passes_mode_filter <skill_dir> → returns 0 (include) or 1 (exclude)
#
# Mode filtering (OMN-5400):
#   - Reads OMNICLAUDE_MODE from environment (default: "full").
#   - When OMNICLAUDE_MODE=lite, only skills with mode: both pass.
#   - When OMNICLAUDE_MODE=full (or unset), all skills pass mode filtering.
#   - Skills without a mode field default to "full" (excluded in lite mode).
# =============================================================================
_skill_passes_mode_filter() {
    local skill_dir="$1"
    local omniclaude_mode="${OMNICLAUDE_MODE:-full}"

    # In full mode, all skills pass mode filtering
    if [[ "$omniclaude_mode" != "lite" ]]; then
        return 0
    fi

    local skill_md="${skill_dir}/SKILL.md"
    if [[ ! -f "$skill_md" ]]; then
        # No SKILL.md — exclude in lite mode (cannot verify mode: both)
        return 1
    fi

    local skill_mode
    skill_mode="$(_skill_frontmatter_value "$skill_md" "mode")"

    # Default to "full" when mode is missing — excluded in lite mode
    [[ -z "$skill_mode" ]] && skill_mode="full"

    if [[ "$skill_mode" == "both" ]]; then
        return 0
    fi
    return 1
}

# =============================================================================
# _skill_passes_filter <skill_dir> → returns 0 (include) or 1 (exclude)
#
# Rules:
#   - Underscore-prefixed dirs (_lib, _shared, etc.) always pass (internal support libs).
#   - Skills without a SKILL.md always pass level/debug checks (cannot read frontmatter).
#   - Mode filter (OMN-5400): applied first; in lite mode, only mode:both skills pass.
#   - When _LEVEL_EXPLICIT=false (default --level advanced, no explicit flag):
#       only debug:true skills are NOT excluded — full backwards-compatible behaviour.
#   - When _LEVEL_EXPLICIT=true:
#       * debug:true skills excluded unless INCLUDE_DEBUG=true
#       * skill level rank must be <= LEVEL_FILTER rank
# =============================================================================
_skill_passes_filter() {
    local skill_dir="$1"
    local skill_name
    skill_name="$(basename "$skill_dir")"

    # Internal support dirs always pass filtering
    if [[ "$skill_name" == _* ]]; then
        return 0
    fi

    # Mode filter (OMN-5400): in lite mode, only mode:both skills pass
    if ! _skill_passes_mode_filter "$skill_dir"; then
        return 1
    fi

    local skill_md="${skill_dir}/SKILL.md"
    if [[ ! -f "$skill_md" ]]; then
        # No SKILL.md — include unconditionally (can't read frontmatter)
        return 0
    fi

    local skill_level skill_debug
    skill_level="$(_skill_frontmatter_value "$skill_md" "level")"
    skill_debug="$(_skill_frontmatter_value "$skill_md" "debug")"

    # Default to "advanced" when level is missing
    [[ -z "$skill_level" ]] && skill_level="advanced"

    # Debug exclusion only applies when --level was explicitly passed
    if [[ "$skill_debug" == "true" && "$INCLUDE_DEBUG" == "false" && "$_LEVEL_EXPLICIT" == "true" ]]; then
        return 1
    fi

    # Level check: skill rank must be <= requested filter rank
    local requested_rank skill_rank
    requested_rank="$(_level_rank "$LEVEL_FILTER")"
    skill_rank="$(_level_rank "$skill_level")"

    if [[ "$skill_rank" -le "$requested_rank" ]]; then
        return 0
    fi
    return 1
}
