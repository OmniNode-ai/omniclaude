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

# --- Early logging setup ---
# Configure LOG_FILE handler before any module-level log calls so that
# warnings during import or initialization are captured to disk.
_LOG_FILE = os.environ.get("LOG_FILE")
if _LOG_FILE:
    try:
        _file_handler = logging.FileHandler(_LOG_FILE)
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
            "Neither typing.NotRequired nor typing_extensions.TypedDict available. "
            "Agent loader TypedDict definitions will use plain dict fallback."
        )
        from typing import TypedDict  # type: ignore[assignment]

        NotRequired = None  # type: ignore[assignment,misc]


def _resolve_agent_definitions_dir() -> Path:
    """
    Resolve the agent definitions directory.

    Resolution priority:
        1. CLAUDE_PLUGIN_ROOT env var  ->  <root>/onex/agents/configs/
        2. Default fallback            ->  ~/.claude/agents/omniclaude/

    Validates that the resolved directory exists.  If CLAUDE_PLUGIN_ROOT is
    set but points to a missing or incomplete directory tree, a warning is
    logged and the default path is returned instead.

    Returns:
        Resolved Path to the agent definitions directory.
    """
    default_dir = Path.home() / ".claude" / "agents" / "omniclaude"
    plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT")

    if plugin_root_env:
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

    return default_dir


# Resolved at import time. To change at runtime, reassign before calling
# load_agent(). See _resolve_agent_definitions_dir() for resolution order.
AGENT_DEFINITIONS_DIR = _resolve_agent_definitions_dir()


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
            try:
                return path.read_text()
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
