# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PreToolUse dispatch guard for wrong-approach violation prevention (OMN-6230).

Enforces three-tier architectural constraints at tool boundaries:

1. Hard block (high-confidence): hardcoded secrets/connection URLs, raw
   database connection strings, API keys written inline — these are always
   wrong regardless of context.

2. Warn (medium-confidence): implementation file creation that bypasses
   polymorphic-agent dispatch — surfaces a message but does not block,
   because the pattern is ambiguous (worktree setup, tests, etc. are
   legitimate direct writes).

3. CLAUDE.md only (expectation): agent-selection guidance that cannot be
   safely inferred at tool boundaries — not enforced here.

The guard is intentionally conservative on hard blocks: only patterns with
near-zero false-positive rate are blocked. Ambiguous patterns are warnings.

CLI usage (invoked by pre_tool_use_dispatch_guard.sh):

    python3 -m omniclaude.hooks.pre_tool_use_dispatch_guard < tool_input.json

Reads JSON from stdin (Claude Code PreToolUse hook format).
Exits 0 (allow), 1 (warn — allow but emit advisory), or 2 (block).

Output:
    Exit 0: echoes the original JSON to stdout (pass-through).
    Exit 1: prints JSON advisory to stdout, echoes original to stderr.
    Exit 2: prints JSON block decision to stdout.

Related:
    - OMN-6230: Encode Architectural Constraints to Eliminate Wrong-Approach Defaults
    - OMN-6233: Task 4 — extends this module (adds shared _violation_patterns module)
