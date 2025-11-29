"""Agent registry utilities for loading and managing agent definitions.

This module provides utilities for discovering and loading agent definition
YAML files from the claude/agents/ directory.
"""

from pathlib import Path
from typing import Any

import yaml


AGENTS_DIR = Path(__file__).parent


def list_agents() -> list[str]:
    """List all available agent names.

    Returns:
        List of agent names (without .yaml extension).
        Excludes 'agent-registry' as it's a meta-file.
    """
    return sorted(
        [f.stem for f in AGENTS_DIR.glob("*.yaml") if f.stem != "agent-registry"]
    )


def load_agent(name: str) -> dict[str, Any]:
    """Load an agent definition by name.

    Args:
        name: The agent name (without .yaml extension).

    Returns:
        The parsed agent definition as a dictionary.

    Raises:
        FileNotFoundError: If the agent definition file doesn't exist.
    """
    path = AGENTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Agent '{name}' not found at {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_registry() -> dict[str, Any]:
    """Load the agent registry file.

    Returns:
        The parsed agent registry as a dictionary.

    Raises:
        FileNotFoundError: If agent-registry.yaml doesn't exist.
    """
    return load_agent("agent-registry")


def get_agent_count() -> int:
    """Get the count of available agent definitions.

    Returns:
        Number of agent definition files (excluding registry).
    """
    return len(list_agents())


def agent_exists(name: str) -> bool:
    """Check if an agent definition exists.

    Args:
        name: The agent name to check.

    Returns:
        True if the agent definition file exists, False otherwise.
    """
    path = AGENTS_DIR / f"{name}.yaml"
    return path.exists()
