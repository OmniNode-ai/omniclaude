#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# SessionStart hook-inventory parity (OMN-17020)
#
# Prints, at session start, any disagreement between
# plugins/onex/hooks/contracts/hook_inventory.yaml, the live hooks.json, the
# scripts on disk, and this machine's ONEX_HOOKS_MASK.
#
# WARN ONLY, BY CONSTRUCTION. Every path in this script ends in `exit 0`,
# including the ones that fail. DoD item 3 of OMN-17020 says the bootstrap
# parity check "warns (does not block session start)", and that is not a
# nicety: a hook-manifest mismatch that made the machine unusable would be a
# far larger outage than the drift it reports. The fail-CLOSED half of this
# control is the `hook-inventory-gate` CI check, which cannot lock anyone out
# of anything.
#
# Why the mask surface is here and not in CI: ONEX_HOOKS_MASK is a per-machine
# fact that common.sh re-reads from ~/.omnibase/.env under `set -a`. A GitHub
# runner has no such file, so a CI check over it would pass because its input
# is absent — worse than no check. Building this hook found WORKTREE_GUARD
# (0x800000000000000) cleared in the operator Mac's live mask, i.e.
# pre_tool_use_worktree_guard.sh registered under the OMN-14330 carve-out and
# dark in practice. That is the exact RC-B shape one surface over from the one
# OMN-13244 produced, and only a live check can see it.
#
# Repo-root resolution has NO guessed default (CLAUDE.md rules 6 and 8): a
# wrong tree would report another checkout's inventory as if it were this one.
# The order is (1) the source tree the plugin is running from, (2) $OMNI_HOME/
# omniclaude. If neither resolves, the hook says which variable is missing and
# exits 0.

set -uo pipefail

_SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SELF}/../.." && pwd)}"

_marker="plugins/onex/hooks/contracts/hook_inventory.yaml"
REPO_ROOT=""

# (1) Running from source: <repo>/plugins/onex is the plugin root.
_from_source="$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd || true)"
if [[ -n "$_from_source" && -f "${_from_source}/${_marker}" ]]; then
    REPO_ROOT="$_from_source"
fi

# (2) Plugin cache install: fall back to the canonical clone, if declared.
if [[ -z "$REPO_ROOT" && -n "${OMNI_HOME:-}" && -f "${OMNI_HOME}/omniclaude/${_marker}" ]]; then
    REPO_ROOT="${OMNI_HOME}/omniclaude"
fi

if [[ -z "$REPO_ROOT" ]]; then
    echo "[hook-inventory] SKIPPED: cannot locate the omniclaude tree that owns the hook inventory."
    if [[ -z "${OMNI_HOME:-}" ]]; then
        echo "[hook-inventory]   Missing env var: OMNI_HOME"
        echo "[hook-inventory]   Expected value:  absolute path to the omni_home workspace"
    else
        echo "[hook-inventory]   Looked in: ${PLUGIN_ROOT}/../.. and ${OMNI_HOME}/omniclaude"
    fi
    exit 0
fi

# common.sh resolves PYTHON_CMD (and, as a side effect, re-reads ONEX_HOOKS_MASK
# from ~/.omnibase/.env — which is precisely the value this check must see).
# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/common.sh" 2>/dev/null || true

_PY="${PYTHON_CMD:-python3}"
_LIB="${REPO_ROOT}/plugins/onex/hooks/lib/hook_inventory.py"

if [[ ! -f "$_LIB" ]]; then
    echo "[hook-inventory] SKIPPED: parity lib missing at ${_LIB}"
    exit 0
fi

# The third disable surface: OMNICLAUDE_MODE. `mode.sh` resolves "lite" by
# DEFAULT for any cwd outside omni_home/omni_worktrees with no local
# omnibase_core, and nine registered hooks -- three of them enforcement guards
# -- exit 0 silently under lite. Resolve it HERE, with mode.sh's own function,
# rather than reimplementing that resolution order in Python where it would
# drift.
_MODE=""
# shellcheck source=/dev/null
if source "${PLUGIN_ROOT}/lib/mode.sh" 2>/dev/null && declare -F omniclaude_mode >/dev/null 2>&1; then
    _MODE="$(omniclaude_mode 2>/dev/null || true)"
fi

# PYTHONPATH is cleared so an ambient value cannot shadow PyYAML or a sibling
# module with a same-named one from another tree (the OMN-11422 worktree rule).
ONEX_HOOK_INVENTORY_REPO_ROOT="$REPO_ROOT" \
ONEX_HOOK_INVENTORY_MODE="$_MODE" \
    env -u PYTHONPATH "$_PY" "$_LIB" 2>&1 || true

exit 0
