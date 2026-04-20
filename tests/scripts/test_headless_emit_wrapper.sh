#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Unit test for scripts/headless-emit-wrapper.sh
#
# Verifies:
#   1. emit_task_event invokes kcat with the configured broker + topic and payload
#      (not docker exec — regression guard for OMN-9289).
#   2. Producer success returns 0 and does not write to the degraded log.
#   3. Producer failure appends an EMIT_FAILED line that preserves the stderr
#      cause so operators can debug without re-running.
#   4. Missing KAFKA_BOOTSTRAP_SERVERS fails fast with a descriptive cause
#      instead of a silent hang or bland error.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="${SCRIPT_DIR}/../../scripts/headless-emit-wrapper.sh"

[[ -f "${WRAPPER}" ]] || { echo "FAIL: wrapper missing at ${WRAPPER}"; exit 1; }

# Regression guard: the docker-exec path is what caused OMN-9289.
if grep -qE '^[[:space:]]*docker[[:space:]]+exec[[:space:]]+.*rpk' "${WRAPPER}"; then
  echo "FAIL: wrapper still uses 'docker exec ... rpk' (OMN-9289 regression)"
  exit 1
fi

# Sandbox: stub kcat on PATH, redirect degraded log to a tmp file.
TMPDIR_RUN="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_RUN}"' EXIT

STUB_BIN="${TMPDIR_RUN}/bin"
mkdir -p "${STUB_BIN}"

# -------- Case 1: producer success path --------
cat > "${STUB_BIN}/kcat" <<'STUB'
#!/usr/bin/env bash
# Record args + stdin payload for the test to assert against.
printf '%s\n' "$@" > "${KCAT_ARGS_FILE}"
cat > "${KCAT_PAYLOAD_FILE}"
exit 0
STUB
chmod +x "${STUB_BIN}/kcat"

export PATH="${STUB_BIN}:${PATH}"
export KAFKA_BOOTSTRAP_SERVERS="127.0.0.1:19092"
export HEADLESS_EMIT_LOG="${TMPDIR_RUN}/degraded.log"
export KCAT_ARGS_FILE="${TMPDIR_RUN}/args.txt"
export KCAT_PAYLOAD_FILE="${TMPDIR_RUN}/payload.txt"
export ONEX_RUN_ID="test-run-42"

unset _HEADLESS_EMIT_LOADED
# shellcheck source=/dev/null
source "${WRAPPER}"

emit_task_event "task-assigned" "OMN-9289" '"session_id": "s1"'

grep -q -- '-b' "${KCAT_ARGS_FILE}" || { echo "FAIL: kcat not invoked with -b"; exit 1; }
grep -q "127.0.0.1:19092" "${KCAT_ARGS_FILE}" || { echo "FAIL: broker not forwarded"; exit 1; }
grep -q "onex.evt.omniclaude.task-assigned.v1" "${KCAT_ARGS_FILE}" || { echo "FAIL: wrong topic"; exit 1; }
grep -q '"task_id": "OMN-9289"' "${KCAT_PAYLOAD_FILE}" || { echo "FAIL: task_id missing from payload"; exit 1; }
grep -q '"dispatch_surface": "headless_claude"' "${KCAT_PAYLOAD_FILE}" || { echo "FAIL: dispatch_surface missing"; exit 1; }
grep -q '"session_id": "s1"' "${KCAT_PAYLOAD_FILE}" || { echo "FAIL: extra_json not merged"; exit 1; }
[[ ! -s "${HEADLESS_EMIT_LOG}" ]] || { echo "FAIL: success path wrote to degraded log"; exit 1; }

# -------- Case 2: producer failure path preserves stderr cause --------
cat > "${STUB_BIN}/kcat" <<'STUB'
#!/usr/bin/env bash
echo "% ERROR: Local: Broker transport failure" >&2
exit 1
STUB
chmod +x "${STUB_BIN}/kcat"

: > "${HEADLESS_EMIT_LOG}"
unset _HEADLESS_EMIT_LOADED _HEADLESS_EMIT_FAIL_COUNT
# shellcheck source=/dev/null
source "${WRAPPER}"

stderr_output="$(emit_task_event "task-completed" "OMN-9289" 2>&1 >/dev/null)"

echo "${stderr_output}" | grep -q "EMIT_FAILED" || { echo "FAIL: failure path missing EMIT_FAILED marker"; exit 1; }
echo "${stderr_output}" | grep -q "Broker transport failure" || { echo "FAIL: failure path lost kcat stderr cause"; exit 1; }
grep -q "EMIT_FAILED" "${HEADLESS_EMIT_LOG}" || { echo "FAIL: degraded log missing EMIT_FAILED"; exit 1; }
grep -q "Broker transport failure" "${HEADLESS_EMIT_LOG}" || { echo "FAIL: degraded log missing cause"; exit 1; }

# -------- Case 3: missing broker env fails fast with a clear cause --------
unset KAFKA_BOOTSTRAP_SERVERS
: > "${HEADLESS_EMIT_LOG}"
unset _HEADLESS_EMIT_LOADED _HEADLESS_EMIT_FAIL_COUNT HEADLESS_EMIT_BROKERS
# shellcheck source=/dev/null
source "${WRAPPER}"

stderr_output="$(emit_task_event "task-assigned" "OMN-9289" 2>&1 >/dev/null)"
echo "${stderr_output}" | grep -q "KAFKA_BOOTSTRAP_SERVERS unset" || {
  echo "FAIL: missing-broker case should report KAFKA_BOOTSTRAP_SERVERS unset"
  exit 1
}

echo "PASS: tests/scripts/test_headless_emit_wrapper.sh"