"""

from __future__ import annotations

import json
import re
import sys

# ---------------------------------------------------------------------------
# Hard-block patterns: connection strings / hardcoded credentials
# ---------------------------------------------------------------------------
# These patterns match file *content* that would be written/edited.
# Only trigger when the content is being written to a YAML, env, py, or
# JSON file — not when it appears in a Python comment or docstring (we
# can't distinguish reliably, so we scan the full content string).

_HARDCODED_URL_PATTERNS: list[tuple[str, str]] = [
    # PostgreSQL / psycopg2 / SQLAlchemy connection strings
    (
        r"postgresql(?:\+\w+)?://[^{}\s\"']{6,}",
        "Hardcoded PostgreSQL connection URL detected. "
        "Use Infisical or ~/.omnibase/.env instead of inline credentials.",
    ),
    # Redis connection strings
    (
        r"redis(?:s)?://[^{}\s\"']{4,}",
        "Hardcoded Redis/Valkey connection URL detected. "
        "Use Infisical or ~/.omnibase/.env instead of inline credentials.",
    ),
    # Private IP LLM endpoints hardcoded (192.168.x.x:PORT) # onex-allow-internal-ip # kafka-fallback-ok
    # Allow only in comments — but since we can't reliably detect comments in
    # arbitrary file formats, we match the pattern and note that config files
    # should reference env vars.
    (
        r"http://192\.168\.\d+\.\d+:\d+(?:/\S*)?",
        "Hardcoded private-network LLM endpoint detected. "
        "Reference LLM_CODER_URL / LLM_EMBEDDING_URL env vars instead of inline IPs.",
    ),
    # Passwords / secrets assigned literally in YAML/env style
    (
        r"(?:password|secret|api_key|apikey)\s*[=:]\s*['\"]?[A-Za-z0-9+/]{8,}['\"]?",
        "Hardcoded credential value detected. "
        "Store secrets in Infisical or ~/.omnibase/.env, never inline.",
    ),
]

# ---------------------------------------------------------------------------
# Warn patterns: direct implementation writes that may bypass poly-agent
# ---------------------------------------------------------------------------
# File path suffixes that indicate an ONEX node implementation file.
# Writing these directly (without a polymorphic-agent dispatch) is a
# medium-confidence wrong-approach signal.

_IMPLEMENTATION_FILE_SUFFIXES: tuple[str, ...] = (
    "_effect.py",
    "_compute.py",
    "_reducer.py",
    "_orchestrator.py",
)

_IMPLEMENTATION_DIR_PATTERNS: list[str] = [
    "src/omnibase",
    "src/omniintelligence",
    "src/omnimemory",
    "src/omninode",
    "src/omnibase_infra",
]

# ---------------------------------------------------------------------------
# Tools that carry file content (Edit, Write)
# ---------------------------------------------------------------------------

_CONTENT_TOOLS = {"Edit", "Write"}
_BASH_TOOL = "Bash"


# ---------------------------------------------------------------------------
# Core guard logic
# ---------------------------------------------------------------------------


def _extract_written_content(tool_name: str, tool_input: dict[str, object]) -> str:
    """Return the content string that will be written, or '' if not applicable."""
    if tool_name == "Write":
        return str(tool_input.get("content", ""))
    if tool_name == "Edit":
        # Edit has new_string (the replacement content)
        return str(tool_input.get("new_string", ""))
    if tool_name == _BASH_TOOL:
        return str(tool_input.get("command", ""))
    return ""


def _extract_file_path(tool_name: str, tool_input: dict[str, object]) -> str:
    """Return the target file path for the tool call."""
    if tool_name in ("Write", "Edit"):
        return str(tool_input.get("file_path", ""))
    return ""


def _check_hardcoded_url(content: str) -> tuple[bool, str]:
    """Return (blocked, reason) if a hard-block pattern matches."""
    for pattern, reason in _HARDCODED_URL_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True, reason
    return False, ""


def _check_implementation_bypass(tool_name: str, file_path: str) -> tuple[bool, str]:
    """Return (warn, reason) if a direct implementation file write is detected."""
    if tool_name not in _CONTENT_TOOLS:
        return False, ""
    if not file_path:
        return False, ""

    fp_lower = file_path.lower()

    # Check suffix
    suffix_match = any(fp_lower.endswith(s) for s in _IMPLEMENTATION_FILE_SUFFIXES)
    # Check directory
    dir_match = any(pat in file_path for pat in _IMPLEMENTATION_DIR_PATTERNS)

    if suffix_match and dir_match:
        return (
            True,
            f"Direct write to ONEX node implementation file detected: {file_path}\n"
            "Consider dispatching through onex:polymorphic-agent for ONEX node "
            "creation to ensure intelligence integration and observability.",
        )
    return False, ""


def run_guard(stdin_json: str) -> tuple[int, str]:
    """Run the dispatch guard against hook JSON from stdin.

    Args:
        stdin_json: Raw JSON string from Claude Code PreToolUse hook.

    Returns:
        Tuple of (exit_code, output_json_or_passthrough).
        exit_code 0: allow (output is original JSON).
        exit_code 1: warn (output is advisory JSON; original JSON must be
                     re-emitted by the caller from stderr or re-parsed).
        exit_code 2: block (output is block JSON).
    """
    try:
        hook_data: dict[str, object] = json.loads(stdin_json)
    except json.JSONDecodeError:
        # Can't parse — fail open
        return 0, stdin_json

    tool_name: str = str(hook_data.get("tool_name", ""))
    raw_input = hook_data.get("tool_input", {})
    tool_input: dict[str, object] = raw_input if isinstance(raw_input, dict) else {}

    content = _extract_written_content(tool_name, tool_input)
    file_path = _extract_file_path(tool_name, tool_input)

    # --- Tier 1: Hard block ---
    if content:
        blocked, reason = _check_hardcoded_url(content)
        if blocked:
            block_json = json.dumps(
                {
                    "decision": "block",
                    "reason": (
                        f"[dispatch-guard] BLOCKED — {reason}\n\n"
                        "Fix: reference environment variables (Infisical / ~/.omnibase/.env) "
                        "instead of hardcoding connection strings or credentials."
                    ),
                }
            )
            return 2, block_json

    # --- Tier 2: Warn (allow, but surface advisory) ---
    warned, warn_reason = _check_implementation_bypass(tool_name, file_path)
    if warned:
        # Exit 1 — shell script will print advisory to stderr and still allow
        advisory_json = json.dumps(
            {
                "decision": "warn",
                "reason": f"[dispatch-guard] ADVISORY — {warn_reason}",
            }
        )
        return 1, advisory_json

    # --- Pass through ---
    return 0, stdin_json


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the dispatch guard.

    Reads hook JSON from stdin. Writes output to stdout.
    Returns exit code: 0 allow, 1 warn, 2 block.
    """
    stdin_data = sys.stdin.read()
    exit_code, output = run_guard(stdin_data)
    print(output)  # noqa: T201
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
