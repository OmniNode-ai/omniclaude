#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Session-start advisory: verify the `onex` CLI is installed and meets the
# min_version pinned in plugin-compat.yaml. Warns only — never blocks.
#
# OMN-8799 (SD-12): Marketplace package pin. Plugin declares the pin; this
# hook surfaces drift to the user so R-class skills don't fail later with
# obscure "onex: command not found" or schema-incompatibility errors.
#
# Contract:
#   - Reads: ${CLAUDE_PLUGIN_ROOT}/plugin-compat.yaml (min_runtime_version)
#   - Reads: ${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json (requires.onex_cli.min_version — cross-check)
#   - Prints advisory to stderr if onex missing or below pin
#   - Always exits 0 (non-blocking, per Hook Performance Budgets contract)

set -u

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
if [[ -z "$PLUGIN_ROOT" ]]; then
    exit 0
fi

COMPAT_YAML="${PLUGIN_ROOT}/plugin-compat.yaml"
if [[ ! -f "$COMPAT_YAML" ]]; then
    exit 0
fi

# Extract onex_cli.min_version with a small awk state-machine so we don't
# require Python at hook runtime (SessionStart path must stay <50ms; no
# interpreter spin-up).
MIN_VERSION="$(awk '
    /^onex_cli:/ { in_block = 1; next }
    in_block && /^[^[:space:]]/ { in_block = 0 }
    in_block && /^[[:space:]]+min_version:/ {
        gsub(/^[[:space:]]+min_version:[[:space:]]*"?|"?[[:space:]]*$/, "")
        print
        exit
    }
' "$COMPAT_YAML" 2>/dev/null)"
if [[ -z "${MIN_VERSION:-}" ]]; then
    exit 0
fi

if ! command -v onex >/dev/null 2>&1; then
    printf '\n[onex-cli-pin] onex CLI not found on PATH.\n' >&2
    printf '[onex-cli-pin]   Required: omnibase-core >= %s (see plugin-compat.yaml).\n' "$MIN_VERSION" >&2
    printf '[onex-cli-pin]   Install:  pipx install '"'"'omnibase-core>=%s'"'"'\n\n' "$MIN_VERSION" >&2
    exit 0
fi

INSTALLED_VERSION="$(onex --version 2>/dev/null | head -n1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)"
if [[ -z "${INSTALLED_VERSION:-}" ]]; then
    exit 0
fi

# Lightweight semver comparison: IFS-split into three ints, compare lexically.
ver_lt() {
    # returns 0 (true) if $1 < $2
    local a b
    a="$1"; b="$2"
    local IFS=.
    # shellcheck disable=SC2206
    local av=($a) bv=($b)
    for i in 0 1 2; do
        local ai="${av[$i]:-0}" bi="${bv[$i]:-0}"
        if (( 10#$ai < 10#$bi )); then return 0; fi
        if (( 10#$ai > 10#$bi )); then return 1; fi
    done
    return 1
}

if ver_lt "$INSTALLED_VERSION" "$MIN_VERSION"; then
    printf '\n[onex-cli-pin] onex CLI %s is below the pin.\n' "$INSTALLED_VERSION" >&2
    printf '[onex-cli-pin]   Required: omnibase-core >= %s (see plugin-compat.yaml).\n' "$MIN_VERSION" >&2
    printf '[onex-cli-pin]   Upgrade:  pipx upgrade omnibase-core\n\n' >&2
fi

exit 0
