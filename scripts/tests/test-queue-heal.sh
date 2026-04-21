#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# test-queue-heal.sh — Tests for queue method-mismatch heal block [OMN-9434]
#
# Validates _queue_heal() logic in cron-merge-sweep.sh by extracting the
# function and running it with a mocked `gh` on the PATH. Tests verify:
#   1. Armed+CLEAN PR not in queue → dequeue+requeue mutations called
#   2. Armed+CLEAN PR already in queue → no mutations called
#   3. gh pr list failure → skips repo, exits 0 (fail-open)
#   4. mergeQueue GraphQL failure → skips repo, exits 0 (fail-open)
#   5. Unarmed or non-CLEAN PRs are ignored (no API calls)
#
# Compatible with bash 3.2 (macOS system bash — uses PATH mock, not export -f).
#
# Usage: bash scripts/tests/test-queue-heal.sh
#
# [OMN-9434]

set -euo pipefail

PASS=0
FAIL=0
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SWEEP_SCRIPT="${SCRIPT_DIR}/../cron-merge-sweep.sh"

_assert() {
  local desc="$1" expected="$2" actual="$3"
  if [[ "${actual}" == "${expected}" ]]; then
    echo "PASS: ${desc}"
    PASS=$((PASS + 1))
  else
    echo "FAIL: ${desc} — expected '${expected}', got '${actual}'"
    FAIL=$((FAIL + 1))
  fi
}

_assert_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if echo "${haystack}" | grep -q "${needle}"; then
    echo "PASS: ${desc}"
    PASS=$((PASS + 1))
  else
    echo "FAIL: ${desc} — expected '${needle}' in output"
    echo "  actual: ${haystack}"
    FAIL=$((FAIL + 1))
  fi
}

_assert_not_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if echo "${haystack}" | grep -q "${needle}"; then
    echo "FAIL: ${desc} — did NOT expect '${needle}' in output"
    echo "  actual: ${haystack}"
    FAIL=$((FAIL + 1))
  else
    echo "PASS: ${desc}"
    PASS=$((PASS + 1))
  fi
}

# ---------------------------------------------------------------------------
# Harness: extract _queue_heal into a runnable file with stubs + mocked PATH
# ---------------------------------------------------------------------------

_make_runner() {
  local mock_gh="$1"    # path to mock gh script
  local calls_file="$2" # file where mock records calls
  local runner
  runner="$(mktemp /tmp/queue-heal-runner-XXXXXX)"

  cat > "${runner}" << RUNNER_EOF
#!/usr/bin/env bash
set -euo pipefail
# Inject mock gh ahead of real gh on PATH
export PATH="$(dirname "${mock_gh}"):${PATH}"
LOG_DIR="/tmp"
RUN_ID="test-run"
log() { echo "[log] \$*"; }
sleep() { : ; }
RUNNER_EOF

  # Append _queue_heal function from sweep script
  awk '/^_queue_heal\(\)/{found=1} found{print} found && /^\}$/{exit}' \
    "${SWEEP_SCRIPT}" >> "${runner}"

  # Append call that runs the function
  echo '_queue_heal 2>/dev/null' >> "${runner}"

  chmod +x "${runner}"
  echo "${runner}"
}

_make_mock_gh() {
  local mode="$1"  # scenario name driving behavior
  local calls_file="$2"
  local mock_dir
  mock_dir="$(mktemp -d /tmp/mock-gh-XXXXXX)"
  local mock_gh="${mock_dir}/gh"

  case "${mode}" in

    heal_needed)
      cat > "${mock_gh}" << 'MOCK_EOF'
#!/usr/bin/env bash
# Mock gh: PR 42 armed+CLEAN, not in queue → triggers heal
# NOTE: check dequeuePullRequest/enqueuePullRequest BEFORE mergeQueue because
# the mutation queries contain "mergeQueueEntry" which would match a mergeQueue grep.
subcmd="${1:-}"; shift || true
if [[ "${subcmd}" == "pr" && "${1:-}" == "list" ]]; then
  echo '[{"number":42,"id":"PR_abc123","autoMergeRequest":{"mergeMethod":"MERGE"},"mergeStateStatus":"CLEAN"}]'
elif [[ "${subcmd}" == "api" && "${1:-}" == "graphql" ]]; then
  full_args="$*"
  if echo "${full_args}" | grep -q "dequeuePullRequest"; then
    echo "dequeue_called" >> CALLS_FILE
    echo '{"data":{"dequeuePullRequest":{"clientMutationId":"x"}}}'
  elif echo "${full_args}" | grep -q "enqueuePullRequest"; then
    echo "enqueue_called" >> CALLS_FILE
    echo '{"data":{"enqueuePullRequest":{"mergeQueueEntry":{"position":1,"state":"QUEUED"}}}}'
  elif echo "${full_args}" | grep -q "mergeQueue"; then
    echo "9999"  # queue contains PR 9999 only — 42 absent
  fi
