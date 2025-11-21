#!/usr/bin/env python3
"""
Hybrid Agent Selector

Intelligent 3-stage agent selection pipeline:
1. Pattern Detection (explicit, ~1ms, confidence=1.0)
2. Trigger Matching (keyword, ~5ms, confidence=0.7-0.9)
3. AI Selection (semantic, ~500ms, confidence=0.0-1.0)

Author: OmniClaude Framework
Version: 1.0.0
"""

import json
import sys
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


# Add project root to path for config import
project_root = (
    Path(__file__).resolve().parents[2]
)  # lib → claude_hooks → omniclaude root
sys.path.insert(0, str(project_root))

# Import existing detection systems
from agent_detector import AgentDetector
from ai_agent_selector import AIAgentSelector

from config import settings


class SelectionMethod(Enum):
    """Agent selection method."""

    PATTERN = "pattern"
    TRIGGER = "trigger"
    AI = "ai"
    NONE = "none"


@dataclass
class AgentSelection:
    """Result of agent selection."""

    found: bool
    agent_name: Optional[str] = None
    confidence: float = 0.0
    method: SelectionMethod = SelectionMethod.NONE
    reasoning: str = ""
    latency_ms: float = 0.0
    alternatives: List[str] = None

    def __post_init__(self):
        if self.alternatives is None:
            self.alternatives = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        result["method"] = self.method.value
        return result


