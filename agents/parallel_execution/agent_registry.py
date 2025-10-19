"""
Agent Registry - Dynamic agent discovery and validation system.

Provides a decorator-based self-registration system for agents. Agents use the
@register_agent decorator to register themselves with metadata. This eliminates
the need for directory scanning and import validation.

Legacy scanning functionality is still available but deprecated.
"""

import importlib.util
import inspect
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

# Configure logging for agent registry
logger = logging.getLogger(__name__)

# Global registry for decorator-based agent registration
_AGENT_REGISTRY: Dict[str, Dict[str, Any]] = {}

# Type variable for decorator
T = TypeVar("T")


def register_agent(
    agent_name: str, agent_type: str, capabilities: List[str], description: str = ""
) -> Callable[[T], T]:
    """
    Decorator for agent self-registration.

    This decorator allows agents to register themselves with the registry by
    adding metadata at module load time. This eliminates the need for directory
    scanning and import validation.

    Args:
        agent_name: Unique identifier for the agent (e.g., "analyzer", "researcher")
        agent_type: Type category of the agent (e.g., "analyzer", "researcher",
                    "validator", "debug", "coder")
        capabilities: List of capabilities the agent provides
        description: Human-readable description of the agent's purpose

    Returns:
        Decorator function that registers the agent and returns the original class/function

    Example:
        >>> @register_agent(
        ...     agent_name="analyzer",
        ...     agent_type="analyzer",
        ...     capabilities=["architecture_analysis", "design_patterns"],
        ...     description="Architectural and code quality analysis agent"
        ... )
        ... class ArchitecturalAnalyzer:
        ...     def execute(self, task):
        ...         pass

        >>> # Or with a function
        >>> @register_agent(
        ...     agent_name="simple_agent",
        ...     agent_type="coder",
        ...     capabilities=["code_generation"],
        ...     description="Simple code generation agent"
        ... )
        ... def execute(task):
        ...     pass
    """

    def decorator(cls_or_func: T) -> T:
        """Inner decorator that performs the registration."""
        # Log registration start
        logger.info("[AgentRegistry] Registering agent: '%s'", agent_name)
        logger.info("[AgentRegistry]   Type: %s", agent_type)
        logger.info("[AgentRegistry]   Capabilities: %s", capabilities)

        # Store agent metadata in global registry
        _AGENT_REGISTRY[agent_name] = {
            "agent_name": agent_name,
            "agent_type": agent_type,
            "capabilities": capabilities,
            "description": description,
            "class_or_function": cls_or_func,
            "is_class": inspect.isclass(cls_or_func),
            "module_name": f"agent_{agent_name}",  # Standard naming convention
        }

        # Log registration completion with total count
        total_registered = len(_AGENT_REGISTRY)
        logger.info("[AgentRegistry] Total registered agents: %d", total_registered)

        # Return the original class/function unchanged
        return cls_or_func

    return decorator


def get_registered_agents() -> Dict[str, Dict[str, Any]]:
    """
    Get all registered agents and their metadata.

    Returns:
        Dictionary mapping agent names to their metadata dictionaries.
        Each metadata dict contains:
        - agent_name: str
        - agent_type: str
        - capabilities: List[str]
        - description: str
        - class_or_function: The registered class or function
        - is_class: bool (True if registered item is a class)
        - module_name: str (module name for importing)

    Example:
        >>> agents = get_registered_agents()
        >>> for name, metadata in agents.items():
        ...     print(f"{name}: {metadata['description']}")
    """
    return _AGENT_REGISTRY.copy()


def agent_is_registered(name: str) -> bool:
    """
    Check if an agent is registered via the decorator.

    Args:
        name: Agent name to check

    Returns:
        True if the agent is registered, False otherwise

    Example:
        >>> if agent_is_registered("analyzer"):
        ...     print("Analyzer agent is available")
    """
    return name in _AGENT_REGISTRY


def get_agent_metadata(name: str) -> Optional[Dict[str, Any]]:
    """
    Get metadata for a registered agent.

    Args:
        name: Agent name

    Returns:
        Metadata dictionary if agent is registered, None otherwise

    Example:
        >>> metadata = get_agent_metadata("analyzer")
        >>> if metadata:
        ...     print(f"Capabilities: {metadata['capabilities']}")
    """
    return _AGENT_REGISTRY.get(name)


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
            has_execute = hasattr(module, "execute") and callable(
                getattr(module, "execute")
            )
            has_agent = hasattr(
                module, "agent"
            )  # Pydantic AI agents have 'agent' attribute

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

    First checks the decorator registry (preferred), then falls back to
    directory scanning (deprecated).

    Args:
        name: Agent name to check.

    Returns:
        True if agent exists, False otherwise.
    """
    # Check decorator registry first (preferred method)
    if agent_is_registered(name):
        return True

    # Fall back to legacy scanning (deprecated)
    return get_registry().agent_exists(name)


def get_available_agents() -> Dict[str, str]:
    """
    Convenience function to get all available agents.

    Combines decorator-registered agents (preferred) with scanned agents (deprecated).

    Returns:
        Dictionary mapping agent names to module paths.
    """
    # Start with decorator-registered agents
    registered = get_registered_agents()
    agents = {name: metadata["module_name"] for name, metadata in registered.items()}

    # Merge with legacy scanned agents (for backward compatibility)
    scanned = get_registry().get_available_agents()
    agents.update(scanned)

    return agents


def get_agent_module_name(name: str) -> Optional[str]:
    """
    Convenience function to get agent module name.

    Checks decorator registry first (preferred), then falls back to
    directory scanning (deprecated).

    Args:
        name: Agent name.

    Returns:
        Full module name if exists, None otherwise.
    """
    # Check decorator registry first
    metadata = get_agent_metadata(name)
    if metadata:
        return metadata["module_name"]

    # Fall back to legacy scanning
    return get_registry().get_agent_module_name(name)
