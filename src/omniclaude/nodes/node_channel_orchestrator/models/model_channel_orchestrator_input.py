# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Input model for channel orchestrator node."""

from __future__ import annotations

from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope


class ModelChannelOrchestratorInput(ModelChannelEnvelope):
    """Input to the channel orchestrator.

    Extends ModelChannelEnvelope directly -- the orchestrator consumes
    the normalized channel message as-is.
    """
