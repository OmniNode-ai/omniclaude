#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Focused, isolated Lab dev tick tests [OMN-19732]. Bash 3.2 compatible.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TICK="$REPO_ROOT/scripts/omnidash-lab-dev-tick.sh"
# Keep even temporary fixtures within this worktree.
SANDBOX="$(mktemp -d "$SCRIPT_DIR/.lab-dev-test.XXXXXX")"
trap 'rm -rf "$SANDBOX"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

export OMNI_HOME="$SANDBOX/workspace"
export HOME="$SANDBOX/home"
export ONEX_STATE_DIR="$SANDBOX/state"
export OMNIDASH_LAB_DEV_LOG="$SANDBOX/vite.log"
export OMNIDASH_LAB_DEV_ENV_FILE="$HOME/.omnibase/omnidash-lab-dev.env"
export CALLS="$SANDBOX/calls" PS_OUTPUT="$SANDBOX/ps-output"
export PATH="$SANDBOX/bin:$PATH"
mkdir -p "$SANDBOX/bin" "$HOME/.omnibase" "$OMNI_HOME"
: > "$CALLS"
: > "$PS_OUTPUT"
cat > "$SANDBOX/bin/npm" <<'SH'
#!/usr/bin/env bash
printf 'npm %s\n' "$*" >> "$CALLS"
if [[ "$1" == ci ]]; then mkdir -p node_modules; fi
if [[ "$1" == run ]]; then
  if [[ "${EXPECT_ENV:-false}" == true ]]; then
    [[ "${VITE_PROJECTION_API_URL:-}" == 'private-api-value' ]] || exit 1
    [[ "${VITE_PROJECTION_TENANT_ID:-}" == 'private-tenant-value' ]] || exit 1
  fi
  touch "$OMNI_HOME/started"
fi
SH
cat > "$SANDBOX/bin/ps" <<'SH'
#!/usr/bin/env bash
printf 'ps %s\n' "$*" >> "$CALLS"
cat "$PS_OUTPUT"
SH
chmod +x "$SANDBOX/bin/"*
# Exported functions override bash's builtin kill; never signal real processes.
kill() { printf 'kill %s\n' "$*" >> "$CALLS"; }
sleep() { printf 'sleep %s\n' "$*" >> "$CALLS"; }
export -f kill sleep

run_tick() { bash "$TICK" > "$SANDBOX/tick.log" 2>&1; }
clear_calls() { : > "$CALLS"; rm -f "$OMNI_HOME/started"; }
await_start() {
  local attempt
  for attempt in {1..100}; do
    [[ -f "$OMNI_HOME/started" ]] && return 0
    command sleep 0.02
  done
  fail "background npm did not finish: $(cat "$SANDBOX/vite.log")"
}
assert_start() {
  await_start
  grep -Fxq 'npm run dev -- --host 0.0.0.0 --port 3001 --strictPort' "$CALLS" || fail 'dev argv'
  [[ "$(cat "$STATE_FILE")" == "$(git -C "$CLONE" rev-parse HEAD)" ]] || fail 'served HEAD'
}
assert_no_npm() {
  if grep -q '^npm ' "$CALLS"; then fail 'unexpected npm invocation'; fi
}

# (a) Missing clone and manifest are explicit failures.
status=0
run_tick || status=$?
[[ "$status" == 1 ]] || fail 'missing clone must exit 1'
[[ "$(wc -l < "$SANDBOX/tick.log" | tr -d ' ')" == 1 ]] || fail 'expected one diagnostic'
pass 'missing clone exits 1'

CLONE="$OMNI_HOME/omnidash"
git init -q "$CLONE"
status=0
run_tick || status=$?
[[ "$status" == 1 ]] || fail 'missing package.json must exit 1'
pass 'missing package.json exits 1'
printf '{}\n' > "$CLONE/package.json"
printf '{"lockfileVersion": 3}\n' > "$CLONE/package-lock.json"
# Build local fixture history with plumbing; no commit command or hooks.
fixture_head() {
  local tree revision
  git -C "$CLONE" add package.json package-lock.json
  tree="$(git -C "$CLONE" write-tree)"
  revision="$(printf 'tree %s\nauthor Test <test@example.invalid> 1000000000 +0000\ncommitter Test <test@example.invalid> 1000000000 +0000\n\nfixture %s\n' "$tree" "$1" |
    git -C "$CLONE" hash-object -t commit -w --stdin)"
  git -C "$CLONE" update-ref HEAD "$revision"
}
fixture_head initial
mkdir -p "$CLONE/node_modules"
STATE_FILE="$ONEX_STATE_DIR/omnidash-lab-dev/served_head"

