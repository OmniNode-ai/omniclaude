# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for agent mode filtering."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest
import yaml

AGENTS_DIR = Path(__file__).parents[3] / "plugins" / "onex" / "agents" / "configs"


@pytest.mark.unit
def test_every_agent_has_mode_field() -> None:
    """Every agent config must have a mode field."""
    missing: list[str] = []
    for yaml_file in sorted(AGENTS_DIR.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if data and "mode" not in data:
            missing.append(yaml_file.name)
    assert not missing, f"Agent configs missing 'mode' field: {missing}"


@pytest.mark.unit
def test_mode_values_are_valid() -> None:
    """Mode must be 'full' or 'both'."""
    invalid: list[str] = []
    for yaml_file in sorted(AGENTS_DIR.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if data and data.get("mode") not in ("full", "both"):
            invalid.append(f"{yaml_file.name}: mode={data.get('mode')}")
    assert not invalid, f"Invalid mode values: {invalid}"


@pytest.mark.unit
def test_both_mode_agent_count() -> None:
    """Approximately 12-13 agents should be mode: both."""
    count = 0
    for yaml_file in sorted(AGENTS_DIR.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if data and data.get("mode") == "both":
            count += 1
    assert 10 <= count <= 20, f"Expected ~13 both-mode agents, got {count}"


@pytest.mark.unit
def test_lite_mode_filters_full_only_agents() -> None:
    """In lite mode, _build_registry_from_configs skips full-only agents."""
    # Import here to avoid module-level side effects
    import sys

    # We need to reload the module with OMNICLAUDE_MODE set
    module_path = "plugins.onex.hooks.lib.agent_router"

    # Use the function directly from the file
    sys.path.insert(
        0, str(Path(__file__).parents[3] / "plugins" / "onex" / "hooks" / "lib")
    )
    try:
        with mock.patch.dict(os.environ, {"OMNICLAUDE_MODE": "lite"}):
            # Re-import to pick up env change (function reads env at call time)
            if "agent_router" in sys.modules:
                del sys.modules["agent_router"]
            import agent_router

            registry = agent_router._build_registry_from_configs(AGENTS_DIR)
    finally:
        sys.path.pop(0)
        if "agent_router" in sys.modules:
            del sys.modules["agent_router"]

    agent_names = set(registry["agents"].keys())

    # All agents in lite mode must correspond to mode: both YAMLs
    for yaml_file in sorted(AGENTS_DIR.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if not data:
            continue
        stem = yaml_file.stem
        agent_name = stem if stem.startswith("agent-") else f"agent-{stem}"
        if data.get("mode") == "both":
            assert agent_name in agent_names, (
                f"mode:both agent {agent_name} missing in lite registry"
            )
        else:
            assert agent_name not in agent_names, (
                f"mode:full agent {agent_name} should be excluded in lite mode"
            )


@pytest.mark.unit
def test_full_mode_loads_all_agents() -> None:
    """In full mode (default), all agents are loaded."""
    import sys

    sys.path.insert(
        0, str(Path(__file__).parents[3] / "plugins" / "onex" / "hooks" / "lib")
    )
    try:
        with mock.patch.dict(os.environ, {"OMNICLAUDE_MODE": "full"}):
            if "agent_router" in sys.modules:
                del sys.modules["agent_router"]
            import agent_router

            registry = agent_router._build_registry_from_configs(AGENTS_DIR)
    finally:
        sys.path.pop(0)
        if "agent_router" in sys.modules:
            del sys.modules["agent_router"]

    # Count unique agent names (some files may resolve to the same name
    # e.g. address-pr-comments.yaml and agent-address-pr-comments.yaml
    # both become agent-address-pr-comments)
    import re as _re

    unique_names: set[str] = set()
    for yf in AGENTS_DIR.glob("*.yaml"):
        name = yf.stem
        if not name.startswith("agent-"):
            name = f"agent-{name}"
        if _re.match(r"^[a-zA-Z0-9_-]+$", name):
            unique_names.add(name)

    agent_count = len(registry["agents"])
    assert agent_count == len(unique_names), (
        f"Full mode should load all {len(unique_names)} unique agents, got {agent_count}"
    )
