"""
Capability Index - Phase 1
==========================

In-memory index of agent capabilities for fast lookup.

Provides inverted indexes for:
- Capabilities -> Agents
- Domains -> Agents
- Agents -> Capabilities

Enables fast queries like:
- "Which agents can handle debugging?"
- "Which agents work in the API domain?"
- "Which agents have both testing AND deployment capabilities?"
"""

import logging
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


# Define fallback classes for ONEX error handling
class _FallbackEnumCoreErrorCode(str, Enum):
    """Fallback error codes for ONEX compliance."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    OPERATION_FAILED = "OPERATION_FAILED"


class _FallbackOnexError(Exception):
    """Fallback OnexError for ONEX compliance."""

    def __init__(
        self,
        code: str | _FallbackEnumCoreErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


# Import ONEX error handling, fall back to local definitions
try:
    from agents.lib.errors import EnumCoreErrorCode, OnexError
except ImportError:
    EnumCoreErrorCode = _FallbackEnumCoreErrorCode
    OnexError = _FallbackOnexError


logger = logging.getLogger(__name__)


class CapabilityIndex:
    """
    In-memory index of agent capabilities for fast lookup.

    Builds inverted indexes on initialization for O(1) capability
    and domain lookups.

    Attributes:
        registry_path: Path to the agent registry YAML file.
        capability_to_agents: Mapping from capability name to set of agent names.
        agent_to_capabilities: Mapping from agent name to list of capabilities.
        domain_to_agents: Mapping from domain name to set of agent names.
        agent_to_domain: Mapping from agent name to domain context.

    Example:
        >>> index = CapabilityIndex("/path/to/agent-registry.yaml")
        >>> debug_agents = index.find_by_capability("debugging")
        >>> api_agents = index.find_by_domain("api")
    """

    def __init__(self, registry_path: str):
        """
        Initialize index from agent registry.

        Args:
            registry_path: Path to agent-registry.yaml file

        Raises:
            OnexError: If the registry file cannot be read or parsed.
            FileNotFoundError: If the registry file does not exist.
            yaml.YAMLError: If the registry contains invalid YAML.

        Example:
            >>> index = CapabilityIndex("~/.claude/agents/onex/agent-registry.yaml")
            >>> print(index.stats())
        """
        self.registry_path = registry_path
        self.capability_to_agents: dict[str, set[str]] = {}
        self.agent_to_capabilities: dict[str, list[str]] = {}
        self.domain_to_agents: dict[str, set[str]] = {}
        self.agent_to_domain: dict[str, str] = {}

        self._build_index()

    def _build_index(self) -> None:
        """
        Build inverted indexes from registry.

        Creates the following index structures:
        - capability_to_agents: capability -> set of agent names
        - agent_to_capabilities: agent name -> list of capabilities
        - domain_to_agents: domain -> set of agent names
        - agent_to_domain: agent name -> domain

        Returns:
            None

        Raises:
            OnexError: If registry file cannot be read, parsed, or has invalid structure.
            FileNotFoundError: If the registry file does not exist.
            yaml.YAMLError: If the registry contains invalid YAML.

        Example:
            This method is called automatically during __init__.
            It can be called manually to rebuild indexes:
            >>> index._build_index()
        """
        try:
            with open(self.registry_path) as f:
                registry = yaml.safe_load(f)

            if registry is None:
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message="Registry file is empty or contains no valid YAML",
                    details={"registry_path": self.registry_path},
                )

            if "agents" not in registry:
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message="Registry file missing required 'agents' key",
                    details={
                        "registry_path": self.registry_path,
                        "available_keys": list(registry.keys()) if registry else [],
                    },
                )

            agent_count = 0
            capability_count = 0

            for agent_name, agent_data in registry["agents"].items():
                if agent_data is None:
                    logger.warning(
                        f"Agent '{agent_name}' has no data, skipping",
                        extra={"agent_name": agent_name},
                    )
                    continue

                agent_count += 1

                # Index capabilities
                capabilities = agent_data.get("capabilities", [])
                self.agent_to_capabilities[agent_name] = capabilities

                for capability in capabilities:
                    capability_count += 1
                    if capability not in self.capability_to_agents:
                        self.capability_to_agents[capability] = set()
                    self.capability_to_agents[capability].add(agent_name)

                # Index domain
                domain = agent_data.get("domain_context", "general")
                self.agent_to_domain[agent_name] = domain

                if domain not in self.domain_to_agents:
                    self.domain_to_agents[domain] = set()
                self.domain_to_agents[domain].add(agent_name)

            logger.debug(
                f"Built capability index: {agent_count} agents, "
                f"{len(self.capability_to_agents)} unique capabilities, "
                f"{len(self.domain_to_agents)} domains",
                extra={
                    "agent_count": agent_count,
                    "capability_count": len(self.capability_to_agents),
                    "domain_count": len(self.domain_to_agents),
                },
            )

        except FileNotFoundError:
            logger.error(f"Registry file not found: {self.registry_path}")
            raise OnexError(
                code=EnumCoreErrorCode.CONFIGURATION_ERROR,
                message=f"Registry file not found: {self.registry_path}",
                details={"registry_path": self.registry_path},
            )
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in registry: {e}")
            raise OnexError(
                code=EnumCoreErrorCode.VALIDATION_ERROR,
                message=f"Invalid YAML in registry file: {e}",
                details={"registry_path": self.registry_path, "yaml_error": str(e)},
            )
        except OnexError:
            # Re-raise OnexError as-is
            raise
        except Exception as e:
            logger.error(f"Failed to build capability index: {e}", exc_info=True)
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Failed to build capability index: {e}",
                details={
                    "registry_path": self.registry_path,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

    def find_by_capability(self, capability: str) -> list[str]:
        """
        Find agents with specific capability.

        Args:
            capability: Capability to search for

        Returns:
            List of agent names with this capability
        """
        return list(self.capability_to_agents.get(capability, set()))

    def find_by_domain(self, domain: str) -> list[str]:
        """
        Find agents for specific domain.

        Args:
            domain: Domain to search for

        Returns:
            List of agent names in this domain
        """
        return list(self.domain_to_agents.get(domain, set()))

    def get_capabilities(self, agent_name: str) -> list[str]:
        """
        Get capabilities for specific agent.

        Args:
            agent_name: Agent name to look up

        Returns:
            List of agent's capabilities
        """
        return self.agent_to_capabilities.get(agent_name, [])

    def get_domain(self, agent_name: str) -> str:
        """
        Get domain for specific agent.

        Args:
            agent_name: Agent name to look up

        Returns:
            Agent's domain context
        """
        return self.agent_to_domain.get(agent_name, "general")

    def find_agents_with_multiple_capabilities(
        self, capabilities: list[str]
    ) -> list[tuple[str, int]]:
        """
        Find agents with multiple capabilities.

        Useful for complex queries like:
        "Find agents that can do both debugging AND performance analysis"

        Args:
            capabilities: List of required capabilities

        Returns:
            List of (agent_name, capability_count) sorted by count (desc)
        """
        agent_counts: dict[str, int] = {}

        for capability in capabilities:
            agents = self.capability_to_agents.get(capability, set())
            for agent in agents:
                agent_counts[agent] = agent_counts.get(agent, 0) + 1

        # Sort by count (descending)
        return sorted(agent_counts.items(), key=lambda x: x[1], reverse=True)

    def find_agents_with_all_capabilities(self, capabilities: list[str]) -> list[str]:
        """
        Find agents that have ALL specified capabilities.

        Args:
            capabilities: List of required capabilities

        Returns:
            List of agent names that have all capabilities
        """
        if not capabilities:
            return []

        # Start with agents that have the first capability
        result_set = self.capability_to_agents.get(capabilities[0], set()).copy()

        # Intersect with agents that have each subsequent capability
        for capability in capabilities[1:]:
            result_set &= self.capability_to_agents.get(capability, set())

        return list(result_set)

    def get_all_capabilities(self) -> list[str]:
        """
        Get list of all unique capabilities across all agents.

        Returns:
            Sorted list of all capabilities
        """
        return sorted(self.capability_to_agents.keys())

    def get_all_domains(self) -> list[str]:
        """
        Get list of all unique domains across all agents.

        Returns:
            Sorted list of all domains
        """
        return sorted(self.domain_to_agents.keys())

    def stats(self) -> dict[str, int]:
        """
        Get index statistics.

        Returns:
            Dictionary with index statistics
        """
        avg_caps: float = (
            sum(len(caps) for caps in self.agent_to_capabilities.values())
            / len(self.agent_to_capabilities)
            if self.agent_to_capabilities
            else 0.0
        )
        return {
            "total_agents": len(self.agent_to_capabilities),
            "total_capabilities": len(self.capability_to_agents),
            "total_domains": len(self.domain_to_agents),
            "avg_capabilities_per_agent": int(avg_caps),
        }


# Standalone test
if __name__ == "__main__":
    registry_path = Path.home() / ".claude" / "agents" / "onex" / "agent-registry.yaml"

    if registry_path.exists():
        index = CapabilityIndex(str(registry_path))

        print("=== Capability Index Stats ===")
        stats = index.stats()
        for key, value in stats.items():
            if isinstance(value, float):
                print(f"{key}: {value:.1f}")
            else:
                print(f"{key}: {value}")

        print("\n=== All Capabilities ===")
        capabilities = index.get_all_capabilities()
        print(f"Total: {len(capabilities)}")
        for cap in capabilities[:10]:  # Show first 10
            agents = index.find_by_capability(cap)
            print(f"  {cap}: {len(agents)} agents")

        print("\n=== All Domains ===")
        domains = index.get_all_domains()
        for domain in domains:
            agents = index.find_by_domain(domain)
            print(f"  {domain}: {len(agents)} agents")

        print("\n=== Multi-Capability Search ===")
        # Find agents with multiple debugging-related capabilities
        debug_caps = ["debugging", "error_analysis", "root_cause"]
        results = index.find_agents_with_multiple_capabilities(debug_caps)
        print("Agents with debugging capabilities:")
        for agent, count in results[:5]:
            print(f"  {agent}: {count}/{len(debug_caps)} capabilities")

        print("\n=== Agents with ALL capabilities ===")
        # Find agents with all debugging capabilities
        all_debug = index.find_agents_with_all_capabilities(debug_caps)
        print(f"Agents with ALL {debug_caps}:")
        for agent in all_debug:
            print(f"  {agent}")
    else:
        print(f"Registry not found at: {registry_path}")
