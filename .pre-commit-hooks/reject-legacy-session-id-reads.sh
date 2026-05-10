#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Reject direct reads of legacy session-id env vars.
# Allowed reader: plugins/onex/hooks/lib/session_id.py (and test fixtures under tests/).
set -euo pipefail

ALLOWLIST_NAMES=("plugins/onex/hooks/lib/session_id.py")
EXTRA_ALLOWLIST_PATH_GLOBS=("tests/**" ".pre-commit-hooks/**" "**/test_*session_id*.py")

FILES=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --allowlist-name) ALLOWLIST_NAMES+=("$2"); shift 2 ;;
        --)
            shift
            FILES+=("$@")
            break
            ;;
        *) FILES+=("$1"); shift ;;
    esac
done

# Patterns match Python and shell legacy reads (both function-call and dict-subscript forms).
# SESSION_ID is omitted from SH_PAT: it is a valid local variable name in shell scripts; only
# env-var aliases CLAUDE_SESSION_ID and ONEX_SESSION_ID are forbidden direct reads.
PY_PAT='os\.(environ\.get|getenv)\(\s*["'"'"'](CLAUDE_SESSION_ID|ONEX_SESSION_ID|SESSION_ID)["'"'"']|os\.environ\[["'"'"'](CLAUDE_SESSION_ID|ONEX_SESSION_ID|SESSION_ID)["'"'"']\]'
SH_PAT='\$\{?\b(CLAUDE_SESSION_ID|ONEX_SESSION_ID)\b'

rc=0
for f in "${FILES[@]+"${FILES[@]}"}"; do
    [[ -z "$f" ]] && continue
    base=$(basename "$f")
    skip=0
    for allowed in "${ALLOWLIST_NAMES[@]}"; do
        # Support both path-qualified (e.g. plugins/onex/hooks/lib/session_id.py) and basename matches
        if [[ "$f" == *"$allowed" ]] || [[ "$base" == "$allowed" ]]; then
            skip=1; break
        fi
    done
    [[ "$skip" == 1 ]] && continue
    for glob in "${EXTRA_ALLOWLIST_PATH_GLOBS[@]}"; do
        case "$f" in
            $glob) skip=1; break ;;
        esac
    done
    [[ "$skip" == 1 ]] && continue

    if grep -E -n "$PY_PAT" "$f" >/dev/null 2>&1 \
        || grep -E -n "$SH_PAT" "$f" >/dev/null 2>&1; then
        echo "FORBIDDEN: legacy session-id env-var read in $f"
        grep -E -n "$PY_PAT|$SH_PAT" "$f" || true
        echo "  Use resolve_session_id() from plugins.onex.hooks.lib.session_id (Python)"
        echo "  or read CLAUDE_CODE_SESSION_ID directly (shell)."
        rc=1
    fi
done

exit "$rc"
