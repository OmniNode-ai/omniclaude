#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-18841 — the status line's open-PR segment must never render a failed
# refresh as absence.
#
# The defect: every `gh pr list` failure was coerced to "0/0" with stderr
# discarded, and the renderer drops a repo whose counts are both zero, so a
# fleet-wide refusal and "no open PRs anywhere" produced byte-identical output
# — nothing at all. Operating Rule 16's false zero, in the status line.
#
# This suite drives the real script. It never touches the network: `gh` is
# stubbed on PATH and every service host points at a closed local port.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# STATUSLINE_UNDER_TEST lets a RED proof point this suite at a pre-fix copy of
# the script (git show origin/dev:<path> > file) without touching the tree.
STATUSLINE="${STATUSLINE_UNDER_TEST:-$REPO_ROOT/plugins/onex/hooks/scripts/statusline.sh}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FAILURES=0
pass() { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; FAILURES=$((FAILURES + 1)); }

# --- harness ---------------------------------------------------------------

# Service probes must resolve instantly and never reach the LAN.
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=1
export VALKEY_HOST=127.0.0.1 VALKEY_PORT=1
export KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:1
export OMNICLAUDE_MODE=full

make_gh_stub() {
  # $1 = mode: ok | fail_all | graphql_fail_rest_ok | absent
  local mode="$1"
  local dir="$WORK/bin.$mode"
  mkdir -p "$dir"
  [ "$mode" = "absent" ] && { printf '%s' "$dir"; return; }
  cat > "$dir/gh" <<STUB
#!/bin/bash
mode="$mode"
case "\$1" in
  pr)  [ "\$mode" = "ok" ] && { echo '["dev","dev","main"]'; exit 0; }; exit 1 ;;
  api) case "\$mode" in
         ok|graphql_fail_rest_ok) echo '["main","dev"]'; exit 0 ;;
         *) exit 1 ;;
       esac ;;
esac
exit 1
STUB
  chmod +x "$dir/gh"
  printf '%s' "$dir"
}

# render <cache-file> [extra-PATH-dir] -> line 3, ANSI stripped
render() {
  local cache="$1" binreal="${2:-}" out
  out=$(
    PATH="${binreal:+$binreal:}$PATH" \
    ONEX_STATUSLINE_PR_CACHE="$cache" \
    bash "$STATUSLINE" <<< '{"workspace":{"project_dir":"'"$REPO_ROOT"'"},"model":{"id":"t","display_name":"T"},"context_window":{}}' 2>/dev/null
  )
  printf '%s' "$out" | tail -1 | LC_ALL=C sed $'s/\033\\[[0-9;]*m//g'
}

# wait_for_cache <file> <seconds> — the refresh runs in a background subshell
wait_for_cache() {
  local f="$1" n=$(( ${2:-15} * 4 ))
  while [ "$n" -gt 0 ]; do
    [ -s "$f" ] && jq empty < "$f" 2>/dev/null && return 0
    sleep 0.25; n=$((n - 1))
  done
  return 1
}

fixture() { printf '%s' "$2" > "$1"; touch "$1"; }

COUNTS_JSON='{"schema":2,"refreshed_at":9999999999,"status":"ok","failed":[],"repos":{"core":"0/2","infra":"1/14","spi":"0/0","claude":"0/0","node":"0/0","dash":"0/0","intel":"0/0","mem":"0/0","web":"0/0","cc":"0/0","market":"0/0"}}'
FAILED_JSON='{"schema":2,"refreshed_at":9999999999,"status":"degraded","failed":["core","infra","spi","claude","node","dash","intel","mem","web","cc","market"],"repos":{"core":"err","infra":"err","spi":"err","claude":"err","node":"err","dash":"err","intel":"err","mem":"err","web":"err","cc":"err","market":"err"}}'
ZERO_JSON='{"schema":2,"refreshed_at":9999999999,"status":"ok","failed":[],"repos":{"core":"0/0","infra":"0/0","spi":"0/0","claude":"0/0","node":"0/0","dash":"0/0","intel":"0/0","mem":"0/0","web":"0/0","cc":"0/0","market":"0/0"}}'

echo "OMN-18841 statusline open-PR segment"

# --- AC2: three fixture caches, three distinct non-empty segments -----------

echo "AC2 — a failed refresh, a genuine zero and real counts each render distinctly"

