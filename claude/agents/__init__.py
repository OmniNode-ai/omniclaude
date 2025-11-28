"""Claude Code agent definitions and configurations.

This package contains agent-related artifacts:
- Agent definition YAML files (53 definitions)
- Agent registry configurations
- Polymorphic agent system configuration

Available agents can be loaded using the registry module:

    from claude.agents.registry import list_agents, load_agent

    # List all available agents
    agents = list_agents()

    # Load a specific agent definition
    agent_def = load_agent("polymorphic-agent")
"""

from claude.agents.registry import (
    agent_exists,
    get_agent_count,
    list_agents,
    load_agent,
    load_registry,
)


__all__ = [
    "list_agents",
    "load_agent",
    "load_registry",
    "get_agent_count",
    "agent_exists",
]

# Number of available agent definitions
AGENT_COUNT = 52  # Excluding agent-registry.yaml meta-file
