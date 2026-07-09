#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-14190 (Piece 4/5 of the canonical OCC stamp-model, epic OMN-14180):
# Shift-left validation of OCC PR-metadata stamps. This is a THIN SHIM — it owns
# ZERO stamp logic. All parsing/assertion is delegated to the onex CLI command
# `onex occ validate` (omnibase_infra.cli.cli_occ), which itself reuses the
# Piece-2 renderer/parser in omnibase_core. Do not re-implement stamp parsing
# here (CLAUDE.md: no phantom callables / no duplicated logic).
#
# What it does:
#   For each staged *.md / *.txt file that already carries an OCC stamp line
#   (`Evidence-Ticket:` or `Evidence-Source:`), assert the stamp is COMPLETE and
#   well-formed via `onex occ validate`. A half-written stamp (source without a
#   ticket, malformed OCC# ref, etc.) fails at commit time instead of on CI's
#   receipt-gate. Files with no Evidence line are not OCC artifacts and are
#   skipped — arbitrary markdown is never required to carry a stamp.
#
# Staged-blob discipline: content is read from the index (`git show :<file>`),
# not the working tree, so a working-tree edit after `git add` cannot hide a
# malformed stamp (mirrors reject-deploy-gate-skip-token.sh).
#
# Fail-closed on a missing validator: if an OCC artifact is staged but the
# `onex occ` command is unavailable (e.g. the omnibase-infra pin predates it),
# the hook HARD-FAILS rather than silently passing — a missing validator is a
# config error, not a pass (same posture as check_local_paths_wrapper, OMN-9043).
#
# Usage:
#   Invoked by pre-commit with staged filenames as arguments.
#   --self-test   Run synthetic self-tests and exit.

set -euo pipefail

TICKET_REF="OMN-14190"
RULE_REF="CLAUDE.md Rule #5 (enforcement, not detection) + Rule #10 (no bypass)"
STAMP_LINE_RE='^Evidence-(Ticket|Source):'

# Resolve the repo root of THIS hook so we can find the uv project + wrapper
# regardless of the caller's cwd (pre-commit sets cwd to the repo root, but be
# defensive). No hardcoded absolute paths (CLAUDE.md Rule #6).
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HOOK_DIR/.." && pwd)"

# ──────────────────────────────────────────────────────────────────────────────
# onex invocation — worktree-safe `uv run onex` (unset GIT_DIR/GIT_WORK_TREE so
# uv's internal git subprocess can resolve the repo, matching
# scripts/uv-run-worktree-safe.sh).
# ──────────────────────────────────────────────────────────────────────────────
run_onex() {
    (
        cd "$REPO_ROOT"
        unset GIT_DIR 2>/dev/null || true
        unset GIT_WORK_TREE 2>/dev/null || true
        # Prefer an already-resolved `onex` (activated venv / dev shell) for speed;
        # fall back to `uv run --no-sync` so a pre-commit invocation reuses the
        # already-synced project env instead of re-resolving on every commit.
        if command -v onex >/dev/null 2>&1; then
            onex "$@"
        else
            uv run --no-sync onex "$@"
        fi
    )
}

onex_occ_available() {
    run_onex occ --help >/dev/null 2>&1
}

# ──────────────────────────────────────────────────────────────────────────────
# Read the staged blob of a path (index), falling back to the working tree for
# paths not in the index (self-test temp files, edge cases).
# ──────────────────────────────────────────────────────────────────────────────
read_staged() {
    local file="$1"
    if git cat-file -e ":$file" 2>/dev/null; then
        git show ":$file"
    elif [[ -f "$file" ]]; then
        cat "$file"
    fi
}

# Validate one body (passed on stdin) via the onex CLI. Echoes onex's message on
# failure, prefixed with the original file name. Returns onex's exit status.
validate_body() {
    local label="$1"
    local body="$2"
    local output rc
    output="$(printf '%s' "$body" | run_onex occ validate --stdin 2>&1)" && rc=0 || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        echo "ERROR: OCC stamp in $label is incomplete or malformed:" >&2
        # Re-label onex's <stdin> reference with the real file name.
        echo "${output//<stdin>/$label}" >&2
    fi
    return "$rc"
}

