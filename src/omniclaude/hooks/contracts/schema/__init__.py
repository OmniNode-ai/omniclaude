# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Shared JSON Schema models for hook contracts.

This module provides canonical schema models for representing JSON Schema-like
definitions within hook contracts. All hook contract files should import from
this module rather than defining their own schema models.

Design Principles:
    1. Single source of truth - one model set for all contracts
    2. Permissive by default - extra="ignore" for forward compatibility
    3. Strict enforcement at boundary - use assert_no_extra_fields() where needed
    4. Contract-schema dialect - model only the keywords we actually use

Strictness Policy:
    Models use extra="ignore" so unknown JSON Schema keywords are silently
    dropped. This provides forward compatibility when JSON Schema evolves.

    For contracts that require strict validation (no unknown fields allowed),
    call assert_no_extra_fields() after parsing:

        >>> definition = ModelJsonSchemaDefinition.model_validate(data)
        >>> assert_no_extra_fields(definition)  # Raises if extra fields present

Ticket: OMN-1812 - Consolidate hook contract schema models
"""

from omniclaude.hooks.contracts.schema.model_json_schema import (
    ModelJsonSchemaDefinition,
    ModelJsonSchemaProperty,
    assert_no_extra_fields,
)

__all__ = [
    "ModelJsonSchemaProperty",
    "ModelJsonSchemaDefinition",
    "assert_no_extra_fields",
]