fi
MOCK_EOF
      # Inject actual calls_file path
      sed -i.bak "s|CALLS_FILE|${calls_file}|g" "${mock_gh}"
      ;;

    already_queued)
      cat > "${mock_gh}" << 'MOCK_EOF'
#!/usr/bin/env bash
# NOTE: check mutations before mergeQueue — mutation queries contain "mergeQueueEntry"
subcmd="${1:-}"; shift || true
if [[ "${subcmd}" == "pr" && "${1:-}" == "list" ]]; then
  echo '[{"number":42,"id":"PR_abc123","autoMergeRequest":{"mergeMethod":"SQUASH"},"mergeStateStatus":"CLEAN"}]'
elif [[ "${subcmd}" == "api" && "${1:-}" == "graphql" ]]; then
  full_args="$*"
  if echo "${full_args}" | grep -q "dequeuePullRequest"; then
    echo "dequeue_called" >> CALLS_FILE
    echo '{}'
  elif echo "${full_args}" | grep -q "enqueuePullRequest"; then
    echo "enqueue_called" >> CALLS_FILE
    echo '{}'
  elif echo "${full_args}" | grep -q "mergeQueue"; then
    echo "42"  # PR 42 IS in queue
  fi
fi
MOCK_EOF
      sed -i.bak "s|CALLS_FILE|${calls_file}|g" "${mock_gh}"
      ;;

    pr_list_fails)
      cat > "${mock_gh}" << 'MOCK_EOF'
#!/usr/bin/env bash
subcmd="${1:-}"; shift || true
if [[ "${subcmd}" == "pr" ]]; then
  exit 1
fi
MOCK_EOF
      ;;

    queue_query_fails)
      cat > "${mock_gh}" << 'MOCK_EOF'
#!/usr/bin/env bash
# NOTE: check mutations before mergeQueue to avoid false match on mergeQueueEntry
subcmd="${1:-}"; shift || true
if [[ "${subcmd}" == "pr" && "${1:-}" == "list" ]]; then
  echo '[{"number":42,"id":"PR_abc123","autoMergeRequest":{"mergeMethod":"MERGE"},"mergeStateStatus":"CLEAN"}]'
elif [[ "${subcmd}" == "api" && "${1:-}" == "graphql" ]]; then
  full_args="$*"
  if echo "${full_args}" | grep -q "dequeuePullRequest"; then
    echo '{"data":{"dequeuePullRequest":{"clientMutationId":"x"}}}'
  elif echo "${full_args}" | grep -q "enqueuePullRequest"; then
    echo '{"data":{"enqueuePullRequest":{"mergeQueueEntry":{"position":1,"state":"QUEUED"}}}}'
  elif echo "${full_args}" | grep -q "mergeQueue"; then
    exit 1  # simulate GQL failure on the queue entries query
  fi
fi
MOCK_EOF
      ;;

    non_candidates)
      cat > "${mock_gh}" << 'MOCK_EOF'
#!/usr/bin/env bash
subcmd="${1:-}"; shift || true
if [[ "${subcmd}" == "pr" && "${1:-}" == "list" ]]; then
  # Unarmed + non-CLEAN variants — none should trigger heal
  echo '[
    {"number":10,"autoMergeRequest":null,"mergeStateStatus":"CLEAN"},
    {"number":11,"autoMergeRequest":{"mergeMethod":"SQUASH"},"mergeStateStatus":"BLOCKED"},
    {"number":12,"autoMergeRequest":null,"mergeStateStatus":"BLOCKED"}
  ]'
elif [[ "${subcmd}" == "api" ]]; then
  echo "unexpected_api_call" >> CALLS_FILE
  echo '{}'
fi
MOCK_EOF
      sed -i.bak "s|CALLS_FILE|${calls_file}|g" "${mock_gh}"
      ;;
  esac

  chmod +x "${mock_gh}"
  echo "${mock_gh}"
}

# ---------------------------------------------------------------------------
# Test 1: Armed+CLEAN PR not in queue → dequeue+requeue called
# ---------------------------------------------------------------------------

test_heal_triggered_when_not_in_queue() {
  local calls_file
  calls_file="$(mktemp /tmp/gh-calls-XXXXXX)"
  local mock_gh
  mock_gh="$(_make_mock_gh "heal_needed" "${calls_file}")"
  local runner
  runner="$(_make_runner "${mock_gh}" "${calls_file}")"

  local output
  output="$(ONEX_QUEUE_REPOS="omniclaude" bash "${runner}" 2>/dev/null)"

  _assert_contains "heal_not_in_queue: dequeue called" "dequeue_called" "$(cat "${calls_file}")"
  _assert_contains "heal_not_in_queue: enqueue called" "enqueue_called" "$(cat "${calls_file}")"
  _assert_contains "heal_not_in_queue: HEALED logged" "HEALED" "${output}"

  rm -f "${runner}" "${calls_file}"
  rm -rf "$(dirname "${mock_gh}")"
}

