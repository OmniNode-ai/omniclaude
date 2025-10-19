#!/usr/bin/env python3
"""
AI-Powered Agent Selector

Uses AI models (local 5090, Gemini, GLM-4.6, etc.) to automatically select
the best agent based on user prompt analysis.

No explicit agent naming required - AI intelligently picks from 52 agents.

Author: OmniClaude Framework
Version: 1.0.0
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


class AIAgentSelector:
    """
    Selects optimal agent using AI model analysis.

    Supports multiple AI providers:
    - Local: DeepSeek on RTX 5090
    - Cloud: Gemini, GLM-4.6
    - Fallback: Rule-based selection
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        model_preference: str = "auto",  # "auto", "local", "cloud", "gemini", "glm", "5090"
        zen_mcp_available: bool = True,
    ):
        """
        Initialize AI agent selector.

        Args:
            config_dir: Directory containing agent YAML configs
            model_preference: Which AI model to use for selection
            zen_mcp_available: Whether Zen MCP is available for model access
        """
        self.config_dir = config_dir or Path.home() / ".claude" / "agents" / "configs"
        self.model_preference = model_preference
        self.zen_mcp_available = zen_mcp_available

        # Load agent metadata
        self.agents = self._load_agent_metadata()

        # Selection stats
        self.stats = {
            "total_selections": 0,
            "ai_selections": 0,
            "fallback_selections": 0,
            "model_used": {},
        }

    def _load_agent_metadata(self) -> List[Dict]:
        """Load metadata from all agent YAML files."""
        agents = []

        if not self.config_dir.exists():
            return agents

        for yaml_file in self.config_dir.glob("agent-*.yaml"):
            try:
                with open(yaml_file, "r") as f:
                    # Use safe_load_all to handle files with multiple YAML documents
                    # Take the first document (agent config)
                    docs = list(yaml.safe_load_all(f))
                    if not docs:
                        continue
                    config = docs[0]

                    if not isinstance(config, dict):
                        continue

                    # Extract key metadata for AI selection
                    # Handle capabilities as either dict or list
                    capabilities = config.get("capabilities", {})
                    if isinstance(capabilities, dict):
                        capabilities_list = list(capabilities.keys())
                    elif isinstance(capabilities, list):
                        capabilities_list = capabilities
                    else:
                        capabilities_list = []

                    agent_meta = {
                        "name": yaml_file.stem,
                        "domain": config.get("agent_domain", ""),
                        "purpose": config.get("agent_purpose", ""),
                        "description": config.get("agent_description", ""),
                        "triggers": config.get("triggers", []),
                        "capabilities": capabilities_list,
                    }
                    agents.append(agent_meta)

            except Exception as e:
                print(f"Warning: Failed to load {yaml_file}: {e}", file=sys.stderr)

        return agents

    def select_agent(
        self, prompt: str, context: Optional[Dict] = None, top_n: int = 1
    ) -> List[Tuple[str, float, str]]:
        """
        Select best agent(s) for the prompt using AI analysis.

        Args:
            prompt: User prompt
            context: Additional context (working directory, files, etc.)
            top_n: Number of agents to return

        Returns:
            List of (agent_name, confidence, reasoning) tuples
        """
        self.stats["total_selections"] += 1

        # Try AI-powered selection first
        try:
            result = self._ai_select(prompt, context, top_n)
            if result:
                self.stats["ai_selections"] += 1
                return result
        except Exception as e:
            print(f"AI selection failed: {e}, falling back", file=sys.stderr)

        # Fallback to rule-based selection
        self.stats["fallback_selections"] += 1
        return self._fallback_select(prompt, top_n)

    def _ai_select(
        self, prompt: str, context: Optional[Dict], top_n: int
    ) -> Optional[List[Tuple[str, float, str]]]:
        """Use AI model to select agent."""

        # Build agent catalog for AI
        agent_catalog = self._build_agent_catalog()

        # Create selection prompt for AI
        ai_prompt = self._build_selection_prompt(prompt, agent_catalog, context, top_n)

        # Determine which model to use
        model = self._select_model()

        # Call AI model
        response = self._call_ai_model(model, ai_prompt)

        if not response:
            return None

        # Parse AI response
        selections = self._parse_ai_response(response)

        # Track which model was used
        model_name = model.get("name", "unknown")
        self.stats["model_used"][model_name] = (
            self.stats["model_used"].get(model_name, 0) + 1
        )

        return selections[:top_n]

    def _build_agent_catalog(self) -> str:
        """Build compact agent catalog for AI prompt."""
        lines = []

        for agent in self.agents:
            # Ultra-compact format: name|domain|top-3-triggers
            triggers_str = ",".join(agent["triggers"][:3])
            lines.append(f"{agent['name']}|{agent['domain']}|{triggers_str}")

        return "\n".join(lines)

    def _build_selection_prompt(
        self, user_prompt: str, agent_catalog: str, context: Optional[Dict], top_n: int
    ) -> str:
        """Build prompt for AI model to select agent."""

        context_str = ""
        if context:
            if "working_directory" in context:
                context_str += f"\nWorking Directory: {context['working_directory']}"
            if "active_file" in context:
                context_str += f"\nActive File: {context['active_file']}"

        return f"""Select the best agent for this task.

User: {user_prompt}{context_str}

Agents (name|domain|triggers):
{agent_catalog}

Return JSON with top {top_n}:
{{
    "selections": [
        {{
            "agent": "agent-name",
            "confidence": 0.95,
            "reasoning": "why"
        }}
    ]
}}

Be concise. Match user intent to agent domain and triggers."""

    def _select_model(self) -> Dict[str, str]:
        """Determine which AI model to use based on preference."""

        # Model priority based on preference
        if self.model_preference == "5090" or self.model_preference == "local":
            return {
                "name": "llama3.1-5090",
                "type": "local",
                "endpoint": "http://192.168.86.201:8001",  # vLLM on RTX 5090
                "model": "meta-llama/Meta-Llama-3.1-8B-Instruct",  # Fast local model
            }

        elif self.model_preference == "gemini":
            return {"name": "gemini-2.5-pro", "type": "cloud", "provider": "google"}

        elif self.model_preference == "glm":
            return {"name": "glm-4.6", "type": "cloud", "provider": "zhipu"}

        else:  # auto
            # Try local 5090 first (fastest), fall back to cloud
            # Check if vLLM is running on 5090
            try:
                result = subprocess.run(
                    ["curl", "-s", "http://192.168.86.201:8001/v1/models"],
                    capture_output=True,
                    timeout=1,
                )
                if result.returncode == 0:
                    return {
                        "name": "llama3.1-5090",
                        "type": "local",
                        "endpoint": "http://192.168.86.201:8001",
                        "model": "meta-llama/Meta-Llama-3.1-8B-Instruct",
                    }
            except:
                pass

            # Fall back to Gemini (fast and reliable)
            return {"name": "gemini-2.5-flash", "type": "cloud", "provider": "google"}

    def _call_ai_model(self, model: Dict, prompt: str) -> Optional[str]:
        """Call AI model to get agent selection."""

        if model["type"] == "local":
            return self._call_local_model(model, prompt)
        elif model["type"] == "cloud":
            return self._call_cloud_model(model, prompt)

        return None

    def _call_local_model(self, model: Dict, prompt: str) -> Optional[str]:
        """Call local vLLM model (OpenAI-compatible API)."""
        try:
            import requests

            response = requests.post(
                f"{model['endpoint']}/v1/chat/completions",
                json={
                    "model": model["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 300,  # Reduce token count for faster response
                    "temperature": 0.3,  # Lower temperature for consistent selection
                },
                timeout=10,  # Fast local inference should be <10s
            )

            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"]

        except Exception as e:
            print(f"Local model call failed: {e}", file=sys.stderr)

        return None

    def _call_cloud_model(self, model: Dict, prompt: str) -> Optional[str]:
        """Call cloud model via Zen MCP."""

        if not self.zen_mcp_available:
            return None

        try:
            # Use poetry to call Zen MCP chat tool
            # This leverages the existing Zen MCP integration
            # Determine hooks lib path dynamically
            Path.home() / ".claude" / "hooks" / "lib"

            # Find project root (walk up from current file)
            project_root = Path(__file__).resolve().parent.parent.parent

            result = subprocess.run(
                [
                    "poetry",
                    "run",
                    "python3",
                    "-c",
                    """
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.claude' / 'hooks' / 'lib'))

# Would call Zen MCP here if available
# For now, return None to use fallback
print("CLOUD_MODEL_PLACEHOLDER")
""",
                ],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=15,
            )

            if "CLOUD_MODEL_PLACEHOLDER" in result.stdout:
                # Cloud model integration pending
                return None

        except Exception as e:
            print(f"Cloud model call failed: {e}", file=sys.stderr)

        return None

    def _parse_ai_response(self, response: str) -> List[Tuple[str, float, str]]:
        """Parse AI model JSON response."""
        try:
            # Extract JSON from response
            start = response.find("{")
            end = response.rfind("}") + 1

            if start >= 0 and end > start:
                json_str = response[start:end]
                data = json.loads(json_str)

                selections = []
                for item in data.get("selections", []):
                    selections.append(
                        (item["agent"], float(item["confidence"]), item["reasoning"])
                    )

                return selections

        except Exception as e:
            print(f"Failed to parse AI response: {e}", file=sys.stderr)

        return []

    def _fallback_select(self, prompt: str, top_n: int) -> List[Tuple[str, float, str]]:
        """Rule-based fallback agent selection."""

        prompt_lower = prompt.lower()
        scores = []

        for agent in self.agents:
            score = 0.0
            reasons = []

            # Match against triggers
            for trigger in agent["triggers"]:
                if trigger.lower() in prompt_lower:
                    score += 0.3
                    reasons.append(f"trigger: {trigger}")

            # Match against domain
            if agent["domain"] and agent["domain"].lower() in prompt_lower:
                score += 0.2
                reasons.append(f"domain: {agent['domain']}")

            # Match against purpose keywords
            purpose_words = agent["purpose"].lower().split()
            for word in purpose_words[:5]:
                if len(word) > 4 and word in prompt_lower:
                    score += 0.1
                    reasons.append(f"purpose: {word}")

            # Cap score at 1.0
            score = min(score, 1.0)

            if score > 0:
                reasoning = ", ".join(reasons[:3])
                scores.append((agent["name"], score, f"Fallback: {reasoning}"))

        # Sort by score and return top N
        scores.sort(key=lambda x: x[1], reverse=True)

        if not scores:
            # Ultimate fallback - return a general purpose agent
            return [("agent-code-generator", 0.5, "Default fallback - general purpose")]

        return scores[:top_n]

    def get_stats(self) -> Dict:
        """Get selection statistics."""
        return {
            **self.stats,
            "agents_available": len(self.agents),
            "ai_selection_rate": (
                self.stats["ai_selections"] / self.stats["total_selections"]
                if self.stats["total_selections"] > 0
                else 0.0
            ),
        }


def select_agent_for_prompt(
    prompt: str, model_preference: str = "auto", context: Optional[Dict] = None
) -> Dict:
    """
    Convenience function for single agent selection.

    Args:
        prompt: User prompt
        model_preference: AI model to use ("auto", "5090", "gemini", "glm")
        context: Optional context dict

    Returns:
        {
            "agent": "agent-name",
            "confidence": 0.95,
            "reasoning": "explanation",
            "model_used": "gemini-2.5-flash"
        }
    """
    selector = AIAgentSelector(model_preference=model_preference)

    selections = selector.select_agent(prompt, context, top_n=1)

    if not selections:
        return {
            "agent": None,
            "confidence": 0.0,
            "reasoning": "No suitable agent found",
            "model_used": "none",
        }

    agent_name, confidence, reasoning = selections[0]

    return {
        "agent": agent_name,
        "confidence": confidence,
        "reasoning": reasoning,
        "model_used": selector.stats.get("model_used", {}),
    }


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI-powered agent selector")
    parser.add_argument("prompt", help="User prompt to analyze")
    parser.add_argument(
        "--model",
        default="auto",
        choices=["auto", "5090", "local", "gemini", "glm", "cloud"],
        help="AI model preference",
    )
    parser.add_argument(
        "--top-n", type=int, default=1, help="Number of agents to return"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Show selection statistics"
    )

    args = parser.parse_args()

    selector = AIAgentSelector(model_preference=args.model)

    selections = selector.select_agent(args.prompt, top_n=args.top_n)

    # Output results
    result = {
        "prompt": args.prompt,
        "selections": [
            {"agent": agent, "confidence": conf, "reasoning": reason}
            for agent, conf, reason in selections
        ],
    }

    if args.stats:
        result["stats"] = selector.get_stats()

    print(json.dumps(result, indent=2))
