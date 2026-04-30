#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Lightweight ONEX_HOOKS_MASK gate loader for standalone shell hooks.
# common.sh also exposes onex_hook_gate, but several hook scripts deliberately
# avoid common.sh to keep startup cheap or fail-open. Those scripts still need
# the bitmask gate function before their first behavioral branch.

if ! declare -F onex_hook_gate >/dev/null 2>&1; then
    _ONEX_HOOK_GATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
    _ONEX_HOOK_BITS_PATH="${_ONEX_HOOK_GATE_DIR}/../lib/hook_bits.sh"

    if [[ -f "$_ONEX_HOOK_BITS_PATH" ]]; then
        # shellcheck source=../lib/hook_bits.sh
        source "$_ONEX_HOOK_BITS_PATH"
    fi

    onex_hook_gate() {
        local bit_name="${1:-}"
        [[ -z "$bit_name" ]] && return 0

        if ! declare -F hook_bits_bit_for_name >/dev/null 2>&1; then
            return 0
        fi

        local bit
        bit="$(hook_bits_bit_for_name "$bit_name" 2>/dev/null || true)"
        [[ -z "$bit" ]] && return 0

        local mask
        if declare -F hook_bits_parse_mask >/dev/null 2>&1; then
            mask="$(hook_bits_parse_mask "${ONEX_HOOKS_MASK:-${HOOK_BITS_DEFAULT_MASK:-}}")"
        else
            mask="${ONEX_HOOKS_MASK:-${HOOK_BITS_DEFAULT_MASK:-0}}"
        fi

        if declare -F hook_bits_is_enabled >/dev/null 2>&1; then
            hook_bits_is_enabled "$mask" "$bit"
        else
            (( mask & bit ))
        fi
    }
fi

unset _ONEX_HOOK_GATE_DIR _ONEX_HOOK_BITS_PATH
