#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# test-stall-wiring.sh — Tests for stall detector wiring in cron-merge-sweep [OMN-9406]
#
# Tests the file-stall-tickets.sh shell helper with mocked Linear API responses.
# The run-stall-detector.py driver requires omnimarket installed, so we test
# only the shell pipeline layer here (ticket filing, idempotency, fail-open).
#
# Compatible with bash 3.2 (macOS system bash — no mapfile, no associative arrays).
#
# Usage: bash scripts/tests/test-stall-wiring.sh
#
# [OMN-9406]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FILER="${SCRIPT_DIR}/../lib/file-stall-tickets.sh"

PASS=0
FAIL=0

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

_assert_contains() {
  local desc="$1"
  local needle="$2"
  local haystack="$3"
  if echo "${haystack}" | grep -q "${needle}"; then
    echo "PASS: ${desc}"
    PASS=$((PASS + 1))
  else
    echo "FAIL: ${desc} — expected '${needle}' in output"
    echo "  actual: ${haystack}"
    FAIL=$((FAIL + 1))
  fi
}

# ---------------------------------------------------------------------------
# Test 1: zero stall events → no-op, exits 0
# ---------------------------------------------------------------------------

test_zero_events_noop() {
  local output exit_code
  output="$(echo "[]" | bash "${FILER}" 2>&1)" && exit_code=0 || exit_code=$?

  _assert "zero_events: exits 0" 0 "${exit_code}"
  _assert_contains "zero_events: logs no stall events" "no stall events" "${output}"
}

# ---------------------------------------------------------------------------
# Test 2: no LINEAR_API_KEY → fail-open, exits 0, logs warning
# ---------------------------------------------------------------------------

test_no_api_key_failopen() {
  local one_event
  one_event='[{"pr_number":42,"repo":"OmniNode-ai/omniclaude","stall_count":2,"blocking_reason":"mergeable=CONFLICTING","head_sha":"abc123","first_seen_at":"2026-04-21T00:00:00","last_seen_at":"2026-04-21T00:05:00"}]'

  local output exit_code
  output="$(echo "${one_event}" | env -i PATH="${PATH}" bash "${FILER}" 2>&1)" && exit_code=0 || exit_code=$?

  _assert "no_api_key: exits 0 (fail-open)" 0 "${exit_code}"
  _assert_contains "no_api_key: logs missing key warning" "LINEAR_API_KEY not set" "${output}"
}

# ---------------------------------------------------------------------------
# Test 3: one stall event with mocked Linear API → ticket filed, exits 0
# ---------------------------------------------------------------------------

test_one_event_files_ticket() {
  if ! command -v python3 &>/dev/null; then
    echo "SKIP: test_one_event_files_ticket — python3 not available"
    return
  fi

  local one_event
  one_event='[{"pr_number":99,"repo":"OmniNode-ai/omniclaude","stall_count":2,"blocking_reason":"merge_state_status=BLOCKED","head_sha":"def456","first_seen_at":"2026-04-21T00:00:00","last_seen_at":"2026-04-21T00:05:00"}]'

  # Create a mock curl that:
  # - On team query: returns a team ID
  # - On issue search (idempotency check): returns zero matches
  # - On issue create: returns a created issue identifier
  local mock_dir
  mock_dir="$(mktemp -d)"

  cat > "${mock_dir}/curl" << 'MOCK_CURL'
#!/usr/bin/env bash
# Minimal curl mock that returns canned Linear API responses based on request body.
BODY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --data) BODY="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if echo "${BODY}" | grep -q "teams"; then
  echo '{"data":{"teams":{"nodes":[{"id":"team-abc","name":"Omninode"}]}}}'
elif echo "${BODY}" | grep -q "issueSearch"; then
  echo '{"data":{"issueSearch":{"nodes":[]}}}'
elif echo "${BODY}" | grep -q "issueCreate"; then
  echo '{"data":{"issueCreate":{"issue":{"id":"issue-1","identifier":"OMN-9999","url":"https://linear.app/omninode/issue/OMN-9999"}}}}'
else
  echo '{}'
fi
MOCK_CURL
  chmod +x "${mock_dir}/curl"

  local output exit_code
  output="$(echo "${one_event}" | \
    env LINEAR_API_KEY="test-key" PATH="${mock_dir}:${PATH}" \  # pragma: allowlist secret
    bash "${FILER}" 2>&1)" && exit_code=0 || exit_code=$?

  rm -rf "${mock_dir}"

  _assert "one_event: exits 0" 0 "${exit_code}"
  _assert_contains "one_event: logs FILED" "FILED" "${output}"
}

# ---------------------------------------------------------------------------
# Test 4: idempotency — existing open ticket skips creation
# ---------------------------------------------------------------------------

test_idempotent_skip() {
  if ! command -v python3 &>/dev/null; then
    echo "SKIP: test_idempotent_skip — python3 not available"
    return
  fi

  local one_event
  one_event='[{"pr_number":77,"repo":"OmniNode-ai/omnibase_core","stall_count":3,"blocking_reason":"required_checks_pass=False","head_sha":"aaa111","first_seen_at":"2026-04-21T00:00:00","last_seen_at":"2026-04-21T00:05:00"}]'

  local mock_dir
  mock_dir="$(mktemp -d)"

  cat > "${mock_dir}/curl" << 'MOCK_CURL'
#!/usr/bin/env bash
BODY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --data) BODY="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if echo "${BODY}" | grep -q "teams"; then
  echo '{"data":{"teams":{"nodes":[{"id":"team-abc","name":"Omninode"}]}}}'
elif echo "${BODY}" | grep -q "issueSearch"; then
  # Return one existing match — triggers idempotency skip
  echo '{"data":{"issueSearch":{"nodes":[{"id":"existing-1","title":"[auto-stall-detected] Stalled PR: OmniNode-ai/omnibase_core#77"}]}}}'
else
  echo '{}'
fi
MOCK_CURL
  chmod +x "${mock_dir}/curl"

  local output exit_code
  output="$(echo "${one_event}" | \
    env LINEAR_API_KEY="test-key" PATH="${mock_dir}:${PATH}" \  # pragma: allowlist secret
    bash "${FILER}" 2>&1)" && exit_code=0 || exit_code=$?

  rm -rf "${mock_dir}"

  _assert "idempotent: exits 0" 0 "${exit_code}"
  _assert_contains "idempotent: logs SKIP" "SKIP" "${output}"
}

# ---------------------------------------------------------------------------
# Test 5: empty / null JSON → no-op
# ---------------------------------------------------------------------------

test_null_json_noop() {
  local output exit_code
  output="$(echo "null" | bash "${FILER}" 2>&1)" && exit_code=0 || exit_code=$?
  _assert "null_json: exits 0" 0 "${exit_code}"
}

# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

echo "=== stall-wiring tests [OMN-9406] ==="
echo ""

test_zero_events_noop
test_no_api_key_failopen
test_one_event_files_ticket
test_idempotent_skip
test_null_json_noop

echo ""
echo "--- results ---"
echo "  PASS: ${PASS}"
echo "  FAIL: ${FAIL}"
echo ""

if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
