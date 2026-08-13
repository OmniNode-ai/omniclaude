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
# OMN-16041: `onex --version` reports the omnibase-CORE version, because
# omnibase-core owns the `onex` console script. The `min_version` pin, however,
# now belongs to omnibase-INFRA, which registers every subcommand the skills call
# via the `onex.cli` entry-point group. Comparing the two would compare unrelated
# version lines, so the version comparison below reads
# `console_script_min_version` (core's floor) and the delegate-provider floor is
# surfaced in the advisory text only.
#
# Contract:
#   - Reads: ${CLAUDE_PLUGIN_ROOT}/plugin-compat.yaml (onex_cli.*)
#   - Reads: ${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json (requires.onex_cli.min_version — cross-check)
#   - Prints advisory to stderr if onex missing, below pin, or lacking subcommands
#   - Always exits 0 (non-blocking, per Hook Performance Budgets contract)

set -u
# Parameter expansion, not $(dirname ...): the SessionStart path must not fork a
# process, and a caller with a minimal PATH (as the hook tests use) has no
# `dirname` at all, which previously leaked "command not found" to stderr on a
# path contracted to be silent (pre-existing failure of
# test_silent_when_compat_yaml_absent, fixed here under OMN-16041).
_hook_dir="${BASH_SOURCE[0]%/*}"
[[ "$_hook_dir" == "${BASH_SOURCE[0]}" ]] && _hook_dir="."
source "${_hook_dir}/hook-gate.sh" 2>/dev/null || true
onex_hook_gate SESSION_START_ONEX_CLI_PIN_CHECK || exit 0

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
if [[ -z "$PLUGIN_ROOT" ]]; then
    exit 0
fi

COMPAT_YAML="${PLUGIN_ROOT}/plugin-compat.yaml"
if [[ ! -f "$COMPAT_YAML" ]]; then
    exit 0
fi

# Extract onex_cli.<key> with a small awk state-machine so we don't require
# Python at hook runtime (SessionStart path must stay <50ms; no interpreter
# spin-up). Anchored to `<indent><key>:` so `min_version` never matches
# `console_script_min_version`.
compat_get() {
    awk -v key="$1" '
        /^onex_cli:/ { in_block = 1; next }
        in_block && /^[^[:space:]]/ { in_block = 0 }
        in_block {
            line = $0
            sub(/^[[:space:]]+/, "", line)
            if (index(line, key ":") == 1) {
                sub(/^[^:]+:[[:space:]]*/, "", line)
                gsub(/^"|"[[:space:]]*$/, "", line)
                print line
                exit
            }
        }
    ' "$COMPAT_YAML" 2>/dev/null
}

# Floor for the package that registers the subcommands (omnibase-infra).
MIN_VERSION="$(compat_get min_version)"
DELEGATE_PKG="$(compat_get package)"
# Floor for the package that ships the `onex` executable itself (omnibase-core).
# This is the one `onex --version` actually reports.
CONSOLE_PKG="$(compat_get console_script_package)"
CONSOLE_MIN="$(compat_get console_script_min_version)"
INSTALL_HINT="$(compat_get install_hint)"
if [[ -z "${MIN_VERSION:-}" || -z "${CONSOLE_MIN:-}" ]]; then
    exit 0
fi
: "${DELEGATE_PKG:=omnibase-infra}"
: "${CONSOLE_PKG:=omnibase-core}"
: "${INSTALL_HINT:=uv tool install --with '${DELEGATE_PKG}>=${MIN_VERSION}' '${CONSOLE_PKG}>=${CONSOLE_MIN}'}"

if ! command -v onex >/dev/null 2>&1; then
    printf '\n[onex-cli-pin] onex CLI not found on PATH.\n' >&2
    printf '[onex-cli-pin]   Required: %s >= %s (ships the `onex` executable)\n' "$CONSOLE_PKG" "$CONSOLE_MIN" >&2
    printf '[onex-cli-pin]              + %s >= %s (registers the subcommands)\n' "$DELEGATE_PKG" "$MIN_VERSION" >&2
    printf '[onex-cli-pin]   Install:  %s\n' "$INSTALL_HINT" >&2
    printf '[onex-cli-pin]   or pipx:  pipx install '"'"'%s>=%s'"'"' && pipx inject %s '"'"'%s>=%s'"'"'\n\n' \
        "$CONSOLE_PKG" "$CONSOLE_MIN" "$CONSOLE_PKG" "$DELEGATE_PKG" "$MIN_VERSION" >&2
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

