#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# SessionStart Goal-Surface Hook (OMN-17168)
# ==========================================
#
# Prints the durable session goal at session start: the `state_as_of` of
# `<KNOWLEDGE_BASE_INTERNAL_PATH>/beta/GOAL.md`, its age, and the goal rows.
# When the goal is older than 12h -- or absent entirely -- it prints the exact
# re-baseline command instead of leaving the session to guess.
#
# Why this exists (memory `feedback_session_goal_from_ground_state_reconciled_
# to_plan`): every session is supposed to open from ground state reconciled
# against the rolling plan. That only happens if the goal is visible without
# being remembered. An artifact that has to be recalled to be read is the same
# failure class as a hook that sits on disk unregistered
# (`docs/tracking/2026-08-29-beta-off-the-rails-analysis.md`, RC-A(a)).
#
# INTERIM BY DESIGN. The workflow this hook names is the Claude-workflow
# stopgap. OMN-17169 re-baselines the whole process as ONEX nodes
# (ground-state EFFECTs -> reconcile COMPUTE -> goal projection REDUCER ->
# ORCHESTRATOR); at that point this hook reads the projection, not a file, and
# the `_GOAL_REL_PATH` branch below is replaced rather than deleted.
#
# Contract
# --------
#   Reads:   $KNOWLEDGE_BASE_INTERNAL_PATH/beta/GOAL.md          (only)
#   Writes:  stdout only. No files, no state, no network, ever.
#   Blocks:  never. Exit 0 on every user-visible outcome, including a missing
#            file and an unset env var.
#   Exit 3:  internal error only (an existing GOAL.md that cannot be read),
#            reported with the full absolute path of both the hook and the
#            unreadable file. Exit 3 is non-blocking for SessionStart -- only
#            exit 2 blocks -- so even the error path cannot stall a session.
#
# Fail-fast on config (CLAUDE.md rule 8)
# --------------------------------------
# `KNOWLEDGE_BASE_INTERNAL_PATH` has NO default. A silent fallback to a guessed
# clone path is exactly the cross-machine breakage rule 8 exists to prevent: it
# would surface a stale goal from some other checkout and the session would
# never know. Unset => print the variable name and the expected value, and stop.
#
# Interpreter
# -----------
# Pure bash. No Python, no jq, no interpreter spin-up at all -- which is the
# strongest form of compliance with CLAUDE.md rule 11 (one project Python /
# macOS LAN grant): a hook with no interpreter cannot resolve to the wrong one.
# This also sidesteps the OMN-16996 regression class, where hook Python
# resolved to the uv-managed adhoc-signed `omniclaude/.venv`.
#
# Deliberate omissions, each with a reason
# ----------------------------------------
#   * No `error-guard.sh`. Its EXIT trap converts every non-zero exit to 0,
#     which would silently swallow the exit-3 internal-error path this hook is
#     contracted to surface. The same trap is why the OMN-8928/8929 claim pair
#     cannot block (see OMN-17005).
#   * No `onex_hook_gate` mask bit. The three most recent OMN-13244 carve-outs
#     (`pre_tool_use_lane_open.sh`, `pre_tool_use_lane_liveness_guard.sh`,
#     `subagent_stop_report_contract_guard.sh`) call no gate either. Sharing the
#     `SESSION_START` bit with `session_start_bus_mirror.sh` would mean muting
#     event mirroring also blinds the session to its own goal, and inventing an
#     unassigned bit name would resolve to a no-op pass-through against the
#     generated `hook_bits.sh` table. hooks.json registration is the switch.
#   * No `common.sh`. Nothing here needs its helpers, and it sources the
#     error-guard trap above.

set -u

_HOOK_PATH="${BASH_SOURCE[0]}"
_GOAL_REL_PATH="beta/GOAL.md"
_STALE_HOURS=12
_GOAL_ROWS=15
_PREFIX="[session-goal]"
_WORKFLOW_NAME="morning-ground-state"

# SessionStart delivers a JSON payload on stdin. Nothing here needs it, but an
# unread stdin can hand the caller an EPIPE, so drain it unconditionally.
cat >/dev/null 2>&1 || true

say() { printf '%s %s\n' "$_PREFIX" "$*"; }

