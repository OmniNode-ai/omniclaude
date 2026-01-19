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
import sys
from pathlib import Path

# Python 3.11+ has Required/NotRequired, for 3.10 use typing_extensions
try:
    from typing import NotRequired, TypedDict
except ImportError:
    from typing import NotRequired

    from typing_extensions import TypedDict


logger = logging.getLogger(__name__)

# Agent definitions directory (uses omniclaude namespace)
AGENT_DEFINITIONS_DIR = Path.home() / ".claude" / "agents" / "omniclaude"


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

    Example:
        >>> content = load_agent_yaml("agent-api")
        >>> if content:
        ...     print("Found agent definition")
        ... else:
        ...     print("Agent not found")

        >>> # Also works without "agent-" prefix
        >>> content = load_agent_yaml("research")
    """
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
