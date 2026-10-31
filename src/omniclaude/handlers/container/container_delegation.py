# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds the delegation handlers (OMN-21779)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from omnibase_infra.nodes.node_llm_inference_effect.handlers.bifrost.handler_bifrost_gateway import (
    HandlerBifrostGateway,
)
from omnibase_infra.nodes.node_llm_inference_effect.handlers.handler_llm_openai_compatible import (
    HandlerLlmOpenaiCompatible,
)
from omnimarket.nodes.node_projection_delegation.handlers.handler_projection_delegation import (
    HandlerProjectionDelegation,
)

if TYPE_CHECKING:
    from omnibase_infra.mixins.mixin_llm_http_transport import MixinLlmHttpTransport
    from omnibase_infra.nodes.node_llm_inference_effect.handlers.bifrost.handler_bifrost_response import (
        ModelBifrostResponse,
    )
    from omnibase_infra.nodes.node_llm_inference_effect.handlers.bifrost.model_bifrost_config import (
        ModelBifrostConfig,
    )


def build_projection_delegation() -> HandlerProjectionDelegation:
    """Build the delegation projection handler with its constructor defaults."""
    return HandlerProjectionDelegation()


def build_llm_openai_compatible(
    *, transport: MixinLlmHttpTransport
) -> HandlerLlmOpenaiCompatible:
    """Build the OpenAI-compatible inference handler over the caller's transport."""
    return HandlerLlmOpenaiCompatible(transport=transport)


def build_bifrost_gateway(
    *,
    config: ModelBifrostConfig,
    inference_handler: HandlerLlmOpenaiCompatible,
    on_routing_decision: Callable[[ModelBifrostResponse], None],
) -> HandlerBifrostGateway:
    """Build the Bifrost gateway from the caller's config, handler and routing hook."""
    return HandlerBifrostGateway(
        config=config,
        inference_handler=inference_handler,
        on_routing_decision=on_routing_decision,
    )
