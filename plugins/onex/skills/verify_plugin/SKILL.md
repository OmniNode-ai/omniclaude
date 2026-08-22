---
description: Post-deployment verification suite — runs structural and in-session checks to prove the omniclaude plugin is correctly loaded after deploy + restart
mode: full
version: 1.0.0
level: basic
debug: false
category: deployment
tags: [deployment, verification, health]
author: OmniClaude Team
---

# Verify Plugin

Run a complete post-deployment verification suite. Report PASS or FAIL for each check category.

> **IMPORTANT:** Run this skill only in a **fresh Claude Code session** opened after the deploy + restart cycle. Running it in a stale session may produce false positives from cached environment state.

> **Do not resolve the plugin root from `~/.claude/plugins/`.** Neither
> `installed_plugins.json` nor `plugins/cache/<marketplace>/<plugin>/current` is guaranteed to be
> the load path. For a `directory`-source marketplace, `${CLAUDE_PLUGIN_ROOT}` resolves to the
> marketplace's own `installLocation` — the source checkout — and the cache is never read. A cache
> tree observed in the field was 24 days stale and carried a `hooks.json` two minor versions
> behind the one executing. Verifying the cache verifies a tree that does not run.

## Instructions

1. **Read back the real load path (step 0 — everything else depends on it):**
   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/hooks/lib/plugin_deploy_readback.py"
   ```
   This resolves the load path the way Claude Code does
   (`known_marketplaces.json` → source type → `installLocation` → `marketplace.json` plugin
   `source`) and prints, per agent class (main session / `Task()` subagent / Workflow `agent()`
   subagent): the resolved root, the loaded `hooks.json` version, every registered hook with an
   EXEC-OK check, and the behind/dirty state of the load-path tree vs its upstream.

   Report its **VERDICT** line and every tripwire verbatim. In particular:
   - `MERGED_NOT_DEPLOYED` — the tree is behind upstream. For a directory source there is no
     install step, so `git -C <load path repo> pull --ff-only` *is* the deploy. A merged hook is
     not a live hook.
   - `LOAD_PATH_MISMATCH` — expected today; it means the registry is lying, not that the plugin
     is broken.
   - `RESOLUTION_RULE_CHANGED` — stop. The load path moved. Re-derive it from
     `known_marketplaces.json` before reporting any verdict; do not report a result from the
     previous assumption.

   Then bind the rest of the suite to the path it resolved — **fail closed**, because a suite
   that runs against an empty or wrong `PLUGIN_ROOT` produces the confident-but-false verdict
   this step exists to prevent:
   ```bash
   READBACK="$CLAUDE_PLUGIN_ROOT/hooks/lib/plugin_deploy_readback.py"
   RB_JSON=$(python3 "$READBACK" --json --no-fetch); rb_rc=$?
   if [ "$rb_rc" -eq 1 ]; then
     echo "ABORT: load path unresolvable — report the readback output, run nothing else."; exit 1
   fi
   PLUGIN_ROOT=$(printf '%s' "$RB_JSON" \
     | python3 -c 'import json,sys; print(json.load(sys.stdin).get("resolved_load_path") or "")')
   if [ -z "$PLUGIN_ROOT" ] || [ ! -d "$PLUGIN_ROOT" ]; then
     echo "ABORT: resolved_load_path empty or not a directory — do not fall back to the cache."; exit 1
   fi
   echo "Verifying: $PLUGIN_ROOT"
   ```
   Exit 3 (alarm-level tripwire) is **not** an abort — it is a finding to report alongside the
   rest of the suite.

2. **Run structural checks (Layer 1):**
   ```bash
   bash "$PLUGIN_ROOT/skills/verify_plugin/verify-deploy.sh"
   ```
   Report the exit code and full output verbatim.

3. **In-session behavioral checks (Layer 2):**

   a. **Poly enforcer — weak indirect signal**
   The fact that this skill is running does not prove the enforcer is fully functional. It only proves the current invocation was not blocked. Report this as "enforcer did not block this session" rather than "enforcer is active."
   ```bash
   # Check the hook script exists and is executable
   ls -la "$PLUGIN_ROOT/hooks/scripts/pre_tool_use_poly_enforcer.sh" 2>/dev/null || echo "NOT FOUND"
   ```

   b. **Session-start context injected:**
   ```bash
   echo "CLAUDE_PLUGIN_ROOT=${CLAUDE_PLUGIN_ROOT:-(NOT SET)}"
   ```

   c. **Hook runtime daemon — probe via plugin venv Python (portable, not nc -U):**
   ```bash
   SOCKET="$PLUGIN_ROOT/hooks/hook-runtime.sock"
   export PLUGIN_SOCK="$SOCKET"
   "$PLUGIN_ROOT/lib/.venv/bin/python3" - <<'PYEOF'
   import socket, os, json, sys
   sock_path = os.environ.get("PLUGIN_SOCK", "")
   if not sock_path or not os.path.exists(sock_path):
       print(f"socket not found at {sock_path} (daemon may not be running)")
       sys.exit(0)
   try:
       with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
           s.settimeout(2)
           s.connect(sock_path)
           s.sendall(json.dumps({"action": "ping"}).encode())
           resp = s.recv(1024)
           print(f"daemon responded: {resp.decode()!r}")
   except Exception as e:
       print(f"daemon probe failed: {e}")
   PYEOF
   ```

   d. **Python venv accessible from hook context:**
   ```bash
   "$PLUGIN_ROOT/lib/.venv/bin/python3" -c \
     "import omniclaude; print(f'omniclaude version: {omniclaude.__version__}')"
   ```

   e. **Skill count sanity check (rough proxy only — does not prove discovery or registry resolution):**
   ```bash
   count=$(ls "$PLUGIN_ROOT/skills/" | grep -v '^_' | wc -l | tr -d ' ')
   echo "Skill directories: $count"
   # Threshold: set this to (current count at deploy time) and update when skills are added/removed.
   # This is a floor check, not a contract. It catches accidental mass-deletion, not individual corruption.
   [[ "$count" -ge 90 ]] && echo "✓ skill count ok" || echo "✗ skill count too low (expected ≥ 90)"
   ```

4. **Report summary table:**

   | Check | Type | Status | Notes |
   |-------|------|--------|-------|
   | File structure | file_exists | ✓/✗ | |
   | Load-path readback | command_exit_0 | ✓/✗ | resolved root + hooks.json version + tripwires |
   | JSON validity | command_exit_0 | ✓/✗ | |
   | Skill naming (snake_case) | command_exit_0 | ✓/✗ | |
   | Python venv imports | python_import | ✓/✗ | |
   | No editable installs | command_exit_0 | ✓/✗ | |
   | Hook smoke (exec+shape) | command_exit_0 | ✓/✗ | N hooks, structural only |
   | Settings consistency | file_exists | ✓/✗ | compatibility sanity |
   | Enforcer hook exists | file_exists | ✓/✗ | weak indirect signal |
   | Session context injected | in_session | ✓/✗ | |
   | Hook runtime daemon | python_socket | ✓/✗ | informational |
   | Skill count | in_session | ✓/✗ | rough floor check |

5. **Final verdict:** Output `✓ PLUGIN VERIFIED` or `✗ VERIFICATION FAILED (N checks failed)`.

---

## Routing Contract

- **Classification**: Deterministic
- **Backing node**: `node_verify_effect`
- **Dispatch**: `onex node node_verify_effect`

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose.
