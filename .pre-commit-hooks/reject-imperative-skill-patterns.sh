#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-12237 (Wave 7 imperative-skill migration regression guard):
# Rejects new imperative patterns in skills/*/SKILL.md files.
#
# Imperative patterns detected:
#   1. Bare `Agent(` calls (inline business logic, not dispatch description)
#   2. `TeamCreate` references (should live in a node)
#   3. `curl ` / `wget ` commands (HTTP calls must go through nodes)
#   4. `gh api` / `gh pr` commands (GitHub API must go through nodes)
#   5. `psql` / `pg_` commands (DB access must go through nodes)
#   6. `ssh ` commands (infra ops must go through nodes)
#   7. `asyncio.run(` (direct handler invocation instead of dispatch)
#   8. `http://localhost` / `http://192.168` (direct endpoint calls bypass bus)
#
# ALLOWLISTED skill directories (PURE-SKILL — legitimately use some patterns):
#   handoff, login, preflight, record_friction, set_session,
#   systematic_debugging, unstick_queue, using_git_worktrees, worktree,
#   writing_skills, authorize
#
# ESCAPE HATCH: append `# imperative-ok` to a line to suppress that finding.
#
# BLOCKING — no warn-only mode. CLAUDE.md Rule #5 + Rule #10.
# Ticket: OMN-12237

set -euo pipefail

TICKET_REF="OMN-12237"

# Path (relative to repo root) to the baseline file listing skill dirs with
# pre-existing violations that are tracked for Wave 7 migration cleanup.
# Resolved relative to the script's own directory (repo root/.pre-commit-hooks/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASELINE_FILE="${SCRIPT_DIR}/../plugins/onex/skills/_lib/imperative_skill_baseline.txt"

# ──────────────────────────────────────────────────────────────────────────────
# Allowlisted skill directory names (basename of skill dir only)
# ──────────────────────────────────────────────────────────────────────────────
ALLOWLISTED_SKILLS=(
    "handoff"
    "login"
    "preflight"
    "record_friction"
    "set_session"
    "systematic_debugging"
    "unstick_queue"
    "using_git_worktrees"
    "worktree"
    "writing_skills"
    "authorize"
)

# ──────────────────────────────────────────────────────────────────────────────
# Patterns that indicate imperative inline logic in SKILL.md
# Each entry is a grep -E pattern (extended regex).
# ──────────────────────────────────────────────────────────────────────────────
# Pattern list — order matters only for readable error messages.
declare -a PATTERNS
declare -a PATTERN_LABELS

PATTERNS+=('^[^`]*\bAgent\(')
PATTERN_LABELS+=("Bare Agent( call (inline logic must be in a node)")

PATTERNS+=('\bTeamCreate\b')
PATTERN_LABELS+=("TeamCreate reference (must be in a node)")

PATTERNS+=('(^|[^a-zA-Z])(curl |wget )')
PATTERN_LABELS+=("curl/wget command (HTTP calls must go through nodes)")

PATTERNS+=('(^|[[:space:]])(gh api|gh pr)[[:space:]]')
PATTERN_LABELS+=("gh api/gh pr command (GitHub API must go through nodes)")

PATTERNS+=('(^|[[:space:]])(psql|pg_dump|pg_restore)[[:space:][:punct:]]')
PATTERN_LABELS+=("psql/pg_ command (DB access must go through nodes)")

PATTERNS+=('(^|[[:space:]])ssh [^#]')
PATTERN_LABELS+=("ssh command (infra ops must go through nodes)")

PATTERNS+=('\basyncio\.run\(')
PATTERN_LABELS+=("asyncio.run( (direct handler invocation; use dispatch instead)")

PATTERNS+=('http://(localhost|192\.168)\b')
PATTERN_LABELS+=("http://localhost or http://192.168 (direct endpoint call bypasses bus)")

