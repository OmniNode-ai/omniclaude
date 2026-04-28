#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# test-merge-sweep-ledger.sh — Regression tests for runtime-ledger rendering.
#
# Validates the ledger surface produced by write_result_yaml() so merge-sweep
# no longer reports "complete" without the orchestrator truth attached.
#
# Compatible with bash 3.2 (macOS system bash).
#
# Usage: bash scripts/tests/test-merge-sweep-ledger.sh

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

_extract_fn() {
  local fn_name="$1"
  awk "/^${fn_name}\\(\\)/{capture=1} capture{print} capture && /^\\}/{exit}" \
    "${SWEEP_SCRIPT}"
}

_make_runner() {
  local runner
  runner="$(mktemp /tmp/merge-ledger-runner-XXXXXX)"

  cat > "${runner}" <<'RUNNER_EOF'
#!/usr/bin/env bash
set -euo pipefail
log() { :; }
RUNNER_EOF

  _extract_fn "result_json_path" >> "${runner}"
  echo "" >> "${runner}"
  _extract_fn "count_pr_polish_dispatches" >> "${runner}"
  echo "" >> "${runner}"
  _extract_fn "count_pr_polish_results" >> "${runner}"
  echo "" >> "${runner}"
  _extract_fn "count_pr_polish_results_with_state" >> "${runner}"
  echo "" >> "${runner}"
  _extract_fn "count_pr_polish_results_with_true_field" >> "${runner}"
  echo "" >> "${runner}"
  _extract_fn "snapshot_pr_polish_before" >> "${runner}"
  echo "" >> "${runner}"
  _extract_fn "snapshot_pr_polish_after" >> "${runner}"
  echo "" >> "${runner}"
  _extract_fn "ensure_pr_polish_snapshots" >> "${runner}"
  echo "" >> "${runner}"
  _extract_fn "write_result_yaml" >> "${runner}"

  cat >> "${runner}" <<'RUNNER_EOF'
TMP_ROOT="$(mktemp -d /tmp/merge-ledger-state-XXXXXX)"
STATE_DIR="${TMP_ROOT}/merge-sweep-results"
ONEX_STATE_DIR="${TMP_ROOT}"
MARKET_REPO_ROOT="/tmp/fake-market"
RUN_ID="merge-sweep-test"
CORRELATION_ID="12345678-1234-1234-1234-123456789abc"
DRY_RUN=false
RESUME_REQUESTED=false
MERGE_ONLY=false
REPOS_FILTER="omniclaude"
SWEEP_ARGS="--enable-admin-merge-fallback --admin-fallback-threshold-minutes=15"
POLISH_DISPATCHES_BEFORE=0
POLISH_DISPATCHES_AFTER=1
POLISH_RESULTS_BEFORE=0
POLISH_RESULTS_AFTER=1
mkdir -p "${STATE_DIR}" "${ONEX_STATE_DIR}/merge-sweep/${RUN_ID}" "${ONEX_STATE_DIR}/pr-polish/run-1"
cat > "${STATE_DIR}/${RUN_ID}-attempt-1.json" <<'JSON_EOF'
{
  "ok": true,
  "node_alias": "pr_lifecycle_orchestrator",
  "output_payloads": [
    {
      "prs_inventoried": 4,
      "prs_merged": 1,
      "prs_fixed": 2,
      "prs_skipped": 1
    }
  ]
}
JSON_EOF
cat > "${STATE_DIR}/${RUN_ID}-attempt-1.payload.json" <<'JSON_EOF'
{"run_id":"merge-sweep-test"}
JSON_EOF
cat > "${ONEX_STATE_DIR}/merge-sweep/${RUN_ID}/result.json" <<'JSON_EOF'
{
  "correlation_id": "12345678-1234-1234-1234-123456789abc",
  "prs_inventoried": 4,
  "prs_merged": 1,
  "prs_fixed": 2,
  "prs_skipped": 1,
  "prs_verified": 0,
  "final_state": "COMPLETE",
  "error_message": null
}
JSON_EOF
cat > "${ONEX_STATE_DIR}/pr-polish/run-1/dispatch.json" <<'JSON_EOF'
{"kind":"review-fix"}
JSON_EOF
cat > "${ONEX_STATE_DIR}/pr-polish/run-1/result.json" <<'JSON_EOF'
{
  "final_state": "COMPLETE",
  "skill_changed_head": true,
  "completed_event": {
    "final_phase": "done"
  }
}
JSON_EOF

write_result_yaml "complete" "1" "0"
cat "${STATE_DIR}/${RUN_ID}.yaml"
RUNNER_EOF

  chmod +x "${runner}"
  echo "${runner}"
}

test_runtime_truth_fields_present() {
  local runner output
  runner="$(_make_runner)"
  output="$(bash "${runner}")"

  _assert_contains "ledger includes correlation_id" "correlation_id: \"12345678-1234-1234-1234-123456789abc\"" "${output}"
  _assert_contains "ledger includes orchestrator final state" "final_state: \"COMPLETE\"" "${output}"
  _assert_contains "ledger includes prs_fixed count" "prs_fixed: 2" "${output}"
  _assert_contains "ledger includes runtime result path" "result_json:" "${output}"
  _assert_contains "ledger includes new polish dispatch count" "dispatch_breadcrumbs_new_this_run: 1" "${output}"
  _assert_contains "ledger includes new polish result count" "result_files_new_this_run: 1" "${output}"
  _assert_contains "ledger includes completed polish result count" "completed_results_observed_total: 1" "${output}"
  _assert_contains "ledger includes changed-head result count" "changed_head_results_observed_total: 1" "${output}"
  _assert_contains "ledger includes polish observation note" "actual pr_polish completion is observed from result.json files" "${output}"

  rm -f "${runner}"
}

echo "=== merge-sweep ledger tests ==="
echo ""

test_runtime_truth_fields_present

echo ""
echo "--- results ---"
echo "  PASS: ${PASS}"
echo "  FAIL: ${FAIL}"
echo ""

if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
