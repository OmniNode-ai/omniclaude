#!/usr/bin/env python3
"""
Agent Pattern Detection Library
Identifies agent invocations in user prompts and extracts agent configuration.
"""

import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class AgentDetector:
    """Detects and extracts agent invocation patterns from prompts."""

    AGENT_PATTERNS = [
        r"@(agent-[a-z0-9-]+)",  # @agent-name pattern (lowercase only, no underscores)
        r'Task\([^)]*agent["\']?\s*[:=]\s*["\']([^"\']+)["\']',  # Task(agent="agent-name")
        r"use\s+(?:the\s+)?(agent-[a-z0-9-]+)",  # use agent-name, use the agent-name
        r"invoke\s+(?:the\s+)?(agent-[a-z0-9-]+)",  # invoke agent-name, invoke the agent-name
        r'subagent_type["\']?\s*[:=]\s*["\']([^"\']+)["\']',  # subagent_type="agent-name"
        # Polly patterns (dictation-friendly for agent-workflow-coordinator)
        # Handles: poly, polly, pollys, pollies, etc (flexible for dictation errors)
        r"dispatch\s+(?:for\s+|4\s+)?pol(?:ly|y|lys|ys|lies|ies|lie|ie)",  # "dispatch for Polly", "dispatch 4 poly"
        r"@pol(?:ly|y|lys|ys|lies|ies|lie|ie)",  # "@poly", "@polly", "@pollys"
        r"use\s+(?:the\s+)?pol(?:ly|y|lys|ys|lies|ies|lie|ie)",  # "use poly", "use the polly"
        r"invoke\s+(?:the\s+)?pol(?:ly|y|lys|ys|lies|ies|lie|ie)",  # "invoke poly", "invoke pollies"
        # Add flexible workflow coordinator patterns
        r"(?:use|invoke)\s+(?:the\s+)?agent\s+workflow\s+coordinator",  # "use agent workflow coordinator"
        r"(?:use|invoke)\s+(?:the\s+)?workflow\s+coordinator",  # "use workflow coordinator"
        r"(?:use|invoke)\s+(?:the\s+)?agent\s+workflow\s+coordination",  # "use agent workflow coordination"
    ]

    # Context-aware generic patterns - extract task description for intelligent routing
    GENERIC_AGENT_PATTERNS = [
        r"use\s+(?:an?\s+)?agent\s+(?:to\s+|for\s+)?(.+)",  # "use an agent to verify Qdrant"
        r"dispatch\s+(?:an?\s+)?agent\s+(?:to\s+|for\s+)?(.+)",  # "dispatch an agent to check logs"
        r"Task\(([^)]+)\)",  # Task(description) - bare task calls
        r"spawn\s+(?:an?\s+)?agent\s+(?:to\s+|for\s+)?(.+)",  # "spawn an agent to analyze"
        r"call\s+(?:an?\s+)?agent\s+(?:to\s+|for\s+)?(.+)",  # "call an agent to investigate"
        r"invoke\s+(?:an?\s+)?agent\s+(?:to\s+|for\s+)?(.+)",  # "invoke an agent for testing"
    ]

    # Automated workflow trigger patterns - launch dispatch_runner.py
    AUTOMATED_WORKFLOW_PATTERNS = [
        r"coordinate\s+(?:a\s+)?workflow",  # "coordinate a workflow", "coordinate workflow"
        r"orchestrate\s+(?:a\s+)?workflow",  # "orchestrate a workflow"
        r"execute\s+workflow",  # "execute workflow"
        r"run\s+(?:automated\s+)?workflow",  # "run workflow", "run automated workflow"
    ]

    # Use agent-definitions/ (consolidated system)
    AGENT_CONFIG_DIR = Path.home() / ".claude" / "agent-definitions"
    AGENT_REGISTRY_PATH = (
        Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"
    )

    def __init__(self):
        """Initialize detector and load agent registry."""
        self._registry = None
        self._load_registry()

    def _load_registry(self):
        """Load agent registry for trigger-based detection."""
        try:
            if self.AGENT_REGISTRY_PATH.exists():
                with open(self.AGENT_REGISTRY_PATH, "r") as f:
                    self._registry = yaml.safe_load(f)
        except Exception as e:
            print(f"Warning: Could not load agent registry: {e}", file=sys.stderr)
            self._registry = None

    def _detect_by_triggers(self, prompt: str) -> Optional[str]:
        """
        Detect agent by matching prompt against activation triggers.
        Uses word-boundary matching to avoid false positives.

        Args:
            prompt: User prompt text

        Returns:
            Agent name if triggers match, None otherwise
        """
        if not self._registry or "agents" not in self._registry:
            return None

        prompt_lower = prompt.lower()
        best_match = None
        best_score = 0

        for agent_key, agent_info in self._registry["agents"].items():
            triggers = agent_info.get("activation_triggers", [])
            if not triggers:
                continue

            # Count how many triggers match with flexible matching
            matches = 0
            for trigger in triggers:
                trigger_lower = trigger.lower()
                # Use flexible matching that handles plurals and variations
                # Match "test" in "tests", "testing", etc.
                pattern = r"\b" + re.escape(trigger_lower) + r"(?:s|ing|ed)?\b"
                if re.search(pattern, prompt_lower):
                    matches += 1

            if matches > best_score:
                best_score = matches
                best_match = agent_info.get("name", f"agent-{agent_key}")

        # Require at least 1 trigger match
        return best_match if best_score > 0 else None

    def detect_automated_workflow(self, prompt: str) -> bool:
        """
        Detect if user wants to trigger automated Python workflow (dispatch_runner.py).

        Args:
            prompt: User prompt text

        Returns:
            True if automated workflow trigger detected, False otherwise
        """
        prompt_lower = prompt.lower()

        for pattern in self.AUTOMATED_WORKFLOW_PATTERNS:
            if re.search(pattern, prompt_lower):
                return True

        return False

    def detect_generic_agent_invocation(self, prompt: str) -> Optional[Dict[str, str]]:
        """
        Detect generic agent invocation patterns that require context-aware routing.

        Patterns like "use an agent to X" or "Task(X)" don't specify an agent,
        so we extract the task description and let the router analyze context.

        Args:
            prompt: User prompt text

        Returns:
            Dict with 'type': 'generic' and 'task_description' if matched, None otherwise
        """
        for pattern in self.GENERIC_AGENT_PATTERNS:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match and match.groups():
                task_description = match.group(1).strip()
                return {
                    "type": "generic",
                    "task_description": task_description,
                    "original_prompt": prompt,
                }

        return None

    def detect_agent(self, prompt: str) -> Optional[str]:
        """
        Detect agent invocation pattern in prompt using explicit patterns only.
        Does NOT perform trigger-based matching - that's handled by HybridAgentSelector.

        Args:
            prompt: User prompt text

        Returns:
            Agent name if detected, 'CONTEXT_AWARE_ROUTING' for generic patterns, None otherwise
        """
        # First check for generic patterns that need context-aware routing
        generic_match = self.detect_generic_agent_invocation(prompt)
        if generic_match:
            # Return special marker to signal context-aware routing needed
            return "CONTEXT_AWARE_ROUTING"

        # Try explicit pattern matching (case-insensitive)
        for i, pattern in enumerate(self.AGENT_PATTERNS):
            match = re.search(
                pattern, prompt, re.IGNORECASE
            )  # Case-insensitive matching
            if match:
                # Handle patterns that capture groups vs those that don't
                if match.groups():
                    agent_name = match.group(1)
                    # Ensure it starts with 'agent-'
                    if not agent_name.startswith("agent-"):
                        agent_name = f"agent-{agent_name}"
                    return agent_name
                else:
                    # Handle patterns that don't capture groups
                    # Map to agent-workflow-coordinator for both "workflow" and "pol" patterns
                    if (
                        "workflow" in pattern and "coordinator" in pattern
                    ) or "pol" in pattern:
                        return "agent-workflow-coordinator"

        # No pattern matched - return None
        # Note: Trigger-based detection is available via _detect_by_triggers()
        # but is intentionally not called here to keep pattern detection pure
        return None

    def load_agent_config(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Load agent configuration from YAML file.

        Args:
            agent_name: Name of the agent (e.g., 'agent-debug-intelligence')

        Returns:
            Agent configuration dict or None if not found
        """
        # Strip 'agent-' prefix from agent name for file lookup
        # Files are named 'research.yaml', 'performance.yaml', etc.
        # but agent names are 'agent-research', 'agent-performance', etc.
        file_name = (
            agent_name.replace("agent-", "", 1)
            if agent_name.startswith("agent-")
            else agent_name
        )
        config_path = self.AGENT_CONFIG_DIR / f"{file_name}.yaml"

        if not config_path.exists():
            # Try with full agent name as fallback
            config_path = self.AGENT_CONFIG_DIR / f"{agent_name}.yaml"
            if not config_path.exists():
                return None

        try:
            with open(config_path, "r") as f:
                content = f.read()

                # Handle files with YAML + Markdown content
                # Only parse content before first '---' separator (if present after frontmatter)
                # Split on '\n---\n' to separate YAML from markdown documentation
                parts = content.split("\n---\n")
                yaml_content = parts[0] if len(parts) > 1 else content

                # Parse only the YAML portion
                config = yaml.safe_load(yaml_content)

                if not config or not isinstance(config, dict):
                    return None

                result: Dict[str, Any] = config
                return result
        except Exception as e:
            print(f"Error loading agent config: {e}", file=sys.stderr)
            return None

    def extract_intelligence_queries(
        self, agent_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract domain and implementation queries from agent config.

        Args:
            agent_config: Loaded agent configuration

        Returns:
            Dict with domain_query, implementation_query, and other metadata
        """
        # Extract from nested YAML structure
        domain_queries = agent_config.get("framework_integration", {}).get(
            "domain_queries", {}
        )
        agent_identity = agent_config.get("agent_identity", {})
        agent_philosophy = agent_config.get("agent_philosophy", {})

        # Get domain and implementation queries
        domain_query = (
            domain_queries.get("domain", "") if isinstance(domain_queries, dict) else ""
        )
        implementation_query = (
            domain_queries.get("implementation", "")
            if isinstance(domain_queries, dict)
            else ""
        )

        # Get agent domain from capabilities or identity
        capabilities = agent_config.get("capabilities", {})
        if isinstance(capabilities, dict):
            primary_caps = capabilities.get("primary", [])
            agent_domain = (
                ", ".join(primary_caps[:2])
                if primary_caps
                else agent_identity.get("title", "")
            )
        else:
            agent_domain = agent_identity.get("title", "")

        # Get agent purpose from philosophy or identity
        agent_purpose = agent_philosophy.get(
            "core_responsibility", ""
        ) or agent_identity.get("description", "")

        return {
            "domain_query": domain_query,
            "implementation_query": implementation_query,
            "agent_context": "general",
            "match_count": 5,
            "agent_domain": agent_domain,
            "agent_purpose": agent_purpose,
        }

    def get_framework_references(self) -> list[str]:
        """
        Get list of framework references to inject.

        Returns:
            List of framework file references
        """
        return [
            "@MANDATORY_FUNCTIONS.md",
            "@quality-gates-spec.yaml",
            "@performance-thresholds.yaml",
            "@COMMON_WORKFLOW.md",
        ]


# CLI interface for testing
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: agent_detector.py <prompt>", file=sys.stderr)
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])  # Join all args to handle spaces
    detector = AgentDetector()

    agent_name = detector.detect_agent(prompt)

    if agent_name:
        print(f"AGENT_DETECTED:{agent_name}")

        config = detector.load_agent_config(agent_name)
        if config:
            queries = detector.extract_intelligence_queries(config)
            print(f"DOMAIN_QUERY:{queries['domain_query']}")
            print(f"IMPLEMENTATION_QUERY:{queries['implementation_query']}")
            print(f"AGENT_CONTEXT:{queries['agent_context']}")
            print(f"AGENT_DOMAIN:{queries['agent_domain']}")
            print(f"AGENT_PURPOSE:{queries['agent_purpose']}")
            print(f"MATCH_COUNT:{queries['match_count']}")
        else:
            print(f"CONFIG_NOT_FOUND:{agent_name}", file=sys.stderr)
    else:
        print("NO_AGENT_DETECTED")

    sys.exit(0)
