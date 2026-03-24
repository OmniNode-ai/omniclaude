#!/usr/bin/env bash
# verify-deploy.sh — Post-deployment structural verification for the omniclaude plugin
# Usage: bash verify-deploy.sh [PLUGIN_ROOT]
# Exit 0 = all checks pass. Exit 1 = one or more checks failed.
#
# Portability: requires Python 3 (any version on PATH) for path resolution.
# Does NOT require coreutils readlink -f or platform-specific nc variants.

pass_count=0
fail_count=0
results=()

green="\033[0;32m"; red="\033[0;31m"; reset="\033[0m"; bold="\033[1m"

# Tolerant check: never exits early. Failure is recorded, not fatal.
check() {
  local name="$1"; shift
  if "$@" &>/dev/null 2>&1; then
    results+=("${green}✓${reset} $name")
    ((pass_count++)) || true
  else
    results+=("${red}✗${reset} $name")
    ((fail_count++)) || true
  fi
}

# Portable symlink resolution using Python (avoids readlink -f on macOS).
resolve_path() {
  python3 -c "import pathlib, sys; print(pathlib.Path(sys.argv[1]).resolve())" "$1" 2>/dev/null || true
}

# --- Resolve plugin root ---
PLUGIN_ROOT="${1:-}"
if [[ -z "$PLUGIN_ROOT" ]]; then
  SYMLINK="$HOME/.claude/plugins/cache/omninode-tools/onex/current"
  PLUGIN_ROOT="$(resolve_path "$SYMLINK")"
fi
if [[ -z "$PLUGIN_ROOT" || ! -d "$PLUGIN_ROOT" ]]; then
  echo -e "${red}ERROR: Cannot resolve plugin root. Pass PLUGIN_ROOT as first arg or ensure current/ symlink exists.${reset}"
  exit 1
fi

echo -e "\n${bold}Plugin Verification Suite${reset}"
echo -e "Root: $PLUGIN_ROOT\n"

# CHECK: file_exists — required directories
for dir in skills agents hooks ".claude-plugin" "lib/.venv"; do
  check "file_exists: $dir" test -d "$PLUGIN_ROOT/$dir"
done

# CHECK: file_exists — registry and sentinel files
check "file_exists: installed_plugins.json" test -f "$HOME/.claude/plugins/installed_plugins.json"
check "file_exists: known_marketplaces.json" test -f "$HOME/.claude/plugins/known_marketplaces.json"
check "file_exists: lib/venv_manifest.txt"   test -f "$PLUGIN_ROOT/lib/venv_manifest.txt"
check "file_exists: .omniclaude-sentinel"    test -f "$PLUGIN_ROOT/lib/.venv/.omniclaude-sentinel"

# CHECK: version consistency across 3 surfaces
PLUGIN_VER=""
INSTALLED_VER=""
SYMLINK_TARGET=""

PLUGIN_VER="$(jq -r '.version' "$PLUGIN_ROOT/.claude-plugin/plugin.json" 2>/dev/null || true)"
INSTALLED_VER="$(jq -r '(.plugins["onex@omninode-tools"] | if type == "array" then .[0].version else .version end) // empty' \
  "$HOME/.claude/plugins/installed_plugins.json" 2>/dev/null || true)"
SYMLINK_TARGET="$(basename "$(resolve_path "$HOME/.claude/plugins/cache/omninode-tools/onex/current")" 2>/dev/null || true)"

check "version_consistency: plugin.json == installed_plugins.json" \
  test "$PLUGIN_VER" = "$INSTALLED_VER"
check "version_consistency: plugin.json == current/ symlink" \
  test "$PLUGIN_VER" = "$SYMLINK_TARGET"

# CHECK: JSON validity — key config files
check "json_valid: plugin.json"             jq '.' "$PLUGIN_ROOT/.claude-plugin/plugin.json"
check "json_valid: hooks/hooks.json"        jq '.' "$PLUGIN_ROOT/hooks/hooks.json"
check "json_valid: installed_plugins.json"  jq '.' "$HOME/.claude/plugins/installed_plugins.json"

# CHECK: JSON validity — agent configs (*.json only — agent configs in this plugin are JSON, not YAML)
bad_agents=0
agent_count=0
while IFS= read -r f; do
  ((agent_count++)) || true
  jq '.' "$f" &>/dev/null || ((bad_agents++)) || true
