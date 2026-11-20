# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Composition root for the installed customer-assets entry point."""

from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omnibase_core.utils.util_run_coro_sync import run_coro_sync

from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.handler_onboarding_assets import (
    HandlerOnboardingAssets,
)


def build_onboarding_assets_container() -> ModelONEXContainer:
    """Register the package-owned resolver before any consumer calls it."""
    container = ModelONEXContainer()
    run_coro_sync(
        container.service_registry.register_instance(
            interface=HandlerOnboardingAssets, instance=HandlerOnboardingAssets()
        )
    )
    return container
