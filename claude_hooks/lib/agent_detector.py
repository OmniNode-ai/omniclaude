#!/usr/bin/env python3
"""
Agent Pattern Detection Library
Identifies agent invocations in user prompts and extracts agent configuration.
"""

import re
import sys
import yaml
from pathlib import Path
from typing import Optional, Dict, Any


class AgentDetector:
    """Detects and extracts agent invocation patterns from prompts."""

    AGENT_PATTERNS = [
        r"@(agent-[a-z0-9-]+)",  # @agent-name pattern (lowercase only, no underscores)
        r'Task\([^)]*agent["\']?\s*[:=]\s*["\']([^"\']+)["\']',  # Task(agent="agent-name")
        r"use\s+(?:the\s+)?(agent-[a-z0-9-]+)",  # use agent-name, use the agent-name
        r"invoke\s+(?:the\s+)?(agent-[a-z0-9-]+)",  # invoke agent-name, invoke the agent-name
        r'subagent_type["\']?\s*[:=]\s*["\']([^"\']+)["\']',  # subagent_type="agent-name"
        # Add flexible workflow coordinator patterns
        r"(?:use|invoke)\s+(?:the\s+)?agent\s+workflow\s+coordinator",  # "use agent workflow coordinator"
        r"(?:use|invoke)\s+(?:the\s+)?workflow\s+coordinator",  # "use workflow coordinator"
        r"(?:use|invoke)\s+(?:the\s+)?agent\s+workflow\s+coordination",  # "use agent workflow coordination"
    ]

    # Automated workflow trigger patterns - launch dispatch_runner.py
    AUTOMATED_WORKFLOW_PATTERNS = [
        r"coordinate\s+(?:a\s+)?workflow",          # "coordinate a workflow", "coordinate workflow"
        r"orchestrate\s+(?:a\s+)?workflow",         # "orchestrate a workflow"
        r"execute\s+workflow",                      # "execute workflow"
        r"run\s+(?:automated\s+)?workflow",         # "run workflow", "run automated workflow"
    ]

    AGENT_CONFIG_DIR = Path.home() / ".claude" / "agents" / "configs"
    AGENT_REGISTRY_PATH = Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"

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
                pattern = r'\b' + re.escape(trigger_lower) + r'(?:s|ing|ed)?\b'
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

    def detect_agent(self, prompt: str) -> Optional[str]:
        """
        Detect agent invocation pattern in prompt using explicit patterns only.
        Does NOT perform trigger-based matching - that's handled by HybridAgentSelector.

        Args:
            prompt: User prompt text

        Returns:
            Agent name if detected, None otherwise
        """
        # Try explicit pattern matching (case-insensitive)
        for i, pattern in enumerate(self.AGENT_PATTERNS):
            match = re.search(pattern, prompt, re.IGNORECASE)  # Case-insensitive matching
            if match:
                # Handle patterns that capture groups vs those that don't
                if match.groups():
                    agent_name = match.group(1)
                    # Ensure it starts with 'agent-'
                    if not agent_name.startswith("agent-"):
                        agent_name = f"agent-{agent_name}"
                    return agent_name
                else:
                    # Handle workflow coordinator patterns that don't capture groups
                    if "workflow" in pattern and "coordinator" in pattern:
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
        config_path = self.AGENT_CONFIG_DIR / f"{agent_name}.yaml"

        if not config_path.exists():
            return None

        try:
            with open(config_path, "r") as f:
                # Use safe_load_all to handle files with multiple YAML documents
                # Take the first document (agent config)
                docs = list(yaml.safe_load_all(f))
                if not docs:
                    return None
                config = docs[0]

                if not isinstance(config, dict):
                    return None

                return config
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
        return {
            "domain_query": agent_config.get("domain_query", ""),
            "implementation_query": agent_config.get("implementation_query", ""),
            "agent_context": agent_config.get("agent_context", "general"),
            "match_count": agent_config.get("match_count", 5),
            "agent_domain": agent_config.get("agent_domain", ""),
            "agent_purpose": agent_config.get("agent_purpose", ""),
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
