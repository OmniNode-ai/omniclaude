#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Test suite for scripts/deploy-gate/checkout-occ-contracts.sh [OMN-12564].
#
# Proves the OCC partial-clone checkout is bounded and self-diagnosing:
#   - a forced stall (injected slow/blocked git fetch) terminates at the
#     configured timeout, not an indefinite spin;
#   - on failure the script emits the full diagnostic block (OCC ref, exact
#     fetch command, elapsed time, last git subprocess, process/subprocess
#     tree) so future hangs are diagnosable from the job log alone;
#   - a successful checkout (fake git that populates contracts) exits 0.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SUT="${REPO_ROOT}/scripts/deploy-gate/checkout-occ-contracts.sh"

FAILURES=0
fail() {
  echo "FAIL: $*" >&2
  FAILURES=$((FAILURES + 1))
}
pass() {
  echo "PASS: $*"
}

[ -f "$SUT" ] || {
  echo "FAIL: system under test missing: $SUT" >&2
  exit 1
}

# ---------------------------------------------------------------------------
# Shared scratch + a fake `git` shim dir placed first on PATH.
# ---------------------------------------------------------------------------
make_fake_git() {
  # $1 = behavior: "hang" | "ok"
  local behavior="$1"
  local bindir
  bindir="$(mktemp -d)"
  cat >"${bindir}/git" <<FAKE
#!/usr/bin/env bash
# Fake git shim for OCC checkout tests. Behavior=${behavior}
# Forward the no-op plumbing commands (init/remote/sparse-checkout) to real git
# so the working tree is set up, but intercept fetch/checkout.
REAL_GIT="\$(PATH="${PATH_WITHOUT_SHIM}" command -v git)"

# Find the subcommand (skip global -C <dir> and -c k=v options).
sub=""
args=("\$@")
i=0
while [ \$i -lt \${#args[@]} ]; do
  a="\${args[\$i]}"
  case "\$a" in
    -C) i=\$((i + 2)); continue ;;
    -c) i=\$((i + 2)); continue ;;
    -*) i=\$((i + 1)); continue ;;
    *) sub="\$a"; break ;;
  esac
done

# behavior is baked in at shim-generation time (literal substitution below).
case "${behavior}:\$sub" in
  hang:fetch)
    # Simulate a wedged filtered fetch / index-pack loop: sleep far past the
    # script's fetch timeout. The script must kill us via its own timeout.
    sleep 600
    exit 0
    ;;
  ok:fetch)
    exit 0
    ;;
  ok:checkout)
    # Populate the contracts dir to mimic a successful checkout. The -C dir is
    # args[1] when invoked as: git -C <dir> checkout ...
    target="\${args[1]:-.}"
    mkdir -p "\${target}/contracts"
    : >"\${target}/contracts/OMN-0000.yaml"
    exit 0
    ;;
  *)
    exec "\$REAL_GIT" "\$@"
    ;;
esac
FAKE
  chmod +x "${bindir}/git"
  echo "$bindir"
}

PATH_WITHOUT_SHIM="$PATH"
export PATH_WITHOUT_SHIM

