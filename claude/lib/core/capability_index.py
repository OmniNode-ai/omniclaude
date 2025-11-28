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

from pathlib import Path
from typing import Dict, List, Set, Tuple

import yaml


class CapabilityIndex:
    """
    In-memory index of agent capabilities for fast lookup.

    Builds inverted indexes on initialization for O(1) capability
    and domain lookups.
    """

    def __init__(self, registry_path: str):
        """
        Initialize index from agent registry.

        Args:
            registry_path: Path to agent-registry.yaml file
        """
        self.registry_path = registry_path
        self.capability_to_agents: Dict[str, Set[str]] = {}
        self.agent_to_capabilities: Dict[str, List[str]] = {}
        self.domain_to_agents: Dict[str, Set[str]] = {}
        self.agent_to_domain: Dict[str, str] = {}

        self._build_index()

    def _build_index(self):
        """
        Build inverted indexes from registry.

        Creates:
        - capability_to_agents: capability -> set of agent names
        - agent_to_capabilities: agent name -> list of capabilities
        - domain_to_agents: domain -> set of agent names
        - agent_to_domain: agent name -> domain
        """
        with open(self.registry_path) as f:
            registry = yaml.safe_load(f)

        for agent_name, agent_data in registry["agents"].items():
            # Index capabilities
            capabilities = agent_data.get("capabilities", [])
            self.agent_to_capabilities[agent_name] = capabilities

            for capability in capabilities:
                if capability not in self.capability_to_agents:
                    self.capability_to_agents[capability] = set()
                self.capability_to_agents[capability].add(agent_name)

            # Index domain
            domain = agent_data.get("domain_context", "general")
            self.agent_to_domain[agent_name] = domain

            if domain not in self.domain_to_agents:
                self.domain_to_agents[domain] = set()
            self.domain_to_agents[domain].add(agent_name)

    def find_by_capability(self, capability: str) -> List[str]:
        """
        Find agents with specific capability.

        Args:
            capability: Capability to search for

        Returns:
            List of agent names with this capability
        """
        return list(self.capability_to_agents.get(capability, set()))

    def find_by_domain(self, domain: str) -> List[str]:
        """
        Find agents for specific domain.

        Args:
            domain: Domain to search for

        Returns:
            List of agent names in this domain
        """
        return list(self.domain_to_agents.get(domain, set()))

    def get_capabilities(self, agent_name: str) -> List[str]:
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
        self, capabilities: List[str]
    ) -> List[Tuple[str, int]]:
        """
        Find agents with multiple capabilities.

        Useful for complex queries like:
        "Find agents that can do both debugging AND performance analysis"

        Args:
            capabilities: List of required capabilities

        Returns:
            List of (agent_name, capability_count) sorted by count (desc)
        """
        agent_counts: Dict[str, int] = {}

        for capability in capabilities:
            agents = self.capability_to_agents.get(capability, set())
            for agent in agents:
                agent_counts[agent] = agent_counts.get(agent, 0) + 1

        # Sort by count (descending)
        return sorted(agent_counts.items(), key=lambda x: x[1], reverse=True)

    def find_agents_with_all_capabilities(self, capabilities: List[str]) -> List[str]:
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

    def get_all_capabilities(self) -> List[str]:
        """
        Get list of all unique capabilities across all agents.

        Returns:
            Sorted list of all capabilities
        """
        return sorted(self.capability_to_agents.keys())

    def get_all_domains(self) -> List[str]:
        """
        Get list of all unique domains across all agents.

        Returns:
            Sorted list of all domains
        """
        return sorted(self.domain_to_agents.keys())

    def stats(self) -> Dict[str, int]:
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
    registry_path = (
        Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"
    )

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
