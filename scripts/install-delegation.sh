#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# install-delegation.sh — Customer installer for the ONEX delegation feature [OMN-10626].
#
# Routes simple Claude Code tasks to cheaper local models (or local LLMs on Apple
# Silicon). The installer is dry-run by default; pass --apply to execute.
#
# What it installs:
#   1. The omniclaude delegation runner Python package (pip install)
#   2. SQLite database directory at ~/.omninode/delegation/
#   3. A dedicated native delegation plugin, its interpreter binding and ownership
#      manifest; unrelated Claude Code hooks and settings are preserved.
#   4. Rollback manifest at ~/.omninode/delegation/rollback-manifest.json
#
# Idempotent: re-running detects existing state and only acts on diffs.
#
# Usage:
#   bash install-delegation.sh                 # dry-run (default)
#   bash install-delegation.sh --apply         # execute
#   bash install-delegation.sh --apply --from-source <repo>   # install from source
#   bash install-delegation.sh --uninstall     # remove via rollback manifest
#   bash install-delegation.sh --help

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

INSTALL_ROOT="${HOME}/.omninode/delegation"
INSTALL_DB="${INSTALL_ROOT}/delegation.sqlite"
INSTALL_HOOKS_JSON="${INSTALL_ROOT}/hooks-delegation.json"
# The installed hooks keep the plugin's own layout, so every path they resolve
# relative to themselves (error-guard.sh, hook bits, mode.sh, repo_guard.sh,
# the routing runner, cost_accounting as plugins.onex.hooks.lib) exists
# (OMN-22498). The old flat hook-scripts/ copy could not run.
INSTALL_PLUGIN_ROOT="${INSTALL_ROOT}/plugin/plugins/onex"
INSTALL_SCRIPTS_DIR="${INSTALL_PLUGIN_ROOT}/hooks/scripts"
ROLLBACK_MANIFEST="${INSTALL_ROOT}/rollback-manifest.json"

CLAUDE_SETTINGS="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}/settings.json"
CLAUDE_SETTINGS_BACKUP_DIR="${INSTALL_ROOT}/backups"

SOURCE_HOOK_CONFIG="${REPO_ROOT}/plugins/onex/hooks/hooks-delegation.v1.json"
SOURCE_HOOK_SCRIPTS="${REPO_ROOT}/plugins/onex/hooks/scripts"
PACKAGE_NAME="omninode-claude"

# Bifrost contract endpoints: repo defaults stay packaged with empty endpoint_url
# fields; user-specific endpoints live in this overlay only (OMN-10717).
INSTALL_BIFROST_OVERLAY="${INSTALL_ROOT}/bifrost_overrides.yaml"
LEGACY_INSTALL_BIFROST="${INSTALL_ROOT}/bifrost_delegation.yaml"

DRY_RUN=true
APPLY=false
UNINSTALL=false
PAUSE=false
FROM_SOURCE=""
PYTHON_BIN=""
ENDPOINT_URL=""
SKIP_PIP=false
SKIP_SMOKE=false
# Run state: what this run moved or copied aside so a run that stops before
# Claude's installer succeeds can put it back (restore_run_state).
SETTINGS_SNAPSHOT=""
SETTINGS_EXISTED=false
SETTINGS_SAVED=false
TREE_SNAPSHOT=""
RUN_BACKUP=""
# The paths under INSTALL_ROOT a run replaces: the hook config (or native
# marker), the plugin tree, the old flat copy and the marketplace metadata.
RUN_OWNED_PATHS=(hooks-delegation.json plugin hook-scripts .claude-plugin)
# A signal held while Claude's installer runs (hold_signals), as an exit status.
PENDING_SIGNAL_STATUS=""

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
  C_RED=$'\033[31m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""
fi

