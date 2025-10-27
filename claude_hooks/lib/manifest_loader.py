#!/usr/bin/env python3
"""
Manifest Loader - Load dynamic system manifest via event bus for hook injection

Used by user-prompt-submit hook to inject manifest into agent context.

Key Changes (v2.0):
- Now uses event bus pattern (Kafka) instead of static YAML
- Queries archon-intelligence-adapter for dynamic system state
- Falls back to minimal manifest if queries timeout or fail
- Maintains same API for backward compatibility

Architecture:
    manifest_loader.py → manifest_injector.py → IntelligenceEventClient
      → Kafka event bus → archon-intelligence-adapter
      → Qdrant/Memgraph/PostgreSQL queries → formatted manifest
"""

import os
import sys
from pathlib import Path
from uuid import uuid4


def load_manifest(correlation_id: str = None, agent_name: str = None):
    """
    Load and return dynamic system manifest.

    Queries archon-intelligence-adapter via event bus for current system state.
    Falls back to minimal manifest if queries fail or timeout.

    Args:
        correlation_id: Optional correlation ID for tracking (auto-generated if not provided)
        agent_name: Optional agent name for logging/traceability

    Returns:
        Formatted manifest string ready for agent prompt injection
    """
    # Generate correlation ID if not provided
    if correlation_id is None:
        correlation_id = str(uuid4())

    # Add agents/lib to path - try multiple locations
    project_path = os.environ.get("PROJECT_PATH", "")
    search_paths = []

    # Add project path if available (prioritize project directory)
    if project_path:
        search_paths.append(Path(project_path) / "agents" / "lib")

    # Add home directory
    search_paths.append(Path.home() / ".claude" / "agents" / "lib")

    # Add current working directory as fallback
    search_paths.append(Path.cwd() / "agents" / "lib")

    # Add all existing paths to sys.path
    for lib_path in search_paths:
        if lib_path.exists():
            sys.path.insert(0, str(lib_path))

    try:
        from manifest_injector import inject_manifest

        # Call inject_manifest with correlation_id and agent_name (new v2.0 API)
        # This will query event bus for dynamic data or fall back to minimal manifest
        manifest = inject_manifest(correlation_id=correlation_id, agent_name=agent_name)
        return manifest

    except ImportError as e:
        # manifest_injector not found - installation issue
        return (
            f"System Manifest: Not available (import error: {str(e)})\n"
            "Install manifest_injector.py to ~/.claude/agents/lib/"
        )

    except Exception as e:
        # Any other error - non-blocking
        # Note: manifest_injector has its own fallback to minimal manifest,
        # so this should be rare (only for catastrophic failures)
        return (
            f"System Manifest: Not available (error: {str(e)})\n"
            "Using built-in intelligence instead of dynamic manifest."
        )


if __name__ == "__main__":
    # Test with explicit correlation ID and agent_name from environment
    test_correlation_id = str(uuid4())
    agent_name = os.environ.get("AGENT_NAME")
    print(
        f"Testing manifest load (correlation_id: {test_correlation_id}, agent_name: {agent_name})"
    )
    print("=" * 70)
    print(load_manifest(test_correlation_id, agent_name))