class HybridAgentSelector:
    """
    Intelligent agent selection with multi-stage fallback.

    Provides 3-stage detection:
    1. Pattern Detection: Fast explicit pattern matching
    2. Trigger Matching: Keyword-based agent discovery
    3. AI Selection: Semantic intent analysis (optional)

    Performance:
    - Stage 1: ~1-2ms (always runs)
    - Stage 2: ~2-5ms (runs if stage 1 fails)
    - Stage 3: ~100-500ms (optional, runs if stage 2 fails)
    """

    def __init__(
        self,
        enable_ai: bool = True,
        confidence_threshold: float = 0.8,
        model_preference: str = "auto",
        timeout_ms: int = 500,
        config: Optional[Dict] = None,
    ):
        """
        Initialize hybrid agent selector.

        Args:
            enable_ai: Enable AI-powered selection (Stage 3)
            confidence_threshold: Minimum confidence for AI selection
            model_preference: AI model to use (auto, local, gemini, glm, 5090)
            timeout_ms: Maximum time for AI selection
            config: Optional configuration dictionary
        """
        # Load configuration
        self.config = config or self._load_config()

        # Apply overrides from constructor
        self.enable_ai = (
            enable_ai if enable_ai is not None else self.config.get("enable_ai", True)
        )
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold
            else self.config.get("confidence_threshold", 0.8)
        )
        self.model_preference = model_preference or self.config.get(
            "model_preference", "auto"
        )
        self.timeout_ms = (
            timeout_ms if timeout_ms else self.config.get("timeout_ms", 500)
        )

        # Initialize detection systems
        self.pattern_detector = AgentDetector()
        self.ai_selector = None

        # Initialize AI selector if enabled
        if self.enable_ai:
            try:
                self.ai_selector = AIAgentSelector(
                    model_preference=self.model_preference, zen_mcp_available=True
                )
            except Exception as e:
                print(
                    f"Warning: AI selector initialization failed: {e}", file=sys.stderr
                )
                self.ai_selector = None
                self.enable_ai = False

        # Statistics tracking
        self.stats = {
            "total_selections": 0,
            "pattern_selections": 0,
            "trigger_selections": 0,
            "ai_selections": 0,
            "no_agent_selections": 0,
            "total_latency_ms": 0.0,
            "avg_latency_ms": 0.0,
        }

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from settings and config file."""
        # Use Pydantic Settings for base configuration
        # Note: These settings use environment variables automatically
        config = {
            "enable_ai": settings.enable_ai_agent_selection,
            "confidence_threshold": settings.ai_agent_confidence_threshold,
            "model_preference": settings.ai_model_preference,
            "timeout_ms": settings.ai_selection_timeout_ms,
        }

        # Try to load from config file for additional overrides
        config_path = Path.home() / ".claude" / "hooks" / "agent-selector-config.yaml"
        if config_path.exists():
            try:
                import yaml

                with open(config_path, "r") as f:
                    file_config = yaml.safe_load(f)
                    if file_config and "agent_selection" in file_config:
                        config.update(file_config["agent_selection"])
            except Exception as e:
                print(f"Warning: Could not load config file: {e}", file=sys.stderr)

        return config

    def select_agent(
        self, prompt: str, context: Optional[Dict] = None
    ) -> AgentSelection:
        """
        Select best agent using 3-stage pipeline.

        Args:
            prompt: User prompt
            context: Optional context (working_directory, files, etc.)

        Returns:
            AgentSelection with results
        """
        start_time = time.time()
        self.stats["total_selections"] += 1

        # Stage 1: Pattern Detection
        result = self._stage_1_pattern(prompt)
        if result.found:
            result.latency_ms = (time.time() - start_time) * 1000
            self._update_stats(result)
            return result

        # Stage 2: Trigger Matching
        result = self._stage_2_triggers(prompt)
        if result.found:
            result.latency_ms = (time.time() - start_time) * 1000
            self._update_stats(result)
            return result

        # Stage 3: AI Selection (if enabled)
        if self.enable_ai and self.ai_selector:
            result = self._stage_3_ai(prompt, context)
            if result.found and result.confidence >= self.confidence_threshold:
                result.latency_ms = (time.time() - start_time) * 1000
                self._update_stats(result)
                return result

        # No agent detected
        result = AgentSelection(
            found=False,
            confidence=0.0,
            method=SelectionMethod.NONE,
            reasoning="No agent matched in any detection stage",
            latency_ms=(time.time() - start_time) * 1000,
        )
        self.stats["no_agent_selections"] += 1
        self._update_stats(result)
        return result

    def _stage_1_pattern(self, prompt: str) -> AgentSelection:
        """
        Stage 1: Pattern Detection

        Detects explicit agent invocations:
        - @agent-name
        - use agent-name
        - invoke agent-name
        - Task(agent="agent-name")

        Performance: ~1-2ms
        Confidence: 1.0 (explicit)
        """
        agent_name = self.pattern_detector.detect_agent(prompt)

        if agent_name:
            # Load agent config to verify it exists
            config = self.pattern_detector.load_agent_config(agent_name)
            if config:
                return AgentSelection(
                    found=True,
                    agent_name=agent_name,
                    confidence=1.0,
                    method=SelectionMethod.PATTERN,
                    reasoning="Explicit agent invocation pattern detected in prompt",
                )

        return AgentSelection(found=False)

    def _stage_2_triggers(self, prompt: str) -> AgentSelection:
        """
        Stage 2: Trigger Matching

        Matches prompt against agent activation triggers.
        Uses keyword matching with scoring.

        Performance: ~2-5ms
        Confidence: 0.7-0.9 (keyword-based)
        """
        # Use the private method from AgentDetector
        agent_name = self.pattern_detector._detect_by_triggers(prompt)

        if agent_name:
            # Calculate confidence based on trigger matches from registry
            # Get triggers from registry (not individual config files)
            triggers = []
            if (
                self.pattern_detector._registry
                and "agents" in self.pattern_detector._registry
            ):
                for agent_key, agent_info in self.pattern_detector._registry[
                    "agents"
                ].items():
                    if agent_info.get("name") == agent_name:
                        triggers = agent_info.get("activation_triggers", [])
                        break

            if triggers:
                prompt_lower = prompt.lower()
                matches = sum(
                    1 for trigger in triggers if trigger.lower() in prompt_lower
                )

                # Confidence based on number of trigger matches
                confidence = min(0.7 + (matches * 0.1), 0.95)

                return AgentSelection(
                    found=True,
                    agent_name=agent_name,
                    confidence=confidence,
                    method=SelectionMethod.TRIGGER,
                    reasoning=f"Matched {matches} activation trigger(s) for {agent_name}",
                )

        return AgentSelection(found=False)

    def _stage_3_ai(self, prompt: str, context: Optional[Dict]) -> AgentSelection:
        """
        Stage 3: AI Selection

        Uses AI models to analyze prompt semantically and select best agent.

        Models:
        - Local: DeepSeek on RTX 5090 (via Ollama)
        - Cloud: Gemini Flash, GLM-4.6 (via Zen MCP)

        Performance: ~100-500ms
        Confidence: 0.0-1.0 (AI-scored)
        """
        if not self.ai_selector:
            return AgentSelection(found=False)

        try:
            # Call AI selector
            selections = self.ai_selector.select_agent(
                prompt=prompt,
                context=context,
                top_n=3,  # Get top 3 for alternatives
            )

            if selections and len(selections) > 0:
                # Extract primary selection
                agent_name, confidence, reasoning = selections[0]

                # Extract alternatives
                alternatives = [name for name, _, _ in selections[1:]]

                return AgentSelection(
                    found=True,
                    agent_name=agent_name,
                    confidence=confidence,
                    method=SelectionMethod.AI,
                    reasoning=reasoning,
                    alternatives=alternatives,
                )

        except Exception as e:
            print(f"AI selection failed: {e}", file=sys.stderr)

        return AgentSelection(found=False)

    def _update_stats(self, result: AgentSelection):
        """Update selection statistics."""
        if result.method == SelectionMethod.PATTERN:
            self.stats["pattern_selections"] += 1
        elif result.method == SelectionMethod.TRIGGER:
            self.stats["trigger_selections"] += 1
        elif result.method == SelectionMethod.AI:
            self.stats["ai_selections"] += 1

        self.stats["total_latency_ms"] += result.latency_ms
        if self.stats["total_selections"] > 0:
            self.stats["avg_latency_ms"] = (
                self.stats["total_latency_ms"] / self.stats["total_selections"]
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get selection statistics."""
        stats = dict(self.stats)

        # Add AI selector stats if available
        if self.ai_selector:
            stats["ai_selector_stats"] = self.ai_selector.get_stats()

        # Add rates
        if stats["total_selections"] > 0:
            total = stats["total_selections"]
            stats["pattern_rate"] = stats["pattern_selections"] / total
            stats["trigger_rate"] = stats["trigger_selections"] / total
            stats["ai_rate"] = stats["ai_selections"] / total
            stats["no_agent_rate"] = stats["no_agent_selections"] / total

        return stats