log_info() { printf '%s[INFO]%s %s\n' "${C_BLUE}" "${C_RESET}" "$*"; }
log_step() { printf '%s[STEP]%s %s\n' "${C_BOLD}" "${C_RESET}" "$*"; }
log_warn() { printf '%s[WARN]%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*" >&2; }
log_err()  { printf '%s[ERR ]%s %s\n' "${C_RED}" "${C_RESET}" "$*" >&2; }
log_ok()   { printf '%s[ OK ]%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; }
log_dry()  { printf '%s[DRY ]%s %s\n' "${C_DIM}" "${C_RESET}" "$*"; }

# Run a command for real, or log it as dry-run.
run_or_dry() {
  if "${DRY_RUN}"; then
    log_dry "would run: $*"
  else
    "$@"
  fi
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

usage() {
  cat <<EOF
${C_BOLD}install-delegation.sh${C_RESET} — install the ONEX delegation feature for Claude Code.

Usage:
  $0 [--apply | --pause | --uninstall] [--from-source <path>] [--python <bin>]

Options:
  --apply                 Execute changes (default is dry-run preview).
  --pause                 Remove delegation entry points; a classic install keeps its
                          pending-history helper, a native install clears pending history.
  --uninstall             Restore prior state using the rollback manifest.
  --endpoint-url <url>    LLM endpoint URL to write into the bifrost endpoint
                          overlay (e.g. http://llm.example.com:8000). If omitted
                          during --apply, an interactive prompt will ask for it.
  --from-source <path>    Install the omniclaude package from a local repo
                          (default: install ${PACKAGE_NAME} from package index).
  --python <bin>          Python interpreter to use for pip install
                          (default: python3 from PATH; must be 3.12+).
  --skip-pip              Skip pip install (assume omniclaude is already
                          importable; useful for CI and re-runs).
  --skip-smoke            Skip the post-install smoke test.
  -h, --help              Show this help.

Examples:
  $0                      Preview the install plan (no changes).
  $0 --apply              Run the install for real.
  $0 --apply --endpoint-url http://llm.example.com:8000
  $0 --uninstall          Roll back the install.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)        APPLY=true; DRY_RUN=false; shift; continue ;;
    --pause)        PAUSE=true; DRY_RUN=false; shift; continue ;;
    --uninstall)    UNINSTALL=true; DRY_RUN=false; shift; continue ;;
    --from-source)  requirement="a path"; destination=FROM_SOURCE ;;
    --python)       requirement="an interpreter path"; destination=PYTHON_BIN ;;
    --endpoint-url) requirement="a URL"; destination=ENDPOINT_URL ;;
    --skip-pip)     SKIP_PIP=true; shift; continue ;;
    --skip-smoke)   SKIP_SMOKE=true; shift; continue ;;
    -h|--help)      usage; exit 0 ;;
    *)              log_err "unknown argument: $1"; usage >&2; exit 2 ;;
  esac
  if [[ $# -lt 2 || -z "${2:-}" ]]; then
    log_err "$1 requires $requirement"
    exit 2
  fi
  printf -v "$destination" '%s' "$2"
  shift 2
done

if { "${APPLY}" && { "${UNINSTALL}" || "${PAUSE}"; }; } || { "${UNINSTALL}" && "${PAUSE}"; }; then
  log_err "--apply, --pause and --uninstall are mutually exclusive"
  exit 2
fi

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

check_claude_cli() {
  if ! command -v claude >/dev/null 2>&1; then
    log_err "Claude Code CLI not found on PATH. Install from https://claude.com/claude-code"
    return 1
  fi
  local ver
  ver="$(claude --version 2>&1 | head -1 || true)"
  if [[ ! "$ver" =~ ([0-9]+)\.([0-9]+)\.([0-9]+) ]] ||
     (( BASH_REMATCH[1] < 2 || (BASH_REMATCH[1] == 2 && BASH_REMATCH[2] < 1) ||
        (BASH_REMATCH[1] == 2 && BASH_REMATCH[2] == 1 && BASH_REMATCH[3] < 287) )); then
    log_err "Native delegation output requires Claude Code 2.1.287 or newer (${ver})"
    return 1
  fi
  log_ok "Claude Code CLI: ${ver}"
}

resolve_python() {
  if [[ -n "${PYTHON_BIN}" ]]; then
    if [[ ! -x "${PYTHON_BIN}" ]] && ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
      log_err "Python interpreter not found: ${PYTHON_BIN}"
      return 1
    fi
  else
    PYTHON_BIN="$(command -v python3 || true)"
    if [[ -z "${PYTHON_BIN}" ]]; then
      log_err "python3 not found on PATH"
      return 1
    fi
  fi
  # The native mod refuses a non-absolute interpreter binding, so a bare name
  # or relative path becomes absolute here. Symlinks are kept as given: a venv's
  # python must keep its venv path.
  if [[ "${PYTHON_BIN}" != */* ]]; then
    PYTHON_BIN="$(command -v "${PYTHON_BIN}")"
  fi
  if [[ "${PYTHON_BIN}" != /* ]]; then
    PYTHON_BIN="$(cd "$(dirname "${PYTHON_BIN}")" && pwd)/$(basename "${PYTHON_BIN}")"
  fi
  if ! "${PYTHON_BIN}" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then
    local pyver
    pyver="$("${PYTHON_BIN}" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo unknown)"
    log_err "Python 3.12+ required (found ${pyver} at ${PYTHON_BIN})"
    return 1
  fi
  log_ok "Python: ${PYTHON_BIN} ($("${PYTHON_BIN}" -c 'import sys; print(sys.version.split()[0])'))"
}

check_source_files() {
  if [[ -n "${FROM_SOURCE}" ]]; then
    REPO_ROOT="$(cd "${FROM_SOURCE}" && pwd)"
    SOURCE_HOOK_CONFIG="${REPO_ROOT}/plugins/onex/hooks/hooks-delegation.v1.json"
    SOURCE_HOOK_SCRIPTS="${REPO_ROOT}/plugins/onex/hooks/scripts"
  fi
  if [[ ! -f "${SOURCE_HOOK_CONFIG}" ]]; then
    log_err "hook config missing at ${SOURCE_HOOK_CONFIG}"
    return 1
  fi
  if [[ ! -d "${SOURCE_HOOK_SCRIPTS}" ]]; then
    log_err "hook scripts dir missing at ${SOURCE_HOOK_SCRIPTS}"
    return 1
  fi
  log_ok "source files present at ${REPO_ROOT}"
}

# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------

ensure_install_dir() {
  log_step "ensure install dirs (${INSTALL_ROOT})"
  # plugin/ is left to install_hook_config, so it moves aside the tree as it was.
  run_or_dry mkdir -p "${INSTALL_ROOT}" "${CLAUDE_SETTINGS_BACKUP_DIR}"
}

install_python_package() {
  log_step "install Python package (${PACKAGE_NAME})"
  if "${SKIP_PIP}"; then
    log_info "--skip-pip set: assuming package already importable"
    return 0
  fi
  local desired_version install_target installed_version
  desired_version="${OMNICLAUDE_INSTALL_VERSION:-}"
  if [[ -z "${desired_version}" ]]; then
    desired_version="$("${PYTHON_BIN}" - "${REPO_ROOT}/pyproject.toml" <<'PY'
import pathlib
import sys
import tomllib

data = tomllib.loads(pathlib.Path(sys.argv[1]).read_text())
print(data["project"]["version"])
PY
)"
  fi
  if [[ -n "${FROM_SOURCE}" ]]; then
    install_target="${REPO_ROOT}"
  else
    install_target="${PACKAGE_NAME}==${desired_version}"
  fi
  if "${DRY_RUN}"; then
    log_dry "would: ${PYTHON_BIN} -m pip install --user --upgrade '${install_target}'"
    return 0
  fi
  installed_version="$("${PYTHON_BIN}" - "${PACKAGE_NAME}" <<'PY' 2>/dev/null || true
from importlib.metadata import PackageNotFoundError, version
import sys

try:
    print(version(sys.argv[1]))
except PackageNotFoundError:
    raise SystemExit(1)
PY
)"
  if [[ -z "${FROM_SOURCE}" && "${installed_version}" == "${desired_version}" ]]; then
    log_info "${PACKAGE_NAME} ${installed_version} already installed — skipping pip install"
    return 0
  fi
  "${PYTHON_BIN}" -m pip install --user --upgrade "${install_target}"
  log_ok "installed ${install_target}"
}

deploy_bifrost_contract() {
  log_step "write bifrost endpoint overlay to ${INSTALL_BIFROST_OVERLAY}"

  # Locate the canonical bifrost contract (omnimarket owns it; omniclaude ships
  # no copy, OMN-17102). Prefer the omnimarket sibling clone (monorepo layout),
  # then the omnimarket installed for PYTHON_BIN. The contract is only read to
  # find the local backend ids an --endpoint-url applies to.
  local bifrost_source=""
  local search_paths=(
    "${REPO_ROOT}/../omnimarket/src/omnimarket/configs/bifrost_delegation.yaml"
  )
  for p in "${search_paths[@]}"; do
    if [[ -f "$p" ]]; then
      bifrost_source="$(cd "$(dirname "$p")" && pwd)/$(basename "$p")"
      break
    fi
  done
  if [[ -z "${bifrost_source}" ]]; then
    bifrost_source="$("${PYTHON_BIN}" - <<'PY' 2>/dev/null || true
import importlib.util
import pathlib

spec = importlib.util.find_spec("omnimarket")
for root in (spec.submodule_search_locations or []) if spec else []:
    candidate = pathlib.Path(root) / "configs" / "bifrost_delegation.yaml"
    if candidate.is_file():
        print(candidate)
        break
PY
)"
  fi

  if [[ -z "${bifrost_source}" && -n "${ENDPOINT_URL}" ]]; then
    log_warn "canonical bifrost_delegation.yaml (omnimarket) not found — skipping endpoint overlay"
    log_warn "The routing handler will load the packaged default contract without endpoint overrides"
    return 0
  fi

  log_info "source: ${bifrost_source}"

  # Prompt for endpoint URL if not provided via --endpoint-url (interactive only).
  if [[ -z "${ENDPOINT_URL}" ]] && ! "${DRY_RUN}" && [[ -t 0 ]]; then
    printf '\n%sEnter the LLM endpoint URL%s (e.g. http://llm.example.com:8000): ' \
      "${C_BOLD}" "${C_RESET}"
    read -r ENDPOINT_URL
    if [[ -z "${ENDPOINT_URL}" ]]; then
      log_warn "no endpoint URL provided — deploying contract with empty endpoints"
    fi
  fi

  if "${DRY_RUN}"; then
    log_dry "would read backend IDs from ${bifrost_source}"
    log_dry "would write overlay ${INSTALL_BIFROST_OVERLAY}"
    if [[ -f "${LEGACY_INSTALL_BIFROST}" ]]; then
      log_dry "would preserve endpoints from legacy ${LEGACY_INSTALL_BIFROST}"
    fi
    if [[ -n "${ENDPOINT_URL}" ]]; then
      log_dry "would write endpoint_url=${ENDPOINT_URL} into local backend overlay entries"
    fi
    return 0
  fi

  "${PYTHON_BIN}" - "${bifrost_source}" "${INSTALL_BIFROST_OVERLAY}" "${LEGACY_INSTALL_BIFROST}" "${ENDPOINT_URL}" <<'PY'
import pathlib
import sys

import yaml

source_path, overlay_path, legacy_path = map(pathlib.Path, sys.argv[1:4])
endpoint_url = sys.argv[4]


def load_mapping(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text())
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SystemExit(f"invalid bifrost yaml at {path}")
    return data


source = load_mapping(source_path)
existing_overlay = load_mapping(overlay_path)
legacy = load_mapping(legacy_path)

backends_by_id: dict[str, dict] = {}
for container in (legacy, existing_overlay):
    for backend in container.get("backends") or []:
        if not isinstance(backend, dict):
            continue
        backend_id = backend.get("backend_id")
        existing_endpoint = str(backend.get("endpoint_url") or "").strip()
        if backend_id:
            # Endpoint overlays also carry model bindings and backend-specific
            # settings. Reinstallation must not discard those saved fields.
            preserved = {**backend, "backend_id": str(backend_id)}
            if existing_endpoint:
                preserved["endpoint_url"] = existing_endpoint
            backends_by_id[str(backend_id)] = preserved

if endpoint_url:
    for backend in source.get("backends") or []:
        if not isinstance(backend, dict):
            continue
        backend_id = backend.get("backend_id")
        if backend_id and backend.get("tier") == "local":
            preserved = backends_by_id.setdefault(
                str(backend_id), {"backend_id": str(backend_id)}
            )
            preserved["endpoint_url"] = endpoint_url

overlay = {**legacy, **existing_overlay, "backends": list(backends_by_id.values())}
overlay_path.parent.mkdir(parents=True, exist_ok=True)
overlay_path.write_text(yaml.dump(overlay, default_flow_style=False, sort_keys=False))
print(f"wrote {len(overlay['backends'])} endpoint overlay entries to {overlay_path}")
PY
  log_ok "wrote bifrost endpoint overlay to ${INSTALL_BIFROST_OVERLAY}"
}

native_plugin() {
  PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}" "${PYTHON_BIN}" -m \
    omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.container_onboarding_assets \
    "$1" "${INSTALL_ROOT}" "${CLAUDE_SETTINGS}" "${PYTHON_BIN}"
}

install_hook_config() {
  log_step "install hook config to ${INSTALL_HOOKS_JSON}"
  # Rewrite ${CLAUDE_PLUGIN_ROOT} → INSTALL_ROOT so hook commands work outside
  # the plugin context.
  if "${DRY_RUN}"; then
    log_dry "would rewrite \${CLAUDE_PLUGIN_ROOT} → ${INSTALL_PLUGIN_ROOT}"
    log_dry "would copy hook scripts: ${SOURCE_HOOK_SCRIPTS%/hooks/scripts}/{hooks,lib} → ${INSTALL_PLUGIN_ROOT}"
    return 0
  fi
  # Install the plugin's hooks and lib trees (not their tests) in the plugin's
  # own layout: the hook scripts source error-guard.sh, the hook-bit table,
  # mode.sh and repo_guard.sh by relative path, and run the routing runner and
  # cost_accounting from hooks/lib (OMN-22498). A fresh copy each run keeps a
  # re-install from mixing two versions.
  snapshot_install_tree
  mkdir -p "${INSTALL_PLUGIN_ROOT}"
  cp -R "${SOURCE_HOOK_SCRIPTS%/hooks/scripts}/hooks" "${SOURCE_HOOK_SCRIPTS%/hooks/scripts}/lib" "${INSTALL_PLUGIN_ROOT}/"
  rm -rf "${INSTALL_PLUGIN_ROOT}/hooks/tests" && find "${INSTALL_PLUGIN_ROOT}" -type d -name __pycache__ -prune -exec rm -rf {} +
  native_plugin prepare
  log_ok "wrote ${INSTALL_HOOKS_JSON}"
}

# Move this run's owned paths aside (same filesystem, so mv), so a run that
# stops before Claude's installer succeeds can put the tree back as it was.
# The folder is the whole run state on disk, so a run killed outright, even
# part way through a restore, can be put back by the next one
# (recover_stale_run_state): .claude-settings names the profile this run
# edits, each owned path is either moved in or marked .absent.<name>,
# .settings.saved or .settings.absent is settings.json before this run, and
# .run-backup names the pre-install backup this run made.
snapshot_install_tree() {
  TREE_SNAPSHOT="$(mktemp -d "${CLAUDE_SETTINGS_BACKUP_DIR}/install-tree.run.XXXXXX")"
  printf '%s\n' "${CLAUDE_SETTINGS}" > "${TREE_SNAPSHOT}/.claude-settings"
  local name
  for name in "${RUN_OWNED_PATHS[@]}"; do
    if [[ -e "${INSTALL_ROOT}/${name}" || -L "${INSTALL_ROOT}/${name}" ]]; then
      mv "${INSTALL_ROOT}/${name}" "${TREE_SNAPSHOT}/${name}"
    else
      : > "${TREE_SNAPSHOT}/.absent.${name}"
    fi
  done
}

# Put back what this run replaced: the owned install paths, settings.json and,
# when this run made it, the pre-install settings backup no manifest will name.
# Safe to call twice and from the EXIT trap at any point of the run.
restore_run_state() {
  local name
  # Settings first: the settings snapshot lives in the tree snapshot folder.
  if [[ -n "${SETTINGS_SNAPSHOT}" ]]; then
    if "${SETTINGS_SAVED}"; then
      if "${SETTINGS_EXISTED}"; then
        cp "${SETTINGS_SNAPSHOT}" "${CLAUDE_SETTINGS}"
      else
        rm -f "${CLAUDE_SETTINGS}"
      fi
    fi
    rm -f "${SETTINGS_SNAPSHOT}"
  fi
  if [[ -n "${TREE_SNAPSHOT}" ]]; then
    for name in "${RUN_OWNED_PATHS[@]}"; do
      if [[ -e "${TREE_SNAPSHOT}/${name}" || -L "${TREE_SNAPSHOT}/${name}" ]]; then
        rm -rf "${INSTALL_ROOT:?}/${name}"
        mv "${TREE_SNAPSHOT}/${name}" "${INSTALL_ROOT}/${name}"
      elif [[ -e "${TREE_SNAPSHOT}/.absent.${name}" ]]; then
        # Absent before this run: whatever is there now is this run's.
        rm -rf "${INSTALL_ROOT:?}/${name}"
        rm -f "${TREE_SNAPSHOT}/.absent.${name}"
      fi
      # Otherwise it is already back, or the snapshot never reached it.
    done
    rm -rf "${TREE_SNAPSHOT}"
  fi
  if [[ -n "${RUN_BACKUP}" ]]; then
    rm -f "${RUN_BACKUP}"
  fi
  TREE_SNAPSHOT=""
  SETTINGS_SNAPSHOT=""; SETTINGS_SAVED=false; RUN_BACKUP=""
}

# Claude's installer succeeded: this run's changes stand. The snapshot folder
# is renamed out of the install-tree.run.* pattern in one step before it is
# deleted, so a run killed while deleting it is never taken for a stale run
# (recover_stale_run_state only clears the leftover).
commit_run_state() {
  if [[ -n "${TREE_SNAPSHOT}" ]]; then
    local committed="${TREE_SNAPSHOT%/*}/install-tree.done.${TREE_SNAPSHOT##*/install-tree.run.}"
    mv "${TREE_SNAPSHOT}" "${committed}"
    rm -rf "${committed}"
  fi
  TREE_SNAPSHOT=""
  SETTINGS_SNAPSHOT=""; SETTINGS_SAVED=false; RUN_BACKUP=""
}

# A run killed outright (SIGKILL, power loss) runs no trap and leaves its
# install-tree.run.* folder in backups/ with the tree moved aside and the old
# rows already gone. Put that before-state back before this run snapshots
# anything, or this run would save the half-installed state as its own
# before-state and orphan the old snapshot (OMN-23413 review).
recover_stale_run_state() {
  local run settings="${CLAUDE_SETTINGS}"
  if ! "${DRY_RUN}"; then
    for run in "${CLAUDE_SETTINGS_BACKUP_DIR}"/install-tree.done.*; do
      if [[ -d "${run}" && ! -L "${run}" ]]; then
        rm -rf "${run}"
      fi
    done
  fi
  for run in "${CLAUDE_SETTINGS_BACKUP_DIR}"/install-tree.run.*; do
    [[ -d "${run}" && ! -L "${run}" ]] || continue
    if "${DRY_RUN}"; then
      log_dry "would restore a stale run snapshot left by an interrupted run: ${run}"
      continue
    fi
    TREE_SNAPSHOT="${run}"
    SETTINGS_SNAPSHOT=""; SETTINGS_SAVED=false; SETTINGS_EXISTED=false
    if [[ -f "${run}/.settings.saved" ]]; then
      SETTINGS_SNAPSHOT="${run}/.settings.saved"; SETTINGS_SAVED=true; SETTINGS_EXISTED=true
    elif [[ -e "${run}/.settings.absent" ]]; then
      SETTINGS_SNAPSHOT="${run}/.settings.absent"; SETTINGS_SAVED=true
    fi
    # Write settings back to the profile that run edited, not this run's.
    CLAUDE_SETTINGS="${settings}"
    if [[ -f "${run}/.claude-settings" ]]; then
      CLAUDE_SETTINGS="$(<"${run}/.claude-settings")"
    fi
    RUN_BACKUP=""
    if [[ -f "${run}/.run-backup" ]]; then
      RUN_BACKUP="$(<"${run}/.run-backup")"
      # Only ever a backup this installer names; never a path from elsewhere.
      [[ "${RUN_BACKUP%/*}" == "${CLAUDE_SETTINGS_BACKUP_DIR}" && "${RUN_BACKUP##*/}" == settings.json.*.bak ]] || RUN_BACKUP=""
    fi
    restore_run_state
    log_warn "restored a stale run snapshot left by an interrupted run (${run}): ${CLAUDE_SETTINGS} and the delegation files in ${INSTALL_ROOT} are back to their state before that run."
    CLAUDE_SETTINGS="${settings}"
  done
}

# bash runs a trap only after the foreground command exits, so a signal sent
# while Claude's installer runs lands after Claude has finished. If Claude
# succeeded it has registered the plugin from the new tree: restoring the old
# tree then would leave that registration pointing at deleted files with no
# manifest. So while it runs a signal is only recorded; Claude's result decides
# and the signal is acted on after (exit_on_signals) (OMN-23413 review).
hold_signals() {
  trap 'PENDING_SIGNAL_STATUS=129' HUP
  trap 'PENDING_SIGNAL_STATUS=130' INT
  trap 'PENDING_SIGNAL_STATUS=143' TERM
}

# A signal becomes an exit, so the EXIT trap (on_install_exit) runs. A signal
# held by hold_signals is acted on now.
exit_on_signals() {
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  if [[ -n "${PENDING_SIGNAL_STATUS}" ]]; then
    log_err "stopped by a signal after Claude's plugin installer finished; the install and its rollback manifest are kept."
    exit "${PENDING_SIGNAL_STATUS}"
  fi
}

# Any exit before commit_run_state (an error under set -e, a signal) restores.
on_install_exit() {
  local status=$?
  if [[ -n "${TREE_SNAPSHOT}${SETTINGS_SNAPSHOT}" ]]; then
    restore_run_state
    log_err "install stopped (exit ${status}) before Claude's plugin installer finished; ${CLAUDE_SETTINGS} and the delegation files in ${INSTALL_ROOT} (hooks-delegation.json, plugin/, .claude-plugin/) are restored to their state before this run."
  fi
  return "${status}"
}

install_native_plugin() {
  if "${DRY_RUN}"; then
    log_dry "would install native delegation from ${INSTALL_ROOT} with Claude's plugin installer"
    return 0
  fi
  # Do not load runtime user/project preferences for a plugin ownership change:
  # Claude otherwise migrates unrelated model aliases (opus -> opus[1m]). Its
  # scoped plugin writer still preserves and updates the selected user profile.
  local status=0
  hold_signals
  claude --setting-sources "" plugin install onex-delegation --marketplace "${INSTALL_ROOT}" --scope user --json || status=$?
  if (( status != 0 )); then
    # merge_user_settings already removed the old owned rows and
    # install_hook_config replaced the tree they run from. Put both back byte
    # for byte, so a failed upgrade leaves the previous delegation in place
    # instead of none, and write no rollback manifest (OMN-23413 review).
    restore_run_state
    log_err "Claude's plugin installer failed (exit ${status}); ${CLAUDE_SETTINGS} and the delegation files in ${INSTALL_ROOT} (hooks-delegation.json, plugin/, .claude-plugin/) are restored to their state before this run, so the delegation installed before it is unchanged. Fix the error above and re-run."
    exit "${PENDING_SIGNAL_STATUS:-1}"
  fi
  commit_run_state
}

merge_user_settings() {
  log_step "merge delegation hooks into ${CLAUDE_SETTINGS}"
  # PRE_INSTALL_BACKUP holds the backup that captures state from BEFORE this
  # install ever ran. We only create it once — on the first --apply — and
  # subsequent runs (idempotent re-installs) do not overwrite it. The rollback
  # manifest below records this path so --uninstall can always reach the true
  # pre-install state.
  PRE_INSTALL_BACKUP=""
  if [[ -f "${ROLLBACK_MANIFEST}" ]]; then
    # Read prior backup path from manifest to preserve it.
    PRE_INSTALL_BACKUP="$("${PYTHON_BIN}" - "${ROLLBACK_MANIFEST}" <<'PY' 2>/dev/null || echo ""
import json, pathlib, sys
try:
    m = json.loads(pathlib.Path(sys.argv[1]).read_text())
    print(m.get("settings_backup") or "")
except Exception:
    print("")
PY
)"
  fi
  local backup_path="${PRE_INSTALL_BACKUP}"
  if [[ -z "${backup_path}" && -f "${CLAUDE_SETTINGS}" ]]; then
    backup_path="${CLAUDE_SETTINGS_BACKUP_DIR}/settings.json.$(date +%Y%m%dT%H%M%S).bak"
  fi

  if "${DRY_RUN}"; then
    if [[ -n "${backup_path}" && -z "${PRE_INSTALL_BACKUP}" ]]; then
      log_dry "would back up existing settings → ${backup_path}"
    elif [[ -n "${PRE_INSTALL_BACKUP}" ]]; then
      log_dry "would reuse pre-install backup at ${PRE_INSTALL_BACKUP}"
    else
      log_dry "would create new settings.json (none exists)"
    fi
    log_dry "would merge hooks block from ${INSTALL_HOOKS_JSON} (preserving existing hooks)"
    PRE_INSTALL_BACKUP="${backup_path}"
    return 0
  fi

  mkdir -p "$(dirname "${CLAUDE_SETTINGS}")"
  if [[ -n "${backup_path}" && -z "${PRE_INSTALL_BACKUP}" && -f "${CLAUDE_SETTINGS}" ]]; then
    printf '%s\n' "${backup_path}" > "${TREE_SNAPSHOT}/.run-backup"
    cp "${CLAUDE_SETTINGS}" "${backup_path}"
    RUN_BACKUP="${backup_path}"
    log_info "backed up existing settings → ${backup_path}"
    PRE_INSTALL_BACKUP="${backup_path}"
  fi
  # This run's own before-state (the backup above is the first install's), so
  # install_native_plugin can restore it exactly if Claude's installer fails.
  # Kept in the run's snapshot folder under a name that appears only once it
  # is whole, so a later run never restores a half-written copy.
  SETTINGS_EXISTED=false
  if [[ -f "${CLAUDE_SETTINGS}" ]]; then
    cp "${CLAUDE_SETTINGS}" "${TREE_SNAPSHOT}/.settings.part"
    mv "${TREE_SNAPSHOT}/.settings.part" "${TREE_SNAPSHOT}/.settings.saved"
    SETTINGS_SNAPSHOT="${TREE_SNAPSHOT}/.settings.saved"
    SETTINGS_EXISTED=true
  else
    : > "${TREE_SNAPSHOT}/.settings.absent"
    SETTINGS_SNAPSHOT="${TREE_SNAPSHOT}/.settings.absent"
  fi
  # Only now does the snapshot hold the before-state a restore may write back.
  SETTINGS_SAVED=true

  "${PYTHON_BIN}" - "${CLAUDE_SETTINGS}" "${INSTALL_HOOKS_JSON}" "${INSTALL_ROOT}" <<'PY'
import json, pathlib, sys
settings_path = pathlib.Path(sys.argv[1])
if not settings_path.exists():
    sys.exit(0)
settings = json.loads(settings_path.read_text(encoding="utf-8"))
if "hooks" not in settings:
    sys.exit(0)

# Remove earlier owned command hooks; the native plugin is registered by the
# vendor CLI. Preserve every unrelated hook and setting: the file is written
# only when an owned row was removed, and "hooks" itself is never added or
# dropped, so settings holding nothing of ours stay byte for byte the same.
existing = settings["hooks"]
removed = False
for event in list(existing):
    groups, changed = [], False
    for g in existing[event]:
        kept = [h for h in g.get("hooks", []) if f"{sys.argv[3]}/" not in (h.get("command") or "")]
        if len(kept) != len(g.get("hooks", [])):
            changed = True
            if not kept:
                continue
        groups.append({**g, "hooks": kept})
    if changed:
        removed = True
        existing[event] = groups
        if not groups:
            existing.pop(event)

# A whitespace-preserving JSON rewrite is not attempted: when an owned row is
# removed only the formatting changes (two-space indent). Values, non-ASCII
# included, are written as they were read, never escaped.
if removed:
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
PY
  log_ok "merged delegation hooks into ${CLAUDE_SETTINGS}"
}

write_rollback_manifest() {
  log_step "write rollback manifest (${ROLLBACK_MANIFEST})"
  if "${DRY_RUN}"; then
    log_dry "would record actions for --uninstall in ${ROLLBACK_MANIFEST}"
    return 0
  fi
  # Use the pre-install backup tracked in merge_user_settings; this stays
  # stable across idempotent re-runs so --uninstall always restores the true
  # pre-install state.
  "${PYTHON_BIN}" - "${ROLLBACK_MANIFEST}" "${INSTALL_ROOT}" "${CLAUDE_SETTINGS}" "${PRE_INSTALL_BACKUP:-}" "${INSTALL_HOOKS_JSON}" <<'PY'
import json, sys, pathlib, datetime
manifest_path, install_root, settings_path, backup_path, hooks_json = sys.argv[1:6]
manifest = pathlib.Path(manifest_path)
# Preserve created_at from prior manifest if present.
created_at = datetime.datetime.now(datetime.UTC).isoformat()
prior_backup = None
if manifest.exists():
    try:
        prior = json.loads(manifest.read_text())
        created_at = prior.get("created_at", created_at)
        prior_backup = prior.get("settings_backup")
    except Exception:
        pass
data = {
    "version": 1,
    "entrypoint": "native",
    "created_at": created_at,
    "install_root": install_root,
    "claude_settings": settings_path,
    "settings_backup": (backup_path or prior_backup) or None,
    "installed_hook_config": hooks_json,
    "package": "omninode-claude",
}
manifest.write_text(json.dumps(data, indent=2) + "\n")
PY
  log_ok "wrote rollback manifest"
}

run_smoke_test() {
  log_step "smoke test: open SQLite database"
  if "${SKIP_SMOKE}"; then
    log_info "--skip-smoke set: skipping smoke test"
    return 0
  fi
  if "${DRY_RUN}"; then
    log_dry "would open SQLite at ${INSTALL_DB} and write a test row"
    return 0
  fi
  # Use stdlib sqlite3 — independent of omniclaude package install state so the
  # smoke test exercises the install layout, not the package imports. Package
  # smoke is implicitly covered by the pip install step succeeding above.
  "${PYTHON_BIN}" - "${INSTALL_DB}" <<'PY'
import pathlib, sqlite3, sys
db = pathlib.Path(sys.argv[1])
db.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(db)
try:
    conn.execute("CREATE TABLE IF NOT EXISTS install_smoke_test (id INTEGER PRIMARY KEY, ts TEXT)")
    conn.execute("INSERT INTO install_smoke_test (ts) VALUES (datetime('now'))")
    conn.commit()
    rows = conn.execute("SELECT count(*) FROM install_smoke_test").fetchone()
    print(f"smoke test rows: {rows[0]}")
finally:
    conn.close()
PY
  log_ok "smoke test passed"
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

uninstall() {
  if [[ ! -f "${ROLLBACK_MANIFEST}" ]]; then
    log_err "no rollback manifest at ${ROLLBACK_MANIFEST}; nothing to roll back"
    exit 1
  fi
  log_step "rolling back via ${ROLLBACK_MANIFEST}"
  resolve_python
  local native
  native="$(native_plugin remove)"
  # The verdict is the last line the module prints, read as text: running it
  # as a command would run whatever else reached stdout (OMN-23413 review).
  native="${native##*$'\n'}"
  # Native removal is owned by the package handler. Only older command-hook
  # installs need the legacy consumer's exact-command rollback API, and they
  # still roll back where omnimarket is not installed (OMN-23413 review).
  if [[ "${native}" != true ]]; then
    "${PYTHON_BIN}" - "${ROLLBACK_MANIFEST}" "${PAUSE}" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
pause = sys.argv[2] == "true"

try:
    from omnimarket.nodes.node_onex_setup_effect.handlers.handler_setup_claude import HandlerSetupClaude
except ModuleNotFoundError as e:
    if not (e.name or "").startswith("omnimarket"):
        raise
    # Local copy: same exact-command removal the classic installer always did,
    # kept so a classic install rolls back where omnimarket is not installed.
    def rollback_hook_registration(manifest_path: Path, preserve_history: bool = False) -> str:
        """Remove exact installer-owned registrations, optionally retaining history."""
        manifest = json.loads(manifest_path.read_text())
        pause = preserve_history
        backup = manifest.get("settings_backup")
        settings = manifest.get("claude_settings")
        hooks_config = manifest.get("installed_hook_config")
        settings_path = Path(settings) if settings else None
        if settings_path is None:
            raise SystemExit("rollback manifest missing claude_settings")
        if not settings_path.exists():
            if backup and Path(backup).exists():
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                settings_path.write_text(Path(backup).read_text())
                return f"restored missing {settings} from {backup}"
            return ""
        current = json.loads(settings_path.read_text())
        hook_cfg = {}
        if hooks_config and Path(hooks_config).exists():
            hook_cfg = json.loads(Path(hooks_config).read_text()).get("hooks", {})
        delegation_commands = {
            hook.get("command")
            for groups in hook_cfg.values()
            for group in groups
            for hook in group.get("hooks", [])
            if hook.get("command")
            and not (pause and "--history-only" in hook["command"])
        }
        hooks = current.get("hooks", {})
        for event in list(hooks):
            filtered_groups = []
            for group in hooks.get(event, []):
                filtered_hooks = [
                    hook
                    for hook in group.get("hooks", [])
                    if hook.get("command") not in delegation_commands
                ]
                if filtered_hooks:
                    filtered_groups.append({**group, "hooks": filtered_hooks})
            if filtered_groups:
                hooks[event] = filtered_groups
            else:
                hooks.pop(event, None)
        if hooks:
            current["hooks"] = hooks
        else:
            current.pop("hooks", None)
        if current:
            settings_path.write_text(json.dumps(current, indent=2) + "\n")
            return f"removed delegation hooks from {settings}"
        settings_path.unlink()
        return f"removed {settings} after clearing installer-managed hooks"

    print(rollback_hook_registration(manifest_path, pause))
else:
    print(HandlerSetupClaude.rollback_hook_registration(manifest_path, pause))
PY
  fi
  if "${PAUSE}" && [[ "${native}" != true ]]; then
    log_ok "delegation paused; pending-history hook retained"
    return 0
  fi
  # Every owned path, .claude-plugin/ included: its marketplace.json names
  # ./plugin/plugins/onex, which is gone after this.
  local name
  for name in "${RUN_OWNED_PATHS[@]}"; do
    rm -rf "${INSTALL_ROOT:?}/${name}"
  done
  log_ok "removed installed hook config, scripts and marketplace metadata"
  log_info "preserved: ${INSTALL_DB} (delete manually to discard telemetry)"
  log_info "uninstall complete"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print_banner() {
  printf '\n%s=== ONEX Delegation Installer ===%s\n' "${C_BOLD}" "${C_RESET}"
  if "${DRY_RUN}"; then
    printf '%sMode:%s dry-run (preview only — pass --apply to execute)\n' "${C_BOLD}" "${C_RESET}"
  else
    printf '%sMode:%s APPLY\n' "${C_BOLD}" "${C_RESET}"
  fi
  printf '%sInstall root:%s %s\n' "${C_BOLD}" "${C_RESET}" "${INSTALL_ROOT}"
  printf '%sSource repo:%s  %s\n\n' "${C_BOLD}" "${C_RESET}" "${REPO_ROOT}"
}

print_next_steps() {
  cat <<EOF

${C_GREEN}${C_BOLD}Installation complete.${C_RESET}

  Database:       ${INSTALL_DB}
  Bifrost overlay: ${INSTALL_BIFROST_OVERLAY}
  Hook config:    ${INSTALL_HOOKS_JSON}
  Hook scripts:   ${INSTALL_SCRIPTS_DIR}
  Rollback:       ${ROLLBACK_MANIFEST}
  Settings:       ${CLAUDE_SETTINGS}

Next steps:
  1. Restart any running Claude Code sessions so the new hooks load.
  2. Open a new session — eligible prompts use native delegation output.
  3. Inspect telemetry:
       sqlite3 ${INSTALL_DB} '.tables'
  4. To roll back:
       bash $0 --uninstall

EOF
}

# One run at a time on an install root. Without this a second run reads the
# live run's install-tree.run.* folder as a stale one and restores it under the
# live run's feet. The lock is an flock on a file in the install root, held on
# fd 9 until the process exits (the kernel drops it on any exit, SIGKILL
# included, so a dead run never blocks the next). A dry run writes nothing and
# takes no lock. Known limit, not fixed: SIGKILL after Claude's installer has
# written its registry but before commit_run_state restores the old tree while
# Claude's registry already names the new plugin; the next run (or --uninstall)
# is what puts that right. Without flock(1) (macOS) runs are not serialised.
acquire_run_lock() {
  "${DRY_RUN}" && return 0
  if ! command -v flock >/dev/null 2>&1; then
    log_warn "flock is not installed; concurrent install-delegation runs are not prevented."
    return 0
  fi
  mkdir -p "${INSTALL_ROOT}"
  exec 9>>"${INSTALL_ROOT}/.install.lock"
  if ! flock -n 9; then
    log_err "another install-delegation run is in progress on ${INSTALL_ROOT}; wait for it to finish and re-run."
    exit 1
  fi
}

main() {
  print_banner
  acquire_run_lock
  recover_stale_run_state

  if "${UNINSTALL}" || "${PAUSE}"; then
    uninstall
    return 0
  fi

  log_step "prerequisite checks"
  check_claude_cli
  resolve_python
  check_source_files
  "${PYTHON_BIN}" - "${ROLLBACK_MANIFEST}" "${CLAUDE_SETTINGS}" <<'PY'
import json, pathlib, sys
manifest, settings = map(pathlib.Path, sys.argv[1:])
if manifest.exists():
    prior = json.loads(manifest.read_text()).get("claude_settings")
    if not prior or pathlib.Path(prior).resolve() != settings.resolve():
        raise SystemExit("Delegation belongs to another Claude profile; uninstall that profile before changing it.")
PY

  # From here until Claude's installer succeeds, any exit restores this run's
  # changes; the signal traps turn a signal into an exit so the EXIT trap runs.
  trap on_install_exit EXIT
  exit_on_signals
  ensure_install_dir
  install_python_package
  deploy_bifrost_contract
  install_hook_config
  merge_user_settings
  install_native_plugin
  write_rollback_manifest
  # Claude's installer has finished and the manifest is written: a signal held
  # while it ran is acted on now, with the install kept.
  exit_on_signals
  run_smoke_test

  if "${DRY_RUN}"; then
    printf '\n%sDry-run complete.%s Re-run with %s--apply%s to execute.\n' \
      "${C_YELLOW}${C_BOLD}" "${C_RESET}" "${C_BOLD}" "${C_RESET}"
  else
    print_next_steps
  fi
}

main "$@"
