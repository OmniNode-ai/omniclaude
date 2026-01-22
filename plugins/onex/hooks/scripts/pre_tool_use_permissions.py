#!/usr/bin/env python3
"""
Pre-Tool-Use Permission Hook for Claude Code (OMN-94/OMN-95)

This script provides intelligent permission management for Claude Code hooks,
implementing:
- Destructive command detection with improved regex patterns
- Sensitive path detection for credential/system files
- Safe temp path validation
- Token bucket rate limiting (optional, defense-in-depth)
- Smart permission caching (Phase 2 placeholder)

Rate Limiting Strategy:
-----------------------
Two-layer rate limiting provides defense-in-depth:

1. **Implicit Rate Limiting** (always active):
   - Claude Code enforces a 5000ms hook timeout
   - This limits hooks to ~12 requests/minute in the worst case
   - Most hooks complete in <50ms, so practical throughput is higher
   - Acts as backstop against runaway/stuck hooks

2. **Explicit Rate Limiting** (opt-in via PERMISSION_HOOK_RATE_LIMIT=true):
   - Token bucket algorithm with configurable parameters
   - 10 requests/second sustained rate (RATE_LIMIT_REQUESTS_PER_SECOND)
   - 20 request burst capacity (RATE_LIMIT_BURST_SIZE)
   - Persistent state across hook invocations
   - Fail-open design: allows requests on any error

Why Both?
- Implicit: Protects against runaway/stuck hooks
- Explicit: Protects against rapid-fire legitimate requests
- Defense in depth: Multiple layers for security

Security Pattern Design:
------------------------
IMPORTANT: These patterns provide DEFENSE-IN-DEPTH, NOT a security boundary.

The destructive command patterns are designed to:
- Catch accidental destructive commands (the 99% case)
- Use word boundaries to prevent false positives (e.g., 'rm' in 'transform')
- Be case-insensitive for command matching
- Cover common command paths (/bin/, /usr/bin/, /usr/local/bin/)
- Account for command chaining (;, &&, ||, |)

KNOWN BYPASS VECTORS (documented, by design):
- Variable expansion: CMD=rm; $CMD -rf /
- Command substitution: $(echo rm) -rf /
- Character escaping: r\\m -rf /
- Alias/function tricks: alias x=rm; x file
- Indirect execution: command rm file
- Encoding tricks: echo base64 | base64 -d | sh

For true security boundaries, rely on:
- OS-level permissions
- Sandboxing/containerization
- Claude Code's built-in permission system
- User confirmation dialogs

Testing:
--------
Run tests with: python -m pytest tests/hooks/test_pre_tool_use_permissions.py -v
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

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

# Rate limiting constants - defense-in-depth beyond the hook timeout
# The 5000ms Claude Code timeout provides implicit limiting (~12 req/min worst case)
# These provide additional protection via explicit token bucket rate limiting
RATE_LIMIT_REQUESTS_PER_SECOND = 10  # Max sustained requests per second
RATE_LIMIT_BURST_SIZE = 20  # Allow short bursts up to this size
RATE_LIMIT_WINDOW_SECONDS = 60  # Sliding window for tracking (informational)

# Rate limiting state file (lightweight persistence between invocations)
RATE_LIMIT_STATE_FILE = Path.home() / ".claude" / ".cache" / "rate-limit-state.json"

# Rate limiting feature flag (set to True to enable explicit rate limiting)
# When False, relies on Claude Code's implicit 5000ms timeout rate limiting
RATE_LIMIT_ENABLED = os.environ.get("PERMISSION_HOOK_RATE_LIMIT", "false").lower() == "true"

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

# SECURITY: Pattern separator for matching commands at start of line or after
# shell command separators (;, &&, ||, |, newline). This prevents matching
# 'rm' inside words like 'form' or 'transform'.
# The (?:^|(?<=\n)|(?<=[;&|])\s*) uses lookbehind for precise matching.
_CMD_START = r"(?:^|(?<=\n)|[;&|]\s*)"

# SECURITY: Path prefix pattern for matching absolute paths to commands.
# Covers /bin/, /usr/bin/, /usr/local/bin/ prefixes.
_BIN_PATH = r"(?:/(?:usr/(?:local/)?)?bin/)?"

DESTRUCTIVE_PATTERNS = [
    # rm command - avoid matching 'rm' in words like 'form', 'transform'
    # Matches: rm, rm -rf, rm -f, etc. at start or after separator
    # Also matches /bin/rm, /usr/bin/rm, /usr/local/bin/rm
    # SECURITY: Uses word boundary (\b) after command name to prevent partial matches
    re.compile(
        _CMD_START + _BIN_PATH + r"rm\b\s+(?:-[rfivdPI]+\s+)*",
        re.MULTILINE | re.IGNORECASE,
    ),
    # rmdir command - remove directories
    re.compile(
        _CMD_START + _BIN_PATH + r"rmdir\b\s+",
        re.MULTILINE | re.IGNORECASE,
    ),
    # dd command - disk destroyer, often used for data wiping
    # Avoid matching 'add', 'odd', etc. by requiring word boundary
    re.compile(
        _CMD_START + _BIN_PATH + r"dd\b\s+",
        re.MULTILINE | re.IGNORECASE,
    ),
    # mkfs command - format filesystems
    # Matches mkfs, mkfs.ext4, mkfs.xfs, etc.
    re.compile(
        _CMD_START + r"(?:/(?:usr/)?s?bin/)?" + r"mkfs(?:\.[a-z0-9]+)?\b\s+",
        re.MULTILINE | re.IGNORECASE,
    ),
    # Dangerous redirects - truncating files on absolute paths
    # SECURITY: Avoid false positives on ./path or relative paths
    re.compile(
        r">\s*/(?!dev/null|dev/stderr|dev/stdout)",
        re.MULTILINE,
    ),
    # curl/wget piped to shell - remote code execution
    # SECURITY: Case-insensitive to catch CURL, Curl, etc.
    re.compile(
        r"(?:curl|wget)\b\s+[^|]*\|\s*(?:ba)?sh\b",
        re.MULTILINE | re.IGNORECASE,
    ),
    # eval with variables - dynamic code execution
    # SECURITY: Word boundary prevents matching 'evaluate', etc.
    re.compile(
        _CMD_START + r"eval\b\s+",
        re.MULTILINE | re.IGNORECASE,
    ),
    # chmod/chown with recursive on system paths
    re.compile(
        r"(?:chmod|chown)\b\s+-[rR]\s+[^/]*(?:/bin|/etc|/usr|/var|/sys|/proc)",
        re.MULTILINE | re.IGNORECASE,
    ),
    # Kill signals - SIGKILL and SIGTERM variants
    re.compile(
        _CMD_START + _BIN_PATH + r"kill\b\s+(?:-(?:9|KILL|SIGKILL)\s+)",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(
        _CMD_START + _BIN_PATH + r"pkill\b\s+",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(
        _CMD_START + _BIN_PATH + r"killall\b\s+",
        re.MULTILINE | re.IGNORECASE,
    ),
    # Git destructive operations
    # SECURITY: Matches --force, --force-with-lease, -f (short form)
    re.compile(
        r"git\b\s+push\b[^;|&\n]*(?:--force|-f)\b",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(
        r"git\b\s+reset\b\s+--hard\b",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(
        r"git\b\s+clean\b\s+-[fdxX]+",
        re.MULTILINE | re.IGNORECASE,
    ),
    # Command substitution executing destructive commands (partial coverage)
    # Catches: $(rm ...), `rm ...`
    re.compile(r"\$\(\s*rm\b\s+", re.MULTILINE | re.IGNORECASE),
    re.compile(r"`\s*rm\b\s+", re.MULTILINE | re.IGNORECASE),
    # xargs piping to destructive commands
    re.compile(r"xargs\b\s+(?:-[^\s]+\s+)*rm\b", re.MULTILINE | re.IGNORECASE),
    # base64 decoded and piped to shell (common obfuscation)
    re.compile(
        r"base64\b\s+(?:-d|--decode)[^|]*\|\s*(?:ba)?sh\b",
        re.MULTILINE | re.IGNORECASE,
    ),
    # Additional obfuscation patterns
    # printf with hex escapes piped to shell
    re.compile(
        r"printf\b\s+['\"]?\\x[0-9a-f]+[^|]*\|\s*(?:ba)?sh\b",
        re.MULTILINE | re.IGNORECASE,
    ),
    # python/perl/ruby one-liners executing shell commands
    re.compile(
        r"(?:python|perl|ruby)\b[^|]*\|\s*(?:ba)?sh\b",
        re.MULTILINE | re.IGNORECASE,
    ),
    # Shred command - secure file deletion
    re.compile(
        _CMD_START + _BIN_PATH + r"shred\b\s+",
        re.MULTILINE | re.IGNORECASE,
    ),
    # fdisk/gdisk/parted - partition manipulation
    re.compile(
        _CMD_START + r"(?:/(?:usr/)?s?bin/)?" + r"(?:fdisk|gdisk|parted)\b\s+",
        re.MULTILINE | re.IGNORECASE,
    ),
]

# Patterns for commands that modify important files
# Note: Use /\.dir/ pattern instead of ~/dir to match actual paths
# (~ is shell expansion, not present in actual file paths)
#
# SECURITY: These patterns are case-sensitive for path matching because:
# 1. Unix/Linux filesystems are case-sensitive
# 2. macOS (HFS+/APFS) can be case-insensitive but paths still have canonical forms
# 3. Matching the exact path form prevents false positives
SENSITIVE_PATH_PATTERNS = [
    # System configuration files
    re.compile(r"/etc/(?:passwd|shadow|sudoers|hosts|fstab|crontab)"),
    re.compile(r"/etc/ssh/"),  # SSH server config
    re.compile(r"/etc/pam\.d/"),  # PAM authentication
    # Root user directory
    re.compile(r"/root/"),
    # User credential directories (any user's home)
    # SECURITY: Matches /Users/*/.ssh/, /home/*/.ssh/, etc.
    re.compile(r"/\.ssh/"),
    re.compile(r"/\.gnupg/"),
    re.compile(r"/\.aws/"),
    re.compile(r"/\.kube/"),  # Kubernetes config
    re.compile(r"/\.docker/"),  # Docker config (may contain registry creds)
    re.compile(r"/\.npmrc"),  # npm auth tokens
    re.compile(r"/\.pypirc"),  # PyPI auth tokens
    re.compile(r"/\.netrc"),  # FTP/HTTP credentials
    re.compile(r"/\.gitconfig"),  # Git credentials
    # System binaries and libraries
    re.compile(r"/usr/(?:bin|lib|local)/"),
    re.compile(r"/bin/"),
    re.compile(r"/sbin/"),
    # System data directories
    re.compile(r"/var/(?:log|lib|run)/"),
    # Kernel/proc/sys virtual filesystems
    re.compile(r"/proc/"),
    re.compile(r"/sys/"),
    # Boot files
    re.compile(r"/boot/"),
    # macOS specific
    re.compile(r"/System/"),  # macOS system files
    re.compile(
        r"/Library/(?:Keychains|Security)(?:/|$)"
    ),  # macOS keychains (with or without trailing slash)
]

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def load_json(path: Path) -> dict[str, Any] | None:
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
        with open(path, encoding="utf-8") as f:
            result: dict[str, Any] = json.load(f)
            return result
    except (json.JSONDecodeError, OSError, PermissionError) as e:
        # Log error but don't crash - graceful degradation
        print(f"Warning: Failed to load {path}: {e}", file=sys.stderr)
        return None


def save_json(path: Path, data: dict[str, Any]) -> bool:
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


def _load_rate_limit_state() -> tuple[float, float]:
    """
    Load rate limit state from persistent storage.

    Returns:
        Tuple of (tokens, last_update_time). Defaults to full bucket if no state.

    Raises:
        None - returns defaults on any error.
    """
    try:
        if RATE_LIMIT_STATE_FILE.exists():
            with open(RATE_LIMIT_STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
                return float(state.get("tokens", RATE_LIMIT_BURST_SIZE)), float(
                    state.get("last_update", time.time())
                )
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        pass
    return float(RATE_LIMIT_BURST_SIZE), time.time()


def _save_rate_limit_state(tokens: float, last_update: float) -> None:
    """
    Save rate limit state to persistent storage.

    Args:
        tokens: Current token count.
        last_update: Timestamp of last update.

    Raises:
        None - silently fails on error (fail-open design).
    """
    try:
        RATE_LIMIT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(RATE_LIMIT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"tokens": tokens, "last_update": last_update}, f)
    except (OSError, PermissionError):
        pass  # Fail-open: don't block on state save failure


def check_rate_limit() -> bool:
    """
    Check if the current request should be rate limited using token bucket algorithm.

    Token Bucket Algorithm:
    -----------------------
    - Bucket starts with RATE_LIMIT_BURST_SIZE tokens
    - Tokens are added at RATE_LIMIT_REQUESTS_PER_SECOND rate
    - Each request consumes 1 token
    - Request is allowed if tokens >= 1, otherwise rate limited

    Rate Limiting Strategy:
    -----------------------
    Claude Code enforces a 5000ms (5 second) hook timeout, which provides
    implicit rate limiting - hooks cannot execute more than ~12 times per
    minute in the worst case. This token bucket provides ADDITIONAL protection:

    1. **Implicit Rate Limiting** (always active):
       - 5000ms hook timeout = max ~12 requests/minute if hooks always timeout
       - In practice, hooks complete in <50ms, so this is rarely hit

    2. **Explicit Rate Limiting** (when RATE_LIMIT_ENABLED=true):
       - Token bucket with 10 requests/second sustained rate
       - Burst capacity of 20 requests for spikes
       - Configurable via PERMISSION_HOOK_RATE_LIMIT env var

    Why Both?
    - Implicit: Protects against runaway/stuck hooks
    - Explicit: Protects against rapid-fire legitimate requests
    - Defense in depth: Multiple layers for security

    Returns:
        True if request is allowed, False if rate limited.
        When RATE_LIMIT_ENABLED is False, always returns True (relies on implicit limiting).

    Raises:
        None - designed for fail-open behavior on errors.

    Example:
        >>> # Enable rate limiting via environment
        >>> os.environ["PERMISSION_HOOK_RATE_LIMIT"] = "true"
        >>> if not check_rate_limit():
        ...     return {"decision": "deny", "reason": "Rate limited"}
        >>> # Proceed with request
    """
    # If explicit rate limiting is disabled, rely on Claude Code's implicit timeout
    if not RATE_LIMIT_ENABLED:
        return True

    try:
        # Load current state
        tokens, last_update = _load_rate_limit_state()
        current_time = time.time()

        # Refill tokens based on elapsed time
        elapsed = current_time - last_update
        tokens = min(RATE_LIMIT_BURST_SIZE, tokens + elapsed * RATE_LIMIT_REQUESTS_PER_SECOND)

        # Check if we have tokens available
        if tokens >= 1.0:
            # Consume one token and save state
            tokens -= 1.0
            _save_rate_limit_state(tokens, current_time)
            return True
        else:
            # Rate limited - save state but don't consume
            _save_rate_limit_state(tokens, current_time)
            return False

    except Exception:
        # Fail-open: allow request on any error
        return True


def check_permission_cache(tool_name: str, params: dict[str, Any]) -> str | None:
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
    tool_name: str, params: dict[str, Any], hook_input: dict[str, Any]
) -> dict[str, Any]:
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
        $ echo '{"tool_name": "Bash"}' | python pre_tool_use_permissions.py
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
