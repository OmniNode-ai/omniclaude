#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# intent.sh - session intent resolution [OMN-18368]
#
# The third resolution axis, beside mode.sh. Mode answers "how much of this
# plugin applies to this working directory"; intent answers "what was this
# session opened to do", which mode structurally cannot express. A session
# opened only to re-authenticate a tool server resolves to `full` mode -- its
# working directory is the workspace -- and still wants no status output.
#
# Three intents, and no more:
#
#   quiet   opened to re-authenticate, to check connectivity, or to do one
#           thing that is not this workspace's process. Prints nothing but a
#           blocker.
#   normal  ordinary interactive work.
#   tick    a scheduled or dispatched workflow opened this session; the verdict
#           belongs on that run's receipt, not in the transcript.
#
# Resolution order, highest first:
#
#   1. an explicit argument              (how a skill passes --intent)
#   2. $OMNICLAUDE_SESSION_INTENT        (whoever opens the session)
#   3. a per-session marker file         (how a scheduled tick declares itself)
#   4. ~/.config/omniclaude/session-intent   (persistent preference, the
#                                             sibling of the mode file)
#   5. "normal"                          (the default)
#
# INFERENCE NEVER RESOLVES TO QUIET, and that is the property that matters more
# than the order. Every fall-through lands on `normal`; an invalid or unusable
# value at any layer falls THROUGH to the next source rather than being honoured
# and rather than short-circuiting to the default. A wrongly-quiet session hides
# a blocker; a wrongly-normal session costs one line. There is no auto-detection
# branch here and there must never be one: quiet is declared, never deduced.
#
# The marker file is honoured only while it is FRESH. A marker outlives the
# session that wrote it, and a stale one left by a dead tick would silence the
# next human session that happened to open on the same host -- which is the same
# failure as inferring quiet, arriving by a different route.
#
# Pure bash, no interpreter (CLAUDE.md rule 11): a resolver with no interpreter
# cannot resolve to the wrong one, and every SessionStart hook sources this on
# a sub-50ms budget.

# Seconds a per-session marker stays authoritative. A session-start declaration
# is consumed at session start; anything older is a leftover, not a statement.
OMNICLAUDE_SESSION_INTENT_MAX_MARKER_AGE="${OMNICLAUDE_SESSION_INTENT_MAX_MARKER_AGE:-600}"

# Echoes the argument if it is one of the three intents, else returns 1.
_omniclaude_intent_valid() {
    case "${1:-}" in
        quiet|normal|tick) printf '%s' "$1"; return 0 ;;
    esac
    return 1
}

# Echoes the first line of a file, trimmed of surrounding whitespace.
_omniclaude_intent_read_file() {
    local path="$1" value=""
    [[ -f "$path" && -r "$path" ]] || return 1
    IFS= read -r value < "$path" 2>/dev/null || return 1
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

# Echoes the file's age in seconds, or returns 1 when it cannot be read.
_omniclaude_intent_file_age() {
    local path="$1" mtime now
    mtime="$(date -u -r "$path" +%s 2>/dev/null)" \
        || mtime="$(stat -c %Y "$path" 2>/dev/null)" \
        || return 1
    [[ -n "$mtime" ]] || return 1
    now="$(date -u +%s)"
    printf '%s' $(( now - mtime ))
}

# Absolute path of the per-session marker file. Overridable so a workflow that
# owns its own run directory can declare the intent there instead.
omniclaude_session_intent_marker_path() {
    if [[ -n "${OMNICLAUDE_SESSION_INTENT_FILE:-}" ]]; then
        printf '%s' "$OMNICLAUDE_SESSION_INTENT_FILE"
        return 0
    fi
    printf '%s/session-intent' "${ONEX_HOOKS_STATE_DIR:-${HOME}/.onex_state/hooks}"
}

omniclaude_session_intent() {
    local explicit="${1:-}" value marker age

    # 1. Explicit argument.
    if [[ -n "$explicit" ]] && value="$(_omniclaude_intent_valid "$explicit")"; then
        printf '%s\n' "$value"
        return 0
    fi

    # 2. Environment variable.
    if [[ -n "${OMNICLAUDE_SESSION_INTENT:-}" ]] \
        && value="$(_omniclaude_intent_valid "$OMNICLAUDE_SESSION_INTENT")"; then
        printf '%s\n' "$value"
        return 0
    fi

    # 3. Per-session marker, if fresh.
    marker="$(omniclaude_session_intent_marker_path)"
    if [[ -f "$marker" ]] && age="$(_omniclaude_intent_file_age "$marker")"; then
        if (( age >= 0 && age <= OMNICLAUDE_SESSION_INTENT_MAX_MARKER_AGE )); then
            if value="$(_omniclaude_intent_read_file "$marker")" \
                && value="$(_omniclaude_intent_valid "$value")"; then
                printf '%s\n' "$value"
                return 0
            fi
        fi
    fi

    # 4. Persistent preference, beside ~/.config/omniclaude/mode.
    if value="$(_omniclaude_intent_read_file "${HOME}/.config/omniclaude/session-intent")" \
        && value="$(_omniclaude_intent_valid "$value")"; then
        printf '%s\n' "$value"
        return 0
    fi

    # 5. Default. The only value inference is ever allowed to produce.
    printf 'normal\n'
    return 0
}

# Convenience predicates for the hook scripts, so each one states what it means
# rather than re-deriving it from a string comparison.

# True when this session asked for silence: quiet (a person's own declaration)
# or tick (a workflow whose verdict belongs on its receipt). Both suppress
# routine session-start output; neither suppresses a blocker.
omniclaude_session_intent_is_silent() {
    case "$(omniclaude_session_intent "${1:-}")" in
        quiet|tick) return 0 ;;
    esac
    return 1
}

# True only for quiet. Used where tick must still do the work -- a scheduled
# session is this workspace's process and its events still count.
omniclaude_session_intent_is_quiet() {
    [[ "$(omniclaude_session_intent "${1:-}")" == "quiet" ]]
}
