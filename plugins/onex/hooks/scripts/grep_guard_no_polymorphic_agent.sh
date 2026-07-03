#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Regression guard (OMN-9143): block reintroduction of the legacy
# `polymorphic-agent` dispatch target in omniclaude enforcement code paths.
#
# The canonical dispatch namespace is `onex:`-prefixed subagents (with
# `general-purpose` allowed unprefixed). The pre-`onex:` `polymorphic-agent`
# routing target was scrubbed from every enforcement hook; this guard fails
# closed if it ever reappears in the enforcement surface.
#
# SCOPE (enforcement-critical only):
#   - plugins/onex/hooks/scripts/**
#   - plugins/onex/hooks/lib/**
#   - plugins/onex/hooks/hooks.json
#
# Out of scope on purpose (historical/diagnostic, NOT enforcement):
#   - scripts/observability/** routing metrics SQL that measures the legacy
#     agent's transformation rate against historical event rows
#   - tests/lib/core/** routing-fallback tests that assert the documented
#     low-confidence fallback behaviour
#
# Usage:
#   grep_guard_no_polymorphic_agent.sh                 # scan the enforcement tree
#   grep_guard_no_polymorphic_agent.sh -- FILE [FILE]  # scan only given files (pre-commit)
#
# Exit 0 = clean, exit 1 = offender found.
set -euo pipefail

# Repo root: this script lives at plugins/onex/hooks/scripts/, four levels deep.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

# Enforcement surface scanned in full-tree mode.
ENFORCEMENT_GLOBS=(
    "plugins/onex/hooks/scripts"
    "plugins/onex/hooks/lib"
    "plugins/onex/hooks/hooks.json"
)

# Forbidden token: both the kebab-case dispatch target and the snake_case form.
PATTERN='polymorphic[-_]agent'

# This guard script names the token in its own header; allowlist itself so it
# does not flag on its own documentation.
SELF_BASENAME="$(basename "${BASH_SOURCE[0]}")"

is_allowlisted() {
    local f="$1"
    [[ "$(basename "$f")" == "$SELF_BASENAME" ]]
}

scan_files() {
    local rc=0
    local f
    for f in "$@"; do
        [[ -z "$f" ]] && continue
        [[ -f "$f" ]] || continue
        is_allowlisted "$f" && continue
        if grep -E -n -- "$PATTERN" "$f" >/dev/null 2>&1; then
            echo "FORBIDDEN: legacy 'polymorphic-agent' dispatch target in enforcement path: $f"
            grep -E -n -- "$PATTERN" "$f" | sed 's/^/    /'
            rc=1
        fi
    done
    return "$rc"
}

main() {
    local files=()
    if [[ "${1:-}" == "--" ]]; then
        shift
        # Pre-commit mode: only scan passed files that fall inside the enforcement surface.
        local f keep
        for f in "$@"; do
            keep=0
            for g in "${ENFORCEMENT_GLOBS[@]}"; do
                case "$f" in
                    "$g"|"$g"/*) keep=1; break ;;
                esac
            done
            [[ "$keep" == 1 ]] && files+=("$f")
        done
        [[ "${#files[@]}" -eq 0 ]] && exit 0
    else
        # Full-tree mode: enumerate the enforcement surface.
        local g
        for g in "${ENFORCEMENT_GLOBS[@]}"; do
            local target="${REPO_ROOT}/${g}"
            if [[ -d "$target" ]]; then
                while IFS= read -r -d '' f; do
                    files+=("$f")
                done < <(find "$target" -type f -print0)
            elif [[ -f "$target" ]]; then
                files+=("$target")
            fi
        done
    fi

    if scan_files "${files[@]+"${files[@]}"}"; then
        echo "OK: no 'polymorphic-agent' references in enforcement paths"
        exit 0
    else
        echo ""
        echo "The 'polymorphic-agent' dispatch target was retired (OMN-9143)."
        echo "Use an 'onex:'-prefixed subagent (or 'general-purpose') instead."
        exit 1
    fi
}

main "$@"
