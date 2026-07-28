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

# --- Resolve plugin root -------------------------------------------------
# The plugin CACHE is not the load path. This used to default to
# ~/.claude/plugins/cache/<marketplace>/<plugin>/current, which for a
# directory-source marketplace is a tree Claude Code never reads -- one observed
# in the field was 24 days stale and carried a different hooks.json version than
# the one executing. Verifying that tree proved nothing about what runs. Resolve
# through the same chain Claude Code uses instead.
PLUGIN_ROOT="${1:-}"
if [[ -z "$PLUGIN_ROOT" ]]; then
  _READBACK="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/hooks/lib/plugin_deploy_readback.py"
  PLUGIN_ROOT="$(python3 "$_READBACK" --json --no-fetch 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("resolved_load_path") or "")' 2>/dev/null || true)"
fi
if [[ -z "$PLUGIN_ROOT" || ! -d "$PLUGIN_ROOT" ]]; then
  echo -e "${red}ERROR: Cannot resolve plugin root.${reset}"
  echo -e "Pass PLUGIN_ROOT explicitly, or run the readback to see why resolution failed:"
  echo -e "  python3 plugins/onex/hooks/lib/plugin_deploy_readback.py"
  echo -e "Do NOT substitute ~/.claude/plugins/cache/... -- that is not the load path."
  exit 1
fi

echo -e "\n${bold}Plugin Verification Suite${reset}"
echo -e "Root: $PLUGIN_ROOT\n"

# <TICKET>: Resolve repo root (plugin is at plugins/onex/, repo root is ../..)
REPO_ROOT="$(cd "$PLUGIN_ROOT/../.." 2>/dev/null && pwd)"

# CHECK: file_exists — required directories
for dir in skills agents hooks ".claude-plugin"; do
  check "file_exists: $dir" test -d "$PLUGIN_ROOT/$dir"
done
check "file_exists: repo .venv" test -d "$REPO_ROOT/.venv"

# CHECK: file_exists — registry and sentinel files
check "file_exists: installed_plugins.json" test -f "$HOME/.claude/plugins/installed_plugins.json"
check "file_exists: known_marketplaces.json" test -f "$HOME/.claude/plugins/known_marketplaces.json"

# CHECK: load-path truth
#
# This replaces the old "version consistency across 3 surfaces" check, which
# compared plugin.json against installed_plugins.json and the cache current/
# symlink. All three are registry bookkeeping; agreement among them says
# nothing about which hooks execute, and on this box they agreed on 2.3.1
# while the executing hooks.json was two minor versions ahead of the cache.
# The readback below fails on alarm-level tripwires only: a resolution rule
# that stopped holding, a registered-but-missing hook script, or a load-path
# tree behind its upstream (merged-not-deployed).
PLUGIN_VER="$(jq -r '.version // empty' "$PLUGIN_ROOT/.claude-plugin/plugin.json" 2>/dev/null || true)"
READBACK="$PLUGIN_ROOT/hooks/lib/plugin_deploy_readback.py"
check "load_path_readback: no alarm-level tripwire" \
  python3 "$READBACK" --no-fetch
python3 "$READBACK" --no-fetch 2>/dev/null | sed -n '/^TRIPWIRES/,/^VERDICT/p' || true

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

# CHECK: skill naming — all snake_case, no kebab-case dirs (<TICKET>)
kebab_count=0
kebab_count="$(find "$PLUGIN_ROOT/skills" -maxdepth 1 -mindepth 1 -type d \
  -name '*-*' ! -name '_*' 2>/dev/null | wc -l | tr -d ' ')"
check "skill_naming: zero kebab-case dirs (found: $kebab_count)" test "$kebab_count" -eq 0

# CHECK: python_import — venv health (<TICKET>: use repo main venv)
PYTHON="$REPO_ROOT/.venv/bin/python3"
check "python_import: omnibase_spi"       "$PYTHON" -c "import omnibase_spi"
check "python_import: omniclaude"         "$PYTHON" -c "import omniclaude"
check "python_import: TopicBase"          "$PYTHON" -c "from omniclaude.hooks.topics import TopicBase"

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

# CHECK: post-deploy smoke test (<TICKET>)
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
