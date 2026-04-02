#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# cron-closeout.sh — Headless close-out orchestrator using scoped claude -p invocations
#
# Each phase runs in a fresh context window. State persists via cycle-state.yaml
# and per-run output files in the state directory.
#
# Usage:
#   ./scripts/cron-closeout.sh              # Full close-out pipeline
#   ./scripts/cron-closeout.sh --dry-run    # Print phases without executing
#
# Requires: claude CLI, gh CLI (authenticated), ANTHROPIC_API_KEY
#
# Design: Follows the headless decomposition pattern from
# omnibase_infra/docs/patterns/headless_decomposition.md
# - One task per invocation (bounded context)
# - State handoff via files (no shared session state)
# - Idempotent (safe to re-run)
# - Each invocation completes in <15 minutes or times out
#
# [OMN-6935]

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OMNI_HOME="/Volumes/PRO-G40/Code/omni_home"  # local-path-ok: script runs on local machine only
STATE_DIR="${OMNI_HOME}/.onex_state/autopilot"
CYCLE_STATE="${STATE_DIR}/cycle-state.yaml"
LOG_DIR="/tmp/closeout-logs"
PHASE_TIMEOUT=600  # 10 minutes per phase
RUN_ID="closeout-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
RUN_DIR="${STATE_DIR}/runs/${RUN_ID}"
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

# Source credentials
if [[ -f "${HOME}/.omnibase/.env" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.omnibase/.env"
fi

export ONEX_RUN_ID="${RUN_ID}"
export ONEX_UNSAFE_ALLOW_EDITS=1

# ---------------------------------------------------------------------------
# Infrastructure host resolution [OMN-7238]
# After migration to .201, infra may run on a remote host.
# Derive INFRA_HOST from POSTGRES_HOST (set in ~/.omnibase/.env).
# Falls back to localhost for backwards compatibility with local Docker.
# ---------------------------------------------------------------------------

INFRA_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5436}"
KAFKA_BROKERS="${KAFKA_BOOTSTRAP_SERVERS:-${INFRA_HOST}:19092}"

# Source headless emit wrapper for unified event emission [OMN-7034]
# shellcheck disable=SC1091
source "$(dirname "$0")/headless-emit-wrapper.sh"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

preflight() {
  local missing=()

  if ! command -v claude &>/dev/null; then
    missing+=("claude CLI")
  fi

  # API key only required for actual execution (not dry-run)
  if [[ "${DRY_RUN}" != "true" && -z "${ANTHROPIC_API_KEY:-}" ]]; then
    missing+=("ANTHROPIC_API_KEY")
  fi

  if ! command -v gh &>/dev/null; then
    missing+=("gh CLI")
  fi

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: Missing requirements: ${missing[*]}" >&2
    exit 1
  fi
}

preflight

# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------

mkdir -p "${STATE_DIR}" "${RUN_DIR}" "${LOG_DIR}"

# Initialize cycle-state.yaml if it doesn't exist
if [[ ! -f "${CYCLE_STATE}" ]]; then
  cat > "${CYCLE_STATE}" << 'YAML'
# cycle-state.yaml — Managed by cron-closeout.sh
# Tracks deployed versions and cross-run state for the headless close-out pipeline.
last_deploy_version:
  omnibase_infra: "0.29.0"
  omniclaude: "0.18.0"
  omniintelligence: "0.20.0"
  omnimemory: "0.13.0"
  omnibase_core: "0.34.0"
pending_redeploy: []
strike_tracker: {}
consecutive_noop_count: 0
last_cycle_completed_at: null
YAML
  echo "[cron-closeout] Initialized ${CYCLE_STATE}"
fi

# ---------------------------------------------------------------------------
# Lock file — prevent concurrent runs
# ---------------------------------------------------------------------------

LOCK_FILE="${STATE_DIR}/cron-closeout.lock"
LOCK_TIMEOUT=2700  # 45 minutes

if [[ -f "${LOCK_FILE}" ]]; then
  lock_time=$(stat -f %m "${LOCK_FILE}" 2>/dev/null || stat -c %Y "${LOCK_FILE}" 2>/dev/null || echo 0)
  now=$(date +%s)
  age=$(( now - lock_time ))

  if [[ ${age} -lt ${LOCK_TIMEOUT} ]]; then
    echo "SKIP: Previous invocation still running (lock age: ${age}s < ${LOCK_TIMEOUT}s)"
    exit 0
  else
    echo "WARN: Stale lock detected (age: ${age}s). Removing."
    rm -f "${LOCK_FILE}"
  fi
fi

echo "pid=$$ started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"' EXIT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
  local msg="[cron-closeout $(date -u +"%H:%M:%S")] $1"
  echo "${msg}"
  echo "${msg}" >> "${LOG_DIR}/${RUN_ID}.log"
}