C_COUNTS="$WORK/counts.json"; fixture "$C_COUNTS" "$COUNTS_JSON"
C_FAILED="$WORK/failed.json"; fixture "$C_FAILED" "$FAILED_JSON"
C_ZERO="$WORK/zero.json";     fixture "$C_ZERO"   "$ZERO_JSON"
NOGH="$(make_gh_stub absent)"

R_COUNTS="$(render "$C_COUNTS" "$NOGH")"
R_FAILED="$(render "$C_FAILED" "$NOGH")"
R_ZERO="$(render "$C_ZERO" "$NOGH")"

case "$R_COUNTS" in
  *"PRs(main/dev):"*"core·0/2"*"infra·1/14"*) pass "counts render" ;;
  *) fail "counts render" "got: $R_COUNTS" ;;
esac

case "$R_FAILED" in
  *"PRs(main/dev):"*"unreachable"*) pass "a failed refresh renders a visible marker" ;;
  *) fail "a failed refresh renders a visible marker" "got: $R_FAILED" ;;
esac

case "$R_ZERO" in
  *"PRs(main/dev):"*"none open"*) pass "a genuine fleet-wide zero renders visibly" ;;
  *) fail "a genuine fleet-wide zero renders visibly" "got: $R_ZERO" ;;
esac

if [ "$R_FAILED" != "$R_ZERO" ]; then
  pass "failure and genuine zero are distinguishable"
else
  fail "failure and genuine zero are distinguishable" "both: $R_ZERO"
fi

# The original defect, stated as an assertion: neither case may be absent.
for name in R_FAILED R_ZERO; do
  case "${!name}" in
    *"PRs(main/dev):"*) pass "segment present ($name)" ;;
    *) fail "segment present ($name)" "segment absent: ${!name}" ;;
  esac
done

# A cold cache (the post-reboot case) still names the segment.
R_COLD="$(render "$WORK/does-not-exist.json" "$NOGH")"
case "$R_COLD" in
  *"PRs(main/dev):"*) pass "a cold cache renders a pending segment, not absence" ;;
  *) fail "a cold cache renders a pending segment, not absence" "got: $R_COLD" ;;
esac

# --- portability: a GNU-coreutils stat must not blank the segment ----------
#
# `stat -f` is "format" on BSD and "filesystem status" on GNU, where it SUCCEEDS
# and prints a mount point. The BSD-first probe therefore fed "/" into the
# freshness arithmetic on Linux, and the resulting syntax error aborted the rest
# of the section, leaving line 3 empty — this segment disappearing again, by a
# second route. This is the case CI caught that a macOS-only run cannot.

echo "portability — a GNU-style stat does not blank the segment"

GNUSTAT="$WORK/bin.gnustat"
mkdir -p "$GNUSTAT"
cat > "$GNUSTAT/stat" <<'GSTUB'
#!/bin/bash
# GNU semantics: -f is filesystem status (%m = mount point), -c is file format.
if [ "$1" = "-f" ]; then echo "/"; exit 0; fi
exec /usr/bin/stat "$@"
GSTUB
chmod +x "$GNUSTAT/stat"

R_GNU="$(render "$C_COUNTS" "$GNUSTAT")"
case "$R_GNU" in
  *"PRs(main/dev):"*) pass "a GNU-style stat still renders the segment" ;;
  *) fail "a GNU-style stat still renders the segment" "got: $R_GNU" ;;
esac

# --- AC1: the producer records a per-repo sentinel and a status field -------

echo "AC1 — the cache distinguishes a failed repo from a repo with no open PRs"

C_PROD_FAIL="$WORK/prod-fail.json"
GH_FAIL="$(make_gh_stub fail_all)"
PATH="$GH_FAIL:$PATH" ONEX_STATUSLINE_PR_CACHE="$C_PROD_FAIL" \
  bash "$STATUSLINE" <<< '{"workspace":{"project_dir":"'"$REPO_ROOT"'"},"model":{},"context_window":{}}' >/dev/null 2>&1
if wait_for_cache "$C_PROD_FAIL" 20; then
  st=$(jq -r '.status' < "$C_PROD_FAIL")
  nf=$(jq -r '.failed | length' < "$C_PROD_FAIL")
  sent=$(jq -r '.repos.core' < "$C_PROD_FAIL")
  if [ "$st" = "degraded" ] && [ "$nf" -eq 11 ] && [ "$sent" = "err" ]; then
    pass "an all-failure refresh writes status=degraded and a per-repo sentinel"
  else
    fail "an all-failure refresh writes status=degraded and a per-repo sentinel" \
         "status=$st failed=$nf repos.core=$sent"
  fi
  if ! jq -e '.repos | to_entries | map(select(.value == "0/0")) | length == 0' < "$C_PROD_FAIL" >/dev/null; then
    fail "a failed repo is never written as a count" "$(cat "$C_PROD_FAIL")"
  else
    pass "a failed repo is never written as a count"
  fi
