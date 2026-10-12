# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Event model for onex.evt.omniclaw.channel-reply-requested.v1."""

from __future__ import annotations

from omniclaude.nodes.node_channel_orchestrator.models.model_channel_orchestrator_output import (
    ModelChannelOrchestratorOutput,
)


class ModelChannelReplyRequested(ModelChannelOrchestratorOutput):
    """A reply the orchestrator wants dispatched to the originating channel.

    The contract's ``published_events`` entry ``ChannelReplyRequested`` is
    matched to this class by its name minus the ``Model`` prefix, which is how
    the runtime picks the topic for an emitted model. The fields are the
    orchestrator output's, which are field-for-field the request model of the
    reply dispatcher that subscribes to the topic.
    """
