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
#   3. Delegation hook config rewritten to point at the install location, copied
#      to ~/.omninode/delegation/hooks-delegation.json, AND merged into
#      ~/.claude/settings.json hooks block (existing hooks preserved + backed up)
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
INSTALL_SCRIPTS_DIR="${INSTALL_ROOT}/hook-scripts"
ROLLBACK_MANIFEST="${INSTALL_ROOT}/rollback-manifest.json"

CLAUDE_SETTINGS="${HOME}/.claude/settings.json"
CLAUDE_SETTINGS_BACKUP_DIR="${INSTALL_ROOT}/backups"

SOURCE_HOOK_CONFIG="${REPO_ROOT}/plugins/onex/hooks/hooks-delegation.v1.json"
SOURCE_HOOK_SCRIPTS="${REPO_ROOT}/plugins/onex/hooks/scripts"
PACKAGE_NAME="omninode-claude"

DRY_RUN=true
APPLY=false
UNINSTALL=false
FROM_SOURCE=""
PYTHON_BIN=""
SKIP_PIP=false
SKIP_SMOKE=false

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
  $0 [--apply | --uninstall] [--from-source <path>] [--python <bin>]

Options:
  --apply                 Execute changes (default is dry-run preview).
  --uninstall             Restore prior state using the rollback manifest.
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
  $0 --uninstall          Roll back the install.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)        APPLY=true; DRY_RUN=false; shift ;;
    --uninstall)    UNINSTALL=true; DRY_RUN=false; shift ;;
    --from-source)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        log_err "--from-source requires a path"
        usage >&2
        exit 2
      fi
      FROM_SOURCE="$2"
      shift 2
      ;;
    --python)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        log_err "--python requires an interpreter path"
        usage >&2
        exit 2
      fi
      PYTHON_BIN="$2"
      shift 2
      ;;
    --skip-pip)     SKIP_PIP=true; shift ;;
    --skip-smoke)   SKIP_SMOKE=true; shift ;;
    -h|--help)      usage; exit 0 ;;
    *)              log_err "unknown argument: $1"; usage >&2; exit 2 ;;
  esac
done

if "${APPLY}" && "${UNINSTALL}"; then
  log_err "--apply and --uninstall are mutually exclusive"
  usage >&2
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
  if [[ -d "${INSTALL_ROOT}" ]]; then
    log_info "exists: ${INSTALL_ROOT}"
  else
    run_or_dry mkdir -p "${INSTALL_ROOT}"
  fi
  run_or_dry mkdir -p "${INSTALL_SCRIPTS_DIR}" "${CLAUDE_SETTINGS_BACKUP_DIR}"
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