# ──────────────────────────────────────────────────────────────────────────────
# Helper: check whether a skill directory is allowlisted (PURE-SKILL) or in
# the pre-existing-violation baseline (Wave 7 migration backlog).
# ──────────────────────────────────────────────────────────────────────────────
is_allowlisted() {
    local skill_dir="$1"
    local skill_name
    skill_name="$(basename "$skill_dir")"

    # PURE-SKILL allowlist (structural — will not be migrated)
    for allowed in "${ALLOWLISTED_SKILLS[@]}"; do
        if [[ "$skill_name" == "$allowed" ]]; then
            return 0
        fi
    done

    # Pre-existing violation baseline (Wave 7 migration backlog)
    if [[ -f "$BASELINE_FILE" ]]; then
        # Normalise: strip trailing slashes and compare path suffix
        local norm_dir="${skill_dir%/}"
        while IFS= read -r baseline_entry || [[ -n "$baseline_entry" ]]; do
            # Skip comments and blank lines
            [[ "$baseline_entry" =~ ^[[:space:]]*# ]] && continue
            [[ -z "${baseline_entry// }" ]] && continue
            local norm_entry="${baseline_entry%/}"
            # Match either exact path or path suffix (works regardless of relative/absolute)
            if [[ "$norm_dir" == "$norm_entry" || "$norm_dir" == */"$norm_entry" || "$norm_dir" == "$norm_entry"/* ]]; then
                return 0
            fi
            # Also match when norm_dir ends with the basename of norm_entry
            local entry_base
            entry_base="$(basename "$norm_entry")"
            if [[ "$norm_dir" == *"/$entry_base" && "$(basename "$norm_dir")" == "$entry_base" ]]; then
                # Verify the full suffix matches (avoids false positives on shared basenames)
                if [[ "$norm_dir" == *"$norm_entry" ]]; then
                    return 0
                fi
            fi
        done < "$BASELINE_FILE"
    fi

    return 1
}

# ──────────────────────────────────────────────────────────────────────────────
# Self-test mode
# ──────────────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--self-test" ]]; then
    PASS=0
    FAIL=0

    run_test() {
        local name="$1"
        local fake_path="$2"
        local content="$3"
        local expect_exit="$4"

        tmpdir=$(mktemp -d /tmp/imperative-selftest.XXXXXX)
        tmpfile="$tmpdir/SKILL.md"
        printf '%s\n' "$content" > "$tmpfile"

        actual_exit=0
        bash "$0" "$fake_path:$tmpfile" 2>/dev/null || actual_exit=$?

        rm -rf "$tmpdir"

        if [[ "$actual_exit" == "$expect_exit" ]]; then
            echo "  PASS: $name"
            PASS=$((PASS + 1))
        else
            echo "  FAIL: $name (expected exit $expect_exit, got $actual_exit)"
            FAIL=$((FAIL + 1))
        fi
    }

    echo "=== reject-imperative-skill-patterns.sh self-test ==="

    run_test "clean SKILL.md passes" \
        "plugins/onex/skills/my_skill/SKILL.md" \
        "## Overview\nDispatch via onex run-node." \
        0

    run_test "Agent( call rejected" \
        "plugins/onex/skills/my_skill/SKILL.md" \
        "Run Agent(prompt=...) to invoke." \
        1

    run_test "TeamCreate rejected" \
        "plugins/onex/skills/other_skill/SKILL.md" \
        "Call TeamCreate to spawn workers." \
        1

    run_test "curl command rejected" \
        "plugins/onex/skills/my_skill/SKILL.md" \
        "Run: curl http://example.com/api" \
        1

    run_test "gh api rejected" \
        "plugins/onex/skills/my_skill/SKILL.md" \
        "Execute gh api repos/foo" \
        1

    run_test "asyncio.run( rejected" \
        "plugins/onex/skills/my_skill/SKILL.md" \
        "Call asyncio.run(handler())" \
        1

    run_test "http://localhost rejected" \
        "plugins/onex/skills/my_skill/SKILL.md" \
        "POST to http://localhost:8085/run" \
        1

    run_test "http://192.168 rejected" \
        "plugins/onex/skills/my_skill/SKILL.md" \
        "Call http://192.168.86.201:8000/v1" \
        1

    run_test "imperative-ok suppresses finding" \
        "plugins/onex/skills/my_skill/SKILL.md" \
        "Run Agent(prompt=...) # imperative-ok" \
        0

    run_test "allowlisted skill (handoff) passes with Agent(" \
        "plugins/onex/skills/handoff/SKILL.md" \
        "Run Agent(prompt=...) to invoke." \
        0

    run_test "allowlisted skill (authorize) passes with curl" \
        "plugins/onex/skills/authorize/SKILL.md" \
        "Run: curl http://example.com/api" \
        0

    run_test "non-SKILL.md file skipped" \
        "plugins/onex/skills/my_skill/prompt.md" \
        "Run Agent(prompt=...) to invoke." \
        0

    echo ""
    echo "Results: $PASS passed, $FAIL failed"
    if [[ "$FAIL" -gt 0 ]]; then
        exit 1
    fi
    exit 0
fi

# ──────────────────────────────────────────────────────────────────────────────
# Normal mode: scan staged files passed as arguments.
#
# Arguments may be either plain paths (from pre-commit) or
# "fake_path:real_path" pairs used by self-test to simulate allowlist checks
# without creating real staged index entries.
# ──────────────────────────────────────────────────────────────────────────────
FOUND_VIOLATION=0

for arg in "$@"; do
    # Self-test passes "canonical_path:real_file_path"; split on first colon.
    if [[ "$arg" == *:/* ]]; then
        file="${arg%%:*}"
        real_file="${arg#*:}"
    else
        file="$arg"
        real_file=""
    fi

    # Only process SKILL.md files
    case "$file" in
        */SKILL.md|SKILL.md) ;;
        *) continue ;;
    esac

    # Derive the skill directory from the file path and check allowlist.
    skill_dir="$(dirname "$file")"
    if is_allowlisted "$skill_dir"; then
        continue
    fi

    # Read staged blob from index; fall back to working-tree file.
    if [[ -n "$real_file" && -f "$real_file" ]]; then
        content="$(cat "$real_file")"
    elif git cat-file -e ":$file" 2>/dev/null; then
        content="$(git show ":$file")"
    elif [[ -f "$file" ]]; then
        content="$(cat "$file")"
    else
        continue
    fi

    # ── Scan each pattern against each non-imperative-ok line ────────────────
    for i in "${!PATTERNS[@]}"; do
        pat="${PATTERNS[$i]}"
        label="${PATTERN_LABELS[$i]}"

        # Filter out lines with the escape hatch annotation, then grep the rest.
        violations=$(grep -nE "$pat" <<< "$content" | grep -v '#[[:space:]]*imperative-ok' || true)

        if [[ -n "$violations" ]]; then
            echo "ERROR: $file — imperative pattern detected: $label" >&2
            while IFS= read -r line; do
                echo "  $line" >&2
            done <<< "$violations"
            echo "  Fix: move this logic into an omnimarket node and dispatch via onex run-node." >&2
            echo "  Escape: append '# imperative-ok' to suppress a specific line (exceptional use only)." >&2
            echo "  Ticket: $TICKET_REF" >&2
            FOUND_VIOLATION=1
        fi
    done
done

exit "$FOUND_VIOLATION"