# (b) No process starts vite, without reinstalling existing dependencies.
clear_calls
run_tick
assert_start
if grep -q '^npm ci' "$CALLS"; then fail 'first start with dependencies must skip ci'; fi
grep -q 'started: not running' "$SANDBOX/tick.log" || fail 'start reason'
grep -Fxq 'ps -axo pid,pgid,command' "$CALLS" || fail 'ps argv'
pass 'absent vite starts and records HEAD'

# (c) Matching process and HEAD are a silent no-op.
printf '12345 23456 node /fake/node_modules/.bin/vite --host 0.0.0.0 --port 3001 --strictPort\n' > "$PS_OUTPUT"
clear_calls
run_tick
assert_no_npm
[[ ! -s "$SANDBOX/tick.log" ]] || fail 'no-op must be silent'
pass 'running vite at served HEAD is silent'

# (d) HEAD movement targets only the matched process group, then restarts.
old_head="$(cat "$STATE_FILE")"
printf '{"name":"changed"}\n' > "$CLONE/package.json"
fixture_head moved
clear_calls
run_tick
assert_start
grep -Fxq 'kill -TERM -- -23456' "$CALLS" || fail 'wrong process group signal'
grep -Fxq 'sleep 2' "$CALLS" || fail 'restart delay missing'
[[ "$(grep -c '^kill ' "$CALLS")" == 1 ]] || fail 'unexpected extra signal'
grep -Fq "head moved $old_head->$(cat "$STATE_FILE")" "$SANDBOX/tick.log" || fail 'head movement reason'
if grep -q '^npm ci' "$CALLS"; then fail 'unchanged lockfile must skip ci'; fi
pass 'moved HEAD signals only vite group and restarts'

# (e) No git mutation commands, including pull.
if grep -E 'git[[:space:]]+([^;]*[[:space:]])?(fetch|merge|pull|checkout|reset|stash|clean)([[:space:]]|$)' "$TICK"; then
  fail 'forbidden git mutation'
fi
pass 'tick contains no forbidden git mutations'

printf '{"lockfileVersion": 3, "packages": {}}\n' > "$CLONE/package-lock.json"
fixture_head lock_changed
clear_calls
run_tick
assert_start
grep -Fxq 'npm ci --prefer-offline --no-audit --no-fund' "$CALLS" || fail 'lockfile change must install'
pass 'changed lockfile installs dependencies'

: > "$PS_OUTPUT"
rm -rf "$CLONE/node_modules"
rm -f "$STATE_FILE"
clear_calls
run_tick
assert_start
grep -Fxq 'npm ci --prefer-offline --no-audit --no-fund' "$CALLS" || fail 'missing dependencies must install'
pass 'first start installs missing dependencies'

cat > "$OMNIDASH_LAB_DEV_ENV_FILE" <<'SH'
VITE_PROJECTION_API_URL=private-api-value
VITE_PROJECTION_TENANT_ID=private-tenant-value
SH
export EXPECT_ENV=true
export VITE_PROJECTION_API_URL=previous-private-value
clear_calls
run_tick
assert_start
grep -q 'exported variables:.*VITE_PROJECTION_API_URL' "$SANDBOX/tick.log" || fail 'API name missing'
grep -q 'exported variables:.*VITE_PROJECTION_TENANT_ID' "$SANDBOX/tick.log" || fail 'tenant name missing'
if grep -q 'private-.*value' "$SANDBOX/tick.log"; then fail 'environment value leaked'; fi
pass 'environment passes to npm while logs contain only names'

# A grep process or a vite command with extra arguments is not the target.
printf '12345 23456 grep -F vite --host 0.0.0.0 --port 3001 --strictPort\n12346 23457 node /fake/vite --host 0.0.0.0 --port 3001 --strictPort --open\n' > "$PS_OUTPUT"
clear_calls
run_tick
assert_start
if grep -q '^kill ' "$CALLS"; then fail 'signalled an unrelated process'; fi
pass 'grep and nonexact vite commands are excluded'

# Exercise the derived state directory fallback.
unset ONEX_STATE_DIR
STATE_FILE="$OMNI_HOME/.onex_state/omnidash-lab-dev/served_head"
clear_calls
run_tick
assert_start
pass 'state directory falls back to required OMNI_HOME'

for bundle in install uninstall; do
  awk '/^TICKS=\(/{active=1; next} /^\)/{active=0} active' "$REPO_ROOT/scripts/tick-bundle-$bundle.sh" |
    grep -Fq '"ai.omninode.omnidash-lab-dev"' || fail "label absent from $bundle"
done
[[ -x "$TICK" ]] || fail 'tick must be executable'
pass 'executable tick registered in both bundle scripts'
echo 'ALL TESTS PASSED'
