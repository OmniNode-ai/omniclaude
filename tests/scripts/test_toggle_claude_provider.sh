#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Test suite for scripts/toggle-claude-provider.sh [OMN-19393, plan task E4].
#
# Proves:
#   - the script reads the USER file at ~/.omninode/config/claude-providers.json,
#     never the shipped examples/config-overlays/claude-providers.example.json;
#   - when the user file is absent it exits non-zero and names the example path
#     (this is the RED-first regression: the pre-refactor script had zai,
#     gemini-* and the native-claude switch hardcoded and worked with NO
#     config file at all -- moving the config out of source without this
#     check would silently work "by accident" via stale hardcoded values);
#   - `help` works with no config file present (it does not need one);
#   - switching to a provider with a base_url populates settings.json from
#     the config file's own values (not from anything baked into the script),
#     and switching back to a null-base_url provider clears the override;
#   - the whole run is confined to a scratch HOME (never touches the real
#     ~/.claude/settings.json or ~/.omninode/config).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SUT="${REPO_ROOT}/scripts/toggle-claude-provider.sh"
EXAMPLE_CONFIG="${REPO_ROOT}/examples/config-overlays/claude-providers.example.json"

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
[ -f "$EXAMPLE_CONFIG" ] || {
  echo "FAIL: example config missing: $EXAMPLE_CONFIG" >&2
  exit 1
}
command -v jq >/dev/null 2>&1 || {
  echo "SKIP: jq not installed, cannot exercise $SUT" >&2
  exit 0
}

SCRATCH_ROOT="$(mktemp -d)"
trap 'rm -rf "$SCRATCH_ROOT"' EXIT

new_scratch_home() {
  local home="$1"
  mkdir -p "${home}/.claude"
  cat > "${home}/.claude/settings.json" <<'JSON'
{
  "env": {}
}
JSON
}

# ---------------------------------------------------------------------------
# 1. Absent user config: exits non-zero and names the example path. ONLY with
#    HOME pointed at a scratch dir -- this never touches the real
#    ~/.omninode/config or ~/.claude/settings.json.
# ---------------------------------------------------------------------------
HOME_NO_CONFIG="${SCRATCH_ROOT}/home-no-config"
new_scratch_home "$HOME_NO_CONFIG"

out="$(HOME="$HOME_NO_CONFIG" "$SUT" zai 2>&1)"
code=$?
if [ "$code" -eq 0 ]; then
  fail "absent config file: expected non-zero exit, got 0. Output: $out"
else
  pass "absent config file: exits non-zero ($code)"
fi
if echo "$out" | grep -q "examples/config-overlays/claude-providers.example.json"; then
  pass "absent config file: error names the example path"
else
  fail "absent config file: error does not name the example path. Output: $out"
fi

# `status` (no explicit action) also needs the file -- only `help` is exempt.
HOME="$HOME_NO_CONFIG" "$SUT" status >/dev/null 2>&1
code_status=$?
if [ "$code_status" -ne 0 ]; then
  pass "absent config file: 'status' also refuses"
else
  fail "absent config file: 'status' should also refuse, got exit 0"
fi

# ---------------------------------------------------------------------------
# 2. `help` needs no config file.
# ---------------------------------------------------------------------------
out_help="$(HOME="$HOME_NO_CONFIG" "$SUT" help 2>&1)"
code_help=$?
if [ "$code_help" -eq 0 ] && echo "$out_help" | grep -qi "usage"; then
  pass "'help' works with no config file present"
else
  fail "'help' should exit 0 and print usage with no config file. exit=$code_help output=$out_help"
fi

# ---------------------------------------------------------------------------
# 3. With the user file present (copied from the shipped example), switch to
#    a provider with a base_url, then switch back to the null-base_url
#    provider. Values must come from the config file, not the script.
# ---------------------------------------------------------------------------
HOME_WITH_CONFIG="${SCRATCH_ROOT}/home-with-config"
new_scratch_home "$HOME_WITH_CONFIG"
mkdir -p "${HOME_WITH_CONFIG}/.omninode/config"
cp "$EXAMPLE_CONFIG" "${HOME_WITH_CONFIG}/.omninode/config/claude-providers.json"

CFG="${HOME_WITH_CONFIG}/.omninode/config/claude-providers.json"
expected_base_url="$(jq -r '.providers.zai.base_url' "$CFG")"
expected_sonnet="$(jq -r '.providers.zai.models.sonnet' "$CFG")"

out_switch="$(HOME="$HOME_WITH_CONFIG" ZAI_API_KEY="scratch-test-key" "$SUT" zai 2>&1)"
code_switch=$?
settings_base_url="$(jq -r '.env.ANTHROPIC_BASE_URL // empty' "${HOME_WITH_CONFIG}/.claude/settings.json")"
settings_sonnet="$(jq -r '.env.ANTHROPIC_DEFAULT_SONNET_MODEL // empty' "${HOME_WITH_CONFIG}/.claude/settings.json")"
settings_token="$(jq -r '.env.ANTHROPIC_AUTH_TOKEN // empty' "${HOME_WITH_CONFIG}/.claude/settings.json")"

