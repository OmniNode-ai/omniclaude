#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Regression guard: every hook script that emits `hookSpecificOutput` must also
# emit `hookEventName`. Per the Claude Code hook schema, `hookSpecificOutput`
# without `hookEventName` is rejected by the client — `additionalContext`,
# `suppressOutput`, `decision`, and other directives are silently dropped.
#
# Ticket: OMN-9072
#
# Scope: plugins/onex/hooks/{scripts,lib}/ and plugins/onex/hooks/*.sh.
# Excludes: test fixtures and this script itself.
#
# Exit codes:
#   0 — all hookSpecificOutput emitters include hookEventName
#   1 — one or more offenders found (printed to stderr)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_DIRS=(
  "${REPO_ROOT}/plugins/onex/hooks/scripts"
  "${REPO_ROOT}/plugins/onex/hooks/lib"
)

# Also include top-level *.sh in plugins/onex/hooks/
HOOK_TOP_SH="${REPO_ROOT}/plugins/onex/hooks"

# Gather candidates into a temp file so this works on bash 3.x (no mapfile)
tmp_candidates="$(mktemp)"
trap 'rm -f "$tmp_candidates"' EXIT

{
  for d in "${HOOK_DIRS[@]}"; do
    [[ -d "$d" ]] || continue
    grep -rl --include='*.sh' --include='*.py' 'hookSpecificOutput' "$d" 2>/dev/null || true
  done
  if [[ -d "$HOOK_TOP_SH" ]]; then
    # -d maxdepth emulation: only *.sh directly under HOOK_TOP_SH, not recursive
    for f in "$HOOK_TOP_SH"/*.sh; do
      [[ -f "$f" ]] || continue
      if grep -q 'hookSpecificOutput' "$f" 2>/dev/null; then
        echo "$f"
      fi
    done
  fi
} | sort -u > "$tmp_candidates"

found_offender=0
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  case "$file" in
    */check_hook_event_names.sh) continue ;;
  esac
  if ! grep -q 'hookEventName' "$file"; then
    if [[ "$found_offender" -eq 0 ]]; then
      echo "ERROR: hook scripts emit hookSpecificOutput without hookEventName (OMN-9072):" >&2
      found_offender=1
    fi
    echo "  - ${file#"${REPO_ROOT}/"}" >&2
  fi
done < "$tmp_candidates"

if [[ "$found_offender" -eq 1 ]]; then
  echo "" >&2
  echo "Claude Code rejects hookSpecificOutput payloads lacking hookEventName." >&2
  echo 'Add "hookEventName": "<EventName>" matching the hook slot in hooks.json.' >&2
  exit 1
fi

exit 0