install_hook_config() {
  log_step "install hook config to ${INSTALL_HOOKS_JSON}"
  # Rewrite ${CLAUDE_PLUGIN_ROOT} → INSTALL_ROOT so hook commands work outside
  # the plugin context.
  if "${DRY_RUN}"; then
    log_dry "would rewrite \${CLAUDE_PLUGIN_ROOT}/hooks/scripts/* → ${INSTALL_SCRIPTS_DIR}/*"
    log_dry "would copy hook scripts: ${SOURCE_HOOK_SCRIPTS} → ${INSTALL_SCRIPTS_DIR}"
    return 0
  fi
  # Copy hook scripts referenced by hooks-delegation.v1.json.
  local script
  for script in session-start.sh session-end.sh pre_tool_use_delegation.sh \
                post_tool_use_cost_accounting.sh user_prompt_delegation_classifier.sh; do
    if [[ -f "${SOURCE_HOOK_SCRIPTS}/${script}" ]]; then
      cp "${SOURCE_HOOK_SCRIPTS}/${script}" "${INSTALL_SCRIPTS_DIR}/${script}"
      chmod +x "${INSTALL_SCRIPTS_DIR}/${script}"
    else
      log_warn "hook script missing in source: ${script} (skipped)"
    fi
  done
  # Rewrite the JSON so commands point at INSTALL_SCRIPTS_DIR.
  "${PYTHON_BIN}" - "${SOURCE_HOOK_CONFIG}" "${INSTALL_HOOKS_JSON}" "${INSTALL_SCRIPTS_DIR}" "${INSTALL_ROOT}" <<'PY'
import json, sys, pathlib
src, dst, scripts_dir, install_root = sys.argv[1:5]
data = json.loads(pathlib.Path(src).read_text())
def rewrite(value):
    if isinstance(value, str):
        # The source uses "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/<name>". Rewrite
        # it to point at the standalone install dir, taking care not to double
        # up the "scripts" path segment.
        v = value.replace("${CLAUDE_PLUGIN_ROOT}/hooks/scripts", scripts_dir)
        v = v.replace("${CLAUDE_PLUGIN_ROOT}", install_root)
        return v
    if isinstance(value, list):
        return [rewrite(v) for v in value]
    if isinstance(value, dict):
        return {k: rewrite(v) for k, v in value.items()}
    return value
pathlib.Path(dst).write_text(json.dumps(rewrite(data), indent=2) + "\n")
PY
  log_ok "wrote ${INSTALL_HOOKS_JSON}"
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
    cp "${CLAUDE_SETTINGS}" "${backup_path}"
    log_info "backed up existing settings → ${backup_path}"
    PRE_INSTALL_BACKUP="${backup_path}"
  fi

  "${PYTHON_BIN}" - "${CLAUDE_SETTINGS}" "${INSTALL_HOOKS_JSON}" <<'PY'
import json, pathlib, sys
settings_path = pathlib.Path(sys.argv[1])
hooks_path = pathlib.Path(sys.argv[2])
hook_cfg = json.loads(hooks_path.read_text())
delegation_hooks = hook_cfg.get("hooks", {})

if settings_path.exists():
    settings = json.loads(settings_path.read_text())
else:
    settings = {}

existing = settings.setdefault("hooks", {})
# Merge per-event arrays without duplicating commands already present.
for event, new_groups in delegation_hooks.items():
    cur_groups = existing.setdefault(event, [])
    existing_cmds = set()
    for group in cur_groups:
        for hook in group.get("hooks", []):
            cmd = hook.get("command")
            if cmd:
                existing_cmds.add(cmd)
    for group in new_groups:
        filtered_hooks = [h for h in group.get("hooks", []) if h.get("command") not in existing_cmds]
        if filtered_hooks:
            new_group = {**group, "hooks": filtered_hooks}
            cur_groups.append(new_group)

settings_path.write_text(json.dumps(settings, indent=2) + "\n")
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
  "${PYTHON_BIN}" - "${ROLLBACK_MANIFEST}" <<'PY'
import json, pathlib, sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text())
backup = manifest.get("settings_backup")
settings = manifest.get("claude_settings")
hooks_config = manifest.get("installed_hook_config")
settings_path = pathlib.Path(settings) if settings else None
if settings_path is None:
    raise SystemExit("rollback manifest missing claude_settings")
if not settings_path.exists():
    if backup and pathlib.Path(backup).exists():
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(pathlib.Path(backup).read_text())
        print(f"restored missing {settings} from {backup}")
    raise SystemExit(0)
current = json.loads(settings_path.read_text())
hook_cfg = {}
if hooks_config and pathlib.Path(hooks_config).exists():
    hook_cfg = json.loads(pathlib.Path(hooks_config).read_text()).get("hooks", {})
delegation_commands = {
    hook.get("command")
    for groups in hook_cfg.values()
    for group in groups
    for hook in group.get("hooks", [])
    if hook.get("command")
}
hooks = current.get("hooks", {})
for event in list(hooks):
    filtered_groups = []
    for group in hooks.get(event, []):
        filtered_hooks = [
            hook for hook in group.get("hooks", [])
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
    print(f"removed delegation hooks from {settings}")
else:
    settings_path.unlink()
    print(f"removed {settings} after clearing installer-managed hooks")
PY
  rm -f "${INSTALL_HOOKS_JSON}"
  rm -rf "${INSTALL_SCRIPTS_DIR}"
  log_ok "removed installed hook config + scripts"
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
  Hook config:    ${INSTALL_HOOKS_JSON}
  Hook scripts:   ${INSTALL_SCRIPTS_DIR}
  Rollback:       ${ROLLBACK_MANIFEST}
  Settings:       ${CLAUDE_SETTINGS}

Next steps:
  1. Restart any running Claude Code sessions so the new hooks load.
  2. Open a new session — delegation hooks fire on Agent/Task tool use.
  3. Inspect telemetry:
       sqlite3 ${INSTALL_DB} '.tables'
  4. To roll back:
       bash $0 --uninstall

EOF
}

main() {
  print_banner

  if "${UNINSTALL}"; then
    uninstall
    return 0
  fi

  log_step "prerequisite checks"
  check_claude_cli
  resolve_python
  check_source_files

  ensure_install_dir
  install_python_package
  install_hook_config
  merge_user_settings
  write_rollback_manifest
  run_smoke_test

  if "${DRY_RUN}"; then
    printf '\n%sDry-run complete.%s Re-run with %s--apply%s to execute.\n' \
      "${C_YELLOW}${C_BOLD}" "${C_RESET}" "${C_BOLD}" "${C_RESET}"
  else
    print_next_steps
  fi
}

main "$@"
