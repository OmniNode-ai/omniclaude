#!/usr/bin/env python3
"""
Simple Agent Loader - Load agent YAML definitions

Loads agent configuration from YAML files and returns context injection
for the polymorphic agent framework.

Usage:
    echo '{"agent_name": "agent-api"}' | python3 simple_agent_loader.py

Output:
    JSON with success status and context injection:
    {
        "success": true,
        "context_injection": "... agent YAML content ...",
        "agent_name": "agent-api"
    }
"""

import json
import logging
import os
import sys
from pathlib import Path

# --- Early logging setup (MUST remain above all other module-level code) ---
# ORDERING INVARIANT: The LOG_FILE file handler must be installed before any
# module-level logger.warning() calls (e.g., the TypedDict import fallback
# below).  Moving this block after the import section will silently lose
# those early warnings.  See issue #3 in the review.
_LOG_FILE = os.environ.get("LOG_FILE")
if _LOG_FILE:
    try:
        _file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        _file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        )
        logging.getLogger().addHandler(_file_handler)
    except OSError:
        pass  # If log file is inaccessible, continue without file logging

logger = logging.getLogger(__name__)

# Python 3.11+ has Required/NotRequired, for 3.10 use typing_extensions.
# Graceful degradation: if neither typing nor typing_extensions provides
# these, we warn and fall back so the hook never crashes at import time.
try:
    from typing import NotRequired, TypedDict
except ImportError:
    try:
        from typing import NotRequired

        from typing_extensions import TypedDict
    except ImportError:
        logger.warning(
            "Neither typing.NotRequired nor typing_extensions available. "
            "Agent loader TypedDict definitions will use plain dict fallback."
        )
        from typing import TypedDict  # type: ignore[assignment]

        # NotRequired must be subscriptable (e.g., NotRequired[list[str]])
        # at class-body evaluation time.  A bare None would crash with
        # TypeError, so provide a no-op wrapper that passes through the
        # inner type.
        class _NotRequiredFallback:  # type: ignore[no-redef]
            """Subscriptable stand-in for typing.NotRequired."""

            def __class_getitem__(cls, item):  # type: ignore[override]
                return item

        NotRequired = _NotRequiredFallback  # type: ignore[assignment,misc]

# Maximum context length to prevent truncation in hook output
# Claude Code truncates at 10k chars; we use 6k to leave room for other context
MAX_CONTEXT_LENGTH = 6000
_TRUNCATION_MARKER = (
    "\n\n# ... (truncated for brevity - see full YAML in agents/configs/)\n"
)


def _resolve_agent_definitions_dir() -> Path:
    """
    Resolve the agent definitions directory.

    Resolution priority:
        1. CLAUDE_PLUGIN_ROOT env var  ->  <root>/onex/agents/configs/
        2. Default fallback            ->  ~/.claude/agents/omniclaude/

    This function never raises exceptions.  If CLAUDE_PLUGIN_ROOT is set but
    points to a missing or incomplete directory tree, a warning is logged and
    the default path is returned.  If even the default path cannot be
    constructed (e.g., HOME is unset), the current working directory is used
    as the fallback base.

    Returns:
        Resolved Path to the agent definitions directory.
    """
    # Build the default directory with a safety net for missing HOME.
    # Path.home() raises RuntimeError when HOME is unset on Unix, or
    # KeyError on some Windows configurations.
    try:
        default_dir = Path.home() / ".claude" / "agents" / "omniclaude"
    except (RuntimeError, KeyError):
        logger.warning(
            "Cannot determine HOME directory; using current working directory "
            "as fallback base for agent definitions."
        )
        default_dir = Path.cwd() / ".claude" / "agents" / "omniclaude"

    plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()

    if plugin_root_env:
        try:
            plugin_root = Path(plugin_root_env)
            if not plugin_root.is_dir():
                logger.warning(
                    "CLAUDE_PLUGIN_ROOT is set but directory does not exist: %s. "
                    "Falling back to default agent definitions directory: %s",
                    plugin_root_env,
                    default_dir,
                )
                return default_dir

            configs_dir = plugin_root / "onex" / "agents" / "configs"
            if configs_dir.is_dir():
                return configs_dir

            logger.warning(
                "CLAUDE_PLUGIN_ROOT is set but agents/configs subdirectory not found: %s. "
                "Falling back to default agent definitions directory: %s",
                configs_dir,
                default_dir,
            )
        except OSError as exc:
            logger.warning(
                "Error resolving CLAUDE_PLUGIN_ROOT (%s): %s. "
                "Falling back to default agent definitions directory: %s",
                plugin_root_env,
                exc,
                default_dir,
            )

    return default_dir


