#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-13023 (retro B-11): Reject Z-suffixed timestamps adjacent to file-mtime
# citations in handoff/evidence documents.
#
# Failure class this prevents (PROCESS_FAILURE_RETRO.md §5.1, 2026-06-11):
# an evening handoff transcribed local-EDT `ls -l` mtimes with a `Z` suffix,
# manufacturing a false "16:00Z mass worker death / 4h undetected" outage
# narrative that a later investigation consumed as fact. UTC timestamps must
# come from `date -u` or epoch conversion — never from local-time file
# listings relabeled as UTC.
#
# Matches files:
#   docs/handoffs/**/*.md
#   docs/evidence/**/*.md
#
# Fires when a single line contains BOTH:
#   (a) an mtime-citation marker: `ls -l`, `ls -la`, `mtime`, `Finder`,
#       `last modified`, `modified at`, `modification time`
#   (b) a Z-suffixed clock time (e.g. `16:00Z`, `2026-06-11T16:00:12Z`)
#
# Escape hatch (same line): `utc-ok: <reason>` — use ONLY when the timestamp
# was independently produced by `date -u`/epoch conversion and the mtime
# marker is incidental prose. Cite the conversion.
#
# Fails with:
#   UTC_MTIME_MISLABEL: <file>:<line> — Z-suffixed time cited next to an mtime
#
# CLAUDE.md Rule #5 (enforcement, not detection). No warn-only mode.

set -euo pipefail

TICKET_REF="OMN-13023"
MTIME_MARKER='(ls -la?|mtime|Finder|last modified|modified at|modification time)'
Z_TIME='[0-9]{2}:[0-9]{2}(:[0-9]{2})?(\.[0-9]+)?Z'
ESCAPE='utc-ok:'

FOUND_VIOLATION=0

for file in "$@"; do
    case "$file" in
        *.md) ;;
        *) continue ;;
    esac

    # Only handoff/evidence documents
    case "$file" in
        docs/handoffs/*.md|docs/evidence/*.md|\
        docs/handoffs/*/*.md|docs/evidence/*/*.md|\
        */docs/handoffs/*.md|*/docs/evidence/*.md|\
        */docs/handoffs/*/*.md|*/docs/evidence/*/*.md) ;;
        *) continue ;;
    esac

    # Read from staged index when available; fall back to working tree for self-test
    if git cat-file -e ":$file" 2>/dev/null; then
        content="$(git show ":$file")"
    elif [[ -f "$file" ]]; then
        content="$(cat "$file")"
    else
        continue
    fi

    lineno=0
    while IFS= read -r line; do
        lineno=$((lineno + 1))
        if grep -qE "$ESCAPE" <<<"$line"; then
            continue
        fi
        if grep -qiE "$MTIME_MARKER" <<<"$line" && grep -qE "$Z_TIME" <<<"$line"; then
            echo "UTC_MTIME_MISLABEL: ${file}:${lineno} — Z-suffixed time cited next to an mtime marker (${TICKET_REF})" >&2
            echo "  ${line}" >&2
            echo "  Local file mtimes are NOT UTC. Source the timestamp from 'date -u' or epoch conversion," >&2
            echo "  or drop the Z suffix and label the timezone explicitly. Escape hatch: 'utc-ok: <reason>'." >&2
            FOUND_VIOLATION=1
        fi
    done <<<"$content"
done

exit "$FOUND_VIOLATION"
