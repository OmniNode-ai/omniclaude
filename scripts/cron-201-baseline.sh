#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# cron-201-baseline.sh — Daily .201 infrastructure baseline health check [OMN-9721]
#
# Performs 4-category checks and emits a JSON result to stdout and
# /tmp/cron-201-baseline-stdout.log.
#
# Check categories (per plan Track E / E1a, v2 Edit 5):
#   1. liveness        — LLM endpoint /health probes + Kafka broker reachability
#   2. env_integrity   — uv sync --frozen against omnimarket pyproject.toml
#                        (returns "deferred" when not running on .201 host)
#   3. runtime_topology — consumer-group registry diff (no hardcoded count)
#   4. deferred        — deploy-agent reachability stub (OMN-9713)
#
# Friction policy:
#   liveness   → category=critical  (service down = actionable alert)
#   env        → category=warn      (stale env = investigate, not page)
#   topology   → category=warn      (group drift = investigate)
#   deferred   → category=info      (placeholder, not a failure)
#
# Usage:
#   ./scripts/cron-201-baseline.sh              # Full run
#   ./scripts/cron-201-baseline.sh --dry-run    # Print what would run, exit 0
#
# INSTALLATION DEFERRED — launchctl bootstrap requires user approval.
# This script is shipped but NOT installed automatically.
# See scripts/launchd/ai.omninode.201-baseline.plist for the plist template.
#
# [OMN-9721]

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONEX_REGISTRY_ROOT="${OMNI_HOME:-${ONEX_REGISTRY_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}}"
STATE_DIR="${ONEX_REGISTRY_ROOT}/.onex_state/201-baseline-results"
LOG_FILE="/tmp/cron-201-baseline-stdout.log"
LOCK_FILE="${STATE_DIR}/cron-201-baseline.lock"
LOCK_TIMEOUT=7200  # 2 hours — daily tick, generous budget

RUN_ID="201-baseline-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
DRY_RUN=false

# .201 infrastructure addresses (never hardcode in source; override via env)
DOT201_HOST="${ONEX_DOT201_HOST:-192.168.86.201}"
DOT200_HOST="${ONEX_DOT200_HOST:-192.168.86.200}"

# LLM endpoints to probe (host:port label)
VLLM_ENDPOINTS=(
  "${DOT201_HOST}:8000:vllm-coder"
  "${DOT201_HOST}:8001:vllm-reasoning"
  "${DOT201_HOST}:8100:vllm-embeddings"
)
MLX_ENDPOINTS=(
  "${DOT200_HOST}:8101:mlx-deepseek-r1"
  "${DOT200_HOST}:8102:mlx-qwen3-next"
)

# Kafka bootstrap for broker reachability check
KAFKA_BOOTSTRAP="${ONEX_KAFKA_BOOTSTRAP:-${KAFKA_BOOTSTRAP_SERVERS:-192.168.86.201:19092}}"

# Expected consumer groups registry — F0/F1's eventual registry will be the
# long-term source of truth; for now read from this default path if it exists.
# Override via ONEX_CONSUMER_GROUPS_REGISTRY env var.
DEFAULT_REGISTRY="${ONEX_REGISTRY_ROOT}/omnibase_infra/contracts/runtime/expected_consumer_groups.yaml"
CONSUMER_GROUPS_REGISTRY="${ONEX_CONSUMER_GROUPS_REGISTRY:-${DEFAULT_REGISTRY}}"

# omnimarket pyproject for env_integrity check (local uv sync --frozen)
OMNIMARKET_DIR="${ONEX_REGISTRY_ROOT}/omni_worktrees"  # adjusted per host; see check logic

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Environment bootstrap
# ---------------------------------------------------------------------------

