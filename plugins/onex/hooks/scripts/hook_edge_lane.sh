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
    # OMN-20109: parsed with bash builtins only. The sed|head and awk this
    # replaced were four execs and four forks on every hook invocation; the
    # reads below are the same two reads, with the same anchors.
    local self="${BASH_SOURCE[0]}" dir contract
    dir="${self%/*}"; [[ "$self" == */* ]] || dir=.
    contract="${dir}/../contracts/hook_edge_lane.yaml"
    [[ -r "$contract" ]] || return 0

    local lane="" line
    # Top-level `lane:` only — anchored to column 0 so a nested key of the same
    # name inside known_lanes/relay can never be mistaken for the declaration.
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^lane:[[:space:]]*\"?([^\"#]*)\"?[[:space:]]*$ ]]; then
            lane="${BASH_REMATCH[1]}"
            break
        fi
    done < "$contract"
    lane="${lane%"${lane##*[![:space:]]}"}"
    [[ -n "$lane" ]] || return 0

    local brokers="" in_lanes=0 in_want=0 key
    # Walk into known_lanes, stop at the named lane's block, take its
    # bootstrap_servers. Bounded to the block by the two-space indent level.
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^known_lanes:[[:space:]]*$ ]]; then
            in_lanes=1
            continue
        fi
        if (( in_lanes )) && [[ "$line" =~ ^[^[:space:]] ]]; then
            in_lanes=0
        fi
        if (( in_lanes )) && [[ "$line" == "  "[!' ']* ]]; then
            key="${line#  }"
            key="${key%%:*}"
            in_want=0
            [[ "$key" == "$lane" ]] && in_want=1
            continue
        fi
        if (( in_lanes && in_want )) && [[ "$line" == "    bootstrap_servers:"* ]]; then
            line="${line#*:}"
            line="${line#"${line%%[![:space:]]*}"}"
            if [[ "$line" == *"#"* ]]; then
                line="${line%%#*}"
                line="${line%"${line##*[![:space:]]}"}"
            fi
            brokers="${line//\"/}"
            break
        fi
    done < "$contract"
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
