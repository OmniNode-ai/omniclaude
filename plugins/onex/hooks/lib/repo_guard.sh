#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Shared Repo-Guard Helper for ONEX Hooks
# =========================================
# Provides `is_omninode_repo`, used by hook scripts to scope their behavior
# to OmniNode repositories only. External users of the Claude Code plugin
# (for example, contributors working in unrelated projects) should never see
# ONEX-specific output, reminders, or blocking errors firing on their tool
# calls.
#
# Usage (from a hook script):
#
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   # shellcheck source=lib/repo_guard.sh
#   . "$SCRIPT_DIR/lib/repo_guard.sh"
#   if ! is_omninode_repo; then
#       exit 0
#   fi
#
# Detection heuristic — returns 0 (true) if ANY of the following is present at
# the resolved repo root:
#   * pyproject.toml referencing omnibase_/omniclaude/omninode
#   * package.json referencing omnidash/@omni/omniweb
#   * .github/workflows/ directory with at least one .yml/.yaml file
#     (combined with another OmniNode marker — not a universal marker)
#   * CLAUDE.md at repo root mentioning OmniNode projects
#   * .onex_state/ directory at repo root
#   * contract.yaml anywhere within the first two levels of the repo
#
# Repo root resolution order:
#   1. $CLAUDE_PROJECT_DIR (set by Claude Code for the session)
#   2. `git rev-parse --show-toplevel`
#   3. $PWD (last-resort, avoids hard failure)
#
# Safe to source from any shell that supports `[[ ]]` (bash, zsh).
# Never prints to stdout. All side effects are guarded with redirects.

# Guard against double-source (functions are idempotent but sourcing repeatedly
# is wasteful).
if [[ "${_OMNICLAUDE_REPO_GUARD_SOURCED:-0}" == "1" ]]; then
    return 0 2>/dev/null || true
fi
_OMNICLAUDE_REPO_GUARD_SOURCED=1

# Resolve the repo root for guard checks. Prints the resolved path on stdout.
# Prefers $CLAUDE_PROJECT_DIR, falls back to git, then $PWD.
_repo_guard_resolve_root() {
    local root=""
    if [[ -n "${CLAUDE_PROJECT_DIR:-}" && -d "${CLAUDE_PROJECT_DIR}" ]]; then
        root="${CLAUDE_PROJECT_DIR}"
    elif root=$(git rev-parse --show-toplevel 2>/dev/null) && [[ -n "$root" ]]; then
        :
    else
        root="${PWD:-.}"
    fi
    printf '%s\n' "$root"
}

# Returns 0 if the resolved repo root looks like an OmniNode repo, 1 otherwise.
# Never blocks, never writes to stdout, never depends on network access.
is_omninode_repo() {
    local root
    root="$(_repo_guard_resolve_root)"

    # Unresolvable root -> not an OmniNode repo (fail safe to no-op).
    if [[ -z "$root" || ! -d "$root" ]]; then
        return 1
    fi

    # Marker 1: pyproject.toml referencing an OmniNode package.
    if [[ -f "$root/pyproject.toml" ]]; then
        if grep -qE '(omnibase_|omniclaude|omninode)' "$root/pyproject.toml" 2>/dev/null; then
            return 0
        fi
    fi

    # Marker 2: package.json referencing an OmniNode package.
    if [[ -f "$root/package.json" ]]; then
        if grep -qE '(omnidash|@omni|omniweb)' "$root/package.json" 2>/dev/null; then
            return 0
        fi
    fi

    # Marker 3: CLAUDE.md at repo root mentions OmniNode.
    if [[ -f "$root/CLAUDE.md" ]]; then
        if grep -qiE 'omninode|omnibase|omniclaude|omnidash' "$root/CLAUDE.md" 2>/dev/null; then
            return 0
        fi
    fi

    # Marker 4: .onex_state/ directory at repo root.
    if [[ -d "$root/.onex_state" ]]; then
        return 0
    fi

    # Marker 5: contract.yaml within the first two levels of the repo.
    # Limiting depth keeps this fast even on large trees.
    local contract
    contract=$(find "$root" -maxdepth 2 -name 'contract.yaml' -print -quit 2>/dev/null)
    if [[ -n "$contract" ]]; then
        return 0
    fi

    # Marker 6: a .github/workflows/ directory with at least one workflow file,
    # combined with any other faint OmniNode hint (presence alone is too weak —
    # many unrelated repos have workflow files). Use it as a tie-breaker when
    # we already saw a pyproject.toml or package.json but it did not match the
    # primary regexes (e.g. a new repo not yet wired to omnibase).
    if [[ -d "$root/.github/workflows" ]]; then
        local wf
        wf=$(find "$root/.github/workflows" -maxdepth 1 \
            \( -name '*.yml' -o -name '*.yaml' \) -print -quit 2>/dev/null)
        if [[ -n "$wf" ]]; then
            # Secondary hint: any file in .github/ referencing OmniNode.
            if grep -rqE 'omninode|omnibase|omniclaude|omnidash' \
                "$root/.github" 2>/dev/null; then
                return 0
            fi
        fi
    fi

    return 1
}
