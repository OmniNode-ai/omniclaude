# Tutorial: Adding a Custom PostToolUse Handler

This tutorial walks through adding a new PostToolUse handler module from scratch.
By the end you will have:

- A Python module in `plugins/onex/hooks/lib/`
- A registration entry in `plugins/onex/hooks/hooks.json`
- A unit test following the project's conftest patterns
- A deployed and verified handler in a live Claude Code session

---

## Before You Start

Understand the PostToolUse hook contract:

- Claude Code calls the hook script after every matched tool execution.
- The script receives a JSON blob on stdin and must pass it through to stdout.
- The hook **must exit 0** — any non-zero exit blocks the tool result from
  reaching Claude.
- The performance budget is **< 100 ms** on the synchronous path. Use
  background subshells (`( ... ) &`) for any work that may be slow.

The existing handler script is `plugins/onex/hooks/scripts/post-tool-use-quality.sh`.
Rather than modifying that script, you will add a new Python module and invoke
it from the script, or create a second hook entry in `hooks.json` targeting the
same or a narrower tool matcher.

---

## Step 1: Create a Python Module in `plugins/onex/hooks/lib/`

Create `plugins/onex/hooks/lib/my_tool_observer.py`:

```python
#!/usr/bin/env python3
"""my_tool_observer — example PostToolUse handler.

Logs a summary line for each matched tool execution. Designed as a
non-blocking, non-raising module suitable for use inside the PostToolUse hook.

Design constraints (from CLAUDE.md):
    - Never raise exceptions — callers rely on silent failure.
    - Never block on Kafka or network I/O synchronously.
    - Performance budget: < 100 ms total for the sync hook path.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def observe_tool_execution(tool_info: dict[str, Any]) -> None:
    """Process a single PostToolUse event.

    Args:
        tool_info: Parsed JSON payload from Claude Code (stdin to the hook).
            Keys present: ``tool_name``, ``tool_input``, ``tool_response``,
            ``sessionId``.

    Returns:
        None. All output goes to the log; never to stdout (that is reserved
        for passing ``tool_info`` back to Claude Code unmodified).
    """
    tool_name: str = tool_info.get("tool_name", "unknown")
    session_id: str = tool_info.get("sessionId", "")
    file_path: str = tool_info.get("tool_input", {}).get("file_path", "")
    error: str = tool_info.get("tool_response", {}).get("error", "") or ""

    status = "error" if error else "ok"
    logger.info(
        "tool_observed tool=%s file=%s session=%s status=%s",
        tool_name,
        file_path or "(none)",
        session_id[:8],
        status,
    )


def main() -> int:
    """CLI entry point — reads tool_info JSON from stdin, returns 0 always."""
    try:
        raw = sys.stdin.read()
        tool_info: dict[str, Any] = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("my_tool_observer: malformed stdin JSON: %s", exc)
        return 0

    try:
        observe_tool_execution(tool_info)
    except Exception as exc:  # noqa: BLE001
        # Non-blocking: log and continue regardless of error type.
        logger.warning("my_tool_observer: unhandled error: %s", exc)

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    sys.exit(main())


__all__ = ["observe_tool_execution", "main"]
```

Key points in this skeleton:

- `observe_tool_execution` is the testable unit. It never calls `sys.exit` or
  writes to stdout.
- `main` handles the stdin/stdout contract required by the hook. It always
  returns 0.
- Errors are caught and logged, never re-raised.

---

## Step 2: Invoke the Module from the Hook Script

You have two options:

### Option A: Add a new hook entry in `hooks.json` (preferred for new handlers)

This keeps your handler isolated. Add a second entry under `PostToolUse`:

```json
"PostToolUse": [
  {
    "matcher": "^(Read|Write|Edit|Bash|Glob|Grep|Task|Skill|WebFetch|WebSearch|NotebookEdit|NotebookRead)$",
    "hooks": [
      {
        "type": "command",
        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-tool-use-quality.sh"
      }
    ]
  },
  {
    "matcher": "^(Write|Edit)$",
    "hooks": [
      {
        "type": "command",
        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/my-tool-observer.sh"
      }
    ]
  }
]
```

Then create `plugins/onex/hooks/scripts/my-tool-observer.sh`:

