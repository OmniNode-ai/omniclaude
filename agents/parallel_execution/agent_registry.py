"""
Agent Registry - Dynamic agent discovery and validation system.

Scans the agents/parallel_execution directory for available agent modules
and provides an API for checking agent existence and getting agent modules.
"""

import os
import importlib.util
import inspect
from pathlib import Path
from typing import Dict, List, Optional, Set
from functools import lru_cache


class AgentRegistry:
    """Registry for dynamically discovering and validating available agents."""

    def __init__(self, agents_directory: Optional[str] = None):
        """
        Initialize the agent registry.

        Args:
            agents_directory: Path to agents directory. Defaults to current file's directory.
        """
        if agents_directory is None:
            agents_directory = Path(__file__).parent
        else:
            agents_directory = Path(agents_directory)

        self.agents_directory = agents_directory
        self._cache: Optional[Dict[str, str]] = None

    def _scan_agents(self) -> Dict[str, str]:
        """
        Scan the agents directory for agent modules.

        Returns:
            Dictionary mapping agent names to module file paths.
        """
        agents = {}

        # Look for files matching pattern: agent_*.py
        for file_path in self.agents_directory.glob("agent_*.py"):
            if file_path.name == "agent_registry.py":  # Skip self
                continue

            # Extract agent name from filename
            # agent_researcher.py -> researcher
            agent_name = file_path.stem.replace("agent_", "")

            # Validate the module has required structure
            if self._validate_agent_module(file_path):
                agents[agent_name] = str(file_path)

        return agents

    def _validate_agent_module(self, file_path: Path) -> bool:
        """
        Validate that an agent module has the required structure.

        Args:
            file_path: Path to the agent module file.

        Returns:
            True if the module is valid, False otherwise.
        """
        try:
            # Load the module
            spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
            if spec is None or spec.loader is None:
                return False

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Check for required execute() function or agent attribute
            has_execute = hasattr(module, "execute") and callable(getattr(module, "execute"))
            has_agent = hasattr(module, "agent")  # Pydantic AI agents have 'agent' attribute

            return has_execute or has_agent

        except Exception:
            return False

    @lru_cache(maxsize=1)
    def get_available_agents(self) -> Dict[str, str]:
        """
        Get all available agents with caching.

        Returns:
            Dictionary mapping agent names to their module file paths.
        """
        if self._cache is None:
            self._cache = self._scan_agents()
        return self._cache.copy()

    def agent_exists(self, name: str) -> bool:
        """
        Check if an agent with the given name exists.

        Args:
            name: Agent name to check (e.g., "researcher", "analyzer").

        Returns:
            True if the agent exists, False otherwise.
        """
        agents = self.get_available_agents()
        return name in agents

    def get_agent_module_path(self, name: str) -> Optional[str]:
        """
        Get the module path for a named agent.

        Args:
            name: Agent name (e.g., "researcher").

        Returns:
            Module file path if agent exists, None otherwise.
        """
        agents = self.get_available_agents()
        return agents.get(name)

    def get_agent_module_name(self, name: str) -> Optional[str]:
        """
        Get the full module name for importing.

        Args:
            name: Agent name (e.g., "researcher").

        Returns:
            Full module name (e.g., "agent_researcher") if exists, None otherwise.
        """
        if self.agent_exists(name):
            return f"agent_{name}"
        return None

    def clear_cache(self):
        """Clear the agent cache to force re-scanning."""
        self._cache = None
        self.get_available_agents.cache_clear()


# Global registry instance
_registry: Optional[AgentRegistry] = None


def get_registry() -> AgentRegistry:
    """Get the global agent registry instance."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry


def agent_exists(name: str) -> bool:
    """
    Convenience function to check if an agent exists.

    Args:
        name: Agent name to check.

    Returns:
        True if agent exists, False otherwise.
    """
    return get_registry().agent_exists(name)


def get_available_agents() -> Dict[str, str]:
    """
    Convenience function to get all available agents.

    Returns:
        Dictionary mapping agent names to module paths.
    """
    return get_registry().get_available_agents()


def get_agent_module_name(name: str) -> Optional[str]:
    """
    Convenience function to get agent module name.

    Args:
        name: Agent name.

    Returns:
        Full module name if exists, None otherwise.
    """
    return get_registry().get_agent_module_name(name)
