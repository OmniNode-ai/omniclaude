#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PreCompact Hook - Portable Plugin Version
# Writes a lightweight context snapshot to /tmp before the conversation is compressed.
# UserPromptSubmit re-injects the snapshot on the next prompt (post-compact context recovery).
#
# Gate: Register this script in hooks.json ONLY after pre-compact-probe.sh confirms
# that (a) the hook fires, (b) session_id is non-"missing", (c) keys are present.
# See pre-compact-probe.sh for verification steps.

set -euo pipefail

# Portable Plugin Configuration
# Resolve absolute path of this script, handling relative invocation.
# Falls back to python3 if realpath is unavailable (non-GNU macOS without coreutils).
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${HOOKS_DIR}/logs/pre-compact.log"

# Detect project root
PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
elif [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
else
    PROJECT_ROOT="$(pwd)"
fi

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

# Load environment variables
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Source shared functions (provides log(), KAFKA_ENABLED)
source "${HOOKS_DIR}/scripts/common.sh"

# Snapshot files contain repo context — restrict to owner only
umask 077

# ── Parse session_id and CWD from stdin ───────────────────────────────────────
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // .sessionId // .session.id // empty' 2>/dev/null || true)
SESSION_CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
# Do NOT rely on $PWD — PreCompact hook CWD is not guaranteed to track session

if [[ -z "$SESSION_ID" ]]; then
    log "PreCompact: session_id not found in payload — skipping. Keys: $(echo "$INPUT" | jq -r 'keys | @csv' 2>/dev/null || echo '(jq unavailable)')"
    exit 0  # known limitation: no session_id = no snapshot; non-fatal
fi

# ── Portable timeout helper ───────────────────────────────────────────────────
# timeout(1) is not available on macOS without coreutils. gtimeout is from brew coreutils.
TO=$(command -v gtimeout 2>/dev/null || command -v timeout 2>/dev/null || true)
# Usage: ${TO:+$TO 5} git -C ... (expands to "timeout 5 git ..." if TO is set)

# ── Active ticket detection — deterministic, worktree-scoped ─────────────────
OMNI_WORKTREES_DIR="${OMNI_WORKTREES_DIR:-/Volumes/PRO-G40/Code/omni_worktrees}"  # local-path-ok
ACTIVE_TICKET=""
ACTIVE_STATE_FILE=""
REPO_PATH=""  # initialized explicitly; used later in git gate

# Priority 1: CWD match — require worktree prefix, not just any OMN in path
if [[ -n "$SESSION_CWD" ]]; then
    if [[ "$SESSION_CWD" == "$OMNI_WORKTREES_DIR"/OMN-[0-9]* ]]; then
        ACTIVE_TICKET=$(echo "$SESSION_CWD" | sed "s|$OMNI_WORKTREES_DIR/||" | grep -o "OMN-[0-9]\+" 2>/dev/null || true)
        if [[ -n "$ACTIVE_TICKET" ]]; then
            ACTIVE_STATE_FILE="$HOME/.claude/pipelines/$ACTIVE_TICKET/state.yaml"
            if [[ ! -f "$ACTIVE_STATE_FILE" ]]; then
                ACTIVE_STATE_FILE=""
                ACTIVE_TICKET=""
            fi
        fi
    fi
fi

# Priority 2: pipeline state scan — prefer repo_path prefix match, else newest mtime
if [[ -z "$ACTIVE_TICKET" ]]; then
    BEST_MATCH=""
    BEST_MATCH_MTIME=0

    while IFS= read -r f; do
        # "in-progress" = current_phase exists and is not "done"
        phase=$(sed -n 's/^current_phase:[[:space:]]*//p' "$f" 2>/dev/null | head -1)
        [[ -z "$phase" || "$phase" == "done" ]] && continue

        repo_path=$(sed -n 's/^repo_path:[[:space:]]*//p' "$f" 2>/dev/null | head -1)

        # Prefer repo_path that is a prefix of SESSION_CWD (exact match wins immediately)
        if [[ -n "$SESSION_CWD" && -n "$repo_path" && "$SESSION_CWD" == "$repo_path"* ]]; then
            BEST_MATCH="$f"
            break
        fi

        # Else track newest by mtime
        mtime=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo 0)
        if (( mtime > BEST_MATCH_MTIME )); then
            BEST_MATCH_MTIME=$mtime
            BEST_MATCH="$f"
        fi
    done < <(find "$HOME/.claude/pipelines" -name "state.yaml" 2>/dev/null)

    if [[ -n "$BEST_MATCH" ]]; then
        ACTIVE_STATE_FILE="$BEST_MATCH"
        ACTIVE_TICKET=$(basename "$(dirname "$ACTIVE_STATE_FILE")")
    fi
fi

# ── Build snapshot — with size cap ───────────────────────────────────────────
# Note: state.yaml values are assumed unquoted and space-free (enforced by pipeline writer).
MAX_SNAPSHOT_BODY=19800  # leave 200 bytes headroom for truncation marker
SNAPSHOT_FILE="/tmp/omniclaude-compact-ctx-${SESSION_ID}"

# Extract state fields safely (sed, not awk)
PHASE=""
BRANCH=""
if [[ -n "$ACTIVE_STATE_FILE" && -f "$ACTIVE_STATE_FILE" ]]; then
    PHASE=$(sed -n 's/^current_phase:[[:space:]]*//p' "$ACTIVE_STATE_FILE" 2>/dev/null | head -1 || true)
    BRANCH=$(sed -n 's/^branch:[[:space:]]*//p' "$ACTIVE_STATE_FILE" 2>/dev/null | head -1 || true)
    REPO_PATH=$(sed -n 's/^repo_path:[[:space:]]*//p' "$ACTIVE_STATE_FILE" 2>/dev/null | head -1 || true)
fi

{
    echo "## Context Snapshot (pre-compact)"
    echo "Captured: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo ""

    if [[ -n "$ACTIVE_TICKET" ]]; then
        echo "### Active Work"
        echo "Ticket: $ACTIVE_TICKET"
        [[ -n "$PHASE" ]]     && echo "Phase: $PHASE"
        [[ -n "$BRANCH" ]]    && echo "Branch: $BRANCH"
        [[ -n "$REPO_PATH" ]] && echo "Repo: $REPO_PATH"
        echo ""

        if [[ -n "$REPO_PATH" ]] && ${TO:+$TO 5} git -C "$REPO_PATH" rev-parse --is-inside-work-tree &>/dev/null; then
            echo "### Recent Git Activity"
            ${TO:+$TO 5} git -C "$REPO_PATH" log --oneline -8 2>/dev/null || echo "(git log unavailable)"
            echo ""
            ${TO:+$TO 5} git -C "$REPO_PATH" status --short 2>/dev/null || echo "(git status unavailable)"
        fi
    else
        echo "### Session"
        echo "CWD: ${SESSION_CWD:-(unknown)}"
        echo "No active pipeline ticket detected."
    fi
} | head -c $MAX_SNAPSHOT_BODY > "$SNAPSHOT_FILE"

# Append truncation marker if body was capped
SNAPSHOT_SIZE=$(wc -c < "$SNAPSHOT_FILE")
if [[ "$SNAPSHOT_SIZE" -ge "$MAX_SNAPSHOT_BODY" ]]; then
    echo "...(truncated)" >> "$SNAPSHOT_FILE"
fi

log "PreCompact: snapshot written to $SNAPSHOT_FILE ($(wc -c < "$SNAPSHOT_FILE") bytes, ticket=${ACTIVE_TICKET:-none})"
exit 0  # always non-fatal