# ============================================================================
# CLI Interface
# ============================================================================


def main():
    """CLI interface for hybrid agent selector."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Hybrid agent selector with AI fallback"
    )
    parser.add_argument("prompt", nargs="+", help="User prompt to analyze")
    parser.add_argument(
        "--enable-ai",
        type=str,
        default="true",
        choices=["true", "false"],
        help="Enable AI-powered selection",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.8,
        help="Minimum confidence for AI selection",
    )
    parser.add_argument(
        "--model-preference",
        default="auto",
        choices=["auto", "local", "gemini", "glm", "5090"],
        help="AI model preference",
    )
    parser.add_argument(
        "--timeout", type=int, default=500, help="AI selection timeout (ms)"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Show selection statistics"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    # Join prompt parts or read from stdin
    if len(args.prompt) == 1 and args.prompt[0] == "-":
        # Read from stdin (Unix convention)
        prompt = sys.stdin.read().strip()
    else:
        prompt = " ".join(args.prompt)

    # Initialize selector
    selector = HybridAgentSelector(
        enable_ai=args.enable_ai.lower() == "true",
        confidence_threshold=args.confidence_threshold,
        model_preference=args.model_preference,
        timeout_ms=args.timeout,
    )

    # Select agent
    result = selector.select_agent(prompt)

    if args.json:
        # JSON output
        output = result.to_dict()
        if args.stats:
            output["stats"] = selector.get_stats()
        print(json.dumps(output, indent=2))
    else:
        # Shell-friendly output (for hook integration)
        if result.found:
            print(f"AGENT_DETECTED:{result.agent_name}")
            print(f"CONFIDENCE:{result.confidence}")
            print(f"METHOD:{result.method.value}")
            print(f"REASONING:{result.reasoning}")
            print(f"LATENCY_MS:{result.latency_ms:.2f}")

            if result.alternatives:
                print(f"ALTERNATIVES:{','.join(result.alternatives)}")

            # Load agent config for additional metadata
            config = selector.pattern_detector.load_agent_config(result.agent_name)
            if config:
                queries = selector.pattern_detector.extract_intelligence_queries(config)
                print(f"DOMAIN_QUERY:{queries['domain_query']}")
                print(f"IMPLEMENTATION_QUERY:{queries['implementation_query']}")
                print(f"AGENT_DOMAIN:{queries['agent_domain']}")
                print(f"AGENT_PURPOSE:{queries['agent_purpose']}")
        else:
            print("NO_AGENT_DETECTED")

        if args.stats:
            print("\n--- Selection Statistics ---", file=sys.stderr)
            stats = selector.get_stats()
            for key, value in stats.items():
                print(f"{key}: {value}", file=sys.stderr)


if __name__ == "__main__":
    main()
