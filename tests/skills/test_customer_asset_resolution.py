# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Installed assets must resolve locally and refuse escaping marketplace paths."""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_resolver_rejects_incomplete_bundle(tmp_path: Path) -> None:
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.handler_onboarding_assets import (
        HandlerOnboardingAssets,
        ModelOnboardingAssetsRequest,
    )

    with pytest.raises(ValueError, match="customer asset bundle"):
        HandlerOnboardingAssets(root=tmp_path).handle(ModelOnboardingAssetsRequest())


@pytest.mark.parametrize("source", ["../../outside", "/tmp/outside"])
def test_resolver_refuses_marketplace_escape(tmp_path: Path, source: str) -> None:
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.handler_onboarding_assets import (
        HandlerOnboardingAssets,
        ModelOnboardingAssetsRequest,
    )

    manifest = tmp_path / "plugins/.claude-plugin/marketplace.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"plugins": [{"source": source}]}))
    installer = tmp_path / "scripts/install-delegation.sh"
    installer.parent.mkdir()
    installer.write_text("# fixture")
    with pytest.raises(ValueError, match="outside"):
        HandlerOnboardingAssets(root=tmp_path).handle(ModelOnboardingAssetsRequest())


def test_customer_entrypoint_resolves_registered_container_handler(
    tmp_path, monkeypatch
):
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer

    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator import (
        handler_onboarding_assets as assets,
    )

    root = tmp_path / "resources/customer"
    manifest = root / "plugins/.claude-plugin/marketplace.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"plugins": [{"source": "./onex"}]}))
    plugin = root / "plugins/onex/.claude-plugin/plugin.json"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(json.dumps({"name": "onex"}))
    installer = root / "scripts/install-delegation.sh"
    installer.parent.mkdir()
    installer.write_text("# fixture")
    monkeypatch.setattr(assets, "files", lambda _package: tmp_path)
    monkeypatch.setattr(assets, "version", lambda _package: "1.0.0")
    resolved = []
    original = ModelONEXContainer.get_service

    def tracked(self, interface, service_name=None):
        result = original(self, interface, service_name)
        resolved.append(result)
        return result

    monkeypatch.setattr(ModelONEXContainer, "get_service", tracked)
    result = assets.customer_assets()
    assert result["marketplace"] == str(root / "plugins")
    assert len(resolved) == 1
    assert isinstance(resolved[0], assets.HandlerOnboardingAssets)