if [[ -f "${HOME}/.omnibase/.env" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.omnibase/.env"
fi

# ---------------------------------------------------------------------------
# Directory + lock setup
# ---------------------------------------------------------------------------

mkdir -p "${STATE_DIR}"

if [[ -f "${LOCK_FILE}" ]]; then
  lock_time=$(stat -f %m "${LOCK_FILE}" 2>/dev/null || stat -c %Y "${LOCK_FILE}" 2>/dev/null || echo 0)
  now=$(date +%s)
  age=$(( now - lock_time ))
  if [[ ${age} -lt ${LOCK_TIMEOUT} ]]; then
    echo "SKIP: Previous invocation still running (lock age: ${age}s < ${LOCK_TIMEOUT}s)"
    exit 0
  fi
  echo "WARN: Stale lock detected (age: ${age}s). Removing."
  rm -f "${LOCK_FILE}"
fi

echo "pid=$$ started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"' EXIT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
  echo "[cron-201-baseline $(date -u +"%H:%M:%S")] $1"
}

# Emit one JSON check result to stdout and to LOG_FILE.
# Args: category name status detail friction_policy
emit_check() {
  local category="$1"
  local name="$2"
  local status="$3"      # ok | warn | fail | deferred
  local detail="$4"
  local friction="$5"    # critical | warn | info

  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  # Sanitize detail: strip chars that would break JSON string interpolation.
  # Detail is a short diagnostic string from controlled sources; stripping
  # quotes/backslashes preserves readability without requiring jq at runtime.
  local safe_detail
  safe_detail="${detail//\"/\'}"
  safe_detail="${safe_detail//\\/\/}"

  local line
  line=$(printf '{"run_id":"%s","ts":"%s","category":"%s","name":"%s","status":"%s","detail":"%s","friction_policy":"%s"}' \
    "${RUN_ID}" "${ts}" "${category}" "${name}" "${status}" "${safe_detail}" "${friction}")

  echo "${line}"
  echo "${line}" >> "${LOG_FILE}"
}

# Probe an HTTP /health endpoint; returns 0 on 2xx, 1 otherwise.
# Fails safely if curl is unavailable.
probe_http_health() {
  local host="$1"
  local port="$2"

  if ! command -v curl &>/dev/null; then
    return 2  # tool missing
  fi

  local http_code
  http_code=$(curl -fsS --max-time 5 -o /dev/null -w "%{http_code}" \
    "http://${host}:${port}/health" 2>/dev/null) || true

  if [[ "${http_code}" =~ ^2 ]]; then
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# DRY RUN short-circuit
# ---------------------------------------------------------------------------

if [[ "${DRY_RUN}" == "true" ]]; then
  log "[DRY RUN] Would run 4-category baseline check:"
  log "  1. liveness      — probe ${#VLLM_ENDPOINTS[@]} vLLM + ${#MLX_ENDPOINTS[@]} MLX endpoints + Kafka"
  log "  2. env_integrity — uv sync --frozen on omnimarket (deferred if not on .201)"
  log "  3. topology      — diff consumer groups vs registry: ${CONSUMER_GROUPS_REGISTRY}"
  log "  4. deferred      — deploy-agent stub (OMN-9713)"
  log "[DRY RUN] Complete. No checks executed."
  exit 0
fi

# ---------------------------------------------------------------------------
# Category 1: liveness
# ---------------------------------------------------------------------------

log "=== Category 1: liveness ==="

for ep in "${VLLM_ENDPOINTS[@]}"; do
  IFS=':' read -r ep_host ep_port ep_label <<< "${ep}"
  probe_result=0
  probe_http_health "${ep_host}" "${ep_port}" || probe_result=$?

  if [[ ${probe_result} -eq 0 ]]; then
    emit_check "liveness" "llm_endpoint_${ep_label}" "ok" "http://${ep_host}:${ep_port}/health → 2xx" "critical"
  elif [[ ${probe_result} -eq 2 ]]; then
    emit_check "liveness" "llm_endpoint_${ep_label}" "deferred" "curl not available on this host" "info"
  else
    emit_check "liveness" "llm_endpoint_${ep_label}" "fail" "http://${ep_host}:${ep_port}/health → non-2xx or timeout" "critical"
  fi
done

for ep in "${MLX_ENDPOINTS[@]}"; do
  IFS=':' read -r ep_host ep_port ep_label <<< "${ep}"
  probe_result=0
  probe_http_health "${ep_host}" "${ep_port}" || probe_result=$?

  if [[ ${probe_result} -eq 0 ]]; then
    emit_check "liveness" "llm_endpoint_${ep_label}" "ok" "http://${ep_host}:${ep_port}/health → 2xx" "critical"
  elif [[ ${probe_result} -eq 2 ]]; then
    emit_check "liveness" "llm_endpoint_${ep_label}" "deferred" "curl not available on this host" "info"
  else
    emit_check "liveness" "llm_endpoint_${ep_label}" "fail" "http://${ep_host}:${ep_port}/health → non-2xx or timeout" "critical"
  fi
done

# Kafka broker reachability — use kcat if available, else rpk via SSH (skip if neither)
kafka_status="deferred"
kafka_detail="neither kcat nor rpk available locally"

if command -v kcat &>/dev/null; then
  kafka_exit=0
  kcat -L -b "${KAFKA_BOOTSTRAP}" -t __consumer_offsets >/dev/null 2>&1 || kafka_exit=$?
  if [[ ${kafka_exit} -eq 0 ]]; then
    kafka_status="ok"
    kafka_detail="kcat -L -b ${KAFKA_BOOTSTRAP} succeeded"
  else
    kafka_status="fail"
    kafka_detail="kcat -L -b ${KAFKA_BOOTSTRAP} exited ${kafka_exit}"
  fi
elif command -v rpk &>/dev/null; then
  kafka_exit=0
  rpk cluster health --brokers "${KAFKA_BOOTSTRAP}" >/dev/null 2>&1 || kafka_exit=$?
  if [[ ${kafka_exit} -eq 0 ]]; then
    kafka_status="ok"
    kafka_detail="rpk cluster health --brokers ${KAFKA_BOOTSTRAP} succeeded"
  else
    kafka_status="fail"
    kafka_detail="rpk cluster health --brokers ${KAFKA_BOOTSTRAP} exited ${kafka_exit}"
  fi
fi

friction_kafka="critical"
[[ "${kafka_status}" == "deferred" ]] && friction_kafka="info"
emit_check "liveness" "kafka_broker" "${kafka_status}" "${kafka_detail}" "${friction_kafka}"

# ---------------------------------------------------------------------------
# Category 2: env_integrity
# ---------------------------------------------------------------------------

log "=== Category 2: env_integrity ==="

# Detect whether we're running on .201 by checking the hostname or
# the presence of the GPU runtime indicator.
current_hostname=$(hostname -s 2>/dev/null || echo "unknown")
on_dot201=false
if [[ "${current_hostname}" == *"201"* ]] || [[ -f "/usr/local/bin/nvidia-smi" ]] || nvidia-smi &>/dev/null 2>&1; then
  on_dot201=true
fi

if [[ "${on_dot201}" == "false" ]]; then
  emit_check "env_integrity" "uv_sync_frozen" "deferred" \
    "not running on .201 (host=${current_hostname}); env_integrity check deferred" "info"
else
  # Find omnimarket — look under OMNI_HOME or ONEX_REGISTRY_ROOT
  omnimarket_path=""
  for candidate in \
    "${ONEX_REGISTRY_ROOT}/omnimarket" \
    "${HOME}/Code/omnimarket" \
    "${OMNI_HOME:-}/omnimarket"
  do
    if [[ -f "${candidate}/pyproject.toml" ]]; then
      omnimarket_path="${candidate}"
      break
    fi
  done

  if [[ -z "${omnimarket_path}" ]]; then
    emit_check "env_integrity" "uv_sync_frozen" "warn" \
      "omnimarket pyproject.toml not found; skipping uv sync check" "warn"
  elif ! command -v uv &>/dev/null; then
    emit_check "env_integrity" "uv_sync_frozen" "warn" \
      "uv not found on PATH; skipping env_integrity check" "warn"
  else
    uv_exit=0
    uv_output=""
    uv_output=$(cd "${omnimarket_path}" && uv sync --frozen 2>&1) || uv_exit=$?
    if [[ ${uv_exit} -eq 0 ]]; then
      emit_check "env_integrity" "uv_sync_frozen" "ok" \
        "uv sync --frozen in ${omnimarket_path} succeeded" "warn"
    else
      emit_check "env_integrity" "uv_sync_frozen" "warn" \
        "uv sync --frozen in ${omnimarket_path} exited ${uv_exit}: ${uv_output:0:200}" "warn"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Category 3: runtime_topology
# ---------------------------------------------------------------------------

log "=== Category 3: runtime_topology ==="

# Read expected consumer groups from registry YAML.
# Registry format (expected_consumer_groups.yaml):
#   consumer_groups:
#     - name: group-a
#     - name: group-b
# F0/F1's registry will be the long-term source of truth for this path.
# Until that ships, the file may not exist — we degrade gracefully.

if [[ ! -f "${CONSUMER_GROUPS_REGISTRY}" ]]; then
  emit_check "runtime_topology" "consumer_group_diff" "deferred" \
    "registry not found at ${CONSUMER_GROUPS_REGISTRY}; topology check deferred until F0/F1 ships registry" "info"
else
  # Parse expected group names from YAML (simple regex; no yq dependency).
  # Assumes standard block-sequence format: "  - name: group-name" per line.
  # Flow-style YAML, comments, or non-standard indentation will not be parsed
  # correctly — if the registry uses these, switch to yq and update this block.
  expected_groups=()
  while IFS= read -r line; do
    # Match lines like "  - name: group-name" or "- name: group-name"
    if [[ "${line}" =~ ^[[:space:]]*-[[:space:]]+name:[[:space:]]*(.+)$ ]]; then
      grp="${BASH_REMATCH[1]}"
      grp="${grp#"${grp%%[! ]*}"}"  # trim leading whitespace
      grp="${grp%"${grp##*[! ]}"}"  # trim trailing whitespace
      expected_groups+=("${grp}")
    fi
  done < "${CONSUMER_GROUPS_REGISTRY}"

  if [[ ${#expected_groups[@]} -eq 0 ]]; then
    emit_check "runtime_topology" "consumer_group_diff" "warn" \
      "registry at ${CONSUMER_GROUPS_REGISTRY} parsed 0 expected groups; check YAML format" "warn"
  else
    # Fetch live consumer groups
    live_groups=()
    rpk_exit=0

    if command -v rpk &>/dev/null; then
      raw_groups=$(rpk group list --brokers "${KAFKA_BOOTSTRAP}" 2>/dev/null) || rpk_exit=$?
      if [[ ${rpk_exit} -eq 0 ]]; then
        while IFS= read -r gl; do
          grp="${gl%%[[:space:]]*}"
          [[ -n "${grp}" && "${grp}" != "GROUP" ]] && live_groups+=("${grp}")
        done <<< "${raw_groups}"
      fi
    elif command -v kcat &>/dev/null; then
      # kcat does not list consumer groups; fall through to deferred
      rpk_exit=2
    else
      rpk_exit=2
    fi

    if [[ ${rpk_exit} -eq 2 ]]; then
      emit_check "runtime_topology" "consumer_group_diff" "deferred" \
        "rpk not available locally; topology check deferred" "info"
    elif [[ ${rpk_exit} -ne 0 ]]; then
      emit_check "runtime_topology" "consumer_group_diff" "warn" \
        "rpk group list exited ${rpk_exit}; cannot diff topology" "warn"
    else
      # Diff expected vs live
      missing_groups=()
      for eg in "${expected_groups[@]}"; do
        found=false
        for lg in "${live_groups[@]}"; do
          [[ "${eg}" == "${lg}" ]] && found=true && break
        done
        [[ "${found}" == "false" ]] && missing_groups+=("${eg}")
      done

      if [[ ${#missing_groups[@]} -eq 0 ]]; then
        emit_check "runtime_topology" "consumer_group_diff" "ok" \
          "all ${#expected_groups[@]} expected groups present in live registry" "warn"
      else
        missing_csv="${missing_groups[*]}"
        emit_check "runtime_topology" "consumer_group_diff" "warn" \
          "missing groups: ${missing_csv// /, } (${#missing_groups[@]} of ${#expected_groups[@]} expected)" "warn"
      fi
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Category 4: deferred
# ---------------------------------------------------------------------------

log "=== Category 4: deferred ==="

emit_check "deferred" "deploy_agent_reachability" "deferred" \
  "deploy-agent reachability check deferred until OMN-9713 ships the agent endpoint" "info"

# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------

log "=== 201-baseline run ${RUN_ID} complete. Results appended to ${LOG_FILE} ==="
exit 0
