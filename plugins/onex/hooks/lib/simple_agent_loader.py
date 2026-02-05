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
import re
import sys
from pathlib import Path
from typing import NotRequired, TypedDict

logger = logging.getLogger(__name__)

# Security: Pattern for valid agent names (alphanumeric, hyphen, underscore only)
_VALID_AGENT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_agent_name(agent_name: str) -> tuple[bool, str]:
    """
    Validate agent name to prevent path traversal attacks.

    Only allows alphanumeric characters, hyphens, and underscores.
    Rejects any path traversal attempts (../, /, \\, etc.).

    Args:
        agent_name: The agent name to validate

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.

    Example:
        >>> validate_agent_name("agent-api")
        (True, "")
        >>> validate_agent_name("../../../etc/passwd")
        (False, "Invalid agent name: contains path traversal characters")
    """
    if not agent_name:
        return False, "Agent name cannot be empty"

    # Check for path traversal characters
    if ".." in agent_name:
        return False, "Invalid agent name: contains path traversal sequence '..'"

    if "/" in agent_name or "\\" in agent_name:
        return False, "Invalid agent name: contains path separator characters"

    # Check against allowlist pattern (alphanumeric, hyphen, underscore)
    if not _VALID_AGENT_NAME_PATTERN.match(agent_name):
        return (
            False,
            "Invalid agent name: must contain only alphanumeric characters, "
            "hyphens, and underscores",
        )

    # Additional length check to prevent DoS via extremely long names
    if len(agent_name) > 128:
        return False, "Invalid agent name: exceeds maximum length of 128 characters"

    return True, ""


# Agent definitions directory resolution with hardened validation
# Priority: CLAUDE_PLUGIN_ROOT/agents/configs (for plugins), then script-relative, then legacy
def _resolve_agent_definitions_dir() -> Path:
    """
    Resolve the agent definitions directory with proper validation.

    Resolution order:
    1. CLAUDE_PLUGIN_ROOT environment variable (if set and valid)
    2. Script-relative path detection (hooks/lib -> plugin_root/agents/configs)
    3. Legacy fallback (~/.claude/agents/omniclaude)

    Returns:
        Path to the agent definitions directory

    Logs warnings for misconfigurations to aid debugging.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()

    if plugin_root:
        plugin_path = Path(plugin_root)

        # Validate the plugin root exists
        if not plugin_path.exists():
            logger.warning(
                f"CLAUDE_PLUGIN_ROOT is set but path does not exist: {plugin_root}. "
                "Falling back to script-relative detection."
            )
        elif not plugin_path.is_dir():
            logger.warning(
                f"CLAUDE_PLUGIN_ROOT is set but is not a directory: {plugin_root}. "
                "Falling back to script-relative detection."
            )
        else:
            agents_dir = plugin_path / "agents" / "configs"
            if agents_dir.exists() and agents_dir.is_dir():
                return agents_dir
            else:
                logger.warning(
                    f"CLAUDE_PLUGIN_ROOT is set but agents/configs not found: {agents_dir}. "
                    "Falling back to script-relative detection."
                )

    # Fallback: try to detect from script location (lib is 2 levels up from agents/configs)
    script_dir = Path(__file__).parent
    possible_plugin_root = script_dir.parent.parent  # hooks/lib -> hooks -> plugin_root
    possible_agents_dir = possible_plugin_root / "agents" / "configs"

    if possible_agents_dir.exists() and possible_agents_dir.is_dir():
        if not plugin_root:
            logger.info(
                f"CLAUDE_PLUGIN_ROOT not set. Using script-relative path: {possible_agents_dir}"
            )
        return possible_agents_dir

    # Legacy fallback
    legacy_dir = Path.home() / ".claude" / "agents" / "omniclaude"
    logger.warning(
        f"Could not resolve agent definitions directory from CLAUDE_PLUGIN_ROOT or "
        f"script location. Using legacy fallback: {legacy_dir}"
    )
    return legacy_dir


AGENT_DEFINITIONS_DIR = _resolve_agent_definitions_dir()


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

    Args:
        agent_name: Name of the agent to load

    Returns:
        List of Path objects to search
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

    Args:
        agent_name: Name of the agent to load (e.g., "agent-api", "research")

    Returns:
        YAML content as string if found, None otherwise

    Raises:
        OSError: If file exists but cannot be read (logged as warning, returns None)
        ValueError: If agent_name contains invalid characters (path traversal prevention)

    Example:
        >>> content = load_agent_yaml("agent-api")
        >>> if content:
        ...     print("Found agent definition")
        ... else:
        ...     print("Agent not found")

        >>> # Also works without "agent-" prefix
        >>> content = load_agent_yaml("research")
    """
    # Security: Validate agent name (defense-in-depth for direct callers)
    is_valid, error_msg = validate_agent_name(agent_name)
    if not is_valid:
        logger.warning(f"load_agent_yaml: {error_msg} (name={agent_name!r})")
        raise ValueError(error_msg)

    search_paths = _get_search_paths(agent_name)

    for path in search_paths:
        if path.exists():
            try:
                return path.read_text()
            except OSError as e:
                logger.warning(f"Failed to read {path}: {e}")

    return None


def load_agent(agent_name: str) -> AgentLoadResult:
    """
    Load agent configuration and prepare context injection.

    This is the main entry point for loading agent definitions. It attempts
    to find and load an agent's YAML configuration file, returning a typed
    result indicating success or failure.

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

    Raises:
        No exceptions are raised; all errors are captured in the result dict.

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
            agent_name=agent_name,
            searched_paths=[],
        )

    # Security: Validate agent name to prevent path traversal attacks
    is_valid, validation_error = validate_agent_name(agent_name)
    if not is_valid:
        logger.warning(
            f"Agent name validation failed: {validation_error} (name={agent_name!r})"
        )
        return AgentLoadFailure(
            success=False,
            error=validation_error,
            agent_name=agent_name,
            searched_paths=[],
        )

    # Get search paths for error reporting
    search_paths = _get_search_paths(agent_name)

    # Load YAML content
    yaml_content = load_agent_yaml(agent_name)

    if yaml_content:
        return AgentLoadSuccess(
            success=True,
            context_injection=yaml_content,
            agent_name=agent_name,
        )
    else:
        # Build descriptive error message with searched paths for debugging
        path_list = ", ".join(str(p) for p in search_paths)
        return AgentLoadFailure(
            success=False,
            error=f"Agent definition not found: '{agent_name}'. Searched: [{path_list}]",
            agent_name=agent_name,
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