# Lite mode: an external contributor using this plugin in an unrelated repo has
# no knowledge-base-internal clone and must never see ONEX-specific output.
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || _SCRIPT_DIR="."
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    # shellcheck disable=SC1090
    source "$_MODE_SH" 2>/dev/null || true
    if declare -F omniclaude_mode >/dev/null 2>&1 && [[ "$(omniclaude_mode)" == "lite" ]]; then
        exit 0
    fi
fi

_TODAY="$(date +%F)"

print_rebaseline_command() {
    say "  Re-baseline first:"
    say "    Workflow({ name: '${_WORKFLOW_NAME}', args: { date: '${_TODAY}' } })"
}

# --------------------------------------------------------------------------- #
# Config: fail fast, no default (CLAUDE.md rule 8)
# --------------------------------------------------------------------------- #
if [[ -z "${KNOWLEDGE_BASE_INTERNAL_PATH:-}" ]]; then
    say "UNSET: cannot locate the session goal."
    say "  Missing env var: KNOWLEDGE_BASE_INTERNAL_PATH"
    say "  Expected value:  absolute path to the knowledge-base-internal clone,"
    say "                   e.g. \$OMNI_HOME/omni_worktrees/<ticket>/knowledge-base-internal"
    say "  The hook reads <that path>/${_GOAL_REL_PATH}. No default is applied, because a"
    say "  guessed clone would surface another checkout's goal as if it were this one."
    exit 0
fi

_KB_ROOT="${KNOWLEDGE_BASE_INTERNAL_PATH}"
_GOAL_FILE="${_KB_ROOT}/${_GOAL_REL_PATH}"

if [[ ! -d "$_KB_ROOT" ]]; then
    say "UNRESOLVED: KNOWLEDGE_BASE_INTERNAL_PATH points at no directory."
    say "  KNOWLEDGE_BASE_INTERNAL_PATH=${_KB_ROOT}"
    say "  Expected: an existing knowledge-base-internal clone containing ${_GOAL_REL_PATH}"
    exit 0
fi

if [[ ! -e "$_GOAL_FILE" ]]; then
    say "MISSING: no session goal at ${_GOAL_FILE}"
    print_rebaseline_command
    exit 0
fi

if [[ ! -r "$_GOAL_FILE" ]]; then
    # Internal error: the file is there and cannot be read. Full paths for both
    # the artifact and the hook, per the hook's own contract.
    say "INTERNAL ERROR: ${_GOAL_FILE} exists but is not readable."
    say "  Hook: ${_HOOK_PATH}"
    exit 3
fi

# --------------------------------------------------------------------------- #
# state_as_of -> epoch
# --------------------------------------------------------------------------- #
# Accepts `state_as_of: <ts>` anywhere in the head of the file (YAML frontmatter
# or a body line), first match wins. A timestamp with an explicit offset or `Z`
# is honoured exactly; a naked timestamp is read as UTC.
_declared_ts="$(
    grep -m1 -iE '^[[:space:]]*[-*]?[[:space:]]*state_as_of[[:space:]]*:' "$_GOAL_FILE" 2>/dev/null \
        | sed -E 's/^[^:]*:[[:space:]]*//; s/^["'"'"']//; s/["'"'"'][[:space:]]*$//; s/[[:space:]]*$//'
)"

# Prints epoch seconds for a UTC wall-clock string "YYYY-MM-DD HH:MM:SS".
# Handles GNU date (Linux/CI) and BSD date (macOS) without probing `uname`.
_wallclock_utc_to_epoch() {
    local wc="$1" out
    out="$(date -u -d "$wc UTC" +%s 2>/dev/null)" && [[ -n "$out" ]] && { printf '%s' "$out"; return 0; }
    out="$(date -u -j -f '%Y-%m-%d %H:%M:%S' "$wc" +%s 2>/dev/null)" && [[ -n "$out" ]] && { printf '%s' "$out"; return 0; }
    return 1
}

