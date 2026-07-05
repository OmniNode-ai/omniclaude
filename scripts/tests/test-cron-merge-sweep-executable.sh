#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# test-cron-merge-sweep-executable.sh — Regression test for the live cron path.
#
# The periodic launchd job executes cron-merge-sweep.sh directly. This test
# proves the executable path reaches normal preflight instead of exiting from a
# stale quarantine guard before any sweep work can begin.

set -euo pipefail

PASS=0
FAIL=0
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SWEEP_SCRIPT="${SCRIPT_DIR}/../cron-merge-sweep.sh"

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

_assert_equals() {
  local desc="$1" expected="$2" actual="$3"
  if [[ "${actual}" == "${expected}" ]]; then
    echo "PASS: ${desc}"
    PASS=$((PASS + 1))
  else
    echo "FAIL: ${desc} — expected '${expected}', got '${actual}'"
    FAIL=$((FAIL + 1))
  fi
}

test_executable_path_reaches_preflight() {
  local tmp_root mock_bin output exit_code
  tmp_root="$(mktemp -d /tmp/merge-sweep-exec-test-XXXXXX)"
  trap 'rm -rf "${tmp_root}"' RETURN
  mock_bin="${tmp_root}/bin"
  mkdir -p "${mock_bin}"

  cat > "${mock_bin}/gh" <<'MOCK_EOF'
#!/usr/bin/env bash
exit 0
MOCK_EOF
  cat > "${mock_bin}/jq" <<'MOCK_EOF'
#!/usr/bin/env bash
exit 0
MOCK_EOF
  chmod +x "${mock_bin}/gh" "${mock_bin}/jq"

  set +e
  output="$(
    PATH="${mock_bin}:${PATH}" \
      HOME="${tmp_root}" \
      ONEX_PYTHON_BIN="${tmp_root}/missing-python" \
      bash "${SWEEP_SCRIPT}" 2>&1
  )"
  exit_code=$?
  set -e

  _assert_equals "executable path exits from preflight" "1" "${exit_code}"
  _assert_contains "preflight reports missing configured python" "Missing requirements: ${tmp_root}/missing-python" "${output}"
  _assert_not_contains "executable path is not quarantined" "\"status\":\"quarantined\"" "${output}"
}

echo "=== cron merge-sweep executable-path tests ==="
echo ""

test_executable_path_reaches_preflight

echo ""
echo "--- results ---"
echo "  PASS: ${PASS}"
echo "  FAIL: ${FAIL}"
echo ""

if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
