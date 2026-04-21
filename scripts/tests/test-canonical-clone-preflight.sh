#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# test-canonical-clone-preflight.sh — Unit-style tests for canonical-clone-preflight.sh
#
# Creates temporary git repos to exercise fast-forward, non-ff, and lock-contention paths.
# Compatible with bash 3.2 (macOS system bash — no mapfile, no associative arrays).
#
# Usage: bash scripts/tests/test-canonical-clone-preflight.sh
#
# [OMN-9405]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
PREFLIGHT_SCRIPT="${LIB_DIR}/canonical-clone-preflight.sh"

PASS=0
FAIL=0

# Shared state set by make_origin_and_clone
TEST_ORIGIN=""
TEST_CLONE=""
TEST_TMP=""

_assert() {
  local desc="$1"
  local expected_exit="$2"
  local actual_exit="$3"
  if [[ "${actual_exit}" -eq "${expected_exit}" ]]; then
    echo "PASS: ${desc}"
    PASS=$((PASS + 1))
  else
    echo "FAIL: ${desc} — expected exit ${expected_exit}, got ${actual_exit}"
    FAIL=$((FAIL + 1))
  fi
}

# Run the preflight in a clean subshell with env vars passed via env(1).
run_preflight() {
  env "$@" bash -c "source '${PREFLIGHT_SCRIPT}'; canonical_clone_preflight test"
}

# ---------------------------------------------------------------------------
# Test setup helpers
# ---------------------------------------------------------------------------

make_origin_and_clone() {
  # Creates a bare "origin" repo and a clone; sets TEST_ORIGIN, TEST_CLONE, TEST_TMP.
  local tmp
  tmp="$(mktemp -d)"
  local origin="${tmp}/origin.git"
  local clone="${tmp}/clone"

  git init --bare "${origin}" -q
  git clone "${origin}" "${clone}" -q 2>/dev/null

  git -C "${clone}" config user.email "test@test.local"
  git -C "${clone}" config user.name "Test"
  echo "init" > "${clone}/file.txt"
  git -C "${clone}" add file.txt
  git -C "${clone}" commit -m "init" -q
  git -C "${clone}" push origin main -q 2>/dev/null

  TEST_ORIGIN="${origin}"
  TEST_CLONE="${clone}"
  TEST_TMP="${tmp}"
}

