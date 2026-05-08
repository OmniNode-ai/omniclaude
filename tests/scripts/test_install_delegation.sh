#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Tests for install-delegation.sh [OMN-10626]:
#   1. --help prints usage and exits 0
#   2. options that require values fail clearly when missing values
#   3. mutually exclusive modes fail clearly
#   4. dry-run by default (no files created in sandbox HOME)
#   5. dry-run names every install step in its plan output
#   6. --apply creates the install layout in a sandbox HOME
#   7. --apply merges hooks into a pre-existing settings.json without dropping
#      existing entries, and stores a backup
#   8. --apply is idempotent (second run does not duplicate hook commands)
#   9. --uninstall removes installer-managed hooks without clobbering later
#      user settings
# Portable to bash 3.2 (macOS default) and bash 5+ (Linux CI).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INSTALL_SCRIPT="${REPO_ROOT}/scripts/install-delegation.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

[[ -x "${INSTALL_SCRIPT}" ]] || fail "install script missing or not executable: ${INSTALL_SCRIPT}"

TMPDIR_SANDBOX="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_SANDBOX}"' EXIT

SANDBOX_HOME="${TMPDIR_SANDBOX}/home"
mkdir -p "${SANDBOX_HOME}/.claude"

# Stub claude CLI so the prereq check passes.
STUB_BIN="${TMPDIR_SANDBOX}/bin"
mkdir -p "${STUB_BIN}"
cat > "${STUB_BIN}/claude" <<'EOF'
#!/usr/bin/env bash
echo "claude 1.0.0-stub"
EOF
chmod +x "${STUB_BIN}/claude"

PY_BIN="$(command -v python3)"
[[ -x "${PY_BIN}" ]] || fail "python3 not on PATH"

run_install() {
  HOME="${SANDBOX_HOME}" PATH="${STUB_BIN}:${PATH}" \
    bash "${INSTALL_SCRIPT}" --python "${PY_BIN}" "$@"
}

# --- Test 1: --help exits 0 and prints usage --------------------------------
HELP_OUT="$(run_install --help 2>&1)"
echo "${HELP_OUT}" | grep -q "Usage" || fail "--help must print usage (got: ${HELP_OUT})"
pass "--help exits 0 and prints usage"

# --- Test 2: options requiring values fail clearly --------------------------
set +e
MISSING_FROM_SOURCE_OUT="$(run_install --from-source 2>&1)"
MISSING_FROM_SOURCE_RC=$?
MISSING_PYTHON_OUT="$(run_install --python 2>&1)"
MISSING_PYTHON_RC=$?
set -e
[[ "${MISSING_FROM_SOURCE_RC}" -eq 2 ]] \
  || fail "--from-source without path must exit 2 (got ${MISSING_FROM_SOURCE_RC})"
echo "${MISSING_FROM_SOURCE_OUT}" | grep -q -- "--from-source requires a path" \
  || fail "--from-source missing value error not clear: ${MISSING_FROM_SOURCE_OUT}"
[[ "${MISSING_PYTHON_RC}" -eq 2 ]] \
  || fail "--python without interpreter must exit 2 (got ${MISSING_PYTHON_RC})"
echo "${MISSING_PYTHON_OUT}" | grep -q -- "--python requires an interpreter path" \
  || fail "--python missing value error not clear: ${MISSING_PYTHON_OUT}"
pass "missing option values fail clearly"

# --- Test 3: mutually exclusive modes fail clearly --------------------------
set +e
MUTEX_OUT="$(run_install --apply --uninstall 2>&1)"
MUTEX_RC=$?
set -e
[[ "${MUTEX_RC}" -eq 2 ]] \
  || fail "--apply --uninstall must exit 2 (got ${MUTEX_RC})"
echo "${MUTEX_OUT}" | grep -q -- "--apply and --uninstall are mutually exclusive" \
  || fail "--apply --uninstall error not clear: ${MUTEX_OUT}"
pass "mutually exclusive modes fail clearly"

# --- Test 4: dry-run does not create install root ---------------------------
rm -rf "${SANDBOX_HOME}/.omninode"
DRY_OUT="$(run_install 2>&1)" || fail "dry-run must exit 0"
[[ ! -d "${SANDBOX_HOME}/.omninode/delegation" ]] \
  || fail "dry-run must not create ${SANDBOX_HOME}/.omninode/delegation"
pass "dry-run does not create install root"

# --- Test 5: dry-run plan covers every step ---------------------------------
for needle in \
  "ensure install dirs" \
  "install Python package" \
  "install hook config" \
  "merge delegation hooks" \
  "write rollback manifest" \
  "smoke test"; do
  echo "${DRY_OUT}" | grep -q "${needle}" \
    || fail "dry-run plan missing step: ${needle}"
done
echo "${DRY_OUT}" | grep -qi "dry-run complete" \
  || fail "dry-run must print completion banner"
echo "${DRY_OUT}" | grep -q "pip install --user --upgrade '${PACKAGE_NAME:-omninode-claude}==" \
  || fail "dry-run should install package name by default, not repo path"
pass "dry-run plan covers every install step"

# --- Test 6: --apply creates the install layout in sandbox HOME -------------
# Write a pre-existing settings.json with an unrelated hook so we can prove
# the merge does not clobber it.
cat > "${SANDBOX_HOME}/.claude/settings.json" <<'EOF'
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "env": {"USER_VAR": "1"},
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "^Bash$",
        "hooks": [
          {"type": "command", "command": "/usr/local/bin/my-existing-hook.sh"}
        ]
      }
    ]
  }
}
EOF

