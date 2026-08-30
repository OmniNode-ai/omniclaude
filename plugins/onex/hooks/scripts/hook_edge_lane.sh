#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# =============================================================================
# Hook-edge bus lane resolver [OMN-17204]
# =============================================================================
# Applies the ONE declared answer from
# ``plugins/onex/hooks/contracts/hook_edge_lane.yaml`` to the hook edge's
# publish target.
#
# MUST be sourced AFTER common.sh, never before. common.sh sources
# ~/.omnibase/.env and $PROJECT_ROOT/.env under `set -a`; sourcing this
# resolver first would let those files overwrite the contract's answer and
# re-open the exact defect this ticket closes. `validate_hook_edge_lane.py`
# fails the build if any *_bus_mirror.sh gets that ordering wrong, so the
# requirement is enforced rather than merely documented.
#
# Usage (from a *_bus_mirror.sh, after `source "${HOOKS_DIR}/scripts/common.sh"`):
#   source "$(dirname "${BASH_SOURCE[0]}")/hook_edge_lane.sh" 2>/dev/null || true
#
# Exports:
#   KAFKA_BOOTSTRAP_SERVERS  — the declared lane's host-side broker
#   KAFKA_BROKERS            — kept in lock-step (common.sh's legacy alias)
#   ONEX_HOOK_EDGE_LANE      — the declared lane NAME, so a downstream probe or
#                              log line can say which lane it meant instead of
#                              re-deriving it from a host:port
#
# Deliberately pure shell — no python3, no PyYAML, no yq. A hook must never
# lose its lane because an interpreter is missing or slow. The parse is a
# narrow, single-purpose reader of two fields from a file this repo owns and
# whose shape a merge gate enforces; it is not a general YAML parser and does
# not pretend to be.
#
# Fail-open: if the contract is unreadable or malformed, this leaves the
# environment untouched and returns 0. That degrades to the pre-OMN-17204
# behaviour for one invocation rather than killing the user's session — and the
# CI gate is what guarantees a malformed contract never reaches a machine.
# =============================================================================

_onex_hook_edge_lane_apply() {
    local contract
    contract="$(cd "$(dirname "${BASH_SOURCE[0]}")/../contracts" 2>/dev/null && pwd)/hook_edge_lane.yaml"
    [[ -r "$contract" ]] || return 0

    local lane
    # Top-level `lane:` only — anchored to column 0 so a nested key of the same
    # name inside known_lanes/relay can never be mistaken for the declaration.
    lane="$(sed -n 's/^lane:[[:space:]]*"\{0,1\}\([^"#]*\)"\{0,1\}[[:space:]]*$/\1/p' "$contract" | head -n 1)"
    lane="${lane%"${lane##*[![:space:]]}"}"
    [[ -n "$lane" ]] || return 0

    local brokers
    # Walk into known_lanes, stop at the named lane's block, take its
    # bootstrap_servers. Bounded to the block by the two-space indent level.
    brokers="$(awk -v want="$lane" '
        /^known_lanes:[[:space:]]*$/ { in_lanes = 1; next }
        in_lanes && /^[^[:space:]]/  { in_lanes = 0 }
        in_lanes && $0 ~ "^  [^ ]" {
            key = $0
            sub(/^  /, "", key); sub(/:.*$/, "", key)
            in_want = (key == want)
            next
        }
        in_lanes && in_want && $0 ~ /^    bootstrap_servers:/ {
            line = $0
            sub(/^[^:]*:[[:space:]]*/, "", line)
            sub(/[[:space:]]*#.*$/, "", line)
            gsub(/"/, "", line)
            print line
            exit
        }
    ' "$contract")"
    [[ -n "$brokers" ]] || return 0

    export ONEX_HOOK_EDGE_LANE="$lane"
    export KAFKA_BOOTSTRAP_SERVERS="$brokers"
    # common.sh derives KAFKA_BROKERS from KAFKA_BOOTSTRAP_SERVERS for legacy
    # Python callers, but it did so before this resolver ran. Re-derive it here
    # unconditionally so the two can never name different lanes.
    export KAFKA_BROKERS="$brokers"
    export KAFKA_ENABLED="true"
}

_onex_hook_edge_lane_apply || true
unset -f _onex_hook_edge_lane_apply