# ---------------------------------------------------------------------------
# Case 1: forced stall terminates at the timeout (bounded, not infinite) and
#         emits the diagnostic block.
# ---------------------------------------------------------------------------
run_stall_case() {
  local work bindir start elapsed out rc
  work="$(mktemp -d)"
  bindir="$(make_fake_git hang)"

  start="$(date +%s)"
  out="$(
    cd "$work" &&
      OCC_REF="dev" \
      OCC_REPO_URL="https://example.invalid/onex_change_control.git" \
      OCC_FETCH_TIMEOUT_SECS=3 \
      OCC_MAX_ATTEMPTS=1 \
      OCC_RETRY_BACKOFF_SECS=0 \
      GH_TOKEN="x" \
      PATH="${bindir}:${PATH}" \
      bash "$SUT" 2>&1
  )"
  rc=$?
  elapsed=$(($(date +%s) - start))

  rm -rf "$bindir"

  # Must FAIL (non-zero) — the stall cannot succeed.
  if [ "$rc" -eq 0 ]; then
    fail "stall case: expected non-zero exit, got 0"
  else
    pass "stall case: non-zero exit ($rc)"
  fi

  # Must be BOUNDED: well under the 600s fake sleep. Allow generous slack for
  # the 3s fetch timeout + diagnostics overhead.
  if [ "$elapsed" -lt 60 ]; then
    pass "stall case: bounded (elapsed=${elapsed}s < 60s)"
  else
    fail "stall case: not bounded (elapsed=${elapsed}s >= 60s — likely spun)"
  fi

  # Must emit the diagnostic block fields.
  echo "$out" | grep -q "OCC checkout diagnostics" || fail "stall case: missing diagnostic header; got: $out"
  echo "$out" | grep -q "OCC ref:" || fail "stall case: missing 'OCC ref:' line"
  echo "$out" | grep -q "Fetch command:" || fail "stall case: missing 'Fetch command:' line"
  echo "$out" | grep -q "Elapsed:" || fail "stall case: missing 'Elapsed:' line"
  echo "$out" | grep -q "Last git subprocess:" || fail "stall case: missing 'Last git subprocess:' line"
  echo "$out" | grep -q "Process tree" || fail "stall case: missing 'Process tree' block"
  # Confirm it actually tripped the timeout (not some other failure).
  echo "$out" | grep -qi "timed out\|timeout" || fail "stall case: no timeout indication in output"
  pass "stall case: diagnostic block emitted"
}

# ---------------------------------------------------------------------------
# Case 2: successful checkout exits 0 and leaves contracts/ in place.
# ---------------------------------------------------------------------------
run_success_case() {
  local work bindir out rc
  work="$(mktemp -d)"
  bindir="$(make_fake_git ok)"

  out="$(
    cd "$work" &&
      OCC_REF="dev" \
      OCC_REPO_URL="https://example.invalid/onex_change_control.git" \
      OCC_FETCH_TIMEOUT_SECS=30 \
      OCC_MAX_ATTEMPTS=1 \
      OCC_RETRY_BACKOFF_SECS=0 \
      GH_TOKEN="x" \
      PATH="${bindir}:${PATH}" \
      bash "$SUT" 2>&1
  )"
  rc=$?

  rm -rf "$bindir"

  if [ "$rc" -eq 0 ]; then
    pass "success case: exit 0"
  else
    fail "success case: expected 0, got $rc; out: $out"
  fi
  if [ -d "${work}/_occ/contracts" ]; then
    pass "success case: _occ/contracts present"
  else
    fail "success case: _occ/contracts missing"
  fi
  rm -rf "$work"
}

# ---------------------------------------------------------------------------
# Case 3: deterministic full-ref checkout — the script must NOT use a
#         lazy blob filter that can re-trigger fetches during checkout.
# ---------------------------------------------------------------------------
run_no_lazy_filter_case() {
  # Inspect only executable lines (strip whole-line comments). The blobless
  # partial-clone filter is what lets checkout re-enter a lazy fetch loop, so it
  # must not appear in any active git command — comments explaining its removal
  # are fine.
  local active
  active="$(grep -vE '^[[:space:]]*#' "$SUT")"
  if printf '%s\n' "$active" | grep -q -- "--filter=blob:none"; then
    fail "no-lazy-filter case: script still uses --filter=blob:none in an active command"
  else
    pass "no-lazy-filter case: no active --filter=blob:none lazy fetch"
  fi
}

run_stall_case
run_success_case
run_no_lazy_filter_case

if [ "$FAILURES" -eq 0 ]; then
  echo "ALL TESTS PASSED"
  exit 0
fi
echo "TESTS FAILED: ${FAILURES}"
exit 1