if [ "$code_switch" -eq 0 ] \
  && [ "$settings_base_url" = "$expected_base_url" ] \
  && [ "$settings_sonnet" = "$expected_sonnet" ] \
  && [ "$settings_token" = "scratch-test-key" ]; then
  pass "switch to zai: settings.json matches the config file's own values"
else
  fail "switch to zai failed or values did not come from the config file. exit=$code_switch base_url=$settings_base_url (want $expected_base_url) sonnet=$settings_sonnet (want $expected_sonnet) token=$settings_token output=$out_switch"
fi

# Missing API key env var: refuses, does not silently write an empty token.
# (Switch back to anthropic first so this is a real switch, not a
# short-circuited "already using zai".)
HOME="$HOME_WITH_CONFIG" "$SUT" anthropic >/dev/null 2>&1
out_missing_key="$(HOME="$HOME_WITH_CONFIG" env -u ZAI_API_KEY "$SUT" zai 2>&1)"
code_missing_key=$?
if [ "$code_missing_key" -ne 0 ]; then
  pass "switch to zai with no ZAI_API_KEY set: refuses"
else
  fail "switch to zai with no ZAI_API_KEY set should refuse, got exit 0: $out_missing_key"
fi

# Switch back to anthropic (base_url: null in the example) clears the override.
out_back="$(HOME="$HOME_WITH_CONFIG" "$SUT" anthropic 2>&1)"
code_back=$?
settings_base_url_after="$(jq -r '.env.ANTHROPIC_BASE_URL // "ABSENT"' "${HOME_WITH_CONFIG}/.claude/settings.json")"
if [ "$code_back" -eq 0 ] && [ "$settings_base_url_after" = "ABSENT" ]; then
  pass "switch back to anthropic: override cleared"
else
  fail "switch back to anthropic should clear ANTHROPIC_BASE_URL. exit=$code_back base_url=$settings_base_url_after output=$out_back"
fi

# ---------------------------------------------------------------------------
# 4. `list` reflects the config file's own provider set, and an unknown
#    provider name is refused by name.
# ---------------------------------------------------------------------------
out_list="$(HOME="$HOME_WITH_CONFIG" "$SUT" list 2>&1)"
if echo "$out_list" | grep -q "zai:" && echo "$out_list" | grep -q "openrouter:"; then
  pass "'list' reflects the config file's provider set"
else
  fail "'list' did not list expected providers. Output: $out_list"
fi

out_unknown="$(HOME="$HOME_WITH_CONFIG" "$SUT" not-a-real-provider 2>&1)"
code_unknown=$?
if [ "$code_unknown" -ne 0 ] && echo "$out_unknown" | grep -q "not-a-real-provider"; then
  pass "unknown provider name is refused by name"
else
  fail "unknown provider name should be refused and named. exit=$code_unknown output=$out_unknown"
fi

# ---------------------------------------------------------------------------
# 5. A provider entry whose api_key_env is not a bare shell identifier is
#    refused by name before the indirect expansion (${!api_key_env}) runs,
#    rather than surfacing as an opaque "bad substitution" or being trusted
#    as-is (ai-reviewer finding on the original E4 PR: api_key_env comes
#    straight from the user's own JSON file).
# ---------------------------------------------------------------------------
HOME_BAD_KEY_ENV="${SCRATCH_ROOT}/home-bad-key-env"
new_scratch_home "$HOME_BAD_KEY_ENV"
mkdir -p "${HOME_BAD_KEY_ENV}/.omninode/config"
cat > "${HOME_BAD_KEY_ENV}/.omninode/config/claude-providers.json" <<'JSON'
{
  "providers": {
    "evil": {
      "name": "evil",
      "base_url": "https://example.invalid",
      "api_key_env": "FOO; touch /tmp/toggle-claude-provider-test-pwned",
      "models": {"haiku": "h", "sonnet": "s", "opus": "o"}
    }
  }
}
JSON

PWNED_MARKER="/tmp/toggle-claude-provider-test-pwned"
rm -f "$PWNED_MARKER"
out_bad_key_env="$(HOME="$HOME_BAD_KEY_ENV" "$SUT" evil 2>&1)"
code_bad_key_env=$?
if [ "$code_bad_key_env" -ne 0 ] \
  && echo "$out_bad_key_env" | grep -q "not a valid environment-variable name" \
  && [ ! -e "$PWNED_MARKER" ]; then
  pass "api_key_env with shell metacharacters is refused by name, nothing executed"
else
  fail "api_key_env with shell metacharacters should be refused and nothing executed. exit=$code_bad_key_env pwned_marker_exists=$([ -e "$PWNED_MARKER" ] && echo yes || echo no) output=$out_bad_key_env"
fi
rm -f "$PWNED_MARKER"

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "ALL PASSED"
  exit 0
else
  echo "${FAILURES} FAILURE(S)"
  exit 1
fi
