#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-11271: Reject handoff documents missing the mandatory ## Infra Health section.
#
# Matches files:
#   docs/handoffs/*.md
#   docs/*handoff*.md
#   docs/tracking/*handoff*.md
#
# Fails with:
#   HANDOFF_MISSING_INFRA_HEALTH: <filename> — add ## Infra Health section
#
# Required by OMN-8867 (handoff template spec) and CLAUDE.md Rule #5 (enforcement, not detection).
# No warn-only mode. Hard fail on missing section.

set -euo pipefail

SECTION_PATTERN='^## Infra Health'
TICKET_REF="OMN-11271"

FOUND_VIOLATION=0

for file in "$@"; do
    case "$file" in
        *.md) ;;
        *) continue ;;
    esac

    # Only process handoff documents
    case "$file" in
        docs/handoffs/*.md|\
        docs/*handoff*.md|\
        docs/tracking/*handoff*.md|\
        */docs/handoffs/*.md|\
        */docs/*handoff*.md|\
        */docs/tracking/*handoff*.md) ;;
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

    if ! grep -qE "$SECTION_PATTERN" <<< "$content"; then
        echo "HANDOFF_MISSING_INFRA_HEALTH: $file — add ## Infra Health section" >&2
        echo "  Ticket: $TICKET_REF | Spec: OMN-8867" >&2
        FOUND_VIOLATION=1
    fi
done

exit "$FOUND_VIOLATION"
