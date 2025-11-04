#!/usr/bin/env python3
"""
Simple Agent Loader for Hook Integration
Loads agent YAML without heavy framework dependencies.

This is a lightweight alternative to agent_invoker.py for hook use cases.
"""

from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def load_agent_yaml(agent_name: str) -> Optional[Dict[str, Any]]:
    """
    Load agent configuration from YAML file.

    Args:
        agent_name: Name of agent to load (e.g., 'polymorphic-agent', 'agent-researcher')

    Returns:
        Agent config dictionary or None if not found
    """
    # Try multiple possible paths
    config_paths = [
        Path.home() / ".claude" / "agent-definitions" / f"{agent_name}.yaml",
        Path.home()
        / ".claude"
        / "agent-definitions"
        / f"{agent_name.replace('agent-', '')}.yaml",
        Path.home() / ".claude" / "agents" / "configs" / f"{agent_name}.yaml",
    ]

    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    return yaml.safe_load(f)
            except Exception as e:
                print(f"ERROR: Failed to load {config_path}: {e}")
                continue

    return None


def format_agent_yaml_for_injection(
    agent_name: str, agent_config: Dict[str, Any]
) -> str:
    """
    Format agent configuration as YAML for context injection.

    Args:
        agent_name: Agent name
        agent_config: Agent configuration dictionary

    Returns:
        Formatted YAML string for injection into Claude context
    """
    try:
        # Convert config back to YAML with proper formatting
        yaml_str = yaml.dump(agent_config, default_flow_style=False, sort_keys=False)

        # Add injection header
        header = f"""
# ============================================================================
# POLYMORPHIC AGENT IDENTITY INJECTION
# ============================================================================
# Agent: {agent_name}
# Source: UserPromptSubmit hook via event-based routing
# Injection Mode: Direct Single Agent (Lightweight)
#
# IMPORTANT: You are now assuming the identity and capabilities of this agent.
# Transform your behavior, expertise, and response patterns accordingly.
# Use the capabilities, philosophy, and framework integration defined below.
# ============================================================================

"""
        return header + yaml_str

    except Exception as e:
        return f"# ERROR: Failed to format agent config: {e}\n"


def load_and_format_agent(agent_name: str) -> Optional[str]:
    """
    Load agent YAML and format it for context injection.

    Args:
        agent_name: Name of agent to load

    Returns:
        Formatted YAML string ready for injection, or None if agent not found
    """
    config = load_agent_yaml(agent_name)
    if not config:
        return None

    return format_agent_yaml_for_injection(agent_name, config)


if __name__ == "__main__":
    import json
    import sys

    # CLI interface for testing
    if len(sys.argv) > 1:
        agent_name = sys.argv[1]
        yaml_str = load_and_format_agent(agent_name)

        if yaml_str:
            print(yaml_str)
            sys.exit(0)
        else:
            print(f"ERROR: Agent not found: {agent_name}", file=sys.stderr)
            sys.exit(1)
    else:
        # JSON input from stdin (hook interface)
        input_data = sys.stdin.read()
        data = json.loads(input_data)
        agent_name = data.get("agent_name")

        if not agent_name:
            print(json.dumps({"error": "No agent_name provided"}))
            sys.exit(1)

        yaml_str = load_and_format_agent(agent_name)

        if yaml_str:
            print(
                json.dumps(
                    {
                        "success": True,
                        "agent_name": agent_name,
                        "context_injection": yaml_str,
                        "loader": "simple_agent_loader",
                    }
                )
            )
        else:
            print(
                json.dumps(
                    {"success": False, "error": f"Agent not found: {agent_name}"}
                )
            )
            sys.exit(1)
