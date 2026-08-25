#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Regression guard: every `hookSpecificOutput` EMISSION must also carry
# `hookEventName`. Per the Claude Code hook schema, `hookSpecificOutput`
# without `hookEventName` is rejected by the client — `additionalContext`,
# `suppressOutput`, `decision`, and other directives are silently dropped.
#
# Ticket: OMN-9072
#
# Granularity (why this is per-emission, not per-file): the original check was
# `grep -q hookEventName "$file"` — a whole-file test. Any file containing at
# least one conforming emitter masked every non-conforming one in the same
# file. That is exactly how session-start.sh's lite-mode branch shipped a
# hookEventName-less SessionStart envelope while the file's three full-mode
# emissions (which do set it) kept the guard green.
#
# Detection: for each line mentioning `hookSpecificOutput`, look for
# `hookEventName` within +/- PROXIMITY_LINES. A window is required because a
# single emission legitimately spans multiple lines in both directions:
#   - jq pipelines put hookEventName FIRST, then chain more .hookSpecificOutput
#     assignments on following lines
#   - jq/python object literals put `hookSpecificOutput: {` first and
#     `hookEventName` on a LATER line
# Known limitation: two emissions closer together than the window can mask each
# other (a conforming one can cover a non-conforming neighbour). That is a much
# smaller hole than whole-file matching, and it fails toward false-negative
# rather than blocking a correct push.
#
# Scope: plugins/onex/hooks/{scripts,lib}/ and plugins/onex/hooks/*.sh.
# Excludes: test fixtures and this script itself.
#
# Exit codes:
#   0 — every hookSpecificOutput emission includes hookEventName
#   1 — one or more offending emissions found (printed to stderr)

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

# Lines to search on each side of a `hookSpecificOutput` mention when looking
# for its `hookEventName`. Sized empirically: 12 is the smallest window that
# clears every in-tree false positive. The binding case is
# lane_termination_guard.py, which builds the envelope with hookEventName at
# :387 and then mutates that same envelope at :398 -- 11 lines later. Narrower
# windows flag the mutation as a separate hookEventName-less emission.
# Override with HOOK_EVENT_NAME_PROXIMITY when adding a longer emission shape.
PROXIMITY_LINES="${HOOK_EVENT_NAME_PROXIMITY:-12}"

found_offender=0
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  # Skip the guard itself and any test fixture under tests/ or fixtures/ directories,
  # where missing hookEventName may be intentional (e.g. fixture for negative tests).
  case "$file" in
    */check_hook_event_names.sh) continue ;;
    */tests/*) continue ;;
    */fixtures/*) continue ;;
    */test-fixtures/*) continue ;;
    */test-hooks.sh) continue ;;
    */test_injection_probe.sh) continue ;;
  esac

  # Report every offending emission as file:line, not just the file.
  offenders="$(awk -v window="$PROXIMITY_LINES" '
    # Track python triple-quoted blocks so prose in docstrings is not mistaken
    # for an emission. Counts quote-markers per line; odd count toggles state.
    function marker_count(s,   n, t) {
      n = 0; t = s
      while (match(t, /"""|\x27\x27\x27/)) { n++; t = substr(t, RSTART + RLENGTH) }
      return n
    }
    {
      line[NR] = $0
      n_mark = marker_count($0)
      # A line bearing a docstring marker is itself prose (it opens or closes
      # the block), so record it as in-doc regardless of the toggle direction.
      indoc[NR] = (in_doc || n_mark > 0)
      if (n_mark % 2 == 1) in_doc = !in_doc
    }
    END {
      for (i = 1; i <= NR; i++) {
        if (index(line[i], "hookSpecificOutput") == 0) continue
        # Prose, not code: shell/python comments and docstring bodies.
        if (line[i] ~ /^[[:space:]]*#/) continue
        if (indoc[i]) continue
        # Escape hatch for prose/accessors that are not emissions, mirroring the
        # existing allowlist-pragma convention used elsewhere in this repo.
        if (line[i] ~ /hook-event-name: not-an-emission/) continue
        lo = i - window; if (lo < 1)  lo = 1
        hi = i + window; if (hi > NR) hi = NR
        covered = 0
        for (j = lo; j <= hi; j++) {
          if (line[j] ~ /^[[:space:]]*#/) continue
          if (indoc[j]) continue
          if (index(line[j], "hookEventName") > 0) { covered = 1; break }
        }
        if (!covered) print i
      }
    }
  ' "$file")"

  [[ -z "$offenders" ]] && continue

  if [[ "$found_offender" -eq 0 ]]; then
    echo "ERROR: hookSpecificOutput emitted without hookEventName (OMN-9072):" >&2
    found_offender=1
  fi
  while IFS= read -r lineno; do
    [[ -z "$lineno" ]] && continue
    echo "  - ${file#"${REPO_ROOT}/"}:${lineno}" >&2
  done <<< "$offenders"
done < "$tmp_candidates"

if [[ "$found_offender" -eq 1 ]]; then
  echo "" >&2
  echo "Claude Code rejects hookSpecificOutput payloads lacking hookEventName." >&2
  echo 'Add "hookEventName": "<EventName>" matching the hook slot in hooks.json.' >&2
  exit 1
fi

exit 0
