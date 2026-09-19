#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-18841 — the statusline open-PR segment must never render a silent false
# zero.
#
# The defect: the PR-cache producer ran one `gh pr list --json` per repo with
# stderr discarded and `|| echo "[]"`, so any gh failure became 0/0. The
# renderer then omitted a repo whose counts were both zero, and omitted the
# WHOLE segment when every repo was zero. A total refresh failure and a
# genuine fleet-wide zero rendered identically: as nothing at all.
#
# These tests drive statusline.sh from fixture caches via ONEX_PR_CACHE_FILE
# and assert the three states are distinguishable in the rendered line, plus
# that the producer falls back to REST when the GraphQL path is refused.
#
# Usage: bash tests/hooks/test_statusline_pr_segment.sh [--verbose]

set -uo pipefail

VERBOSE=false
[ "${1:-}" = "--verbose" ] && VERBOSE=true

PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); printf "  \033[32mPASS\033[0m %s\n" "$1"; }
fail() { FAIL=$((FAIL + 1)); printf "  \033[31mFAIL\033[0m %s\n" "$1"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATUSLINE="$REPO_ROOT/plugins/onex/hooks/scripts/statusline.sh"

if [ ! -f "$STATUSLINE" ]; then
  printf "\033[31mFATAL\033[0m statusline.sh not found at %s\n" "$STATUSLINE"
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  printf "\033[33mSKIP\033[0m jq not installed; this suite renders JSON fixtures\n"
  exit 0
fi

WORK="$(mktemp -d)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

# Claude Code sends this shape on stdin.
MOCK_INPUT='{
  "model": { "display_name": "Opus 5", "id": "claude-opus-5" },
  "workspace": { "project_dir": "'"$REPO_ROOT"'", "current_dir": "'"$REPO_ROOT"'" },
  "context_window": {
    "current_usage": { "input_tokens": 1000, "cache_read_input_tokens": 0 },
    "context_window_size": 200000, "used_percentage": 1, "remaining_percentage": 99
  }
}'

# Render statusline.sh against a fixture cache and return line 3 with the ANSI
# escapes stripped. The fixture is touched so the renderer sees it as fresh and
# spawns no background refresh.
render_line3() {
  local fixture="$1"
  touch "$fixture"
  printf '%s' "$MOCK_INPUT" | \
    env ONEX_PR_CACHE_FILE="$fixture" \
        POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=1 \
        VALKEY_HOST=127.0.0.1 VALKEY_PORT=1 \
        KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:1 \
        bash "$STATUSLINE" 2>/dev/null \
    | sed -n '3p' | sed $'s/\033\\[[0-9;]*m//g'
}

###############################################################################
# AC2 — counts present
###############################################################################
echo ""
echo "=== AC2a: a refresh with real counts renders those counts ==="

FIX_COUNTS="$WORK/counts.json"
cat > "$FIX_COUNTS" <<'EOF'
{"_status":"ok","core":"0/4","infra":"0/14","spi":"0/1","claude":"0/2","node":"1/3","dash":"0/1","intel":"0/2","mem":"0/1","web":"0/1","cc":"0/11","market":"0/20"}
EOF
OUT_COUNTS="$(render_line3 "$FIX_COUNTS")"
$VERBOSE && echo "    line3: $OUT_COUNTS"

if printf '%s' "$OUT_COUNTS" | grep -q "infra·0/14"; then
  pass "counts fixture renders infra·0/14"
else
  fail "counts fixture did not render infra·0/14 — got: $OUT_COUNTS"
fi
if printf '%s' "$OUT_COUNTS" | grep -q "node·1/3"; then
  pass "counts fixture renders node·1/3"
else
  fail "counts fixture did not render node·1/3 — got: $OUT_COUNTS"
fi

###############################################################################
# AC1 + AC2 — a failed refresh is visible, and distinct from a genuine zero
###############################################################################
echo ""
echo "=== AC2b: a fully failed refresh renders a visible marker, never nothing ==="

FIX_FAILED="$WORK/failed.json"
cat > "$FIX_FAILED" <<'EOF'
{"_status":"failed","core":"?","infra":"?","spi":"?","claude":"?","node":"?","dash":"?","intel":"?","mem":"?","web":"?","cc":"?","market":"?"}
EOF
OUT_FAILED="$(render_line3 "$FIX_FAILED")"
$VERBOSE && echo "    line3: $OUT_FAILED"