# `onex --version` reports the CONSOLE-SCRIPT package's version, so it is
# compared against the console-script floor -- never against MIN_VERSION, which
# belongs to a different package (OMN-16041).
if ver_lt "$INSTALLED_VERSION" "$CONSOLE_MIN"; then
    printf '\n[onex-cli-pin] onex CLI %s is below the pin.\n' "$INSTALLED_VERSION" >&2
    printf '[onex-cli-pin]   Required: %s >= %s (see plugin-compat.yaml).\n' "$CONSOLE_PKG" "$CONSOLE_MIN" >&2
    printf '[onex-cli-pin]   Upgrade:  pipx upgrade %s\n\n' "$CONSOLE_PKG" >&2
fi

# A correct `onex` version still has no subcommands if the delegate-provider
# package is absent from the SAME environment -- the OMN-16041 failure mode a
# version check alone cannot see. Detected by looking for the provider's
# dist-info next to the interpreter in the `onex` shebang rather than by running
# `onex delegate --help`, which costs seconds of interpreter + pydantic import
# and would blow the <50ms SessionStart budget.
# Echoes the installed delegate-provider version, or the literal string
# "MISSING". Echoes nothing (and returns 1) when the environment cannot be
# introspected, so an unreadable launcher never produces a false advisory.
delegate_provider_version() {
    local onex_path interpreter env_root dist base
    onex_path="$(command -v onex 2>/dev/null)" || return 1
    interpreter="$(head -n1 "$onex_path" 2>/dev/null)"
    interpreter="${interpreter#\#!}"
    interpreter="${interpreter%%[[:space:]]*}"
    [[ -x "$interpreter" ]] || return 1
    env_root="$(dirname "$(dirname "$interpreter")")"
    for dist in "$env_root"/lib/python*/site-packages/omnibase_infra-*.dist-info; do
        [[ -d "$dist" ]] || continue
        base="$(basename "$dist")"
        base="${base#omnibase_infra-}"
        printf '%s' "${base%.dist-info}"
        return 0
    done
    printf 'MISSING'
    return 0
}

DELEGATE_VERSION="$(delegate_provider_version)" || DELEGATE_VERSION=""
if [[ "$DELEGATE_VERSION" == "MISSING" ]]; then
    printf '\n[onex-cli-pin] `onex` is installed but %s is not in the same environment,\n' "$DELEGATE_PKG" >&2
    printf '[onex-cli-pin]   so `onex delegate` and the other subcommands do not exist.\n' >&2
    printf '[onex-cli-pin]   Required: %s >= %s alongside %s.\n' "$DELEGATE_PKG" "$MIN_VERSION" "$CONSOLE_PKG" >&2
    printf '[onex-cli-pin]   Fix:      %s\n' "$INSTALL_HINT" >&2
    printf '[onex-cli-pin]   or pipx:  pipx inject %s '"'"'%s>=%s'"'"'\n\n' \
        "$CONSOLE_PKG" "$DELEGATE_PKG" "$MIN_VERSION" >&2
elif [[ -n "$DELEGATE_VERSION" ]] && ver_lt "$DELEGATE_VERSION" "$MIN_VERSION"; then
    printf '\n[onex-cli-pin] %s %s is below the pin; subcommands may be missing.\n' \
        "$DELEGATE_PKG" "$DELEGATE_VERSION" >&2
    printf '[onex-cli-pin]   Required: %s >= %s (see plugin-compat.yaml).\n' "$DELEGATE_PKG" "$MIN_VERSION" >&2
    printf '[onex-cli-pin]   Fix:      %s\n\n' "$INSTALL_HINT" >&2
fi

exit 0
