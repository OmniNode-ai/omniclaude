---
description: Post-deployment verification suite — runs structural and in-session checks to prove the omniclaude plugin is correctly loaded after deploy + restart
mode: full
version: 1.0.0
level: basic
debug: false
category: deployment
tags: [deployment, verification, health]
author: OmniClaude Team
mode: full
---

# Verify Plugin

Run a complete post-deployment verification suite. Report PASS or FAIL for each check category.

> **IMPORTANT:** Run this skill only in a **fresh Claude Code session** opened after the deploy + restart cycle. Running it in a stale session may produce false positives from cached environment state.

## Instructions

1. **Resolve plugin root (portable — no readlink -f):**
   ```bash
   PLUGIN_ROOT=$(python3 -c "import pathlib; print(pathlib.Path('$HOME/.claude/plugins/cache/omninode-tools/onex/current').resolve())")
   echo "Verifying: $PLUGIN_ROOT"
   ```

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
   | Version consistency | command_exit_0 | ✓/✗ | 3 surfaces |
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
