#!/usr/bin/env python3
"""
Agent Pathway Detector
Determines which invocation pathway to use for agent requests.

Three pathways supported:
1. coordinator: Spawn agent-workflow-coordinator for complex orchestration
2. direct_single: Execute single agent with context injection
3. direct_parallel: Execute multiple agents in parallel coordination

Author: OmniClaude Framework
Version: 1.0.0
"""

import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class PathwayDetection:
    """Result of pathway detection."""

    pathway: Optional[str]  # "coordinator" | "direct_single" | "direct_parallel" | None
    agents: List[str]  # Agent names to invoke
    task: str  # Cleaned task description
    confidence: float  # Detection confidence (0.0-1.0)
    trigger_pattern: Optional[str]  # Which pattern matched


class AgentPathwayDetector:
    """
    Detects which agent invocation pathway to use based on prompt analysis.

    Priority order:
    1. Explicit coordinator request (coordinate:, orchestrate:, @workflow-coordinator)
    2. Parallel direct agents (parallel:, concurrently:, @parallel)
    3. Single direct agent (@agent-name, use agent-name, invoke agent-name)
    4. Trigger-based detection (fallback to agent_detector.py patterns)
    """

    # Coordinator trigger patterns
    COORDINATOR_PATTERNS = [
        r"\b(coordinate|orchestrate):\s*",
        r"@workflow-coordinator\b",
        r"\bcoordinator\s+mode\b",
    ]

    # Parallel execution patterns
    PARALLEL_PATTERNS = [
        r"\b(parallel|concurrently):\s*",
        r"@parallel\b",
        r"\bmultiple\s+agents?\b",
    ]

    # Single agent patterns
    SINGLE_AGENT_PATTERNS = [
        r"@(agent-[\w-]+)",
        r"\buse\s+(agent-[\w-]+)",
        r"\binvoke\s+(agent-[\w-]+)",
        r"\bwith\s+(agent-[\w-]+)",
    ]

    # Agent name extraction
    AGENT_NAME_PATTERN = r"@?(agent-[\w-]+)"

    def __init__(self):
        """Initialize pathway detector."""
        self.detection_stats = {
            "coordinator": 0,
            "direct_single": 0,
            "direct_parallel": 0,
            "no_agent": 0,
        }

    def detect(self, prompt: str) -> PathwayDetection:
        """
        Detect which invocation pathway to use.

        Args:
            prompt: User prompt to analyze

        Returns:
            PathwayDetection with pathway, agents, task, and confidence
        """
        # Priority 1: Check for coordinator request
        coordinator_result = self._check_coordinator(prompt)
        if coordinator_result:
            self.detection_stats["coordinator"] += 1
            return coordinator_result

        # Priority 2: Check for parallel agents
        parallel_result = self._check_parallel(prompt)
        if parallel_result:
            self.detection_stats["direct_parallel"] += 1
            return parallel_result

        # Priority 3: Check for single agent
        single_result = self._check_single_agent(prompt)
        if single_result:
            self.detection_stats["direct_single"] += 1
            return single_result

        # No agent invocation detected
        self.detection_stats["no_agent"] += 1
        return PathwayDetection(pathway=None, agents=[], task=prompt, confidence=1.0, trigger_pattern=None)

    def _check_coordinator(self, prompt: str) -> Optional[PathwayDetection]:
        """Check if prompt requests coordinator dispatch."""
        for pattern in self.COORDINATOR_PATTERNS:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                # Extract task after trigger
                task = re.sub(pattern, "", prompt, flags=re.IGNORECASE).strip()
                return PathwayDetection(
                    pathway="coordinator",
                    agents=["agent-workflow-coordinator"],
                    task=task or prompt,
                    confidence=1.0,
                    trigger_pattern=pattern,
                )
        return None

    def _check_parallel(self, prompt: str) -> Optional[PathwayDetection]:
        """Check if prompt requests parallel agent execution."""
        for pattern in self.PARALLEL_PATTERNS:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                # Extract all agent names from prompt
                agents = self._extract_agent_names(prompt)

                # Must have at least 2 agents for parallel mode
                if len(agents) >= 2:
                    # Clean task by removing parallel trigger and agent names
                    task = self._clean_task(prompt, pattern, agents)

                    return PathwayDetection(
                        pathway="direct_parallel", agents=agents, task=task, confidence=0.95, trigger_pattern=pattern
                    )

        # Alternative: Check for multiple @agent mentions without explicit parallel keyword
        agents = self._extract_agent_names(prompt)
        if len(agents) >= 2:
            # Implicit parallel mode (lower confidence)
            task = self._clean_task(prompt, None, agents)
            return PathwayDetection(
                pathway="direct_parallel",
                agents=agents,
                task=task,
                confidence=0.85,
                trigger_pattern="implicit_multiple_agents",
            )

        return None

    def _check_single_agent(self, prompt: str) -> Optional[PathwayDetection]:
        """Check if prompt requests single agent execution."""
        for pattern in self.SINGLE_AGENT_PATTERNS:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                agent_name = match.group(1)

                return PathwayDetection(
                    pathway="direct_single", agents=[agent_name], task=prompt, confidence=0.95, trigger_pattern=pattern
                )

        return None

    def _extract_agent_names(self, prompt: str) -> List[str]:
        """
        Extract all agent names from prompt.

        Returns:
            List of unique agent names found in prompt
        """
        matches = re.findall(self.AGENT_NAME_PATTERN, prompt, re.IGNORECASE)

        # Deduplicate while preserving order
        seen = set()
        unique_agents = []
        for agent in matches:
            if agent not in seen:
                seen.add(agent)
                unique_agents.append(agent)

        return unique_agents

    def _clean_task(self, prompt: str, trigger_pattern: Optional[str], agents: List[str]) -> str:
        """
        Clean task description by removing trigger keywords and agent names.

        Args:
            prompt: Original prompt
            trigger_pattern: Pattern that triggered detection (if any)
            agents: Agent names to remove

        Returns:
            Cleaned task description
        """
        task = prompt

        # Remove trigger pattern
        if trigger_pattern:
            task = re.sub(trigger_pattern, "", task, flags=re.IGNORECASE)

        # Remove agent name mentions (but keep context)
        # Replace "@agent-name" with empty string, but keep surrounding text
        for agent in agents:
            # Remove @agent-name mentions
            task = re.sub(rf"@{re.escape(agent)}\b", "", task, flags=re.IGNORECASE)
            # Remove "use agent-name" patterns
            task = re.sub(rf"\buse\s+{re.escape(agent)}\b", "", task, flags=re.IGNORECASE)
            task = re.sub(rf"\binvoke\s+{re.escape(agent)}\b", "", task, flags=re.IGNORECASE)
            task = re.sub(rf"\bwith\s+{re.escape(agent)}\b", "", task, flags=re.IGNORECASE)

        # Clean up extra whitespace and commas
        task = re.sub(r"\s*,\s*,\s*", ", ", task)  # Remove double commas
        task = re.sub(r"\s+", " ", task)  # Normalize whitespace
        task = task.strip(", ")  # Remove leading/trailing commas

        return task.strip()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get detection statistics.

        Returns:
            Dictionary with detection counts and rates
        """
        total = sum(self.detection_stats.values())
        if total == 0:
            return self.detection_stats

        return {
            **self.detection_stats,
            "total": total,
            "rates": {pathway: f"{count/total*100:.1f}%" for pathway, count in self.detection_stats.items()},
        }

    def reset_stats(self):
        """Reset detection statistics."""
        self.detection_stats = {
            "coordinator": 0,
            "direct_single": 0,
            "direct_parallel": 0,
            "no_agent": 0,
        }


def detect_invocation_pathway(prompt: str) -> Dict[str, Any]:
    """
    Convenience function for one-off pathway detection.

    Args:
        prompt: User prompt to analyze

    Returns:
        Dictionary with pathway detection results
    """
    detector = AgentPathwayDetector()
    result = detector.detect(prompt)

    return {
        "pathway": result.pathway,
        "agents": result.agents,
        "task": result.task,
        "confidence": result.confidence,
        "trigger_pattern": result.trigger_pattern,
    }


# ============================================================================
# CLI Interface for Testing
# ============================================================================

if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python agent_pathway_detector.py '<prompt>'")
        print("\nExamples:")
        print("  python agent_pathway_detector.py 'coordinate: Implement authentication'")
        print("  python agent_pathway_detector.py '@agent-testing Analyze test coverage'")
        print("  python agent_pathway_detector.py 'parallel: @agent-testing, @agent-commit Review PR'")
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])

    detector = AgentPathwayDetector()
    result = detector.detect(prompt)

    output = {
        "prompt": prompt,
        "detection": {
            "pathway": result.pathway,
            "agents": result.agents,
            "task": result.task,
            "confidence": result.confidence,
            "trigger_pattern": result.trigger_pattern,
        },
    }

    print(json.dumps(output, indent=2))