# Resolved at import time so that repeated load_agent() calls avoid redundant
# I/O.  The resolution function is designed to never raise, but we add a
# safety net here as a final guard -- per CLAUDE.md, hooks must never crash
# at import time.  To override at runtime, reassign before calling
# load_agent().
try:
    AGENT_DEFINITIONS_DIR = _resolve_agent_definitions_dir()
except Exception as exc:
    logger.warning(
        "Failed to resolve agent definitions directory: %s. "
        "Using current working directory as fallback.",
        exc,
    )
    AGENT_DEFINITIONS_DIR = Path.cwd()


def _validate_agent_name(agent_name: str) -> str | None:
    """
    Validate an agent name to prevent path traversal attacks.

    Rejects names containing path separators, parent-directory references,
    or null bytes.  Returns the sanitized name on success, or ``None`` (with
    a warning) if the name is unsafe.

    Args:
        agent_name: Raw agent name string to validate.

    Returns:
        The validated agent name, or None if the name is unsafe.
    """
    if not agent_name:
        return None

    # Reject null bytes, path separators, and parent-directory traversal
    dangerous_patterns = ("..", "/", "\\", "\x00")
    for pattern in dangerous_patterns:
        if pattern in agent_name:
            logger.warning(
                "Rejected unsafe agent name containing %r: %s",
                pattern,
                repr(agent_name[:80]),
            )
            return None

    # Reject names that resolve outside the expected directory
    # (e.g. names starting with ~ or absolute-looking paths on Windows)
    if agent_name.startswith(("~", "$")):
        logger.warning(
            "Rejected agent name with shell expansion characters: %s",
            repr(agent_name[:80]),
        )
        return None

    return agent_name


def _validate_path_within_bounds(
    file_path: Path, expected_base: Path
) -> tuple[bool, str]:
    """
    Validate that a resolved file path stays within the expected base directory.

    This prevents symlink-based path traversal attacks where a symlink could
    point outside the expected directory structure.

    Args:
        file_path: The file path to validate
        expected_base: The expected base directory that file_path should be within

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.
    """
    try:
        # Resolve both paths to handle symlinks
        resolved_file = file_path.resolve()
        resolved_base = expected_base.resolve()

        # Check if the resolved file path is within the resolved base directory
        try:
            resolved_file.relative_to(resolved_base)
            return True, ""
        except ValueError:
            return (
                False,
                f"Path escapes expected directory: {resolved_file} is not within {resolved_base}",
            )
    except OSError as e:
        return False, f"Failed to resolve path: {e}"


class AgentLoadSuccess(TypedDict):
    """Result when agent is successfully loaded."""

    success: bool  # Always True for this type
    context_injection: str
    agent_name: str


class AgentLoadFailure(TypedDict):
    """Result when agent loading fails."""

    success: bool  # Always False for this type
    error: str
    agent_name: str
    searched_paths: NotRequired[list[str]]


# Union type for load_agent return value
AgentLoadResult = AgentLoadSuccess | AgentLoadFailure


def _get_search_paths(agent_name: str) -> list[Path]:
    """
    Get list of paths to search for agent definition.

    The *agent_name* must already be validated (see ``_validate_agent_name``).
    No additional sanitisation is performed here.

    Args:
        agent_name: Pre-validated name of the agent to load.

    Returns:
        List of Path objects to search.
    """
    return [
        AGENT_DEFINITIONS_DIR / f"{agent_name}.yaml",
        AGENT_DEFINITIONS_DIR / f"{agent_name}.yml",
        # Also check for agent without "agent-" prefix (use removeprefix for safety)
        AGENT_DEFINITIONS_DIR / f"{agent_name.removeprefix('agent-')}.yaml",
        AGENT_DEFINITIONS_DIR / f"{agent_name.removeprefix('agent-')}.yml",
    ]


def load_agent_yaml(agent_name: str) -> str | None:
    """
    Load agent YAML definition file.

    Searches for agent definition files in the ONEX agents directory,
    trying multiple filename patterns to find a match.

    The agent name is validated against path traversal before any
    filesystem access.

    Args:
        agent_name: Name of the agent to load (e.g., "agent-api", "research").

    Returns:
        YAML content as string if found, None if not found, if the name
        fails validation, or if the file cannot be read.

    Example:
        >>> content = load_agent_yaml("agent-api")
        >>> if content:
        ...     print("Found agent definition")
        ... else:
        ...     print("Agent not found")

        >>> # Also works without "agent-" prefix
        >>> content = load_agent_yaml("research")
    """
    safe_name = _validate_agent_name(agent_name)
    if safe_name is None:
        return None

    search_paths = _get_search_paths(safe_name)

    for path in search_paths:
        if path.exists():
            # Security: Validate resolved path stays within agents directory
            # This prevents symlink-based attacks that could read arbitrary files
            is_within_bounds, bounds_error = _validate_path_within_bounds(
                path, AGENT_DEFINITIONS_DIR
            )
            if not is_within_bounds:
                logger.warning(
                    f"load_agent_yaml: Path validation failed for {path}: {bounds_error}"
                )
                continue  # Skip this path and try the next one

            try:
                return path.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning("Failed to read %s: %s", path, e)

    return None


