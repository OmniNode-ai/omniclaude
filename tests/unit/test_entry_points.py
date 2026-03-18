# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OmniNode Team
"""Tests for onex.node_package entry point declaration."""
import importlib.metadata

import pytest


@pytest.mark.unit
def test_node_package_entry_point_declared() -> None:
    """onex.node_package entry point must be declared and importable."""
    eps = importlib.metadata.entry_points(group="onex.node_package")
    names = [ep.name for ep in eps]
    assert "omniclaude" in names, f"Expected 'omniclaude' in {names}"


@pytest.mark.unit
def test_node_package_entry_point_loads() -> None:
    """Entry point value must be an importable package."""
    eps = importlib.metadata.entry_points(group="onex.node_package")
    ep = next(ep for ep in eps if ep.name == "omniclaude")
    pkg = ep.load()
    assert hasattr(pkg, "__path__"), "Entry point must resolve to a package"