# ──────────────────────────────────────────────────────────────────────────────
# Self-test mode
# ──────────────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--self-test" ]]; then
    if ! onex_occ_available; then
        echo "SKIP: 'onex occ' CLI unavailable in this environment — cannot self-test." >&2
        echo "      (bump the omnibase-infra pin to the release carrying $TICKET_REF)" >&2
        exit 0
    fi

    PASS=0
    FAIL=0
    run_test() {
        local name="$1" content="$2" expect_exit="$3"
        # mktemp -d + a fixed .md name so the extension filter matches on both
        # BSD (macOS) and GNU mktemp (BSD `mktemp -t` does not honor a suffix).
        local tmpdir tmpfile
        tmpdir="$(mktemp -d)"
        tmpfile="$tmpdir/body.md"
        printf '%s\n' "$content" > "$tmpfile"
        local actual_exit=0
        bash "$0" "$tmpfile" >/dev/null 2>&1 || actual_exit=$?
        rm -rf "$tmpdir"
        if [[ "$actual_exit" == "$expect_exit" ]]; then
            echo "  PASS: $name"
            PASS=$((PASS + 1))
        else
            echo "  FAIL: $name (expected exit $expect_exit, got $actual_exit)"
            FAIL=$((FAIL + 1))
        fi
    }

    echo "=== validate-occ-pr-stamp.sh self-test ==="
    run_test "complete stamp passes" \
        "Summary paragraph.

Evidence-Ticket: OMN-14190
Evidence-Source: OCC#1408" \
        0
    run_test "non-artifact markdown skipped (no Evidence line)" \
        "Just a plain readme with no stamp." \
        0
    run_test "stamp missing Evidence-Source fails" \
        "Summary.

Evidence-Ticket: OMN-14190" \
        1
    run_test "stamp missing Evidence-Ticket fails" \
        "Summary.

Evidence-Source: OCC#1408" \
        1
    run_test "malformed Evidence-Source fails" \
        "Summary.

Evidence-Ticket: OMN-14190
Evidence-Source: not-a-ref" \
        1

    echo ""
    echo "Results: $PASS passed, $FAIL failed"
    [[ "$FAIL" -gt 0 ]] && exit 1
    exit 0
fi

# ──────────────────────────────────────────────────────────────────────────────
# Normal mode: scan staged files passed as arguments.
# ──────────────────────────────────────────────────────────────────────────────
declare -a ARTIFACT_LABELS=()
declare -a ARTIFACT_BODIES=()

for file in "$@"; do
    case "$file" in
        *.md | *.txt) ;;
        *) continue ;;
    esac
    body="$(read_staged "$file")" || continue
    if grep -qiE "$STAMP_LINE_RE" <<< "$body"; then
        ARTIFACT_LABELS+=("$file")
        ARTIFACT_BODIES+=("$body")
    fi
done

# Nothing to validate → succeed silently (arbitrary files carry no stamp).
if [[ "${#ARTIFACT_LABELS[@]}" -eq 0 ]]; then
    exit 0
fi

# There ARE OCC artifacts — a missing validator is a config error, not a pass.
if ! onex_occ_available; then
    echo "ERROR: OCC stamp artifact staged but 'onex occ' CLI is unavailable." >&2
    echo "  Files: ${ARTIFACT_LABELS[*]}" >&2
    echo "  Bump the omnibase-infra dependency to the release carrying $TICKET_REF" >&2
    echo "  (onex occ stamp/validate). $RULE_REF." >&2
    exit 1
fi

FOUND_VIOLATION=0
for i in "${!ARTIFACT_LABELS[@]}"; do
    if ! validate_body "${ARTIFACT_LABELS[$i]}" "${ARTIFACT_BODIES[$i]}"; then
        FOUND_VIOLATION=1
    fi
done

if [[ "$FOUND_VIOLATION" -ne 0 ]]; then
    echo "" >&2
    echo "Fix: run 'onex occ stamp <file> --ticket OMN-XXXX --evidence-source OCC#N --in-place'" >&2
    echo "then re-stage and commit. Ticket: $TICKET_REF." >&2
fi

exit "$FOUND_VIOLATION"
