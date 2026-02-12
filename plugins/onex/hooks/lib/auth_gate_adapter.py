#!/usr/bin/env python3
"""PreToolUse Authorization Gate Adapter.

Reads tool invocation JSON from stdin, checks authorization state,
outputs a PreToolUse hook response to stdout.
Exit codes: 0 = allow, 1 = deny (shell shim converts to exit 2).
"""

import fnmatch
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

WHITELISTED_PATTERNS = [
    "**/CLAUDE.md",
    "**/MEMORY.md",
    "**/memory/**",
    "**/plans/**",
    "**/docs/**",
    "/tmp/omniclaude-tabs/**",  # noqa: S108 — intentional: shared hook state dir
    "/tmp/omniclaude-auth/**",  # noqa: S108 — intentional: auth state dir
]
AUTH_DIR = "/tmp/omniclaude-auth"  # noqa: S108 — intentional: session-scoped auth state


def _path_matches_pattern(file_path: str, pattern: str) -> bool:
    """Check if file_path matches a glob pattern (supports ** prefixes).

    fnmatch treats * as "any characters" but ** has no special meaning,
    so **/docs/** won't match a relative path like docs/README.md.
    We handle this by also trying the pattern with the **/ prefix stripped.
    """
    if fnmatch.fnmatch(file_path, pattern):
        return True
    # Strip **/ prefix and retry (matches relative paths starting at the dir)
    if pattern.startswith("**/"):
        if fnmatch.fnmatch(file_path, pattern[3:]):
            return True
    # Check basename only for patterns ending in a concrete filename
    # (skip patterns ending in ** like **/memory/**)
    tail = pattern.rsplit("/", 1)[-1]
    if tail and tail != "**" and not tail.endswith("/**"):
        if fnmatch.fnmatch(PurePosixPath(file_path).name, tail):
            return True
    return False


def _is_whitelisted(file_path: str) -> bool:
    return any(_path_matches_pattern(file_path, p) for p in WHITELISTED_PATTERNS)


def _detect_mode() -> str:
    raw = os.environ.get("ENABLE_AUTH_GATE", "").strip().lower()
    if raw == "strict":
        return "strict"
    return "enforce" if raw == "true" else "warn"


def _load_auth(session_id: str) -> dict | None:
    auth_path = Path(AUTH_DIR) / f"{session_id}.json"
    if not auth_path.is_file():
        return None
    try:
        with auth_path.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def decide(tool_name: str, file_path: str, session_id: str, mode: str) -> dict:
    """Return authorization decision: {decision, reason, mode}."""
    # 1. Whitelisted path -- always allow
    if _is_whitelisted(file_path):
        return {"decision": "allow", "reason": "whitelisted_path", "mode": mode}
    # 2. Load auth file
    auth = _load_auth(session_id)
    # 3. No auth file
    if auth is None:
        if mode == "warn":
            return {"decision": "allow", "reason": "no_auth_warn_mode", "mode": mode}
        return {"decision": "deny", "reason": "no_authorization", "mode": mode}
    # 4. Auth expired?
    try:
        expires_at = datetime.fromisoformat(
            auth.get("expires_at", "").replace("Z", "+00:00")
        )
        if expires_at < datetime.now(UTC):
            if mode == "warn":
                return {
                    "decision": "allow",
                    "reason": "auth_expired_warn_mode",
                    "mode": mode,
                }
            return {"decision": "deny", "reason": "authorization_expired", "mode": mode}
    except (ValueError, AttributeError):
        if mode == "warn":
            return {
                "decision": "allow",
                "reason": "auth_expired_warn_mode",
                "mode": mode,
            }
        return {"decision": "deny", "reason": "authorization_expired", "mode": mode}
    # 5. All checks pass
    return {"decision": "allow", "reason": "authorized", "mode": mode}


def _build_output(decision: str, reason: str) -> dict:
    if decision == "allow":
        reason_text = f"Authorization valid: {reason}"
    else:
        reason_text = (
            f"Edit/Write blocked: {reason}. "
            "Run /authorize [reason] to grant authorization."
        )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason_text,
        }
    }


def _error_output(decision: str, msg: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": msg,
        }
    }


def main() -> None:
    mode = _detect_mode()
    try:
        data = json.loads(sys.stdin.read())
        tool_name = data.get("tool_name", "unknown")
        tool_input = data.get("tool_input", {})
        file_path = tool_input.get("file_path", tool_input.get("path", ""))
        session_id = os.environ.get(
            "SESSION_ID", data.get("session_id", data.get("sessionId", ""))
        )
        result = decide(tool_name, file_path, session_id, mode)
        print(json.dumps(_build_output(result["decision"], result["reason"])))
        sys.exit(0 if result["decision"] == "allow" else 1)
    except Exception as exc:
        print(f"auth_gate_adapter error: {exc}", file=sys.stderr)
        if mode == "strict":
            print(
                json.dumps(_error_output("deny", f"Authorization check failed: {exc}"))
            )
            sys.exit(1)
        print(
            json.dumps(
                _error_output("allow", f"Authorization check error (fail-open): {exc}")
            )
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