# ---------------------------------------------------------------------------
# Test 2: Armed+CLEAN PR already in queue → no mutations called
# ---------------------------------------------------------------------------

test_no_heal_when_already_in_queue() {
  local calls_file
  calls_file="$(mktemp /tmp/gh-calls-XXXXXX)"
  local mock_gh
  mock_gh="$(_make_mock_gh "already_queued" "${calls_file}")"
  local runner
  runner="$(_make_runner "${mock_gh}" "${calls_file}")"

  local output
  output="$(ONEX_QUEUE_REPOS="omniclaude" bash "${runner}" 2>/dev/null)"

  _assert_not_contains "no_heal_in_queue: dequeue NOT called" "dequeue_called" "$(cat "${calls_file}" 2>/dev/null || echo "")"
  _assert_not_contains "no_heal_in_queue: enqueue NOT called" "enqueue_called" "$(cat "${calls_file}" 2>/dev/null || echo "")"
  _assert_not_contains "no_heal_in_queue: HEALED not logged" "HEALED" "${output}"

  rm -f "${runner}" "${calls_file}"
  rm -rf "$(dirname "${mock_gh}")"
}

# ---------------------------------------------------------------------------
# Test 3: gh pr list failure → skips repo, exits 0 (fail-open)
# ---------------------------------------------------------------------------

test_fail_open_on_pr_list_error() {
  local calls_file
  calls_file="$(mktemp /tmp/gh-calls-XXXXXX)"
  local mock_gh
  mock_gh="$(_make_mock_gh "pr_list_fails" "${calls_file}")"
  local runner
  runner="$(_make_runner "${mock_gh}" "${calls_file}")"

  local exit_code=0
  local output
  output="$(ONEX_QUEUE_REPOS="omniclaude" bash "${runner}" 2>/dev/null)" || exit_code=$?

  _assert "fail_open_pr_list: exits 0" "0" "${exit_code}"
  _assert_contains "fail_open_pr_list: WARN logged" "WARN" "${output}"

  rm -f "${runner}" "${calls_file}"
  rm -rf "$(dirname "${mock_gh}")"
}

# ---------------------------------------------------------------------------
# Test 4: mergeQueue GraphQL failure → skips repo, exits 0 (fail-open)
# ---------------------------------------------------------------------------

test_fail_open_on_queue_query_error() {
  local calls_file
  calls_file="$(mktemp /tmp/gh-calls-XXXXXX)"
  local mock_gh
  mock_gh="$(_make_mock_gh "queue_query_fails" "${calls_file}")"
  local runner
  runner="$(_make_runner "${mock_gh}" "${calls_file}")"

  local exit_code=0
  local output
  output="$(ONEX_QUEUE_REPOS="omniclaude" bash "${runner}" 2>/dev/null)" || exit_code=$?

  _assert "fail_open_queue_query: exits 0" "0" "${exit_code}"
  _assert_contains "fail_open_queue_query: WARN logged" "WARN" "${output}"

  rm -f "${runner}" "${calls_file}"
  rm -rf "$(dirname "${mock_gh}")"
}

# ---------------------------------------------------------------------------
# Test 5: Unarmed or non-CLEAN PRs are ignored
# ---------------------------------------------------------------------------

test_ignores_unarmed_and_non_clean_prs() {
  local calls_file
  calls_file="$(mktemp /tmp/gh-calls-XXXXXX)"
  local mock_gh
  mock_gh="$(_make_mock_gh "non_candidates" "${calls_file}")"
  local runner
  runner="$(_make_runner "${mock_gh}" "${calls_file}")"

  ONEX_QUEUE_REPOS="omniclaude" bash "${runner}" 2>/dev/null || true

  _assert_not_contains "ignores_non_candidates: no unexpected API calls" \
    "unexpected_api_call" "$(cat "${calls_file}" 2>/dev/null || echo "")"

  rm -f "${runner}" "${calls_file}"
  rm -rf "$(dirname "${mock_gh}")"
}

# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

echo "=== Queue Heal Tests [OMN-9434] ==="
echo ""

test_heal_triggered_when_not_in_queue
test_no_heal_when_already_in_queue
test_fail_open_on_pr_list_error
test_fail_open_on_queue_query_error
test_ignores_unarmed_and_non_clean_prs

echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="

if [[ ${FAIL} -gt 0 ]]; then
  exit 1
fi
exit 0
