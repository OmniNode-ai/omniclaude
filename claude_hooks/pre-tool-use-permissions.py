#!/usr/bin/env python3
"""
Pre-Tool-Use Permission Hook Skeleton for Phase 2 (OMN-95)

This script provides the foundation for intelligent permission management
in Claude Code hooks. It will be expanded during Phase 2 to implement:
- Smart permission caching
- Destructive command detection
- Safe path analysis
- Dynamic permission decisions

Current State: Skeleton that passes through all requests (Phase 1 preparation)
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
        Path to the local tmp directory
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

# These patterns are designed to minimize false positives while catching
# genuinely destructive commands. Key improvements:
# - Use word boundaries and command separators to avoid matching substrings
# - Account for command chaining with ;, &&, ||, |
# - Match commands at start of line or after separators

DESTRUCTIVE_PATTERNS = [
    # rm command - avoid matching 'rm' in words like 'form', 'transform'
    # Matches: rm, rm -rf, rm -f, etc. at start or after separator
    re.compile(r"(?:^|[;&|]\s*)rm\s+(?:-[rfivdP]+\s+)*", re.MULTILINE),
    # rmdir command - remove directories
    re.compile(r"(?:^|[;&|]\s*)rmdir\s+", re.MULTILINE),
    # dd command - disk destroyer, often used for data wiping
    # Avoid matching 'add', 'odd', etc.
    re.compile(r"(?:^|[;&|]\s*)dd\s+", re.MULTILINE),
    # mkfs command - format filesystems
    re.compile(r"(?:^|[;&|]\s*)mkfs(?:\.[a-z0-9]+)?\s+", re.MULTILINE),
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
    re.compile(r"(?:^|[;&|]\s*)kill\s+-9\s+", re.MULTILINE),
    re.compile(r"(?:^|[;&|]\s*)pkill\s+", re.MULTILINE),
    # Git destructive operations
    re.compile(
        r"git\s+(?:push\s+.*--force|reset\s+--hard|clean\s+-[fd]+)", re.MULTILINE
    ),
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
        path: Path to the JSON file

    Returns:
        Parsed JSON as dict, or None on failure
    """
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, PermissionError) as e:
        # Log error but don't crash - graceful degradation
        print(f"Warning: Failed to load {path}: {e}", file=sys.stderr)
        return None


def save_json(path: Path, data: Dict[str, Any]) -> bool:
    """
    Save JSON data atomically using a temporary file.

    This prevents corruption if the process is interrupted during write.

    Args:
        path: Destination path for the JSON file
        data: Dictionary to serialize as JSON

    Returns:
        True on success, False on failure
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
        cmd: Raw bash command string

    Returns:
        Normalized command string
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
        path: File path to check

    Returns:
        True if path is in a safe temp location
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
        cmd: Bash command to analyze

    Returns:
        True if command appears destructive
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
        cmd: Bash command to analyze

    Returns:
        True if command references sensitive paths
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


def check_permission_cache(tool_name: str, params: Dict[str, Any]) -> Optional[str]:
    """
    Check if we have a cached permission decision.

    TODO (Phase 2): Implement permission caching

    Args:
        tool_name: Name of the tool being invoked
        params: Tool parameters

    Returns:
        "allow" or "deny" if cached, None if no cache entry
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
        tool_name: Name of the tool being invoked
        params: Tool parameters
        hook_input: Full hook input data

    Returns:
        Hook response dict (empty for pass-through, or with decision)
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
        Exit code (0 for success)
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
