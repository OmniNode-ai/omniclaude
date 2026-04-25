#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# DGM-Phase4 (OMN-9730): Mechanical block on skip-deploy-gate bypass tokens.
# Rejects any staged file or commit message containing [skip-deploy-gate:].
#
# CLAUDE.md Rule #10: Never bypass local gates. Fix the underlying issue.
# Plan: omni_home/docs/plans/2026-04-25-deploy-gate-matcher-narrowing.md Phase 4
#
# Escape hatch (explicit user approval only):
#   Add a line containing:  # skip-token-allowed: <receipt-id>
#   The receipt-id documents the explicit user approval hand-off.
#   This is NOT a free-text bypass — it requires a traceable approval receipt.
#
# Usage:
#   Invoked by pre-commit with staged filenames as arguments.
#   --self-test       Run synthetic self-tests and exit.
#   --check-pr-body <PR_NUMBER>   Also scan live PR body via gh cli.

set -euo pipefail

SKIP_PATTERN='\[skip-deploy-gate:'
ALLOWLIST_PATTERN='#[[:space:]]*skip-token-allowed:[[:space:]]*[^[:space:]]'

RULE_REF="CLAUDE.md Rule #10 + docs/plans/2026-04-25-deploy-gate-matcher-narrowing.md Phase 4"
TICKET_REF="OMN-9730"

# ──────────────────────────────────────────────────────────────────────────────
# Self-test mode
# ──────────────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--self-test" ]]; then
    PASS=0
    FAIL=0

    run_test() {
        local name="$1"
        local content="$2"
        local expect_exit="$3"

        tmpfile=$(mktemp /tmp/skip-token-selftest.XXXXXX)
        printf '%s\n' "$content" > "$tmpfile"

        # Run hook against the temp file (not --self-test or --check-pr-body mode)
        actual_exit=0
        bash "$0" "$tmpfile" 2>/dev/null || actual_exit=$?

        rm -f "$tmpfile"

        if [[ "$actual_exit" == "$expect_exit" ]]; then
            echo "  PASS: $name"
            PASS=$((PASS + 1))
        else
            echo "  FAIL: $name (expected exit $expect_exit, got $actual_exit)"
            FAIL=$((FAIL + 1))
        fi
    }

    echo "=== reject-deploy-gate-skip-token.sh self-test ==="

    run_test "clean file passes" \
        "This is a clean PR body with no bypass tokens." \
        0

    run_test "skip-deploy-gate token rejected" \
        "[skip-deploy-gate: correctness fix, no deployable artifact change]" \
        1

    run_test "skip-deploy-gate with allowlist receipt passes" \
        "[skip-deploy-gate: correctness fix]
# skip-token-allowed: USER-APPROVAL-2026-04-25-jonah" \
        0

    run_test "allowlist without skip-token passes" \
        "Normal PR body
# skip-token-allowed: some-receipt" \
        0

    run_test "case-insensitive skip-deploy-gate rejected" \
        "[Skip-Deploy-Gate: reason here]" \
        1

    echo ""
    echo "Results: $PASS passed, $FAIL failed"
    if [[ "$FAIL" -gt 0 ]]; then
        exit 1
    fi
    exit 0
fi

# ──────────────────────────────────────────────────────────────────────────────
# PR body check mode
# ──────────────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--check-pr-body" ]]; then
    PR_NUMBER="${2:-}"
    if [[ -z "$PR_NUMBER" ]]; then
        echo "ERROR: --check-pr-body requires a PR number as the next argument" >&2
        exit 1
    fi

    if ! command -v gh &>/dev/null; then
        echo "WARNING: gh cli not available — skipping PR body check" >&2
        exit 0
    fi

    PR_BODY=$(gh pr view "$PR_NUMBER" --json body --jq .body 2>/dev/null || true)
    if [[ -z "$PR_BODY" ]]; then
        echo "WARNING: could not fetch PR body for PR #$PR_NUMBER — skipping" >&2
        exit 0
    fi

    if echo "$PR_BODY" | grep -qiE "$SKIP_PATTERN"; then
        if echo "$PR_BODY" | grep -qE "$ALLOWLIST_PATTERN"; then
            echo "WARNING: [skip-deploy-gate:] found in PR #$PR_NUMBER body but explicit approval receipt present — allowed." >&2
            exit 0
        fi
        echo "ERROR: PR #$PR_NUMBER body contains a [skip-deploy-gate:] bypass token." >&2
        echo "  Per $RULE_REF, bypass is not permitted without explicit user approval." >&2
        echo "  Fix the deploy-gate properly: add dod_evidence or use the structured no_deployable_artifact exception." >&2
        echo "  Ticket: $TICKET_REF" >&2
        exit 1
    fi
    exit 0
fi

# ──────────────────────────────────────────────────────────────────────────────
# Normal mode: scan staged files passed as arguments
# ──────────────────────────────────────────────────────────────────────────────
FOUND_VIOLATION=0

for file in "$@"; do
    [[ -f "$file" ]] || continue

    if grep -qiE "$SKIP_PATTERN" "$file"; then
        # Check for explicit allowlist receipt in the same file
        if grep -qE "$ALLOWLIST_PATTERN" "$file"; then
            echo "WARNING: [skip-deploy-gate:] found in $file but explicit approval receipt present — allowed." >&2
            continue
        fi

        echo "ERROR: $file contains a [skip-deploy-gate:] bypass token." >&2
        echo "  Per $RULE_REF, bypass is not permitted without explicit user approval." >&2
        echo "  Fix the deploy-gate properly:" >&2
        echo "    1. Add dod_evidence with type: no_deployable_artifact (preferred)" >&2
        echo "    2. Narrow the path patterns in validate_pr_deploy_required.py" >&2
        echo "    3. If truly exceptional, add '# skip-token-allowed: <receipt-id>' with a traceable approval receipt" >&2
        echo "  Ticket: $TICKET_REF" >&2
        FOUND_VIOLATION=1
    fi
done

# Also scan the commit message if COMMIT_EDITMSG is available (pre-commit sets GIT_DIR)
COMMIT_MSG_FILE="${GIT_DIR:-$(git rev-parse --git-dir 2>/dev/null || true)}/COMMIT_EDITMSG"
if [[ -f "$COMMIT_MSG_FILE" ]]; then
    if grep -qiE "$SKIP_PATTERN" "$COMMIT_MSG_FILE"; then
        if ! grep -qE "$ALLOWLIST_PATTERN" "$COMMIT_MSG_FILE"; then
            echo "ERROR: commit message contains a [skip-deploy-gate:] bypass token." >&2
            echo "  Per $RULE_REF, bypass is not permitted without explicit user approval." >&2
            echo "  Ticket: $TICKET_REF" >&2
            FOUND_VIOLATION=1
        fi
    fi
fi

exit "$FOUND_VIOLATION"
