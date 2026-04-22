#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Bash tests for plugins/onex/hooks/lib/repo_guard.sh
#
# Runs a small battery of scenarios in ephemeral tmpdirs and reports
# per-case pass/fail. Exits non-zero on any failure so CI can gate on it.
#
# Usage: bash plugins/onex/hooks/lib/test_repo_guard.sh

set -u  # Do not use -e; we explicitly inspect exit codes.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=repo_guard.sh
. "${HERE}/repo_guard.sh"

# Counters are tracked via files so subshells can increment them.
_TEST_STATE_DIR=$(mktemp -d -t repo_guard_counters.XXXXXX)
trap 'rm -rf "$_TEST_STATE_DIR"' EXIT
: > "$_TEST_STATE_DIR/pass"
: > "$_TEST_STATE_DIR/fail"

_pass() {
    printf 'x\n' >> "$_TEST_STATE_DIR/pass"
    printf 'PASS: %s\n' "$1"
}

_fail() {
    printf 'x\n' >> "$_TEST_STATE_DIR/fail"
    printf 'FAIL: %s\n' "$1" >&2
}

# Each test runs in a fresh tmpdir so state never leaks between cases.
# CLAUDE_PROJECT_DIR is explicitly controlled per case; the default is to
# unset it so tests don't get tainted by ambient session state.
_run_case() {
    local name="$1"
    local setup_fn="$2"
    local expected="$3"  # 0 or 1

    local tmp
    tmp=$(mktemp -d -t repo_guard_test.XXXXXX)
    # Ensure the tmpdir is not itself a git worktree that could be
    # detected by fallback logic.
    (
        cd "$tmp" || return 1
        "$setup_fn" "$tmp"
        CLAUDE_PROJECT_DIR="$tmp"
        export CLAUDE_PROJECT_DIR
        if is_omninode_repo; then
            actual=0
        else
            actual=1
        fi
        if [[ "$actual" == "$expected" ]]; then
            _pass "$name (expected=$expected actual=$actual)"
        else
            _fail "$name (expected=$expected actual=$actual)"
        fi
    )
    rm -rf "$tmp"
}

# --- Fixtures ---

setup_empty_readme() {
    local dir="$1"
    printf '# random project\n' > "$dir/README.md"
}

setup_omni_pyproject() {
    local dir="$1"
    cat > "$dir/pyproject.toml" <<'EOF'
[project]
name = "omnibase_core"
dependencies = []
EOF
}

setup_generic_pyproject() {
    local dir="$1"
    cat > "$dir/pyproject.toml" <<'EOF'
[project]
name = "some-third-party"
dependencies = ["requests"]
EOF
}

setup_omni_package_json() {
    local dir="$1"
    cat > "$dir/package.json" <<'EOF'
{"name": "omnidash", "dependencies": {}}
EOF
}

setup_generic_package_json() {
    local dir="$1"
    cat > "$dir/package.json" <<'EOF'
{"name": "random-frontend", "dependencies": {"react": "*"}}
EOF
}

setup_omni_claude_md() {
    local dir="$1"
    printf '# Project\n\nPart of the omninode platform.\n' > "$dir/CLAUDE.md"
}

setup_generic_claude_md() {
    local dir="$1"
    printf '# Some Project\n\nNot related to anything special.\n' > "$dir/CLAUDE.md"
}

setup_onex_state_only() {
    local dir="$1"
    mkdir -p "$dir/.onex_state"
    printf 'hello\n' > "$dir/README.md"
}

setup_workflows_without_omni() {
    local dir="$1"
    mkdir -p "$dir/.github/workflows"
    cat > "$dir/.github/workflows/ci.yml" <<'EOF'
name: CI
on: [push]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps: [{run: "echo hello"}]
EOF
}

setup_contract_yaml() {
    local dir="$1"
    printf 'name: demo\n' > "$dir/contract.yaml"
}

# --- Cases ---

_run_case "tmpdir with only README -> not omninode" setup_empty_readme 1
_run_case "pyproject references omnibase_ -> omninode" setup_omni_pyproject 0
_run_case "pyproject for unrelated package -> not omninode" setup_generic_pyproject 1
_run_case "package.json names omnidash -> omninode" setup_omni_package_json 0
_run_case "package.json for generic frontend -> not omninode" setup_generic_package_json 1
_run_case "CLAUDE.md references omninode -> omninode" setup_omni_claude_md 0
_run_case "CLAUDE.md without omninode keywords -> not omninode" setup_generic_claude_md 1
_run_case ".onex_state/ directory alone -> omninode" setup_onex_state_only 0
_run_case "workflows without omninode mention -> not omninode" setup_workflows_without_omni 1
_run_case "contract.yaml at root -> omninode" setup_contract_yaml 0

# Case: CLAUDE_PROJECT_DIR unset, CWD is a fresh git repo with no markers ->
# guard must not error, and must return 1 (not omninode).
(
    tmp=$(mktemp -d -t repo_guard_gittest.XXXXXX)
    cd "$tmp" || exit 1
    git init -q . >/dev/null 2>&1 || true
    printf '# empty\n' > README.md
    unset CLAUDE_PROJECT_DIR
    if is_omninode_repo; then
        _fail "git repo with no markers, CLAUDE_PROJECT_DIR unset (expected=1)"
    else
        _pass "git repo with no markers, CLAUDE_PROJECT_DIR unset (expected=1)"
    fi
    cd / && rm -rf "$tmp"
)

# Case: CLAUDE_PROJECT_DIR unset, CWD is not a git repo -> returns 1 without error.
(
    tmp=$(mktemp -d -t repo_guard_nogit.XXXXXX)
    cd "$tmp" || exit 1
    unset CLAUDE_PROJECT_DIR
    if is_omninode_repo; then
        _fail "non-git CWD, CLAUDE_PROJECT_DIR unset (expected=1)"
    else
        _pass "non-git CWD, CLAUDE_PROJECT_DIR unset (expected=1)"
    fi
    cd / && rm -rf "$tmp"
)

# Case: real omniclaude tree (if present in this checkout) -> omninode.
# This doubles as a sanity check that detection works on the canonical repo.
if [[ -f "${HERE}/../../../pyproject.toml" ]]; then
    (
        root=$(cd "${HERE}/../../.." && pwd)
        CLAUDE_PROJECT_DIR="$root"
        export CLAUDE_PROJECT_DIR
        if is_omninode_repo; then
            _pass "omniclaude checkout is detected as omninode"
        else
            _fail "omniclaude checkout is detected as omninode"
        fi
    )
fi

PASS_COUNT=$(wc -l < "$_TEST_STATE_DIR/pass" | tr -d ' ')
FAIL_COUNT=$(wc -l < "$_TEST_STATE_DIR/fail" | tr -d ' ')
printf '\nRESULT: %d passed, %d failed\n' "$PASS_COUNT" "$FAIL_COUNT"
if [[ "$FAIL_COUNT" -gt 0 ]]; then
    exit 1
fi
exit 0
