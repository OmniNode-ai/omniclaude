#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-20285 — the status line's optional PR-segment extension, and the launcher
# that resolves the ENABLED onex plugin.
#
# Drives the real scripts. No network: `gh` is absent from the stub PATH dir,
# every service host points at a closed local port, and the extensions here are
# throwaway scripts in a temp dir.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATUSLINE="$REPO_ROOT/plugins/onex/hooks/scripts/statusline.sh"
DEPLOY="$REPO_ROOT/plugins/onex/hooks/scripts/deploy.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FAILURES=0
pass() { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; FAILURES=$((FAILURES + 1)); }

export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=1
export VALKEY_HOST=127.0.0.1 VALKEY_PORT=1
export KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:1
export OMNICLAUDE_MODE=full
# The shipped bound is 300 ms. The suite runs on loaded hosts where a bare
# process start can exceed that, so it widens the bound and keeps the slow
# extension (5 s) well beyond it.
export ONEX_STATUSLINE_EXT_BUDGET_MS=1500

STDIN='{"workspace":{"project_dir":"'"$REPO_ROOT"'"},"model":{"id":"t","display_name":"T"},"context_window":{}}'
strip() { LC_ALL=C sed $'s/\033\\[[0-9;]*m//g'; }

# render <ext-or-"none"> <ext-cache> -> full output, ANSI stripped, on stdout
render() {
  local ext="$1" cache="$2"
  ONEX_STATUSLINE_PR_EXT="$ext" \
  ONEX_STATUSLINE_EXT_CACHE="$cache" \
  ONEX_STATUSLINE_PR_CACHE="$WORK/prcache.json" \
  ONEX_STATE_DIR="$WORK/nostate" HOME="$WORK/home" \
  bash "$STATUSLINE" <<< "$STDIN" 2>/dev/null | strip
}
mkdir -p "$WORK/home"
printf '{"schema":2,"refreshed_at":9999999999,"status":"ok","failed":[],"repos":{"core":"0/2"}}' > "$WORK/prcache.json"

mkext() { # mkext <name> <body...>
  local f="$WORK/$1"; shift
  printf '#!/bin/bash\n%s\n' "$*" > "$f"; chmod +x "$f"; printf '%s' "$f"
}

echo "OMN-20285 statusline PR extension"

# 1. no extension -> built-in segment, three lines
OUT="$(render none "$WORK/c1")"
case "$OUT" in *"PRs(main/dev):"*"core·0/2"*) pass "no extension: built-in segment renders" ;; *) fail "no extension: built-in segment renders" "$OUT" ;; esac
[ "$(printf '%s\n' "$OUT" | wc -l | tr -d ' ')" = "3" ] && pass "no extension: three lines" || fail "no extension: three lines" "$OUT"

# 2. missing path in the env var -> same fallback
OUT="$(render "$WORK/does-not-exist" "$WORK/c2")"
case "$OUT" in *"PRs(main/dev):"*) pass "extension path missing: falls back to built-in" ;; *) fail "extension path missing: falls back to built-in" "$OUT" ;; esac

# 3. two-line extension -> segment on line 3, fourth line printed
EXT="$(mkext ok2 "printf 'SEG-A one\nSEG-B two\n'")"
OUT="$(render "$EXT" "$WORK/c3")"
L3="$(printf '%s\n' "$OUT" | sed -n 3p)"; L4="$(printf '%s\n' "$OUT" | sed -n 4p)"
case "$L3" in *"SEG-A one") pass "extension line 1 is the line-3 PR segment" ;; *) fail "extension line 1 is the line-3 PR segment" "$L3" ;; esac
[ "$L4" = "SEG-B two" ] && pass "extension line 2 becomes line 4" || fail "extension line 2 becomes line 4" "$L4"
case "$OUT" in *"PRs(main/dev):"*) fail "built-in segment is replaced" "$OUT" ;; *) pass "built-in segment is replaced" ;; esac

# 4. one-line extension -> exactly three lines
EXT="$(mkext ok1 "echo ONLY-A")"
OUT="$(render "$EXT" "$WORK/c4")"
[ "$(printf '%s\n' "$OUT" | wc -l | tr -d ' ')" = "3" ] && pass "one-line extension: three lines" || fail "one-line extension: three lines" "$OUT"

