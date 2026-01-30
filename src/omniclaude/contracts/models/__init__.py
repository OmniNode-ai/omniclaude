# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Contract models for OmniClaude handlers.

This module provides Pydantic models for validating handler contract YAML files.
The models enforce strict schema validation to catch errors early and provide
type-safe enums for configuration options.

Example:
    >>> import yaml
    >>> from omniclaude.contracts.models import ModelHandlerContract
    >>> with open("contract.yaml") as f:
    ...     data = yaml.safe_load(f)
    >>> contract = ModelHandlerContract(**data)
"""

from __future__ import annotations

from omniclaude.contracts.models.model_handler_contract import (
    BackoffStrategy,
    ConcurrencyPolicy,
    HandlerKind,
    HandlerPurity,
    IsolationPolicy,
    ModelCircuitBreaker,
    ModelContractMetadata,
    ModelContractVersion,
    ModelHandlerContract,
    ModelHandlerDescriptor,
    ModelRetryPolicy,
    ObservabilityLevel,
)

__all__ = [
    # Enums
    "BackoffStrategy",
    "ConcurrencyPolicy",
    "HandlerKind",
    "HandlerPurity",
    "IsolationPolicy",
    "ObservabilityLevel",
    # Models
    "ModelCircuitBreaker",
    "ModelContractMetadata",
    "ModelContractVersion",
    "ModelHandlerContract",
    "ModelHandlerDescriptor",
    "ModelRetryPolicy",
]
