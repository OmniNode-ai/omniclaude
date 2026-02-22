# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""NL Intent Pipeline node — Stage 1→2 of the NL Intent-Plan-Ticket Compiler.

Parses raw natural language input and emits a typed, structured Intent object
with classification metadata and confidence score.
"""

from omniclaude.nodes.node_nl_intent_pipeline.node import NodeNlIntentPipelineCompute

__all__ = ["NodeNlIntentPipelineCompute"]
