# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for SkillNodeIntrospectionProxy.

Validates that the proxy:
1. Discovers the correct number of skill nodes from a contracts directory.
2. Does not raise when publish_all() is called with event_bus=None.

Related:
    - OMN-2403: Skill Node Introspection Proxy
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from omniclaude.runtime.introspection import SkillNodeIntrospectionProxy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill_node_dirs(tmp_path: Path, names: list[str]) -> Path:
    """Create fake node_skill_*/contract.yaml directories under tmp_path/nodes."""
    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    for name in names:
        node_dir = nodes_dir / f"node_skill_{name}_orchestrator"
        node_dir.mkdir()
        contract = node_dir / "contract.yaml"
        contract.write_text(
            f"name: node_skill_{name}_orchestrator\n"
            "node_type: ORCHESTRATOR_GENERIC\n"
            "contract_version:\n"
            "  major: 1\n"
            "  minor: 0\n"
            "  patch: 0\n"
        )
    return nodes_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkillNodeIntrospectionProxyDiscovery:
    """Proxy discovers the correct number of skill nodes from contracts_dir."""

    def test_proxy_creates_one_entry_per_skill_contract(self, tmp_path: Path) -> None:
        """Given N fake contract.yaml dirs, proxy has N descriptors."""
        skill_names = ["local_review", "ci_watch", "auto_merge"]
        nodes_dir = _make_skill_node_dirs(tmp_path, skill_names)

        proxy = SkillNodeIntrospectionProxy(contracts_dir=nodes_dir, event_bus=None)

        assert proxy.node_count == len(skill_names)

    def test_proxy_with_empty_contracts_dir(self, tmp_path: Path) -> None:
        """Proxy has zero entries when no skill node dirs exist."""
        empty_dir = tmp_path / "nodes"
        empty_dir.mkdir()

        proxy = SkillNodeIntrospectionProxy(contracts_dir=empty_dir, event_bus=None)

        assert proxy.node_count == 0

    def test_proxy_with_nonexistent_contracts_dir(self, tmp_path: Path) -> None:
        """Proxy has zero entries when contracts_dir does not exist."""
        missing_dir = tmp_path / "does_not_exist"

        proxy = SkillNodeIntrospectionProxy(contracts_dir=missing_dir, event_bus=None)

        assert proxy.node_count == 0

    def test_proxy_ignores_non_skill_node_dirs(self, tmp_path: Path) -> None:
        """Proxy only counts node_skill_* dirs, ignoring other directories."""
        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()

        # Create a skill node dir
        skill_dir = nodes_dir / "node_skill_local_review_orchestrator"
        skill_dir.mkdir()
        (skill_dir / "contract.yaml").write_text(
            "name: node_skill_local_review_orchestrator\n"
        )

        # Create a non-skill dir (should be ignored)
        other_dir = nodes_dir / "node_routing_emission_effect"
        other_dir.mkdir()
        (other_dir / "contract.yaml").write_text("name: node_routing_emission_effect\n")

        proxy = SkillNodeIntrospectionProxy(contracts_dir=nodes_dir, event_bus=None)

        assert proxy.node_count == 1


@pytest.mark.unit
class TestSkillNodeIntrospectionProxyPublish:
    """Proxy publish_all() behavior."""

    async def test_proxy_publish_introspection_calls_mixin(
        self, tmp_path: Path
    ) -> None:
        """publish_all() does not raise with event_bus=None."""
        nodes_dir = _make_skill_node_dirs(tmp_path, ["local_review", "pr_watch"])

        proxy = SkillNodeIntrospectionProxy(contracts_dir=nodes_dir, event_bus=None)

        # Must not raise even with no event bus
        await proxy.publish_all(reason="startup")

    async def test_proxy_publish_all_no_raise_on_event_bus_error(
        self, tmp_path: Path
    ) -> None:
        """publish_all() does not raise even when event bus publish fails."""
        nodes_dir = _make_skill_node_dirs(tmp_path, ["ticket_pipeline"])

        mock_bus = MagicMock()
        mock_bus.publish_envelope = AsyncMock(
            side_effect=RuntimeError("Kafka unavailable")
        )

        proxy = SkillNodeIntrospectionProxy(contracts_dir=nodes_dir, event_bus=mock_bus)

        # Must not raise — failures are caught and logged
        await proxy.publish_all(reason="startup")