else
  fail "an all-failure refresh writes a cache" "no cache at $C_PROD_FAIL"
fi

C_PROD_OK="$WORK/prod-ok.json"
GH_OK="$(make_gh_stub ok)"
PATH="$GH_OK:$PATH" ONEX_STATUSLINE_PR_CACHE="$C_PROD_OK" \
  bash "$STATUSLINE" <<< '{"workspace":{"project_dir":"'"$REPO_ROOT"'"},"model":{},"context_window":{}}' >/dev/null 2>&1
if wait_for_cache "$C_PROD_OK" 20; then
  st=$(jq -r '.status' < "$C_PROD_OK")
  nf=$(jq -r '.failed | length' < "$C_PROD_OK")
  haserr=$(jq -r '[.repos[] | select(. == "err")] | length' < "$C_PROD_OK")
  if [ "$st" = "ok" ] && [ "$nf" -eq 0 ] && [ "$haserr" -eq 0 ]; then
    pass "the sentinel is absent on an all-success refresh"
  else
    fail "the sentinel is absent on an all-success refresh" "status=$st failed=$nf err_count=$haserr"
  fi
else
  fail "an all-success refresh writes a cache" "no cache at $C_PROD_OK"
fi

# --- AC3: REST fallback when the GraphQL path refuses -----------------------

echo "AC3 — a GraphQL refusal falls back to the REST pulls endpoint"

C_FALLBACK="$WORK/fallback.json"
GH_FB="$(make_gh_stub graphql_fail_rest_ok)"
PATH="$GH_FB:$PATH" ONEX_STATUSLINE_PR_CACHE="$C_FALLBACK" \
  bash "$STATUSLINE" <<< '{"workspace":{"project_dir":"'"$REPO_ROOT"'"},"model":{},"context_window":{}}' >/dev/null 2>&1
if wait_for_cache "$C_FALLBACK" 20; then
  st=$(jq -r '.status' < "$C_FALLBACK")
  core=$(jq -r '.repos.core' < "$C_FALLBACK")
  if [ "$st" = "ok" ] && [ "$core" = "1/1" ]; then
    pass "real counts land through the REST fallback"
  else
    fail "real counts land through the REST fallback" "status=$st repos.core=$core"
  fi
  R_FB="$(render "$C_FALLBACK" "$NOGH")"
  case "$R_FB" in
    *"core·1/1"*) pass "the fallback counts reach the rendered segment" ;;
    *) fail "the fallback counts reach the rendered segment" "got: $R_FB" ;;
  esac
else
  fail "the REST fallback writes a cache" "no cache at $C_FALLBACK"
fi

# --- AC4: positive control — the marker assertion is load-bearing -----------
#
# Rule 16: a passing assertion proves nothing until the mutation that should
# break it does break it. Delete the visible-error branch from a copy of the
# script and the AC2 failure assertion must stop holding.

echo "AC4 — deleting the visible-error branch turns the failure assertion red"

MUT="$WORK/statusline-mutated.sh"
sed '/PR_BODY="${PR_BODY}${PR_BODY:+ }${RED}⚠${PR_FAILED} unreachable${RESET}"/d' "$STATUSLINE" > "$MUT"
if cmp -s "$MUT" "$STATUSLINE"; then
  fail "the mutation control edits the script" "sed matched nothing — the branch was renamed without updating this control"
else
  R_MUT=$(
    PATH="$NOGH:$PATH" ONEX_STATUSLINE_PR_CACHE="$C_FAILED" \
    bash "$MUT" <<< '{"workspace":{"project_dir":"'"$REPO_ROOT"'"},"model":{},"context_window":{}}' 2>/dev/null \
      | tail -1 | LC_ALL=C sed $'s/\033\\[[0-9;]*m//g'
  )
  case "$R_MUT" in
    *unreachable*) fail "the mutated script loses the marker" "marker survived deletion: $R_MUT" ;;
    *) pass "the mutated script loses the marker, so the AC2 assertion is load-bearing" ;;
  esac
fi

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "PASS — all assertions held"
  exit 0
fi
echo "FAIL — $FAILURES assertion(s) failed"
exit 1