# Run a single headless phase with timeout.
# Arguments: phase_name, prompt, allowed_tools
run_phase() {
  local phase_name="$1"
  local prompt="$2"
  local allowed_tools="$3"
  local output_file="${RUN_DIR}/${phase_name}.txt"

  log "Starting phase: ${phase_name}"

  if [[ "${DRY_RUN}" == "true" ]]; then
    log "[DRY RUN] Would execute: claude -p '${prompt:0:80}...' --allowedTools '${allowed_tools}'"
    echo "DRY_RUN: ${phase_name}" > "${output_file}"
    return 0
  fi

  local exit_code=0
  timeout "${PHASE_TIMEOUT}" claude -p "${prompt}" \
    --print \
    --allowedTools "${allowed_tools}" \
    > "${output_file}" 2>&1 || exit_code=$?

  if [[ ${exit_code} -eq 124 ]]; then
    log "TIMEOUT: Phase ${phase_name} exceeded ${PHASE_TIMEOUT}s"
    echo "TIMEOUT" >> "${output_file}"
    return 1
  elif [[ ${exit_code} -ne 0 ]]; then
    log "FAILED: Phase ${phase_name} exited with code ${exit_code}"
    return 1
  fi

  log "Completed phase: ${phase_name}"
  return 0
}

# Check if a phase output contains a failure indicator
phase_failed() {
  local output_file="${RUN_DIR}/$1.txt"
  if [[ ! -f "${output_file}" ]]; then
    return 0  # missing output = failure
  fi
  # Look for explicit FAIL or HALT markers (case-insensitive)
  if grep -qi "INTEGRATION: FAIL\|HALT\|TIMEOUT" "${output_file}" 2>/dev/null; then
    return 0  # found failure indicator
  fi
  return 1  # no failure found
}

