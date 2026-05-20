#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# test-cron-contract-verify.sh - Regression test for cron-contract-verify prompt defaults.
#
# Verifies dry-run output includes full runtime verification while using a
# temporary canonical clone and mocked claude binary.
#
# Usage: bash scripts/tests/test-cron-contract-verify.sh
#
# [OMN-9071]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CRON_SCRIPT="${SCRIPT_DIR}/../cron-contract-verify.sh"

PASS=0
FAIL=0
TEST_TMP=""
TEST_CLONE=""
TEST_MOCK_DIR=""

_assert_contains() {
  local desc="$1"
  local needle="$2"
  local haystack="$3"
  if echo "${haystack}" | grep -q -- "${needle}"; then
    echo "PASS: ${desc}"
    PASS=$((PASS + 1))
  else
    echo "FAIL: ${desc} - expected '${needle}' in output"
    echo "  actual: ${haystack}"
    FAIL=$((FAIL + 1))
  fi
}

_assert_not_contains() {
  local desc="$1"
  local needle="$2"
  local haystack="$3"
  if echo "${haystack}" | grep -q -- "${needle}"; then
    echo "FAIL: ${desc} - did not expect '${needle}' in output"
    echo "  actual: ${haystack}"
    FAIL=$((FAIL + 1))
  else
    echo "PASS: ${desc}"
    PASS=$((PASS + 1))
  fi
}

_assert_exit() {
  local desc="$1"
  local expected_exit="$2"
  local actual_exit="$3"
  if [[ "${actual_exit}" -eq "${expected_exit}" ]]; then
    echo "PASS: ${desc}"
    PASS=$((PASS + 1))
  else
    echo "FAIL: ${desc} - expected exit ${expected_exit}, got ${actual_exit}"
    FAIL=$((FAIL + 1))
  fi
}

# shellcheck disable=SC2329  # invoked by trap EXIT
cleanup() {
  if [[ -n "${TEST_TMP}" ]]; then
    rm -rf "${TEST_TMP}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

make_canonical_clone() {
  TEST_TMP="$(mktemp -d)"
  local origin="${TEST_TMP}/origin.git"
  local clone="${TEST_TMP}/omniclaude"

  git init --bare "${origin}" -q
  git clone "${origin}" "${clone}" -q 2>/dev/null
  git -C "${clone}" config user.email "test@test.local"
  git -C "${clone}" config user.name "Test"
  echo "init" > "${clone}/file.txt"
  git -C "${clone}" add file.txt
  git -C "${clone}" commit -m "init" -q
  git -C "${clone}" push -u origin HEAD:main -q 2>/dev/null

  TEST_CLONE="${clone}"
}

make_mock_claude() {
  local mock_dir="${TEST_TMP}/bin"
  mkdir -p "${mock_dir}"
  cat > "${mock_dir}/claude" << 'MOCK_CLAUDE'
#!/usr/bin/env bash
echo "mock claude should not run during dry-run" >&2
exit 99
MOCK_CLAUDE
  chmod +x "${mock_dir}/claude"
  TEST_MOCK_DIR="${mock_dir}"
}

test_dry_run_uses_full_runtime_verification() {
  make_canonical_clone
  make_mock_claude

  local output exit_code
  output="$(
    env \
      HOME="${TEST_TMP}/home" \
      OMNI_HOME="${TEST_TMP}/registry" \
      CANONICAL_CLONE="${TEST_CLONE}" \
      PATH="${TEST_MOCK_DIR}:${PATH}" \
      bash "${CRON_SCRIPT}" --dry-run 2>&1
  )" && exit_code=0 || exit_code=$?

  _assert_exit "dry_run: exits 0" 0 "${exit_code}"
  _assert_contains \
    "dry_run: prompt enables full runtime verification" \
    "/onex:contract_sweep --mode runtime --full-runtime-verification" \
    "${output}"
  _assert_not_contains \
    "dry_run: prompt is not registration-only" \
    "claude -p '/onex:contract_sweep --mode runtime' --allowedTools" \
    "${output}"
}

echo "=== cron-contract-verify tests [OMN-9071] ==="
echo ""

test_dry_run_uses_full_runtime_verification

echo ""
echo "--- results ---"
echo "  PASS: ${PASS}"
echo "  FAIL: ${FAIL}"
echo ""

if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