# Run with --skip-pip so we don't need network or omninode-* packages to test
# the install layout. The pip install path is independently exercised in CI by
# the project's normal test suite (pyproject.toml install + import check).
run_install --apply --skip-pip >"${TMPDIR_SANDBOX}/apply.log" 2>&1 \
  || { cat "${TMPDIR_SANDBOX}/apply.log" >&2; fail "--apply must exit 0"; }

[[ -d "${SANDBOX_HOME}/.omninode/delegation" ]] || fail "install root not created"
[[ -f "${SANDBOX_HOME}/.omninode/delegation/hooks-delegation.json" ]] \
  || fail "hook config not written"
[[ -f "${SANDBOX_HOME}/.omninode/delegation/rollback-manifest.json" ]] \
  || fail "rollback manifest not written"
[[ -d "${SANDBOX_HOME}/.omninode/delegation/hook-scripts" ]] \
  || fail "hook scripts dir not created"
pass "--apply creates the install layout"

# --- Test 7: existing settings.json hooks are preserved + backed up ---------
"${PY_BIN}" - "${SANDBOX_HOME}/.claude/settings.json" <<'PY'
import json, pathlib, sys
data = json.loads(pathlib.Path(sys.argv[1]).read_text())
hooks = data.get("hooks", {})
pre = hooks.get("PreToolUse", [])
# Existing user hook must still be there.
existing_cmds = [
    h.get("command") for g in pre for h in g.get("hooks", [])
]
assert "/usr/local/bin/my-existing-hook.sh" in existing_cmds, (
    f"existing user hook lost during merge: {existing_cmds}"
)
# Delegation hook must have been added.
session_start = hooks.get("SessionStart", [])
ss_cmds = [
    h.get("command") for g in session_start for h in g.get("hooks", [])
]
assert any("session-start.sh" in (c or "") for c in ss_cmds), (
    f"delegation SessionStart hook missing after merge: {ss_cmds}"
)
PY
ls "${SANDBOX_HOME}/.omninode/delegation/backups"/settings.json.*.bak >/dev/null \
  || fail "settings.json backup not stored"
pass "settings.json merge preserves existing hooks + writes backup"

# --- Test 8: idempotent — second --apply does not duplicate hooks -----------
BEFORE_HASH="$(shasum "${SANDBOX_HOME}/.claude/settings.json" | awk '{print $1}')"
run_install --apply --skip-pip >"${TMPDIR_SANDBOX}/apply2.log" 2>&1 \
  || { cat "${TMPDIR_SANDBOX}/apply2.log" >&2; fail "second --apply must exit 0"; }
AFTER_HASH="$(shasum "${SANDBOX_HOME}/.claude/settings.json" | awk '{print $1}')"
[[ "${BEFORE_HASH}" == "${AFTER_HASH}" ]] \
  || fail "second --apply mutated settings.json (idempotency violated)"
pass "--apply is idempotent"

# Simulate a user edit made after installation. Uninstall must remove the
# installer-managed hooks without rolling the whole settings file back over
# this later user-owned state.
"${PY_BIN}" - "${SANDBOX_HOME}/.claude/settings.json" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
data = json.loads(p.read_text())
data.setdefault("env", {})["POST_INSTALL_USER_VAR"] = "keep-me"
data.setdefault("hooks", {}).setdefault("PostToolUse", []).append(
    {
        "matcher": "^Read$",
        "hooks": [
            {"type": "command", "command": "/usr/local/bin/post-install-user-hook.sh"}
        ],
    }
)
p.write_text(json.dumps(data, indent=2) + "\n")
PY

# --- Test 9: --uninstall preserves post-install user settings ---------------
run_install --uninstall >"${TMPDIR_SANDBOX}/uninstall.log" 2>&1 \
  || { cat "${TMPDIR_SANDBOX}/uninstall.log" >&2; fail "--uninstall must exit 0"; }
"${PY_BIN}" - "${SANDBOX_HOME}/.claude/settings.json" <<'PY'
import json, pathlib, sys
data = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert data.get("env", {}).get("POST_INSTALL_USER_VAR") == "keep-me", (
    f"post-install user env var lost after uninstall: {data.get('env', {})}"
)
hooks = data.get("hooks", {})
ss = hooks.get("SessionStart", [])
ss_cmds = [h.get("command") for g in ss for h in g.get("hooks", [])]
assert all("session-start.sh" not in (c or "") for c in ss_cmds), (
    f"delegation hook still present after uninstall: {ss_cmds}"
)
pre = hooks.get("PreToolUse", [])
pre_cmds = [h.get("command") for g in pre for h in g.get("hooks", [])]
assert "/usr/local/bin/my-existing-hook.sh" in pre_cmds, (
    f"original user hook lost after uninstall: {pre_cmds}"
)
post = hooks.get("PostToolUse", [])
post_cmds = [h.get("command") for g in post for h in g.get("hooks", [])]
assert "/usr/local/bin/post-install-user-hook.sh" in post_cmds, (
    f"post-install user hook lost after uninstall: {post_cmds}"
)
PY
[[ ! -f "${SANDBOX_HOME}/.omninode/delegation/hooks-delegation.json" ]] \
  || fail "uninstall must remove installed hook config"
pass "--uninstall preserves user settings + removes hook config"

echo ""
echo "ALL TESTS PASSED"