# 5. slow extension, no cache -> bounded, built-in fallback
EXT="$(mkext slow "sleep 5; echo SLOW-SEG")"
T0=$(date +%s)
OUT="$(render "$EXT" "$WORK/c5")"
T1=$(date +%s)
case "$OUT" in *"PRs(main/dev):"*) pass "slow extension, no cache: built-in fallback" ;; *) fail "slow extension, no cache: built-in fallback" "$OUT" ;; esac
[ $((T1 - T0)) -le 4 ] && pass "slow extension is bounded (took $((T1 - T0))s, not 5)" || fail "slow extension is bounded" "took $((T1 - T0))s"

# 6. slow extension WITH a last-good cache -> cached output, not the fallback
printf 'CACHED-A\nCACHED-B\n' > "$WORK/c6"
OUT="$(render "$EXT" "$WORK/c6")"
L3="$(printf '%s\n' "$OUT" | sed -n 3p)"; L4="$(printf '%s\n' "$OUT" | sed -n 4p)"
case "$L3" in *"CACHED-A") pass "slow extension: last good output served (line 3)" ;; *) fail "slow extension: last good output served" "$L3" ;; esac
[ "$L4" = "CACHED-B" ] && pass "slow extension: last good output served (line 4)" || fail "slow extension: cached line 4" "$L4"

# 7. failing extension -> cache then fallback; a good run refreshes the cache
EXT="$(mkext bad "echo PARTIAL; exit 1")"
OUT="$(render "$EXT" "$WORK/c7")"
case "$OUT" in *PARTIAL*) fail "failing extension output is never shown" "$OUT" ;; *"PRs(main/dev):"*) pass "failing extension: built-in fallback, output discarded" ;; *) fail "failing extension fallback" "$OUT" ;; esac
EXT="$(mkext good "echo FRESH")"
render "$EXT" "$WORK/c8" >/dev/null
[ "$(cat "$WORK/c8" 2>/dev/null)" = "FRESH" ] && pass "a good run refreshes the last-good cache" || fail "a good run refreshes the last-good cache" "$(cat "$WORK/c8" 2>/dev/null)"

# 8. launcher resolves the ENABLED plugin, not the disabled cache
H="$WORK/lh"; mkdir -p "$H/.claude/plugins/cache/omninode-tools/onex/9.9.9/hooks/scripts" \
  "$H/.claude/plugins/cache/omninode-tools-dev/onex/1.0.0/hooks/scripts"
printf '#!/bin/bash\necho DISABLED-COPY\n' > "$H/.claude/plugins/cache/omninode-tools/onex/9.9.9/hooks/scripts/statusline.sh"
printf '#!/bin/bash\necho ENABLED-COPY\n' > "$H/.claude/plugins/cache/omninode-tools-dev/onex/1.0.0/hooks/scripts/statusline.sh"
cat > "$H/.claude/settings.json" <<J
{"enabledPlugins":{"onex@omninode-tools":false,"onex@omninode-tools-dev":true}}
J
cat > "$H/.claude/plugins/installed_plugins.json" <<J
{"plugins":{"onex@omninode-tools":[{"installPath":"$H/.claude/plugins/cache/omninode-tools/onex/9.9.9"}],"onex@omninode-tools-dev":[{"installPath":"$H/.claude/plugins/cache/omninode-tools-dev/onex/1.0.0"}]}}
J
HOME="$H" bash "$DEPLOY" >/dev/null 2>&1
OUT="$(HOME="$H" bash "$H/.onex_state/bin/statusline.sh" <<< '{}')"
[ "$OUT" = "ENABLED-COPY" ] && pass "launcher runs the enabled plugin's copy" || fail "launcher runs the enabled plugin's copy" "$OUT"

# 9. nothing enabled / registry unreadable -> newest cached copy under the cache root
printf '{"enabledPlugins":{}}' > "$H/.claude/settings.json"
OUT="$(HOME="$H" bash "$H/.onex_state/bin/statusline.sh" <<< '{}')"
[ "$OUT" = "DISABLED-COPY" ] && pass "no enabled plugin: falls back to the cache root copy" || fail "no enabled plugin: falls back to the cache root copy" "$OUT"

echo
if [ "$FAILURES" -eq 0 ]; then echo "PASS — all assertions held"; exit 0; fi
echo "FAIL — $FAILURES assertion(s) failed"; exit 1
