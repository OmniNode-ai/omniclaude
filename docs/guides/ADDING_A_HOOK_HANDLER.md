# Adding a Hook Handler

## Overview

Hook handlers are Python modules in `plugins/onex/hooks/lib/`. They are called
by the shell hook scripts in `plugins/onex/hooks/scripts/`.

Hook configuration lives in `plugins/onex/hooks/hooks.json`. Each hook type
(`SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`)
maps to one or more shell scripts, which in turn call Python handler modules.

---

## Step 1: Create the Python Module

Create `plugins/onex/hooks/lib/handler_my_feature.py`:

```python
from __future__ import annotations
import sys
import json
from typing import Any


def handle(hook_input: dict[str, Any]) -> dict[str, Any]:
    """
    Process a hook event.

    Returns output dict or empty dict to pass through unchanged.
    The caller (shell script) writes this to stdout and exits 0.
    """
    # Your logic here
    return {}


if __name__ == "__main__":
    data = json.load(sys.stdin)
    result = handle(data)
    json.dump(result, sys.stdout)
```

**Key requirements:**

- Always return a `dict`. An empty dict means "pass through unchanged."
- Never raise unhandled exceptions — catch and log internally.
- Never block on Kafka or network I/O in the sync path. See Performance Budget below.
- Exit 0 on infrastructure failure. Data loss is acceptable; UI freeze is not.

---

## Step 2: Wire to hooks.json

In `plugins/onex/hooks/hooks.json`, add your handler to the appropriate hook.
The file uses `${CLAUDE_PLUGIN_ROOT}` to reference the plugin root, which
Claude Code injects automatically.

**For PostToolUse (with a tool matcher):**

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "^(Read|Write|Edit|Bash)$",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-tool-use-quality.sh"
          }
        ]
      }
    ]
  }
}
```

The `matcher` field is a regex matched against the tool name. Omit it to match
all tools. The actual Python handler is called from the shell script, not
referenced directly in `hooks.json`.

**To call your Python handler from a shell script**, add an invocation inside
the relevant script in `plugins/onex/hooks/scripts/`. For example, inside
`post-tool-use-quality.sh`:

```bash
python "$PLUGIN_LIB/handler_my_feature.py" < /dev/stdin
```

---

## Step 3: Write a Unit Test

Create `tests/unit/hooks/lib/test_handler_my_feature.py`:

```python
import pytest
from handler_my_feature import handle


@pytest.mark.unit
def test_handle_returns_dict_on_minimal_input():
    result = handle({"sessionId": "test-123", "tool_name": "Read"})
    assert isinstance(result, dict)


@pytest.mark.unit
def test_handle_does_not_raise_on_missing_keys():
    result = handle({})
    assert isinstance(result, dict)
```

The `plugins/onex/hooks/lib/` directory is added to `sys.path` by
`tests/conftest.py`, so handler modules can be imported directly by name.

Run the test:

```bash
uv run pytest tests/unit/hooks/lib/test_handler_my_feature.py -v
```

---

## Step 4: Deploy and Verify

Deploy the plugin to the Claude Code plugin cache:

```
/deploy-local-plugin
```

Start a new Claude Code session. The hook will fire on the next matching
lifecycle event.

---

## Step 5: Check Logs

Hook failures are logged to `~/.claude/hooks.log` when `LOG_FILE` is set.

```bash
tail -f ~/.claude/hooks.log
```

Common issues:

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Handler not called | Shell script not updated | Add the Python invocation to the `.sh` script |
| `ModuleNotFoundError` | Wrong Python interpreter | Check `find_python()` logic; set `OMNICLAUDE_PROJECT_ROOT` |
| Hook exits non-zero | Unhandled exception | Wrap handler body in `try/except`; return `{}` on error |

---

## Performance Budget

| Hook | Sync Budget | What Blocks |
|------|-------------|-------------|
| SessionStart | <50ms | Daemon check, stdin read |
| SessionEnd | <50ms | stdin read |
| UserPromptSubmit | <500ms typical (~15s worst-case with delegation) | Routing, context injection, pattern advisory, local delegation |
| PostToolUse | <100ms | stdin read, quality check |

If your handler takes longer than the budget, it must fire-and-forget
(background the work and return `{}` immediately).

See `CLAUDE.md` Performance Budgets section for the full breakdown including
worst-case paths.

---

## Reference

- Hook configuration: `plugins/onex/hooks/hooks.json`
- Shell scripts: `plugins/onex/hooks/scripts/`
- Handler modules: `plugins/onex/hooks/lib/`
- Public entrypoints: `emit_client_wrapper.py`, `context_injection_wrapper.py`,
  `route_via_events_wrapper.py`, `correlation_manager.py`
- Failure mode table: `CLAUDE.md` Failure Modes section
