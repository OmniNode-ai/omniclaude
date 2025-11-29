#!/usr/bin/env python3
"""
Simple Agent Loader - Load agent YAML definitions

Loads agent configuration from YAML files and returns context injection
for the polymorphic agent framework.

Usage:
    echo '{"agent_name": "agent-api"}' | python3 simple_agent_loader.py

Output:
    JSON with success status and context injection:
    {
        "success": true,
        "context_injection": "... agent YAML content ...",
        "agent_name": "agent-api"
    }
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)

# Agent definitions directory
AGENT_DEFINITIONS_DIR = Path.home() / ".claude" / "agent-definitions"


def load_agent_yaml(agent_name: str) -> Optional[str]:
    """
    Load agent YAML definition file.

    Args:
        agent_name: Name of the agent to load

    Returns:
        YAML content as string, or None if not found
    """
    # Try multiple locations
    search_paths = [
        AGENT_DEFINITIONS_DIR / f"{agent_name}.yaml",
        AGENT_DEFINITIONS_DIR / f"{agent_name}.yml",
        # Also check for agent without "agent-" prefix (use removeprefix for safety)
        AGENT_DEFINITIONS_DIR / f"{agent_name.removeprefix('agent-')}.yaml",
        AGENT_DEFINITIONS_DIR / f"{agent_name.removeprefix('agent-')}.yml",
    ]

    for path in search_paths:
        if path.exists():
            try:
                return path.read_text()
            except Exception as e:
                logger.warning(f"Failed to read {path}: {e}")

    return None


def load_agent(agent_name: str) -> Dict[str, Any]:
    """
    Load agent configuration and prepare context injection.

    Args:
        agent_name: Name of the agent to load

    Returns:
        Dictionary with success status and context injection
    """
    if not agent_name:
        return {
            "success": False,
            "error": "No agent name provided",
            "agent_name": agent_name,
        }

    # Load YAML content
    yaml_content = load_agent_yaml(agent_name)

    if yaml_content:
        return {
            "success": True,
            "context_injection": yaml_content,
            "agent_name": agent_name,
        }
    else:
        return {
            "success": False,
            "error": f"Agent definition not found: {agent_name}",
            "agent_name": agent_name,
            "searched_paths": [str(AGENT_DEFINITIONS_DIR)],
        }


def main():
    """CLI entry point - reads JSON from stdin."""
    try:
        # Read input JSON from stdin
        input_data = json.loads(sys.stdin.read())
        agent_name = input_data.get("agent_name", "")

        result = load_agent(agent_name)
        print(json.dumps(result))

    except json.JSONDecodeError as e:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"Invalid JSON input: {e}",
                }
            )
        )
    except Exception as e:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"Unexpected error: {e}",
                }
            )
        )


if __name__ == "__main__":
    main()
