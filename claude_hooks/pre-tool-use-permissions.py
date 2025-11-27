#!/usr/bin/env python3
"""
Pre-Tool-Use Permission Hook Skeleton for Phase 2 (OMN-95)

This script provides the foundation for intelligent permission management
in Claude Code hooks. It will be expanded during Phase 2 to implement:
- Smart permission caching
- Destructive command detection
- Safe path analysis
- Dynamic permission decisions
- Rate limiting (see RATE_LIMIT_* constants)

Current State: Skeleton that passes through all requests (Phase 1 preparation)

Rate Limiting Strategy:
-----------------------
Claude Code enforces a 5000ms (5 second) hook timeout, which provides implicit
rate limiting - hooks cannot execute more than ~12 times per minute in the
worst case. However, in practice:
1. Most hook executions complete in <50ms
2. The timeout acts as a backstop for runaway hooks
3. Phase 2 will implement explicit rate limiting for additional protection

Phase 2 will add:
- Token bucket rate limiting (10 requests/second default)
- Sliding window tracking for burst detection
- Configurable limits via environment variables
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional


# =============================================================================
# CONSTANTS - Paths
# =============================================================================

# Claude settings and cache paths
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CACHE_PATH = Path.home() / ".claude" / ".cache" / "permission-cache.json"

# =============================================================================
# CONSTANTS - Timeouts and Rate Limiting
# =============================================================================

# Claude Code hook timeout (enforced by Claude Code, not this script)
# This provides implicit rate limiting - hooks cannot block indefinitely
# Reference: https://docs.anthropic.com/en/docs/claude-code/hooks
CLAUDE_HOOK_TIMEOUT_MS = 5000  # 5 seconds - enforced by Claude Code

# Rate limiting constants for Phase 2 implementation
# These provide defense-in-depth beyond the hook timeout
RATE_LIMIT_REQUESTS_PER_SECOND = 10  # Max requests per second (Phase 2)
RATE_LIMIT_BURST_SIZE = 20  # Allow short bursts up to this size (Phase 2)
RATE_LIMIT_WINDOW_SECONDS = 60  # Sliding window for tracking (Phase 2)

# =============================================================================
# CONSTANTS - Safe Temporary Directories
# =============================================================================

# POLICY: Always use local ./tmp directory, never system /tmp
# This ensures:
# 1. Temp files are contained within the repository
# 2. No pollution of system temp directories
# 3. Easy cleanup with git clean
# 4. Consistent behavior across environments

SAFE_TEMP_DIRS = frozenset(
    [
        "./tmp",  # Local repository temp directory (PREFERRED)
        "tmp",  # Relative tmp without ./
        ".claude-tmp",  # Claude-specific local temp
        ".claude/tmp",  # Claude cache temp
        "/dev/null",  # Always safe - discards output
    ]
)

# Additional patterns for safe temp paths (compiled once)
SAFE_TEMP_PATTERNS = [
    re.compile(r"^\./tmp/"),  # Local ./tmp/ directory
    re.compile(r"^tmp/"),  # Relative tmp/
    re.compile(r"/\.claude-tmp/"),  # .claude-tmp anywhere in path
    re.compile(r"/\.claude/tmp/"),  # .claude/tmp anywhere in path
]


def ensure_local_tmp_exists() -> Path:
    """
    Ensure the local ./tmp directory exists in the current working directory.

    This is called by hooks and skills to ensure temp files go to the
    repository-local tmp directory instead of system /tmp.

    Returns:
        Path to the local tmp directory.

    Raises:
        None explicitly - directory creation uses exist_ok=True.

    Example:
        >>> tmp_dir = ensure_local_tmp_exists()
        >>> tmp_dir.exists()
        True
    """
    local_tmp = Path.cwd() / "tmp"
    if not local_tmp.exists():
        local_tmp.mkdir(parents=True, exist_ok=True)
        # Create .gitignore if it doesn't exist
        gitignore = local_tmp / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("# Ignore all temp files\n*\n!.gitignore\n")
    return local_tmp


# =============================================================================
# CONSTANTS - Destructive Command Patterns (Improved Regex)
# =============================================================================

# SECURITY NOTE: Defense-in-Depth, NOT a Security Boundary
# =========================================================
# These patterns provide a FIRST LINE OF DEFENSE against accidental destructive
# commands. They are NOT designed to be a comprehensive security boundary.
#
# KNOWN LIMITATIONS AND BYPASS VECTORS:
# -------------------------------------
# These patterns CAN be bypassed by determined or creative users. Known methods:
#
# 1. Variable expansion:
#    - CMD=rm; $CMD -rf /
#    - ${CMD:-rm} -rf /
#    - export X=rm; $X file
#
# 2. Command substitution:
#    - $(echo rm) -rf /
#    - `echo rm` -rf /
#    - $(printf 'rm') file
#
# 3. Character escaping/quoting:
#    - r\m -rf /
#    - 'r'm -rf /
#    - r""m -rf /
#
# 4. Alias/function tricks:
#    - alias x=rm; x -rf /
#    - function x { rm "$@"; }; x file
#
# 5. Indirect execution:
#    - /bin/rm file (partially covered by patterns below)
#    - command rm file
#    - builtin eval 'rm file'
#    - xargs rm < filelist
#
# 6. Encoding tricks:
#    - echo cm0gLXJmIC8= | base64 -d | sh
#    - printf '\x72\x6d' | sh
#
# WHY THIS IS STILL VALUABLE:
# ---------------------------
# - Catches accidental destructive commands (the 99% case)
# - Provides clear signal for audit/logging purposes
# - Raises awareness before executing dangerous operations
# - Works as part of a layered security approach
#
# For true security boundaries, rely on:
# - OS-level permissions
# - Sandboxing/containerization
# - Claude Code's built-in permission system
# - User confirmation dialogs
#
# Pattern Design:
# - Use word boundaries and command separators to avoid matching substrings
# - Account for command chaining with ;, &&, ||, |
# - Match commands at start of line or after separators

DESTRUCTIVE_PATTERNS = [
    # rm command - avoid matching 'rm' in words like 'form', 'transform'
    # Matches: rm, rm -rf, rm -f, etc. at start or after separator
    # Also matches /bin/rm, /usr/bin/rm for absolute path invocation
    re.compile(
        r"(?:^|[;&|]\s*)(?:/(?:usr/)?bin/)?rm\s+(?:-[rfivdP]+\s+)*", re.MULTILINE
    ),
    # rmdir command - remove directories
    re.compile(r"(?:^|[;&|]\s*)(?:/(?:usr/)?bin/)?rmdir\s+", re.MULTILINE),
    # dd command - disk destroyer, often used for data wiping
    # Avoid matching 'add', 'odd', etc.
    re.compile(r"(?:^|[;&|]\s*)(?:/(?:usr/)?bin/)?dd\s+", re.MULTILINE),
    # mkfs command - format filesystems
    re.compile(
        r"(?:^|[;&|]\s*)(?:/(?:usr/)?s?bin/)?mkfs(?:\.[a-z0-9]+)?\s+", re.MULTILINE
    ),
    # Dangerous redirects - truncating files
    re.compile(
        r">\s*/(?!dev/null)", re.MULTILINE
    ),  # redirect to root paths except /dev/null
    # curl/wget piped to shell - remote code execution
    re.compile(r"(?:curl|wget)\s+[^|]*\|\s*(?:ba)?sh", re.MULTILINE),
    # eval with variables - dynamic code execution
    re.compile(r"(?:^|[;&|]\s*)eval\s+", re.MULTILINE),
    # chmod/chown with recursive on system paths
    re.compile(
        r"(?:chmod|chown)\s+-[rR]\s+[^/]*(?:/bin|/etc|/usr|/var|/sys|/proc)",
        re.MULTILINE,
    ),
    # Kill signals
    re.compile(r"(?:^|[;&|]\s*)(?:/(?:usr/)?bin/)?kill\s+-9\s+", re.MULTILINE),
    re.compile(r"(?:^|[;&|]\s*)(?:/(?:usr/)?bin/)?pkill\s+", re.MULTILINE),
    # Git destructive operations
    re.compile(
        r"git\s+(?:push\s+.*--force|reset\s+--hard|clean\s+-[fd]+)", re.MULTILINE
    ),
    # Command substitution executing destructive commands (partial coverage)
    # Catches: $(rm ...), `rm ...`
    re.compile(r"\$\(\s*rm\s+", re.MULTILINE),
    re.compile(r"`\s*rm\s+", re.MULTILINE),
    # xargs piping to destructive commands
    re.compile(r"xargs\s+(?:-[^\s]+\s+)*rm\b", re.MULTILINE),
    # base64 decoded and piped to shell (common obfuscation)
    re.compile(r"base64\s+(?:-d|--decode)[^|]*\|\s*(?:ba)?sh", re.MULTILINE),
]

# Patterns for commands that modify important files
SENSITIVE_PATH_PATTERNS = [
    re.compile(r"/etc/(?:passwd|shadow|sudoers|hosts)"),
    re.compile(r"/root/"),
    re.compile(r"~/.ssh/"),
    re.compile(r"~/.gnupg/"),
    re.compile(r"~/.aws/"),
    re.compile(r"/usr/(?:bin|lib|local)/"),
    re.compile(r"/var/(?:log|lib)/"),
]

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    """
    Load JSON file safely, returning None if file doesn't exist or is invalid.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON as dict, or None on failure.

    Raises:
        None explicitly - all exceptions are caught and logged to stderr.

    Example:
        >>> data = load_json(Path("config.json"))
        >>> if data:
        ...     print(data.get("key"))
    """
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            result: Dict[str, Any] = json.load(f)
            return result
    except (json.JSONDecodeError, OSError, PermissionError) as e:
        # Log error but don't crash - graceful degradation
        print(f"Warning: Failed to load {path}: {e}", file=sys.stderr)
        return None


def save_json(path: Path, data: Dict[str, Any]) -> bool:
    """
    Save JSON data atomically using a temporary file.

    This prevents corruption if the process is interrupted during write.

    Args:
        path: Destination path for the JSON file.
        data: Dictionary to serialize as JSON.

    Returns:
        True on success, False on failure.

    Raises:
        None explicitly - all exceptions are caught and logged to stderr.

    Example:
        >>> success = save_json(Path("config.json"), {"key": "value"})
        >>> print("Saved" if success else "Failed")
    """
    tmp_path = path.with_suffix(".tmp")
    try:
        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())

        # Atomic rename
        tmp_path.rename(path)
        return True

    except (OSError, PermissionError) as e:
        print(f"Warning: Failed to save {path}: {e}", file=sys.stderr)
        # Clean up temp file if it exists
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return False


def normalize_bash_command(cmd: str) -> str:
    """
    Normalize a bash command for consistent pattern matching.

    Operations:
    - Collapse multiple whitespace to single space
    - Strip leading/trailing whitespace
    - Preserve intentional newlines in heredocs (TODO: Phase 2)

    Args:
        cmd: Raw bash command string.

    Returns:
        Normalized command string.

    Raises:
        None - handles empty/None input gracefully.

    Example:
        >>> normalize_bash_command("  rm   -rf   ./tmp  ")
        'rm -rf ./tmp'
    """
    if not cmd:
        return ""

    # Collapse runs of whitespace (spaces, tabs) to single space
    # but preserve newlines for now (they're command separators)
    normalized = re.sub(r"[ \t]+", " ", cmd)

    # Strip leading/trailing whitespace from each line
    lines = [line.strip() for line in normalized.split("\n")]

    # Rejoin and strip overall
    return "\n".join(lines).strip()


def is_safe_temp_path(path: str) -> bool:
    """
    Check if a path is in a safe temporary directory.

    Args:
        path: File path to check.

    Returns:
        True if path is in a safe temp location.

    Raises:
        None - handles empty/None input gracefully.

    Example:
        >>> is_safe_temp_path("./tmp/test.txt")
        True
        >>> is_safe_temp_path("/etc/passwd")
        False
    """
    if not path:
        return False

    # Direct match against known safe dirs
    for safe_dir in SAFE_TEMP_DIRS:
        if path.startswith(safe_dir):
            return True

    # Pattern-based matching for dynamic temp paths
    for pattern in SAFE_TEMP_PATTERNS:
        if pattern.search(path):
            return True

    return False


def is_destructive_command(cmd: str) -> bool:
    """
    Check if a command matches any destructive patterns.

    Args:
        cmd: Bash command to analyze.

    Returns:
        True if command appears destructive.

    Raises:
        None - handles empty/None input gracefully.

    Example:
        >>> is_destructive_command("rm -rf /")
        True
        >>> is_destructive_command("ls -la")
        False
    """
    if not cmd:
        return False

    normalized = normalize_bash_command(cmd)

    for pattern in DESTRUCTIVE_PATTERNS:
        if pattern.search(normalized):
            return True

    return False


def touches_sensitive_path(cmd: str) -> bool:
    """
    Check if a command references sensitive system paths.

    Args:
        cmd: Bash command to analyze.

    Returns:
        True if command references sensitive paths.

    Raises:
        None - handles empty/None input gracefully.

    Example:
        >>> touches_sensitive_path("cat /etc/passwd")
        True
        >>> touches_sensitive_path("cat README.md")
        False
    """
    if not cmd:
        return False

    for pattern in SENSITIVE_PATH_PATTERNS:
        if pattern.search(cmd):
            return True

    return False


# =============================================================================
# PHASE 2 PLACEHOLDER FUNCTIONS
# =============================================================================


def check_rate_limit() -> bool:
    """
    Check if the current request should be rate limited.

    TODO (Phase 2): Implement token bucket rate limiting

    Phase 2 Implementation Plan:
    - Use a simple token bucket algorithm with RATE_LIMIT_REQUESTS_PER_SECOND
    - Store state in a lightweight file or shared memory
    - Support burst handling with RATE_LIMIT_BURST_SIZE
    - Track requests in sliding window of RATE_LIMIT_WINDOW_SECONDS

    Current Mitigation:
    - Claude Code enforces CLAUDE_HOOK_TIMEOUT_MS (5000ms) timeout
    - This provides implicit rate limiting (~12 requests/minute worst case)
    - Most hook executions complete in <50ms, so practical throughput is higher

    Returns:
        True if request is allowed, False if rate limited.
        Phase 1: Always returns True (no rate limiting).

    Raises:
        None - designed for fail-open behavior.

    Example:
        >>> if not check_rate_limit():
        ...     return {"decision": "deny", "reason": "Rate limited"}
        >>> # Proceed with request
    """
    # Phase 1: No rate limiting - always allow
    # The 5000ms hook timeout provides implicit rate limiting
    return True


def check_permission_cache(tool_name: str, params: Dict[str, Any]) -> Optional[str]:
    """
    Check if we have a cached permission decision.

    TODO (Phase 2): Implement permission caching

    Args:
        tool_name: Name of the tool being invoked.
        params: Tool parameters.

    Returns:
        "allow" or "deny" if cached, None if no cache entry.

    Raises:
        None - currently a stub returning None.

    Example:
        >>> result = check_permission_cache("Bash", {"command": "ls"})
        >>> result is None  # Phase 1: always returns None
        True
    """
    # Phase 1: No caching, always return None to proceed with fresh decision
    return None


def make_permission_decision(
    tool_name: str, params: Dict[str, Any], hook_input: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Make a permission decision for a tool invocation.

    TODO (Phase 2): Implement intelligent permission logic

    Args:
        tool_name: Name of the tool being invoked.
        params: Tool parameters.
        hook_input: Full hook input data.

    Returns:
        Hook response dict (empty for pass-through, or with decision).

    Raises:
        None - currently a stub returning empty dict.

    Example:
        >>> decision = make_permission_decision("Bash", {"command": "ls"}, {})
        >>> decision  # Phase 1: always pass-through
        {}
    """
    # Phase 1: Pass through all requests (skeleton behavior)
    return {}


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main() -> int:
    """
    Main entry point for the pre-tool-use permission hook.

    Reads hook input from stdin, processes it, and outputs a decision.

    Current behavior (Phase 1 skeleton):
    - Reads input
    - Outputs empty JSON (pass-through)

    Returns:
        Exit code (0 for success).

    Raises:
        None explicitly - all exceptions are caught internally for fail-safe behavior.

    Example:
        Called by Claude Code hooks system:
        $ echo '{"tool_name": "Bash"}' | python pre-tool-use-permissions.py
        {}
    """
    try:
        # Read input from stdin
        raw_input = sys.stdin.read()

        # Parse JSON input (may be empty for testing)
        if raw_input.strip():
            hook_input = json.loads(raw_input)
        else:
            hook_input = {}

        # Extract tool information if present
        tool_name = hook_input.get("tool_name", "")
        tool_params = hook_input.get("tool_input", {})

        # Phase 1: Pass through - just output empty JSON
        # Phase 2 will add actual permission logic here
        decision = make_permission_decision(tool_name, tool_params, hook_input)

        # Output decision as JSON
        print(json.dumps(decision))
        return 0

    except json.JSONDecodeError as e:
        # Invalid JSON input - log and pass through
        print(f"Warning: Invalid JSON input: {e}", file=sys.stderr)
        print("{}")
        return 0

    except Exception as e:
        # Unexpected error - log and pass through (fail-safe)
        print(f"Error in permission hook: {e}", file=sys.stderr)
        print("{}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
