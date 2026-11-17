# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Composition root for the installed customer-assets entry point."""

import sys

from omnibase_core.models.container.model_onex_container import ModelONEXContainer
from omnibase_core.utils.util_run_coro_sync import run_coro_sync

from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.handler_native_delegation import (
    HandlerNativeDelegation,
)
from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.handler_onboarding_assets import (
    HandlerOnboardingAssets,
)
from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.models.model_native_delegation import (
    ModelNativeDelegationRequest,
)


def build_onboarding_assets_container() -> ModelONEXContainer:
    """Register the package-owned resolver before any consumer calls it."""
    container = ModelONEXContainer()
    run_coro_sync(
        container.service_registry.register_instance(
            interface=HandlerNativeDelegation, instance=HandlerNativeDelegation()
        )
    )
    run_coro_sync(
        container.service_registry.register_instance(
            interface=HandlerOnboardingAssets, instance=HandlerOnboardingAssets()
        )
    )
    return container


if __name__ == "__main__":
    request = ModelNativeDelegationRequest.model_validate(
        dict(
            zip(
                ("operation", "install_root", "claude_settings", "python_bin"),
                sys.argv[1:],
                strict=True,
            )
        )
    )
    container = build_onboarding_assets_container()
    try:
        handler = container.get_service(HandlerNativeDelegation)
        result = handler.handle(request)
        if request.operation == "remove":
            sys.stdout.write(str(result.native).lower() + "\n")
    finally:
        container.close()
