#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-13029 (retro A-11): Reject evidence documents that contain BLOCKER,
# UNFIXED, or defect markers without an anchoring OMN-XXXX ticket reference.
#
# Root cause this prevents (PROCESS_FAILURE_RETRO.md §3.A):
# workflows ordered ticket/PR-filing last, so diagnosis docs stranded defects
# as unanchored prose with no ticket identity. Defects survive indefinitely
# without a ticket anchor — no queue presence, no owner, no close signal.
#
# Matches files:
#   docs/evidence/**/*.md
#
# A file is flagged when:
#   (a) it contains at least one defect marker on any line:
#       BLOCKER, UNFIXED, DEFECT, REGRESSION, BUG-CONFIRMED
#   (b) the entire file contains no OMN-[0-9]+ reference
#
# Both conditions are file-scoped (not line-level): one unanchored defect
# marker anywhere in the file with no ticket anywhere in the file triggers
# the gate.
#
# Escape hatch (file-level): place the token anywhere in the file:
#   <!-- defect-anchor-ok: <reason> -->
# Use only for docs that deliberately catalogue defects without a known ticket
# (e.g. a triage dump that precedes ticket creation). The reason MUST be
# non-empty.
#
# Fails with:
#   DEFECT_ANCHOR_MISSING: <filename> — defect markers present but no OMN-XXXX reference found
#
# Enforcement: CLAUDE.md Rule #5 (enforcement, not detection). Hard fail — no warn-only mode.

set -euo pipefail

TICKET_REF="OMN-13029"
DEFECT_PATTERN='(BLOCKER|UNFIXED|DEFECT|REGRESSION|BUG-CONFIRMED)'
OMN_PATTERN='OMN-[0-9]+'
ESCAPE='defect-anchor-ok:'

FOUND_VIOLATION=0

for file in "$@"; do
    case "$file" in
        *.md) ;;
        *) continue ;;
    esac

    # Only evidence documents
    case "$file" in
        docs/evidence/*.md|\
        docs/evidence/*/*.md|\
        docs/evidence/*/*/*.md|\
        */docs/evidence/*.md|\
        */docs/evidence/*/*.md|\
        */docs/evidence/*/*/*.md) ;;
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

    # Skip if the file-level escape hatch is present
    if grep -qE "$ESCAPE" <<<"$content"; then
        continue
    fi

    # Check for defect markers
    if ! grep -qiE "$DEFECT_PATTERN" <<<"$content"; then
        continue
    fi

    # Defect marker found — check for OMN-XXXX reference
    if ! grep -qE "$OMN_PATTERN" <<<"$content"; then
        echo "DEFECT_ANCHOR_MISSING: $file — defect markers present but no OMN-XXXX reference found" >&2
        echo "  Ticket: $TICKET_REF" >&2
        echo "  Add an OMN-XXXX reference for each unresolved defect, or file a ticket first." >&2
        echo "  Escape hatch (file-level): add '<!-- defect-anchor-ok: <reason> -->' if no ticket exists yet." >&2
        FOUND_VIOLATION=1
    fi
done

exit "$FOUND_VIOLATION"
