# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Capability names a local backend declares in the routing contract."""

from __future__ import annotations

from enum import StrEnum


class EnumContractCapability(StrEnum):
    """Capability names a local backend declares in the routing contract."""

    CODE_GENERATION = "code_generation"
    REASONING = "reasoning"
    CLASSIFICATION = "classification"
    DOCUMENTATION = "documentation"
    EMBEDDING = "embedding"