if printf '%s' "$OUT_FAILED" | grep -q "PRs"; then
  pass "failed fixture still renders a PRs segment"
else
  fail "failed fixture rendered NO PRs segment — this is the silent false zero: $OUT_FAILED"
fi
if printf '%s' "$OUT_FAILED" | grep -q "unavailable"; then
  pass "failed fixture renders the unavailable marker"
else
  fail "failed fixture carries no unavailable marker — got: $OUT_FAILED"
fi

echo ""
echo "=== AC2c: a genuine fleet-wide zero renders visibly and differs from a failure ==="

FIX_ZERO="$WORK/zero.json"
cat > "$FIX_ZERO" <<'EOF'
{"_status":"ok","core":"0/0","infra":"0/0","spi":"0/0","claude":"0/0","node":"0/0","dash":"0/0","intel":"0/0","mem":"0/0","web":"0/0","cc":"0/0","market":"0/0"}
EOF
OUT_ZERO="$(render_line3 "$FIX_ZERO")"
$VERBOSE && echo "    line3: $OUT_ZERO"

if printf '%s' "$OUT_ZERO" | grep -q "PRs"; then
  pass "genuine-zero fixture still renders a PRs segment"
else
  fail "genuine-zero fixture rendered NO PRs segment — got: $OUT_ZERO"
fi
if printf '%s' "$OUT_ZERO" | grep -q "unavailable"; then
  fail "genuine-zero fixture wrongly claims unavailable — got: $OUT_ZERO"
else
  pass "genuine-zero fixture does not claim unavailable"
fi

# The whole point: the two states must not render identically.
PR_SEG_FAILED="$(printf '%s' "$OUT_FAILED" | sed -n 's/.*\(PRs.*\)/\1/p')"
PR_SEG_ZERO="$(printf '%s' "$OUT_ZERO" | sed -n 's/.*\(PRs.*\)/\1/p')"
if [ -n "$PR_SEG_FAILED" ] && [ "$PR_SEG_FAILED" != "$PR_SEG_ZERO" ]; then
  pass "a failed refresh and a genuine zero render differently"
else
  fail "a failed refresh and a genuine zero are indistinguishable (failed='$PR_SEG_FAILED' zero='$PR_SEG_ZERO')"
fi

echo ""
echo "=== AC1: a partial failure names the unreadable repos and keeps the counts it has ==="

FIX_PARTIAL="$WORK/partial.json"
cat > "$FIX_PARTIAL" <<'EOF'
{"_status":"degraded","core":"0/4","infra":"?","spi":"0/0","claude":"?","node":"1/3","dash":"0/0","intel":"0/0","mem":"0/0","web":"0/0","cc":"0/11","market":"0/20"}
EOF
OUT_PARTIAL="$(render_line3 "$FIX_PARTIAL")"
$VERBOSE && echo "    line3: $OUT_PARTIAL"

if printf '%s' "$OUT_PARTIAL" | grep -q "core·0/4"; then
  pass "partial fixture keeps the counts it successfully read"
else
  fail "partial fixture dropped a good count — got: $OUT_PARTIAL"
fi
if printf '%s' "$OUT_PARTIAL" | grep -q "2 unreadable"; then
  pass "partial fixture reports 2 unreadable repos"
else
  fail "partial fixture does not report its unreadable repos — got: $OUT_PARTIAL"
fi

###############################################################################
# AC2 — legacy cache with no _status field still renders
###############################################################################
echo ""
echo "=== AC2d: a legacy cache written before this change still renders its counts ==="

FIX_LEGACY="$WORK/legacy.json"
cat > "$FIX_LEGACY" <<'EOF'
{"core":"0/4","infra":"0/14","spi":"0/1","claude":"0/2","node":"1/3","dash":"0/1","intel":"0/2","mem":"0/1","web":"0/1","cc":"0/11","market":"0/20"}
EOF
OUT_LEGACY="$(render_line3 "$FIX_LEGACY")"
$VERBOSE && echo "    line3: $OUT_LEGACY"

if printf '%s' "$OUT_LEGACY" | grep -q "infra·0/14"; then
  pass "legacy cache without _status still renders its counts"
else
  fail "legacy cache regressed — got: $OUT_LEGACY"