```bash
#!/bin/bash
# my-tool-observer.sh — Invokes my_tool_observer.py for Write/Edit events.
set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOKS_LIB="${PLUGIN_ROOT}/hooks/lib"

# Find Python (same approach as common.sh)
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"

# Read stdin (the tool info JSON)
TOOL_INFO=$(cat)

# Invoke the module (async, non-blocking)
(
    echo "$TOOL_INFO" | PYTHONPATH="${HOOKS_LIB}:${PYTHONPATH:-}" \
        "$PYTHON_CMD" "${HOOKS_LIB}/my_tool_observer.py"
) &

# Always pass the original tool info through
printf '%s\n' "$TOOL_INFO"
exit 0
```

Make it executable:

```bash
chmod +x plugins/onex/hooks/scripts/my-tool-observer.sh
```

### Option B: Call from the existing `post-tool-use-quality.sh`

Add an invocation block inside the existing script, following the same
backgrounded subshell pattern already used for Kafka emission. Consult the
existing script for context — look for the `( ... ) &` pattern.

This option is appropriate for small additions that logically belong with the
existing quality hook. Option A is preferred for independent handlers.

---

## Step 3: Write a Unit Test

Place the test in `tests/unit/hooks/lib/test_my_tool_observer.py`. The project
`conftest.py` adds `plugins/onex/hooks/lib` to `sys.path` automatically, so
imports work without extra path manipulation.

```python
"""Unit tests for my_tool_observer.py.

Tests cover:
    - Normal execution (Write tool, no error)
    - Error-response passthrough (hook still returns 0)
    - Missing keys in tool_info (defensive parsing)
    - Malformed JSON stdin (main() does not raise)
"""
from __future__ import annotations

import io
import json
import logging
from unittest.mock import patch

import pytest

import my_tool_observer
from my_tool_observer import main, observe_tool_execution

# All tests in this module are unit tests — no live services required.
pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_tool_info(
    tool_name: str = "Write",
    file_path: str = "/tmp/example.py",
    session_id: str = "test-session-abc123",
    error: str | None = None,
) -> dict:
    """Build a minimal PostToolUse payload."""
    response: dict = {}
    if error:
        response["error"] = error

    return {
        "tool_name": tool_name,
        "sessionId": session_id,
        "tool_input": {"file_path": file_path, "content": "# placeholder"},
        "tool_response": response,
    }


# ---------------------------------------------------------------------------
# observe_tool_execution
# ---------------------------------------------------------------------------


class TestObserveToolExecution:
    def test_logs_ok_for_successful_write(self, caplog):
        tool_info = _make_tool_info(tool_name="Write", file_path="/tmp/foo.py")
        with caplog.at_level(logging.INFO, logger="my_tool_observer"):
            observe_tool_execution(tool_info)

        assert any("status=ok" in r.message for r in caplog.records)
        assert any("tool=Write" in r.message for r in caplog.records)

    def test_logs_error_when_tool_response_has_error(self, caplog):
        tool_info = _make_tool_info(error="File not found")
        with caplog.at_level(logging.INFO, logger="my_tool_observer"):
            observe_tool_execution(tool_info)

        assert any("status=error" in r.message for r in caplog.records)

    def test_handles_empty_tool_info_gracefully(self):
        # Should not raise even with a completely empty dict.
        observe_tool_execution({})

    def test_handles_missing_tool_response_key(self):
        # tool_response key absent — should not raise.
        observe_tool_execution({"tool_name": "Bash", "sessionId": "s1"})

    def test_session_id_truncated_in_log(self, caplog):
        long_session = "a" * 64
        tool_info = _make_tool_info(session_id=long_session)
        with caplog.at_level(logging.INFO, logger="my_tool_observer"):
            observe_tool_execution(tool_info)

        # Only the first 8 characters should appear
        assert any("session=aaaaaaaa" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMain:
    def test_returns_0_on_valid_input(self, monkeypatch):
        payload = json.dumps(_make_tool_info())
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        assert main() == 0

    def test_returns_0_on_empty_stdin(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert main() == 0

    def test_returns_0_on_malformed_json(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("{not valid json"))
        assert main() == 0

    def test_returns_0_when_observe_raises(self, monkeypatch):
        payload = json.dumps(_make_tool_info())
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        with patch.object(my_tool_observer, "observe_tool_execution", side_effect=RuntimeError("boom")):
            assert main() == 0
```

Run the tests:

```bash
uv run pytest tests/unit/hooks/lib/test_my_tool_observer.py -v -m unit
```

Expected output:

```
tests/unit/hooks/lib/test_my_tool_observer.py::TestObserveToolExecution::test_logs_ok_for_successful_write PASSED
tests/unit/hooks/lib/test_my_tool_observer.py::TestObserveToolExecution::test_logs_error_when_tool_response_has_error PASSED
...
5 passed in 0.12s
```

---

## Step 4: Deploy and Verify in a Live Session

### Deploy

From within a Claude Code session in this project:

```
/deploy-local-plugin
```

This copies `plugins/onex/` into `~/.claude/plugins/cache/`. No restart of
Claude Code is required — the updated hook scripts take effect on the next
tool call.

### Trigger the hook

Ask Claude to edit or write a file, for example:

```
Write a hello world Python script to /tmp/hello.py
```

### Verify the handler ran

The handler logs to stderr of its subshell. To capture that output, check
the pipe from the hook script. If you added `2>> "$LOG_FILE"` to the
subshell in your `.sh` script, look there:

```bash
tail -f plugins/onex/hooks/logs/post-tool-use.log
```

You should see a line from `my_tool_observer` appearing within a second of the
Write tool completing.

Alternatively, add a temporary `print` or file-write to `observe_tool_execution`
during development, then remove it before committing.

---

## Step 5: What to Do if the Hook Does Not Trigger

Work through this checklist in order:

1. **Check the tool matcher.** Confirm your `hooks.json` entry's `matcher`
   regex matches the tool Claude used. For a `Write` tool call, the matcher
   `^(Write|Edit)$` must match literally. Test with:

   ```bash
   echo "Write" | grep -P "^(Write|Edit)$" && echo "matches"
   ```

2. **Validate `hooks.json` syntax.**

   ```bash
   jq . plugins/onex/hooks/hooks.json
   ```

   Any parse error prevents all hooks from loading.

3. **Check script permissions.**

   ```bash
   ls -la plugins/onex/hooks/scripts/my-tool-observer.sh
   ```

   Must have execute bit set. Fix with `chmod +x`.

4. **Check `hooks.log` for Python interpreter errors.**

   ```bash
   cat ~/.claude/hooks.log | grep -i "my_tool_observer\|error\|exit 1"
   ```

   Exit code 1 from any hook is logged by Claude Code. The only legitimate
   reason to exit 1 is if no valid Python interpreter is found. Set
   `PLUGIN_PYTHON_BIN` to an absolute path to override interpreter resolution.

5. **Confirm the plugin cache was updated.** After `/deploy-local-plugin`,
   check that the new script exists in the cache:

   ```bash
   ls ~/.claude/plugins/cache/hooks/scripts/my-tool-observer.sh
   ```

6. **Confirm PYTHONPATH includes the lib directory.** In the shell script,
   `PYTHONPATH` must include `${HOOKS_LIB}` so `import my_tool_observer`
   resolves. Verify with:

   ```bash
   HOOKS_LIB="plugins/onex/hooks/lib" \
       PYTHONPATH="${HOOKS_LIB}" \
       python -c "import my_tool_observer; print('import OK')"
   ```

---

## Reference: Hook Data Contract

Your handler receives a JSON object on stdin with this shape:

```json
{
  "sessionId": "uuid-string",
  "tool_name": "Write",
  "tool_input": {
    "file_path": "/absolute/path/to/file.py",
    "content": "..."
  },
  "tool_response": {
    "filePath": "/absolute/path/to/file.py"
  }
}
```

For `Edit` tools, `tool_input` contains `file_path`, `old_string`, and
`new_string` instead of `content`. For `Read`, `tool_response` contains
`content`. Always use `.get()` with defaults — Claude Code may add or remove
fields across versions.

Your hook script must write the original `tool_info` JSON back to stdout
unchanged. Modifying stdout output changes what Claude Code sees as the tool
result.

---

## Reference: Where Things Live

| Artifact | Location |
|----------|----------|
| Python handler module | `plugins/onex/hooks/lib/<name>.py` |
| Shell wrapper script | `plugins/onex/hooks/scripts/<name>.sh` |
| Hook registration | `plugins/onex/hooks/hooks.json` |
| Unit tests | `tests/unit/hooks/lib/test_<name>.py` |
| Hook logs (PostToolUse) | `plugins/onex/hooks/logs/post-tool-use.log` |
| Pipeline trace log | `~/.claude/logs/pipeline-trace.log` |
| Emit daemon log | `~/.claude/hooks.log` (if `LOG_FILE` is set) |

See [CLAUDE.md](../../CLAUDE.md) "Where to Change Things" for the complete
reference table.