def load_agent(agent_name: str) -> AgentLoadResult:
    """
    Load agent configuration and prepare context injection.

    This is the main entry point for loading agent definitions. It attempts
    to find and load an agent's YAML configuration file, returning a typed
    result indicating success or failure.

    The agent name is validated against path traversal before any
    filesystem access.

    Args:
        agent_name: Name of the agent to load (e.g., "agent-api", "research").
            Can include or omit the "agent-" prefix.

    Returns:
        AgentLoadResult: A TypedDict with the following structure:
            On success (AgentLoadSuccess):
                - success: True
                - context_injection: The YAML content as a string
                - agent_name: The requested agent name
            On failure (AgentLoadFailure):
                - success: False
                - error: Description of the failure
                - agent_name: The requested agent name
                - searched_paths: List of paths that were searched

    Note:
        No exceptions are raised.  All errors (missing name, unsafe name,
        file-not-found, I/O errors) are captured in the returned dict so
        that callers never need try/except.

    Example:
        >>> result = load_agent("agent-api")
        >>> if result["success"]:
        ...     yaml_content = result["context_injection"]
        ...     print(f"Loaded agent: {result['agent_name']}")
        ... else:
        ...     print(f"Error: {result['error']}")
        ...     print(f"Searched: {result.get('searched_paths', [])}")

        >>> # CLI usage via stdin
        >>> # echo '{"agent_name": "agent-api"}' | python3 simple_agent_loader.py
    """
    if not agent_name:
        return AgentLoadFailure(
            success=False,
            error="No agent name provided",
            agent_name=agent_name or "",
            searched_paths=[],
        )

    # Validate agent name against path traversal
    safe_name = _validate_agent_name(agent_name)
    if safe_name is None:
        return AgentLoadFailure(
            success=False,
            error=f"Unsafe agent name rejected: '{agent_name}'",
            agent_name=agent_name,
            searched_paths=[],
        )

    # Get search paths for error reporting
    search_paths = _get_search_paths(safe_name)

    # Load YAML content
    yaml_content = load_agent_yaml(safe_name)

    if yaml_content:
        # Truncate if exceeds max length to prevent hook output truncation
        if len(yaml_content) > MAX_CONTEXT_LENGTH:
            truncated_content = yaml_content[:MAX_CONTEXT_LENGTH] + _TRUNCATION_MARKER
            logger.info(
                f"Truncated agent YAML from {len(yaml_content)} to {len(truncated_content)} chars"
            )
            yaml_content = truncated_content

        return AgentLoadSuccess(
            success=True,
            context_injection=yaml_content,
            agent_name=safe_name,
        )
    else:
        # Build descriptive error message with searched paths for debugging
        path_list = ", ".join(str(p) for p in search_paths)
        return AgentLoadFailure(
            success=False,
            error=f"Agent definition not found: '{safe_name}'. Searched: [{path_list}]",
            agent_name=safe_name,
            searched_paths=[str(p) for p in search_paths],
        )


def main() -> None:
    """
    CLI entry point - reads JSON from stdin.

    Reads a JSON object with 'agent_name' key from stdin and outputs
    the agent load result as JSON to stdout.

    Input format:
        {"agent_name": "agent-api"}

    Output format (success):
        {"success": true, "context_injection": "...", "agent_name": "agent-api"}

    Output format (failure):
        {"success": false, "error": "...", "agent_name": "...", "searched_paths": [...]}
    """
    try:
        # Read input JSON from stdin
        input_data = json.loads(sys.stdin.read())
        agent_name: str = input_data.get("agent_name", "")

        result = load_agent(agent_name)
        print(json.dumps(result))

    except json.JSONDecodeError as e:
        json_error: AgentLoadFailure = {
            "success": False,
            "error": f"Invalid JSON input: {e}",
            "agent_name": "",
            "searched_paths": [],
        }
        print(json.dumps(json_error))
    except Exception as e:
        unexpected_error: AgentLoadFailure = {
            "success": False,
            "error": f"Unexpected error: {e}",
            "agent_name": "",
            "searched_paths": [],
        }
        print(json.dumps(unexpected_error))


if __name__ == "__main__":
    main()
