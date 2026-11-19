# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Resolve packaged customer assets without a source checkout."""

from __future__ import annotations

import json
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.models.model_onboarding_assets import (
    ModelOnboardingAssetsRequest,
    ModelOnboardingAssetsResult,
)


class HandlerOnboardingAssets:
    """Validate the bundle before giving local paths to a vendor installer."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root

    def handle(
        self, request: ModelOnboardingAssetsRequest
    ) -> ModelOnboardingAssetsResult:
        root = self._root or Path(
            str(files("omniclaude").joinpath("resources/customer"))
        )
        root = root.resolve()
        marketplace = root / "plugins"
        manifest = marketplace / ".claude-plugin/marketplace.json"
        installer = root / "scripts/install-delegation.sh"
        if not manifest.is_file() or not installer.is_file():
            raise ValueError(
                "The customer asset bundle is missing; install an omninode-claude wheel containing customer assets."
            )
        for path in (manifest, installer):
            if not path.resolve().is_relative_to(root):
                raise ValueError("Customer asset resolves outside the installed bundle")
        data = json.loads(manifest.read_text())
        plugins = data.get("plugins") if isinstance(data, dict) else None
        if not isinstance(plugins, list) or not plugins:
            raise ValueError("Invalid customer marketplace plugin manifest")
        for plugin in plugins:
            source = plugin.get("source") if isinstance(plugin, dict) else None
            if not isinstance(source, str):
                raise ValueError("Customer marketplace requires local plugin sources")
            target = (marketplace / source / ".claude-plugin/plugin.json").resolve()
            if not target.is_relative_to(marketplace.resolve()):
                raise ValueError(
                    "Customer plugin source resolves outside the installed bundle"
                )
            if not target.is_file():
                raise ValueError("The customer asset bundle has an incomplete plugin")
            json.loads(target.read_text())
        return ModelOnboardingAssetsResult(
            marketplace=str(marketplace),
            installer=str(installer),
            package_version=version("omninode-claude"),
        )


def customer_assets() -> dict[str, str]:
    """Entry-point bridge; resolution remains owned by the bound handler."""
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.container_onboarding_assets import (
        build_onboarding_assets_container,
    )

    container = build_onboarding_assets_container()
    try:
        handler = container.get_service(HandlerOnboardingAssets)
        return handler.handle(ModelOnboardingAssetsRequest()).model_dump()
    finally:
        container.close()
