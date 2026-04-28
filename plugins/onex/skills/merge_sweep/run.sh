#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# run.sh — contract-canonical launcher for /onex:merge_sweep.

set -euo pipefail

RUN_ID="merge-sweep-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
DRY_RUN=false
INVENTORY_ONLY=false
FIX_ONLY=false
MERGE_ONLY=false
REPOS=""
MAX_PARALLEL_POLISH=20
ENABLE_AUTO_REBASE=true
USE_DAG_ORDERING=true
ENABLE_TRIVIAL_COMMENT_RESOLUTION=true
ENABLE_ADMIN_MERGE_FALLBACK=true
ADMIN_FALLBACK_THRESHOLD_MINUTES=15
VERIFY=false
VERIFY_TIMEOUT_SECONDS=30

require_value() {
  local flag="$1"
  local value="${2:-}"
  if [[ -z "${value}" ]]; then
    echo "missing value for ${flag}" >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repos) require_value "$1" "${2:-}"; REPOS="$2"; shift 2 ;;
    --repos=*) REPOS="${1#*=}"; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --inventory-only) INVENTORY_ONLY=true; shift ;;
    --fix-only) FIX_ONLY=true; shift ;;
    --merge-only|--skip-polish) MERGE_ONLY=true; shift ;;
    --max-parallel-polish) require_value "$1" "${2:-}"; MAX_PARALLEL_POLISH="$2"; shift 2 ;;
    --max-parallel-polish=*) MAX_PARALLEL_POLISH="${1#*=}"; shift ;;
    --enable-auto-rebase) require_value "$1" "${2:-}"; ENABLE_AUTO_REBASE="$2"; shift 2 ;;
    --enable-auto-rebase=*) ENABLE_AUTO_REBASE="${1#*=}"; shift ;;
    --use-dag-ordering) require_value "$1" "${2:-}"; USE_DAG_ORDERING="$2"; shift 2 ;;
    --use-dag-ordering=*) USE_DAG_ORDERING="${1#*=}"; shift ;;
    --enable-trivial-comment-resolution) require_value "$1" "${2:-}"; ENABLE_TRIVIAL_COMMENT_RESOLUTION="$2"; shift 2 ;;
    --enable-trivial-comment-resolution=*) ENABLE_TRIVIAL_COMMENT_RESOLUTION="${1#*=}"; shift ;;
    --enable-admin-merge-fallback) require_value "$1" "${2:-}"; ENABLE_ADMIN_MERGE_FALLBACK="$2"; shift 2 ;;
    --enable-admin-merge-fallback=*) ENABLE_ADMIN_MERGE_FALLBACK="${1#*=}"; shift ;;
    --admin-fallback-threshold-minutes) require_value "$1" "${2:-}"; ADMIN_FALLBACK_THRESHOLD_MINUTES="$2"; shift 2 ;;
    --admin-fallback-threshold-minutes=*) ADMIN_FALLBACK_THRESHOLD_MINUTES="${1#*=}"; shift ;;
    --verify)
      if [[ -n "${2:-}" && "${2:-}" != --* ]]; then
        VERIFY="$2"
        shift 2
      else
        VERIFY=true
        shift
      fi
      ;;
    --verify=*) VERIFY="${1#*=}"; shift ;;
    --verify-timeout-seconds) require_value "$1" "${2:-}"; VERIFY_TIMEOUT_SECONDS="$2"; shift 2 ;;
    --verify-timeout-seconds=*) VERIFY_TIMEOUT_SECONDS="${1#*=}"; shift ;;
    --run-id) require_value "$1" "${2:-}"; RUN_ID="$2"; shift 2 ;;
    --run-id=*) RUN_ID="${1#*=}"; shift ;;
    --merge-method|--require-approval|--require-up-to-date|--max-total-merges|--max-parallel-prs|--max-parallel-repos|--authors|--since|--label|--polish-clean-runs)
      echo "unsupported v7 merge_sweep flag: $1" >&2
      exit 2
      ;;
    --resume|--reset-state)
      echo "unsupported v7 merge_sweep flag: $1" >&2
      exit 2
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

OMNI_HOME="${OMNI_HOME:-}"
if [[ -z "${OMNI_HOME}" ]]; then
  echo "OMNI_HOME is required so run.sh can locate omnimarket" >&2
  exit 2
fi
OMNIMARKET_DIR="${OMNI_HOME}/omnimarket"
if [[ ! -d "${OMNIMARKET_DIR}" ]]; then
  echo "omnimarket checkout not found at ${OMNIMARKET_DIR}" >&2
  exit 2
fi

INPUT_JSON="$(
  cd "${OMNIMARKET_DIR}"
  uv run python - \
    "${RUN_ID}" \
    "${DRY_RUN}" \
    "${INVENTORY_ONLY}" \
    "${FIX_ONLY}" \
    "${MERGE_ONLY}" \
    "${REPOS}" \
    "${MAX_PARALLEL_POLISH}" \
    "${ENABLE_AUTO_REBASE}" \
    "${USE_DAG_ORDERING}" \
    "${ENABLE_TRIVIAL_COMMENT_RESOLUTION}" \
    "${ENABLE_ADMIN_MERGE_FALLBACK}" \
    "${ADMIN_FALLBACK_THRESHOLD_MINUTES}" \
    "${VERIFY}" \
    "${VERIFY_TIMEOUT_SECONDS}" <<'PY'
import sys
from uuid import uuid4

from omnibase_core.models.events.model_event_envelope import ModelEventEnvelope
from omnimarket.nodes.node_pr_lifecycle_orchestrator.handlers.handler_pr_lifecycle_orchestrator import (
    ModelPrLifecycleStartCommand,
)


def as_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


(
    run_id,
    dry_run,
    inventory_only,
    fix_only,
    merge_only,
    repos,
    max_parallel_polish,
    enable_auto_rebase,
    use_dag_ordering,
    enable_trivial_comment_resolution,
    enable_admin_merge_fallback,
    admin_fallback_threshold_minutes,
    verify,
    verify_timeout_seconds,
) = sys.argv[1:]

correlation_id = uuid4()
command = ModelPrLifecycleStartCommand(
    correlation_id=correlation_id,
    run_id=run_id,
    dry_run=as_bool(dry_run),
    inventory_only=as_bool(inventory_only),
    fix_only=as_bool(fix_only),
    merge_only=as_bool(merge_only),
    repos=repos,
    max_parallel_polish=int(max_parallel_polish),
    enable_auto_rebase=as_bool(enable_auto_rebase),
    use_dag_ordering=as_bool(use_dag_ordering),
    enable_trivial_comment_resolution=as_bool(enable_trivial_comment_resolution),
    enable_admin_merge_fallback=as_bool(enable_admin_merge_fallback),
    admin_fallback_threshold_minutes=int(admin_fallback_threshold_minutes),
    verify=as_bool(verify),
    verify_timeout_seconds=int(verify_timeout_seconds),
)
envelope = ModelEventEnvelope[ModelPrLifecycleStartCommand](
    event_type="omnimarket.pr-lifecycle-orchestrator-start",
    correlation_id=correlation_id,
    payload=command,
)
print(envelope.model_dump_json())
PY
)"

cd "${OMNIMARKET_DIR}"
uv run python -m omnimarket.nodes.node_pr_lifecycle_orchestrator --input "${INPUT_JSON}"