# Detect pending redeploy by comparing git tags against cycle-state versions
check_pending_redeploy() {
  log "Checking F30: pending redeploy detection"
  local pending=()

  # Read last_deploy_version entries from cycle-state.yaml
  while IFS=': ' read -r repo version; do
    repo=$(echo "${repo}" | xargs)
    version=$(echo "${version}" | xargs | tr -d '"')
    if [[ -z "${repo}" || -z "${version}" || "${version}" == "null" ]]; then
      continue
    fi

    local repo_path="${OMNI_HOME}/${repo}"
    if [[ ! -d "${repo_path}/.git" && ! -f "${repo_path}/.git" ]]; then
      continue
    fi

    # Get latest git tag
    local latest_tag
    latest_tag=$(git -C "${repo_path}" describe --tags --abbrev=0 2>/dev/null || echo "")
    if [[ -n "${latest_tag}" ]]; then
      # Strip scoped prefixes (e.g. "omnibase_core/v0.34.0" -> "0.34.0")
      local tag_version="${latest_tag##*/}"
      tag_version="${tag_version#v}"
      if [[ "${tag_version}" != "${version}" ]]; then
        log "Pending redeploy: ${repo} (deployed: ${version}, latest tag: ${tag_version})"
        pending+=("${repo}")
      fi
    fi
  done < <(awk '/^last_deploy_version:/{found=1; next} found && /^  /{print; next} found{exit}' "${CYCLE_STATE}")

  if [[ ${#pending[@]} -gt 0 ]]; then
    log "Found ${#pending[@]} repos with pending redeploy: ${pending[*]}"
    echo "${pending[*]}" > "${RUN_DIR}/pending_redeploys.txt"
    return 0  # has pending
  else
    log "No pending redeploys detected"
    return 1  # no pending
  fi
}

# Update cycle-state.yaml timestamp after completion
update_cycle_state() {
  local status="$1"
  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  if grep -q "last_cycle_completed_at:" "${CYCLE_STATE}"; then
    sed -i '' "s|last_cycle_completed_at:.*|last_cycle_completed_at: \"${timestamp}\"|" "${CYCLE_STATE}"
  fi

  log "Cycle state updated: status=${status}, completed_at=${timestamp}"
}

# ---------------------------------------------------------------------------
# Strike tracker (circuit breaker)
# ---------------------------------------------------------------------------

CONSECUTIVE_FAILURES=0
MAX_FAILURES=3

record_strike() {
  local phase="$1"
  CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
  log "Strike ${CONSECUTIVE_FAILURES}/${MAX_FAILURES} from phase: ${phase}"

  if [[ ${CONSECUTIVE_FAILURES} -ge ${MAX_FAILURES} ]]; then
    log "CIRCUIT BREAKER: ${MAX_FAILURES} consecutive failures. Halting pipeline."
    update_cycle_state "circuit_breaker"
    exit 2
  fi
}

reset_strikes() {
  CONSECUTIVE_FAILURES=0
}

# ===========================================================================
# Phase A: Prepare
# ===========================================================================

log "=== Close-out run ${RUN_ID} starting ==="
log "State dir: ${RUN_DIR}"
log "Cycle state: ${CYCLE_STATE}"

emit_task_event "task-assigned" "${RUN_ID}" "\"session_id\": \"${ONEX_RUN_ID}\", \"phase\": \"pipeline-start\""

# A1: Merge sweep
if ! run_phase "A1_merge_sweep" \
  "Run merge-sweep: scan all OmniNode-ai repos for open PRs with passing CI. Enable auto-merge on eligible ones (passing CI, no conflicts). If no eligible PRs, report 'nothing_to_merge'. Report results as a markdown summary." \
  "Bash,Read,Glob,Grep"; then
  record_strike "A1_merge_sweep"
fi

# A2: Deploy plugin
if ! run_phase "A2_deploy_plugin" \
  "Deploy the omniclaude plugin to the Claude Code plugin cache. The deploy skill copies plugin files from the repository source to the cache at ~/.claude/plugins/cache/. Run: bash -c 'PLUGIN_SRC=${OMNI_HOME}/omniclaude/plugins/onex; CACHE_DIR=\${HOME}/.claude/plugins/cache/onex; mkdir -p \${CACHE_DIR}; rsync -a --delete \${PLUGIN_SRC}/ \${CACHE_DIR}/; echo DEPLOY_COMPLETE'" \
  "Bash,Read,Glob,Grep"; then
  record_strike "A2_deploy_plugin"
fi

# A3: Verify infrastructure health [OMN-7238: use health endpoints, not local docker]
if ! run_phase "A3_start_env" \
  "Verify infrastructure health on host ${INFRA_HOST}. Run these checks and report status for each:
1. PostgreSQL: psql -h ${INFRA_HOST} -p ${POSTGRES_PORT} -U postgres -d omnibase_infra -c 'SELECT 1'
2. Runtime API: curl -sf http://${INFRA_HOST}:8085/health
3. Intelligence API: curl -sf http://${INFRA_HOST}:8053/health
4. Kafka/Redpanda: kcat -L -b ${KAFKA_BROKERS} -t __consumer_offsets 2>&1 | head -3 (or curl -sf http://${INFRA_HOST}:8082/v3/clusters if Redpanda HTTP proxy is up)
Report HEALTHY or UNHEALTHY for each service. Do NOT attempt to restart anything." \
  "Bash,Read"; then
  record_strike "A3_start_env"
fi

# ===========================================================================
# Phase B: Infrastructure sweep gates (hard gates) [OMN-7002]
# ===========================================================================

log "=== Phase B: Infrastructure sweep gates ==="

# B1: Runtime sweep — verify runtime health endpoints [OMN-7238: remote-aware]
if ! run_phase "B1_runtime_sweep" \
  "Run runtime health verification against ${INFRA_HOST}. Check:
1. Runtime health endpoint: curl -sf http://${INFRA_HOST}:8085/health
2. Intelligence API health: curl -sf http://${INFRA_HOST}:8053/health
3. PostgreSQL connectivity: psql -h ${INFRA_HOST} -p ${POSTGRES_PORT} -U postgres -d omnibase_infra -c 'SELECT 1'
4. Kafka broker reachable: kcat -L -b ${KAFKA_BROKERS} 2>&1 | head -5

If ALL checks pass, print: INTEGRATION: PASS
If ANY critical check fails, print: INTEGRATION: FAIL" \
  "Bash,Read"; then
  record_strike "B1_runtime_sweep"
fi

if phase_failed "B1_runtime_sweep"; then
  log "HALT: Runtime sweep reported failures."
  log "Review output: ${RUN_DIR}/B1_runtime_sweep.txt"
  update_cycle_state "halted_runtime_sweep"
  exit 1
fi

# B2: Data flow sweep — verify Kafka and projections [OMN-7238: remote-aware]
if ! run_phase "B2_data_flow_sweep" \
  "Run data flow verification against ${INFRA_HOST}. Check:
1. Kafka consumer groups active: kcat -L -b ${KAFKA_BROKERS} 2>&1 | grep -c 'topic' (verify broker is responding with topics)
2. Registration projections exist: psql -h ${INFRA_HOST} -p ${POSTGRES_PORT} -U postgres -d omnibase_infra -tAc 'SELECT count(*) FROM registration_projections'

If projections > 0 and Kafka broker responds, print: INTEGRATION: PASS
If projections = 0 or Kafka unreachable, print: INTEGRATION: FAIL" \
  "Bash,Read"; then
  record_strike "B2_data_flow_sweep"
fi

if phase_failed "B2_data_flow_sweep"; then
  log "HALT: Data flow sweep reported failures."
  log "Review output: ${RUN_DIR}/B2_data_flow_sweep.txt"
  update_cycle_state "halted_data_flow_sweep"
  exit 1
fi

# B3: Database sweep — verify projection tables populated [OMN-7238: remote-aware]
if ! run_phase "B3_database_sweep" \
  "Run database health verification against ${INFRA_HOST}. Check projection tables in omnibase_infra:
1. psql -h ${INFRA_HOST} -p ${POSTGRES_PORT} -U postgres -d omnibase_infra -tAc 'SELECT count(*) FROM registration_projections' (must be > 0)
2. psql -h ${INFRA_HOST} -p ${POSTGRES_PORT} -U postgres -d omnibase_infra -tAc 'SELECT count(*) FROM agent_actions' (informational)
3. psql -h ${INFRA_HOST} -p ${POSTGRES_PORT} -U postgres -d omnibase_infra -tAc 'SELECT count(tablename) FROM pg_tables WHERE schemaname='\''public'\''' (total tables)

If registration_projections > 0, print: INTEGRATION: PASS
If registration_projections = 0, print: INTEGRATION: FAIL" \
  "Bash,Read"; then
  record_strike "B3_database_sweep"
fi

if phase_failed "B3_database_sweep"; then
  log "HALT: Database sweep reported failures."
  log "Review output: ${RUN_DIR}/B3_database_sweep.txt"
  update_cycle_state "halted_database_sweep"
  exit 1
fi

# B4b: Data verification — advisory, non-blocking [OMN-6764]
# Runs three data sweeps in dry-run mode. Findings appended to close-day report.
# Does NOT halt pipeline on failure.
log "=== Phase B4b: Data verification (advisory) ==="

if ! run_phase "B4b_data_verification" \
  "Run all three data verification sweeps in dry-run mode. This is advisory only — report findings but do NOT halt.

1. Database sweep (dry-run): Run /database-sweep --dry-run — check projection table health (row counts, staleness, schema drift). Report any tables with zero rows or stale data.

2. Data flow sweep (dry-run): Run /data-flow-sweep --dry-run --skip-playwright — check end-to-end pipeline health (Kafka consumer lag, projection freshness, event flow continuity). Skip Playwright checks. Report any broken data flow paths.

3. Runtime sweep (dry-run): Run /runtime-sweep --dry-run — check node registration and wiring integrity (registered nodes match contracts, dispatch routes are valid). Report any unregistered nodes or broken wiring.

For each sweep, report:
- Status: CLEAN or FINDINGS
- Finding count and summary if any issues found

End with a consolidated summary listing all findings across the three sweeps. These findings will be appended to the close-day report." \
  "Bash,Read,Glob,Grep"; then
  log "WARNING: Data verification phase failed (advisory — not halting)"
fi

# B5: Integration gate — verify critical services [OMN-7238: remote-aware]
if ! run_phase "B5_integration" \
  "Run integration health checks against ${INFRA_HOST}. For each service, test and report PASS or FAIL:
1. PostgreSQL: psql -h ${INFRA_HOST} -p ${POSTGRES_PORT} -U postgres -d omnibase_infra -c 'SELECT 1'
2. Kafka/Redpanda: kcat -L -b ${KAFKA_BROKERS} 2>&1 | head -3 (broker metadata response)
3. Runtime API: curl -sf http://${INFRA_HOST}:8085/health (may not be running — FAIL is OK)
4. Omnidash: curl -sf http://localhost:3000 (runs locally — FAIL is OK)

Critical services are PostgreSQL and Kafka. If BOTH are healthy, print exactly:
  INTEGRATION: PASS
If EITHER critical service is down, print exactly:
  INTEGRATION: FAIL
followed by which services failed." \
  "Bash,Read"; then
  log "HALT: Integration sweep phase failed to execute"
  record_strike "B5_integration"
fi

# Check B5 result
if phase_failed "B5_integration"; then
  log "HALT: Integration gate reported failures. Cannot proceed to release."
  log "Review output: ${RUN_DIR}/B5_integration.txt"
  update_cycle_state "halted_integration"
  exit 1
fi

reset_strikes
log "Integration gate PASSED"

# B6: Contract verification — runtime contract compliance check
log "=== Phase B6: Contract verification ==="

if ! run_phase "B6_contract_verify" \
  "Run contract verification for the registration subsystem. Execute: uv run python -m omnibase_infra.verification.cli --registration-only --json. If the exit code is 0, print CONTRACT_VERIFY: PASS. If exit code is 1, print CONTRACT_VERIFY: FAIL followed by the failing checks. If exit code is 2, print CONTRACT_VERIFY: QUARANTINE." \
  "Bash,Read"; then
  record_strike "B6_contract_verify"
fi

# B6 is a soft gate by default — FAIL warns but does not halt
# Set CONTRACT_VERIFY_HARD_GATE=1 to make it a hard gate
if phase_failed "B6_contract_verify"; then
  if [[ "${CONTRACT_VERIFY_HARD_GATE:-0}" == "1" ]]; then
    log "HALT: Contract verification failed (hard gate enabled)."
    log "Review output: ${RUN_DIR}/B6_contract_verify.txt"
    update_cycle_state "halted_contract_verify"
    exit 1
  else
    log "WARN: Contract verification reported failures (soft gate — continuing)."
    log "Review output: ${RUN_DIR}/B6_contract_verify.txt"
  fi
fi

reset_strikes
log "All infrastructure sweep gates PASSED"

emit_task_event "task-progress" "${RUN_ID}" "\"session_id\": \"${ONEX_RUN_ID}\", \"phase\": \"infra-gates-passed\""

# ===========================================================================
# Phase C: Release and redeploy (conditional)
# ===========================================================================

log "=== Phase C: Release and redeploy ==="

HAS_PENDING_REDEPLOY=false
if check_pending_redeploy; then
  HAS_PENDING_REDEPLOY=true
fi

# C1: Check for unreleased commits
if ! run_phase "C1_release_check" \
  "Check OmniNode-ai Python repos for unreleased commits on main since the last git tag. For each repo in ${OMNI_HOME}/ (omnibase_core, omnibase_infra, omnibase_spi, omniclaude, omniintelligence, omnimemory), run:
  LAST_TAG=\$(git -C ${OMNI_HOME}/<repo> describe --tags --abbrev=0 2>/dev/null)
  git -C ${OMNI_HOME}/<repo> log \${LAST_TAG}..HEAD --oneline
Report which repos have unreleased commits and how many commits each." \
  "Bash,Read,Glob,Grep"; then
  record_strike "C1_release_check"
fi

# C2: Report pending redeploy status
if [[ "${HAS_PENDING_REDEPLOY}" == "true" ]]; then
  if ! run_phase "C2_redeploy_check" \
    "Repos with versions newer than deployed: $(cat "${RUN_DIR}/pending_redeploys.txt" 2>/dev/null || echo 'unknown'). Report which repos need redeployment. Compare git tags in ${OMNI_HOME}/<repo> against the cycle-state deployed versions. Do NOT execute the actual redeploy — just report what would need to happen." \
    "Bash,Read,Glob,Grep"; then
    record_strike "C2_redeploy_check"
  fi
else
  log "No pending redeploys — skipping C2"
  echo "SKIPPED: No pending redeploys detected" > "${RUN_DIR}/C2_redeploy_check.txt"
fi

# ===========================================================================
# Phase D: Dashboard sweep
# ===========================================================================

log "=== Phase D: Dashboard sweep ==="

# D3: Dashboard health check (non-blocking)
if ! run_phase "D3_dashboard_sweep" \
  "Check omnidash dashboard health:
1. curl -sf http://localhost:3000 (main page)
2. curl -sf http://localhost:3000/api/health (health endpoint)
Report which endpoints are responding. This is informational — failures here do not block the pipeline." \
  "Bash,Read"; then
  log "WARNING: Dashboard sweep failed (non-blocking)"
fi

# ===========================================================================
# Phase E: Verification suite [OMN-7006]
# ===========================================================================

log "=== Phase E: Verification suite ==="

# Check if verification was already run this cycle (idempotent)
VERIFICATION_MARKER="${STATE_DIR}/last_verification_run_id"
SKIP_VERIFICATION=false
if [[ -f "${VERIFICATION_MARKER}" ]]; then
  LAST_VERIFICATION_RUN=$(cat "${VERIFICATION_MARKER}")
  if [[ "${LAST_VERIFICATION_RUN}" == "${RUN_ID}" ]]; then
    log "Verification suite already passed in this cycle — skipping"
    SKIP_VERIFICATION=true
  fi
fi

if [[ "${SKIP_VERIFICATION}" == "false" ]]; then
  # E1: Phase 1 integration tests (handler init, runtime health, node registration, dispatch)
  # Critical — blocks close-out on failure
  if ! run_phase "E1_foundation_tests" \
    "Run Phase 1 foundation integration tests in omnibase_infra. Execute:
cd ${OMNI_HOME}/omnibase_infra
uv run pytest tests/integration/test_runtime_health.py tests/integration/test_node_registration.py tests/integration/test_dispatch_roundtrip.py -v --timeout=120

Report PASS count and FAIL count.
If ANY test fails, print: INTEGRATION: FAIL
If ALL tests pass, print: INTEGRATION: PASS" \
    "Bash,Read"; then
    record_strike "E1_foundation_tests"
  fi

  if phase_failed "E1_foundation_tests"; then
    log "CRITICAL: Foundation verification tests failed. Node layer may be dead."
    update_cycle_state "halted_verification_foundation"
    exit 1
  fi

  # E2: Phase 2 pipeline integration tests (pattern, injection, intent)
  # Critical — blocks close-out on failure
  if ! run_phase "E2_pipeline_tests" \
    "Run Phase 2 pipeline integration tests in omnidash. Execute:
cd ${OMNI_HOME}/omnidash
npx vitest run tests/integration/pattern-pipeline.test.ts tests/integration/injection-pipeline.test.ts tests/integration/intent-pipeline.test.ts

Report PASS count and FAIL count.
If ANY test fails, print: INTEGRATION: FAIL
If ALL tests pass, print: INTEGRATION: PASS" \
    "Bash,Read"; then
    record_strike "E2_pipeline_tests"
  fi

  if phase_failed "E2_pipeline_tests"; then
    log "CRITICAL: Pipeline verification tests failed. Data flow may be broken."
    update_cycle_state "halted_verification_pipeline"
    exit 1
  fi

  # E3: Phase 3 Playwright P0 data tests (dashboard rendering)
  # Non-blocking — produces WARN, does not halt close-out
  if ! run_phase "E3_dashboard_tests" \
    "Run Playwright P0 data verification against running omnidash (if available). Execute:
cd ${OMNI_HOME}/omnidash
npx playwright test --config playwright.dataflow.config.ts p0-data-verification.spec.ts 2>&1 || true

Report test results. This is non-blocking — dashboard rendering failures do not affect runtime correctness.
Print INTEGRATION: PASS if tests pass, or describe failures as warnings." \
    "Bash,Read"; then
    log "WARNING: Dashboard verification tests failed (non-blocking)"
  fi

  # Mark verification as complete for this cycle
  echo "${RUN_ID}" > "${VERIFICATION_MARKER}"
  log "Verification suite complete"
fi

# ===========================================================================
# Finalize
# ===========================================================================

log "=== Finalizing close-out run ==="

emit_task_event "task-completed" "${RUN_ID}" "\"session_id\": \"${ONEX_RUN_ID}\", \"phase\": \"pipeline-complete\", \"consecutive_failures\": ${CONSECUTIVE_FAILURES}"

update_cycle_state "complete"

# Write run summary
cat > "${RUN_DIR}/summary.txt" << EOF
Close-out Run Summary
=====================
Run ID:    ${RUN_ID}
Completed: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Dry Run:   ${DRY_RUN}

Phase Results:
  A1 merge-sweep:      $(test -f "${RUN_DIR}/A1_merge_sweep.txt" && echo "executed" || echo "missing")
  A2 deploy-plugin:    $(test -f "${RUN_DIR}/A2_deploy_plugin.txt" && echo "executed" || echo "missing")
  A3 infra-health:     $(test -f "${RUN_DIR}/A3_start_env.txt" && echo "executed" || echo "missing")
  B1 runtime-sweep:    $(test -f "${RUN_DIR}/B1_runtime_sweep.txt" && echo "executed" || echo "missing")
  B2 data-flow-sweep:  $(test -f "${RUN_DIR}/B2_data_flow_sweep.txt" && echo "executed" || echo "missing")
  B3 database-sweep:   $(test -f "${RUN_DIR}/B3_database_sweep.txt" && echo "executed" || echo "missing")
  B4b data-verify:    $(test -f "${RUN_DIR}/B4b_data_verification.txt" && echo "executed" || echo "missing")
  B5 integration-gate: $(test -f "${RUN_DIR}/B5_integration.txt" && echo "executed" || echo "missing")
  B6 contract-verify: $(test -f "${RUN_DIR}/B6_contract_verify.txt" && echo "executed" || echo "missing")
  C1 release-check:    $(test -f "${RUN_DIR}/C1_release_check.txt" && echo "executed" || echo "missing")
  C2 redeploy-check:   $(test -f "${RUN_DIR}/C2_redeploy_check.txt" && echo "executed" || echo "missing")
  D3 dashboard-sweep:  $(test -f "${RUN_DIR}/D3_dashboard_sweep.txt" && echo "executed" || echo "missing")
  E1 foundation-tests: $(test -f "${RUN_DIR}/E1_foundation_tests.txt" && echo "executed" || echo "missing")
  E2 pipeline-tests:   $(test -f "${RUN_DIR}/E2_pipeline_tests.txt" && echo "executed" || echo "missing")
  E3 dashboard-tests:  $(test -f "${RUN_DIR}/E3_dashboard_tests.txt" && echo "executed" || echo "missing")

Pending Redeploy: ${HAS_PENDING_REDEPLOY}
Consecutive Failures: ${CONSECUTIVE_FAILURES}
EOF

log "Close-out run ${RUN_ID} complete"
log "Summary: ${RUN_DIR}/summary.txt"
log "Full log: ${LOG_DIR}/${RUN_ID}.log"