# Prints epoch seconds for an ISO-8601-ish timestamp, or returns 1.
_iso_to_epoch() {
    local raw="${1//T/ }" wall rest sign hh mm offset base
    [[ ${#raw} -lt 10 ]] && return 1

    if [[ ${#raw} -ge 19 ]]; then
        wall="${raw:0:19}"
        rest="${raw:19}"
    else
        wall="${raw:0:10} 00:00:00"
        rest="${raw:10}"
    fi
    [[ "$wall" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}$ ]] || return 1

    base="$(_wallclock_utc_to_epoch "$wall")" || return 1

    # Offset: "", "Z", "+HH:MM", "-HHMM", possibly after fractional seconds.
    [[ "$rest" =~ ^\.[0-9]+(.*)$ ]] && rest="${BASH_REMATCH[1]}"
    [[ "$rest" =~ ^[[:space:]]*(.*)$ ]] && rest="${BASH_REMATCH[1]}"
    offset=0
    if [[ "$rest" =~ ^([+-])([0-9]{2}):?([0-9]{2})$ ]]; then
        sign="${BASH_REMATCH[1]}"
        hh="${BASH_REMATCH[2]}"
        mm="${BASH_REMATCH[3]}"
        offset=$(( (10#$hh * 3600) + (10#$mm * 60) ))
        [[ "$sign" == "-" ]] && offset=$(( -offset ))
    fi

    printf '%s' $(( base - offset ))
}

_now_epoch="$(date -u +%s)"
_goal_epoch=""
_ts_label=""
_ts_source=""

if [[ -n "$_declared_ts" ]]; then
    if _goal_epoch="$(_iso_to_epoch "$_declared_ts")" && [[ -n "$_goal_epoch" ]]; then
        _ts_label="$_declared_ts"
        _ts_source="declared"
    else
        _goal_epoch=""
    fi
fi

if [[ -z "$_goal_epoch" ]]; then
    # No parseable `state_as_of`. Fall back to mtime and SAY SO -- an unlabelled
    # fallback would report file-touch time as if the goal itself were that
    # fresh, which is the failure this whole hook exists to prevent.
    _goal_epoch="$(date -u -r "$_GOAL_FILE" +%s 2>/dev/null || stat -c %Y "$_GOAL_FILE" 2>/dev/null || echo "")"
    if [[ -n "$_declared_ts" ]]; then
        _ts_source="unparsable"
        _ts_label="$_declared_ts"
    else
        _ts_source="absent"
        _ts_label=""
    fi
fi

# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
_stale=0
if [[ -n "$_goal_epoch" ]]; then
    _age_secs=$(( _now_epoch - _goal_epoch ))
    (( _age_secs < 0 )) && _age_secs=0
    _age_hours=$(( _age_secs / 3600 ))
    _age_mins=$(( (_age_secs % 3600) / 60 ))
    (( _age_secs > _STALE_HOURS * 3600 )) && _stale=1

    case "$_ts_source" in
        declared)
            say "state_as_of ${_ts_label} — age ${_age_hours}h${_age_mins}m"
            ;;
        unparsable)
            say "state_as_of ${_ts_label} is unparsable — age ${_age_hours}h${_age_mins}m from file mtime"
            ;;
        *)
            say "no state_as_of line — age ${_age_hours}h${_age_mins}m from file mtime"
            ;;
    esac
else
    # Neither a parseable state_as_of nor a readable mtime: age is unknown, so
    # treat it as stale. An unknown age must never render as fresh.
    _stale=1
    say "age UNKNOWN (no parseable state_as_of, no readable mtime) — treating as stale"
fi

say "source: ${_GOAL_FILE}"

_total_lines="$(wc -l <"$_GOAL_FILE" 2>/dev/null | tr -d '[:space:]')"
[[ -z "$_total_lines" ]] && _total_lines=0

if (( _total_lines > _GOAL_ROWS )); then
    say "--- goal (first ${_GOAL_ROWS} of ${_total_lines} lines) ---"
else
    say "--- goal (${_total_lines} lines) ---"
fi
while IFS= read -r _line || [[ -n "$_line" ]]; do
    printf '  %s\n' "$_line"
done < <(head -n "$_GOAL_ROWS" "$_GOAL_FILE" 2>/dev/null)
if (( _total_lines > _GOAL_ROWS )); then
    say "--- truncated; read ${_GOAL_FILE} for the rest ---"
else
    say "--- end ---"
fi

if (( _stale == 1 )); then
    say "STALE: older than ${_STALE_HOURS}h. This goal predates today's ground state."
    print_rebaseline_command
fi

exit 0