fi

###############################################################################
# AC3 — the producer falls back to REST when the GraphQL path is refused
###############################################################################
echo ""
echo "=== AC3: the producer falls back to REST when 'gh pr list' is refused ==="

STUB_DIR="$WORK/stub"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/gh" <<'EOF'
#!/bin/bash
# Stub gh: the GraphQL path (`gh pr list --json`) is refused exactly as the
# shared GraphQL quota refuses it; the REST path (`gh api .../pulls`) works.
if [ "${1:-}" = "pr" ] && [ "${2:-}" = "list" ]; then
  echo "API rate limit already exceeded for user ID 1002253" >&2
  exit 1
fi
if [ "${1:-}" = "api" ]; then
  echo '["dev","dev","main"]'
  exit 0
fi
exit 1
EOF
chmod +x "$STUB_DIR/gh"

FIX_REFRESH="$WORK/refresh.json"
# Deliberately stale so the renderer spawns the background producer.
echo '{"_status":"ok"}' > "$FIX_REFRESH"
touch -t 202001010000 "$FIX_REFRESH"

printf '%s' "$MOCK_INPUT" | \
  env PATH="$STUB_DIR:$PATH" \
      ONEX_PR_CACHE_FILE="$FIX_REFRESH" \
      POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=1 \
      VALKEY_HOST=127.0.0.1 VALKEY_PORT=1 \
      KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:1 \
      bash "$STATUSLINE" >/dev/null 2>&1

# The producer is backgrounded; give it a bounded window to land.
for _ in $(seq 1 40); do
  if grep -q '"infra"' "$FIX_REFRESH" 2>/dev/null; then break; fi
  sleep 0.25
done
REFRESHED="$(cat "$FIX_REFRESH" 2>/dev/null)"
$VERBOSE && echo "    cache: $REFRESHED"

if printf '%s' "$REFRESHED" | jq -e '.infra == "1/2"' >/dev/null 2>&1; then
  pass "REST fallback produced real counts when the GraphQL path was refused"
else
  fail "REST fallback did not produce counts — cache: $REFRESHED"
fi
if printf '%s' "$REFRESHED" | jq -e '._status == "ok"' >/dev/null 2>&1; then
  pass "a refresh served entirely by the REST fallback is recorded as ok"
else
  fail "REST-served refresh was not recorded as ok — cache: $REFRESHED"
fi

echo ""
echo "=== AC1: both transports failing marks the refresh failed, not zero ==="

STUB2="$WORK/stub2"
mkdir -p "$STUB2"
cat > "$STUB2/gh" <<'EOF'
#!/bin/bash
echo "API rate limit already exceeded for user ID 1002253" >&2
exit 1
EOF
chmod +x "$STUB2/gh"

FIX_BOTH="$WORK/both.json"
echo '{"_status":"ok"}' > "$FIX_BOTH"
touch -t 202001010000 "$FIX_BOTH"

printf '%s' "$MOCK_INPUT" | \
  env PATH="$STUB2:$PATH" \
      ONEX_PR_CACHE_FILE="$FIX_BOTH" \
      POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=1 \
      VALKEY_HOST=127.0.0.1 VALKEY_PORT=1 \
      KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:1 \
      bash "$STATUSLINE" >/dev/null 2>&1

for _ in $(seq 1 40); do
  if grep -q '"infra"' "$FIX_BOTH" 2>/dev/null; then break; fi
  sleep 0.25
done
BOTH="$(cat "$FIX_BOTH" 2>/dev/null)"
$VERBOSE && echo "    cache: $BOTH"

if printf '%s' "$BOTH" | jq -e '.infra == "?"' >/dev/null 2>&1; then
  pass "an unreadable repo is recorded as ? rather than 0/0"
else
  fail "an unreadable repo was recorded as a count — cache: $BOTH"
fi
if printf '%s' "$BOTH" | jq -e '._status == "failed"' >/dev/null 2>&1; then
  pass "a wholly failed refresh is recorded as failed"
else
  fail "a wholly failed refresh was not recorded as failed — cache: $BOTH"
fi

###############################################################################
echo ""
echo "======================================"
printf "  \033[32mPASS: %d\033[0m  \033[31mFAIL: %d\033[0m\n" "$PASS" "$FAIL"
echo "======================================"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
