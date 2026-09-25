#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PostToolUse: fast-forward the canonical clones after a merge (OMN-19607)
# ======================================================================
#
# Operator, 2026-09-25: "we should also add a hook that pulls canonical clones
# after every merge." When the tool call just made was a merge -- `gh pr merge`,
# the REST merge endpoint by PUT, the bulk throttle's arm operation, or the
# GitHub MCP merge tool -- this starts a DETACHED git-only fetch and
# fast-forward of every canonical clone of that repository, under $OMNI_HOME
# and every ONEX_REGISTRY_ROOTS root, and returns.
#
# The engine, its refusal rules and its log are in
# ../lib/canonical_clone_sync.py. Merges this Mac did not make are caught by the
# launchd agent ai.omninode.canonical-clone-sync, which runs the same engine.
#
# Contract
# --------
#   Blocks:  never. Exit 0 on every path, stdout silent.
#   Cost:    one bash string match on every Bash call. Only a payload that
#            contains the word "merge" starts Python; only a real merge starts
#            the detached sync.
#   Quota:   no GitHub API call. git fetch is the git transport.
#   Writes:  $ONEX_STATE_DIR/logs/canonical-clone-sync.jsonl, and the clones'
#            refs, by fast-forward only.

set -u

_payload="$(cat 2>/dev/null || true)"

# The cheap exit, taken by nearly every tool call.
case "$_payload" in
    *merge*) ;;
    *) exit 0 ;;
esac

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || exit 0

# Lite mode: an external contributor has no canonical registry.
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    # shellcheck disable=SC1090
    source "$_MODE_SH" 2>/dev/null || true
    if declare -F omniclaude_mode >/dev/null 2>&1 && [[ "$(omniclaude_mode)" == "lite" ]]; then
        exit 0
    fi
fi

# No registry, no clones to advance. A hook never fails fast (it would print
# into every tool call on a machine with no registry); the engine's own `sync`
# entry point is the one that refuses an unset OMNI_HOME.
if [[ -z "${OMNI_HOME:-}" || ! -d "${OMNI_HOME}" ]]; then
    exit 0
fi

# shellcheck source=onex-paths.sh
source "${_SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true

_ENGINE="${_SCRIPT_DIR}/../lib/canonical_clone_sync.py"
[[ -f "$_ENGINE" ]] || exit 0

# Standard library only, so any 3.12+ interpreter works and no venv is needed.
# The project interpreter (python3.13, rule 11) is preferred when PATH has it.
_py=""
for _candidate in "${PLUGIN_PYTHON_BIN:-}" "$(command -v python3.13 2>/dev/null)" "$(command -v python3 2>/dev/null)"; do
    if [[ -n "$_candidate" && -x "$_candidate" ]]; then
        _py="$_candidate"
        break
    fi
done
[[ -n "$_py" ]] || exit 0

# The engine parses the payload in the foreground (no network) and hands the
# fetch to a detached child in its own session, so this returns at once.
printf '%s' "$_payload" | env -u PYTHONPATH "$_py" "$_ENGINE" hook >/dev/null 2>&1 || true

exit 0
