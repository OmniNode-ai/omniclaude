# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Golden chain payload compute — builds synthetic test payloads for chain validation."""

from .chain_registry import (
    GOLDEN_CHAIN_DEFINITIONS,
    GOLDEN_CHAIN_METADATA,
    get_chain_definitions,
    get_chain_metadata,
)
from .models.model_chain_definition import (
    ModelChainAssertion,
    ModelChainDefinition,
    ModelChainMetadata,
)
from .models.model_enriched_payload import ModelEnrichedPayload
from .node import build_payloads

__all__ = [
    "GOLDEN_CHAIN_DEFINITIONS",
    "GOLDEN_CHAIN_METADATA",
    "ModelChainAssertion",
    "ModelChainDefinition",
    "ModelChainMetadata",
    "ModelEnrichedPayload",
    "build_payloads",
    "get_chain_definitions",
    "get_chain_metadata",
]
