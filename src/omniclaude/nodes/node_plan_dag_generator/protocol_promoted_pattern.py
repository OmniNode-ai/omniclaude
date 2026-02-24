# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Protocol for promoted OmniMemory patterns (OMN-2506 integration).

Defines the interface for promoted ticket generation patterns that the
Plan DAG Generator can use to short-circuit full DAG generation.
"""

from __future__ import annotations

from typing import Protocol

from omniclaude.nodes.node_plan_dag_generator.enums.enum_work_unit_type import (
    EnumWorkUnitType,
)

# Type aliases for work unit and dependency specs.
# unit_type uses EnumWorkUnitType to match _build_dag_from_template's signature.
_WorkUnitSpec = tuple[
    str, str, EnumWorkUnitType, str
]  # (local_id, title, unit_type, scope)
_DepSpec = tuple[str, str]  # (from_local_id, to_local_id)


class PromotedPatternProtocol(Protocol):
    """Protocol for promoted OmniMemory patterns (concrete class in OMN-2506).

    Attributes:
        unit_specs: List of work unit specs as (local_id, title, type, scope).
        dep_specs: List of dependency specs as (from_local_id, to_local_id).
    """

    unit_specs: list[_WorkUnitSpec]
    dep_specs: list[_DepSpec]


__all__ = ["PromotedPatternProtocol"]
