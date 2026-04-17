#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Tests for tick-bundle-install.sh [OMN-9056]:
#   1. Every label in TICKS has a matching template under scripts/launchd/.
#   2. Every template's ProgramArguments[0] resolves to an existing executable
#      after __OMNI_HOME__ expansion.
#   3. The buildloop template exists and invokes cron-closeout.sh --build-only
#      (not the deprecated cron-buildloop.sh).
#   4. The post-install verifier rejects a rendered plist whose
#      ProgramArguments[0] does not exist (fail-fast).
# Portable to bash 3.2 (macOS default) and bash 5+ (Linux CI).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INSTALL_SCRIPT="${REPO_ROOT}/scripts/tick-bundle-install.sh"
LAUNCHD_SRC="${REPO_ROOT}/scripts/launchd"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

# --- Test 1: TICKS array and templates line up ------------------------------
LABELS_RAW="$(
  awk '/^TICKS=\(/{flag=1; next} /^\)/{flag=0} flag{gsub(/[ \t"]/,""); if ($0 != "") print}' \
    "${INSTALL_SCRIPT}"
)"
LABEL_COUNT="$(printf '%s\n' "${LABELS_RAW}" | grep -c . || true)"
[ "${LABEL_COUNT}" -ge 6 ] || fail "TICKS array has ${LABEL_COUNT} entries; expected >=6 (5 original + buildloop)"
pass "TICKS array has ${LABEL_COUNT} entries"

while IFS= read -r label; do
  [ -z "${label}" ] && continue
  tmpl="${LAUNCHD_SRC}/${label}.plist"
  [ -f "${tmpl}" ] || fail "template missing for TICKS entry: ${label} (expected ${tmpl})"
done <<< "${LABELS_RAW}"
pass "every TICKS label has a matching template in ${LAUNCHD_SRC}/"

printf '%s\n' "${LABELS_RAW}" | grep -qx "ai.omninode.buildloop" \
  || fail "ai.omninode.buildloop is NOT in TICKS — OMN-9056 regression"
pass "ai.omninode.buildloop is registered in TICKS"

# --- Test 2: every template's ProgramArguments[0] exists + is executable ----
OMNI_HOME_RESOLVED="$(cd "${REPO_ROOT}/.." && pwd)"
HOME_RESOLVED="${HOME}"

for tmpl in "${LAUNCHD_SRC}"/*.plist; do
  label="$(basename "${tmpl}" .plist)"
  rendered="$(
    sed \
      -e "s|__OMNI_HOME__|${OMNI_HOME_RESOLVED}|g" \
      -e "s|__HOME__|${HOME_RESOLVED}|g" \
      "${tmpl}"
  )"
  prog="$(
    echo "${rendered}" \
      | awk '/<key>ProgramArguments<\/key>/{flag=1; next} flag && /<string>/{gsub(/.*<string>|<\/string>.*/, ""); print; exit}'
  )"
  [ -n "${prog}" ] || fail "[${label}] could not extract ProgramArguments[0]"
  # The rendered path may include argv tail (e.g. "--build-only"); take field 1.
  prog_path="$(printf '%s' "${prog}" | awk '{print $1}')"
  [ -x "${prog_path}" ] || fail "[${label}] ProgramArguments[0] not executable: ${prog_path}"
done
pass "every rendered ProgramArguments[0] exists + is executable"

# --- Test 3: buildloop template invokes closeout --build-only ---------------
BUILDLOOP_TMPL="${LAUNCHD_SRC}/ai.omninode.buildloop.plist"
[ -f "${BUILDLOOP_TMPL}" ] || fail "buildloop template missing at ${BUILDLOOP_TMPL}"

# Only inspect executable <string> entries (ignore documentation comments).
BUILDLOOP_RENDERED="$(
  sed \
    -e "s|__OMNI_HOME__|${OMNI_HOME_RESOLVED}|g" \
    -e "s|__HOME__|${HOME_RESOLVED}|g" \
    "${BUILDLOOP_TMPL}"
)"
BUILDLOOP_PROG_ARGS="$(
  echo "${BUILDLOOP_RENDERED}" \
    | awk '/<key>ProgramArguments<\/key>/{flag=1; next} flag && /<\/array>/{flag=0} flag'
)"
echo "${BUILDLOOP_PROG_ARGS}" | grep -q "cron-closeout.sh" \
  || fail "buildloop ProgramArguments must invoke cron-closeout.sh (cron-buildloop.sh is deprecated)"
echo "${BUILDLOOP_PROG_ARGS}" | grep -q -- "--build-only" \
  || fail "buildloop ProgramArguments must pass --build-only to cron-closeout.sh"
if echo "${BUILDLOOP_PROG_ARGS}" | grep -q "cron-buildloop.sh"; then
  fail "buildloop ProgramArguments must NOT invoke the deprecated cron-buildloop.sh"
fi
pass "buildloop template correctly invokes cron-closeout.sh --build-only"

# --- Test 4: post-install verifier rejects a plist with a missing path ------
TMPDIR_SANDBOX="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_SANDBOX}"' EXIT

SANDBOX_SRC="${TMPDIR_SANDBOX}/launchd"
SANDBOX_HOME="${TMPDIR_SANDBOX}/home"
mkdir -p "${SANDBOX_SRC}" "${SANDBOX_HOME}/Library/LaunchAgents"

cat > "${SANDBOX_SRC}/ai.test.broken.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.test.broken</string>
  <key>ProgramArguments</key>
  <array><string>/nonexistent/does-not-exist.sh</string></array>
  <key>StartInterval</key><integer>3600</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/usr/bin:/bin</string>
    <key>HOME</key><string>__HOME__</string>
    <key>OMNI_HOME</key><string>__OMNI_HOME__</string>
  </dict>
  <key>KeepAlive</key><false/>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
EOF

SANDBOX_INSTALL="${TMPDIR_SANDBOX}/tick-bundle-install.sh"
sed \
  -e "s|LAUNCHD_SRC=.*|LAUNCHD_SRC=\"${SANDBOX_SRC}\"|" \
  -e "s|LAUNCH_AGENTS=.*|LAUNCH_AGENTS=\"${SANDBOX_HOME}/Library/LaunchAgents\"|" \
  "${INSTALL_SCRIPT}" > "${SANDBOX_INSTALL}"
python3 - "${SANDBOX_INSTALL}" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1])
src = p.read_text()
src = re.sub(r"TICKS=\([^)]*\)", 'TICKS=(\n  "ai.test.broken"\n)', src, count=1)
p.write_text(src)
PY
chmod +x "${SANDBOX_INSTALL}"

# Use --dry-run so we don't call launchctl; verifier still runs pre-install.
if OMNI_HOME="${OMNI_HOME_RESOLVED}" HOME="${SANDBOX_HOME}" \
     bash "${SANDBOX_INSTALL}" --dry-run >"${TMPDIR_SANDBOX}/out.log" 2>&1; then
  cat "${TMPDIR_SANDBOX}/out.log" >&2
  fail "installer must exit non-zero when a rendered plist has a missing ProgramArguments[0]"
fi
grep -q "ProgramArguments" "${TMPDIR_SANDBOX}/out.log" \
  || fail "installer failure output must mention ProgramArguments (got: $(cat "${TMPDIR_SANDBOX}/out.log"))"
pass "installer fails fast when ProgramArguments[0] is missing"

echo ""
echo "ALL TESTS PASSED"