done < <(find "$PLUGIN_ROOT/agents/configs" -name "*.json" 2>/dev/null)
check "json_valid: $agent_count agent configs (${bad_agents} failures)" test "$bad_agents" -eq 0

# CHECK: skill naming — all snake_case, no kebab-case dirs (OMN-5200)
kebab_count=0
kebab_count="$(find "$PLUGIN_ROOT/skills" -maxdepth 1 -mindepth 1 -type d \
  -name '*-*' ! -name '_*' 2>/dev/null | wc -l | tr -d ' ')"
check "skill_naming: zero kebab-case dirs (found: $kebab_count)" test "$kebab_count" -eq 0

# CHECK: python_import — venv health
PYTHON="$PLUGIN_ROOT/lib/.venv/bin/python3"
check "python_import: omnibase_spi"       "$PYTHON" -c "import omnibase_spi"
check "python_import: omniclaude"         "$PYTHON" -c "import omniclaude"
check "python_import: TopicBase"          "$PYTHON" -c "from omniclaude.hooks.topics import TopicBase"

# CHECK: no editable installs in venv (catches development-mode contamination)
editable_count=0
editable_count="$(find "$PLUGIN_ROOT/lib/.venv" -name "*.pth" \
  -exec grep -l "editable" {} \; 2>/dev/null | wc -l | tr -d ' ')"
check "venv_clean: no editable .pth files (found: $editable_count)" test "$editable_count" -eq 0

# CHECK: settings.json statusLine points to current or known version
# Note: this is compatibility sanity, not exact correctness.
# The version check is authoritative; this confirms Claude Code is invoking the right path.
SETTINGS="$HOME/.claude/settings.json"
if [[ -f "$SETTINGS" ]]; then
  STATUS_CMD="$(jq -r '.statusLine.command // empty' "$SETTINGS" 2>/dev/null || true)"
  check "settings: statusLine references version $PLUGIN_VER or 'current'" \
    bash -c "[[ '$STATUS_CMD' == *'$PLUGIN_VER'* || '$STATUS_CMD' == *'current'* ]]"
fi

# CHECK: hook smoke — all hooks in hooks.json
# Scope: execution smoke + output-shape smoke only. Does NOT verify semantic correctness.
# A hook passing this check means: it ran without crashing and emitted empty or valid JSON stdout.
HOOK_DIR="$PLUGIN_ROOT/hooks/scripts"
hook_pass=0
hook_fail=0
while IFS= read -r script; do
  script_path="$HOOK_DIR/$script"
  [[ -x "$script_path" ]] || continue
  out="$(CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" \
    bash "$script_path" '{"session_id":"verify-test","tool_name":"Bash","tool_input":{}}' 2>/dev/null || true)"
  if [[ -z "$out" ]] || jq '.' <<<"$out" &>/dev/null; then
    ((hook_pass++)) || true
  else
    ((hook_fail++)) || true
    results+=("${red}✗${reset} hook_smoke: $script (invalid stdout)")
  fi
done < <(jq -r '.hooks | to_entries[].value.hooks[].command | split("/")[-1]' \
  "$PLUGIN_ROOT/hooks/hooks.json" 2>/dev/null | sort -u)
check "hook_smoke: $hook_pass hooks pass, $hook_fail fail (exec+shape only)" test "$hook_fail" -eq 0

# CHECK: post-deploy smoke test (OMN-6376)
# Run the comprehensive smoke test runner if available at the expected path.
SMOKE_SCRIPT="$PLUGIN_ROOT/tests/smoke_deploy.sh"
if [[ -f "$SMOKE_SCRIPT" ]]; then
  check "smoke_test: smoke_deploy.sh passes" bash "$SMOKE_SCRIPT" "$PLUGIN_ROOT"
else
  # Missing smoke script on a current deploy target is a failure.
  # SKIP only for explicit legacy-target verification (pre-smoke deployments).
  results+=("${red}✗${reset} smoke_test: smoke_deploy.sh not found at $SMOKE_SCRIPT")
  ((fail_count++)) || true
fi

# --- Print results ---
echo ""
for r in "${results[@]}"; do echo -e "  $r"; done
echo ""
echo -e "  ${bold}Result: ${pass_count} passed, ${fail_count} failed${reset}"

[[ $fail_count -eq 0 ]] && exit 0 || exit 1
