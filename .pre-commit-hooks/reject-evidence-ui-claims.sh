#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-13025 (A-3): Evidence-language guard — reject docs/evidence/** files that
# contain UI/e2e claims without a Playwright artifact referenced in the same doc.
#
# Root cause: PROCESS_FAILURE_RETRO.md §3.A — top-10 failure #1.
# The 2026-06-11 19:27Z evidence doc claimed "UI POST → full chain live" when
# only curl was run. Overstated evidence prose led to a false "done" declaration.
#
# Rejected claim patterns (case-insensitive, any occurrence):
#   UI POST         — implies browser/UI layer sent the request
#   click           — implies a human or browser click interaction
#   full chain live — implies end-to-end live chain proven through UI
#   end-to-end      — implies browser-driven e2e test completed
#   end to end      — alternate spelling
#
# A claim is allowed only when the document also references a Playwright artifact,
# indicating that the UI/e2e claim is backed by automated browser evidence:
#   playwright      — any reference to the Playwright tool or its artifacts
#   test-results/   — Playwright test-results directory reference
#
# DoD: commit blocked on overstated evidence prose.
#
# There is no suppression mechanism. Fix the evidence doc — either remove the
# unsupported claim or add the Playwright artifact reference that backs it.
#
# CLAUDE.md Rule #5 + Rule #10: Enforcement, not detection. No warn-only mode.

set -euo pipefail

# Forbidden claim patterns (ERE, case-insensitive)
CLAIM_PATTERN='UI POST|full chain live|end-to-end|end to end|click'
# Playwright artifact presence (any of these patterns = artifact referenced)
PLAYWRIGHT_PATTERN='playwright|test-results/'

TICKET_REF="OMN-13025"
RULE_REF="PROCESS_FAILURE_RETRO.md §3.A"

FOUND_VIOLATION=0

for file in "$@"; do
    # Only process markdown files
    case "$file" in
        *.md) ;;
        *) continue ;;
    esac

    # Only enforce on docs/evidence/** paths
    case "$file" in
        docs/evidence/*|\
        */docs/evidence/*) ;;
        *) continue ;;
    esac

    # Read staged blob from index; fall back to working-tree file for self-tests
    # (git show :$file reads the staged content, not the working tree)
    if git cat-file -e ":$file" 2>/dev/null; then
        content="$(git show ":$file")"
    elif [[ -f "$file" ]]; then
        content="$(cat "$file")"
    else
        continue
    fi

    # Check whether the doc contains any forbidden claim
    if ! echo "$content" | grep -qiE "$CLAIM_PATTERN"; then
        # No forbidden claims — pass
        continue
    fi

    # Doc has a forbidden claim — require a Playwright artifact reference
    if echo "$content" | grep -qiE "$PLAYWRIGHT_PATTERN"; then
        # Playwright artifact referenced — claim is backed, allow
        continue
    fi

    # Forbidden claim without Playwright artifact — reject
    MATCHED_CLAIM=$(echo "$content" | grep -oiE "$CLAIM_PATTERN" | head -1)
    echo "EVIDENCE_UI_CLAIM_UNVERIFIED: $file" >&2
    echo "  Matched claim: \"$MATCHED_CLAIM\"" >&2
    echo "  This evidence doc makes a UI/e2e claim but references no Playwright artifact." >&2
    echo "  To fix: add a Playwright artifact reference (screenshot, report path, or test run output)" >&2
    echo "  that proves the UI/e2e assertion was actually automated via Playwright." >&2
    echo "  Ticket: $TICKET_REF | Rule: $RULE_REF" >&2
    FOUND_VIOLATION=1
done

exit "$FOUND_VIOLATION"