cleanup() {
  rm -rf "${TEST_TMP}" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Test 1: fast-forward succeeds
# ---------------------------------------------------------------------------

test_ff_success() {
  make_origin_and_clone
  local origin="${TEST_ORIGIN}"
  local clone="${TEST_CLONE}"
  local tmp="${TEST_TMP}"

  # Add a commit to origin (simulating a new main commit).
  local work
  work="$(mktemp -d)"
  git clone "${origin}" "${work}" -q 2>/dev/null
  git -C "${work}" config user.email "test@test.local"
  git -C "${work}" config user.name "Test"
  echo "new" > "${work}/new.txt"
  git -C "${work}" add new.txt
  git -C "${work}" commit -m "new commit" -q
  git -C "${work}" push origin main -q 2>/dev/null
  rm -rf "${work}"

  local output exit_code
  output="$(run_preflight "CANONICAL_CLONE=${clone}" "ONEX_STATE_DIR=${tmp}/.onex_state" 2>&1)" && exit_code=0 || exit_code=$?

  _assert "ff_success: exits 0" 0 "${exit_code}"

  if echo "${output}" | grep -q "pulled origin/main"; then
    echo "PASS: ff_success: output contains 'pulled origin/main'"
    PASS=$((PASS + 1))
  else
    echo "FAIL: ff_success: expected 'pulled origin/main' in output, got: ${output}"
    FAIL=$((FAIL + 1))
  fi

  cleanup
}

# ---------------------------------------------------------------------------
# Test 2: already-up-to-date succeeds
# ---------------------------------------------------------------------------

test_already_up_to_date() {
  make_origin_and_clone
  local clone="${TEST_CLONE}"
  local tmp="${TEST_TMP}"

  local output exit_code
  output="$(run_preflight "CANONICAL_CLONE=${clone}" "ONEX_STATE_DIR=${tmp}/.onex_state" 2>&1)" && exit_code=0 || exit_code=$?

  _assert "already_up_to_date: exits 0" 0 "${exit_code}"

  if echo "${output}" | grep -q "already up-to-date"; then
    echo "PASS: already_up_to_date: output contains 'already up-to-date'"
    PASS=$((PASS + 1))
  else
    echo "FAIL: already_up_to_date: expected 'already up-to-date' in output, got: ${output}"
    FAIL=$((FAIL + 1))
  fi

  cleanup
}

# ---------------------------------------------------------------------------
# Test 3: non-fast-forward fails with non-zero exit and friction event
# ---------------------------------------------------------------------------

test_non_ff_fails() {
  make_origin_and_clone
  local origin="${TEST_ORIGIN}"
  local clone="${TEST_CLONE}"
  local tmp="${TEST_TMP}"

  # Create a divergent commit on the clone.
  git -C "${clone}" config user.email "test@test.local"
  git -C "${clone}" config user.name "Test"
  echo "local-diverge" > "${clone}/local.txt"
  git -C "${clone}" add local.txt
  git -C "${clone}" commit -m "local diverge" -q

  # Push a different commit to origin so histories diverge.
  local work
  work="$(mktemp -d)"
  git clone "${origin}" "${work}" -q 2>/dev/null
  git -C "${work}" config user.email "test@test.local"
  git -C "${work}" config user.name "Test"
  echo "origin-diverge" > "${work}/origin.txt"
  git -C "${work}" add origin.txt
  git -C "${work}" commit -m "origin diverge" -q
  git -C "${work}" push origin main -q 2>/dev/null
  rm -rf "${work}"

  local state_dir="${tmp}/.onex_state"
  mkdir -p "${state_dir}/friction"

  local exit_code
  run_preflight "CANONICAL_CLONE=${clone}" "ONEX_STATE_DIR=${state_dir}" >/dev/null 2>&1 && exit_code=0 || exit_code=$?

  _assert "non_ff: exits non-zero" 1 "${exit_code}"

  local friction_count
  friction_count="$(find "${state_dir}/friction/" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "${friction_count}" -gt 0 ]]; then
    echo "PASS: non_ff: friction event written (${friction_count} file(s))"
    PASS=$((PASS + 1))
  else
    echo "FAIL: non_ff: expected friction event in ${state_dir}/friction/, found none"
    FAIL=$((FAIL + 1))
  fi

  cleanup
}

# ---------------------------------------------------------------------------
# Test 4: lock contention — second call exits 0 (skip)
# ---------------------------------------------------------------------------

test_lock_contention() {
  if ! command -v flock &>/dev/null; then
    echo "SKIP: lock_contention — flock not available on this system"
    return
  fi

  make_origin_and_clone
  local clone="${TEST_CLONE}"
  local tmp="${TEST_TMP}"

  local lock_file="/tmp/.omniclaude-auto-pull.lock"
  # Hold the lock in a background subshell for 3 seconds.
  (
    exec 9>>"${lock_file}"
    flock 9
    sleep 3
  ) &
  local bg_pid=$!
  sleep 0.3  # give background process time to acquire

  local output exit_code
  output="$(run_preflight "CANONICAL_CLONE=${clone}" "ONEX_STATE_DIR=${tmp}/.onex_state" 2>&1)" && exit_code=0 || exit_code=$?
  wait "${bg_pid}" 2>/dev/null || true

  _assert "lock_contention: exits 0 (skip)" 0 "${exit_code}"

  if echo "${output}" | grep -q "lock held by another process"; then
    echo "PASS: lock_contention: output contains 'lock held by another process'"
    PASS=$((PASS + 1))
  else
    echo "FAIL: lock_contention: expected 'lock held by another process' in output, got: ${output}"
    FAIL=$((FAIL + 1))
  fi

  cleanup
}

# ---------------------------------------------------------------------------
# Test 5: missing clone directory — fails non-zero
# ---------------------------------------------------------------------------

test_missing_clone() {
  local exit_code
  run_preflight "CANONICAL_CLONE=/tmp/does-not-exist-omn-9405" >/dev/null 2>&1 && exit_code=0 || exit_code=$?

  _assert "missing_clone: exits non-zero" 1 "${exit_code}"
}

# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

echo "=== canonical-clone-preflight tests [OMN-9405] ==="
echo ""

test_ff_success
test_already_up_to_date
test_non_ff_fails
test_lock_contention
test_missing_clone

echo ""
echo "--- results ---"
echo "  PASS: ${PASS}"
echo "  FAIL: ${FAIL}"
echo ""

if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
