# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Plan DAG model — the directed acyclic graph of work units.

The Plan DAG is the system-of-record output of Stage 3.  It is consumed by:
- OMN-2504 (Ambiguity Gate): evaluates each node for unresolved ambiguity
- OMN-2503 (Ticket Compiler): compiles each node into an executable ticket
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field, model_validator

from omniclaude.nodes.node_plan_dag_generator.models.model_dag_edge import ModelDagEdge
from omniclaude.nodes.node_plan_dag_generator.models.model_work_unit import (
    ModelWorkUnit,
)


class ModelPlanDag(BaseModel):
    """Directed acyclic graph of work units produced from a typed Intent object.

    Attributes:
        dag_id: Stable identifier for this plan DAG.
        intent_id: ID of the Intent object that produced this DAG.
        nodes: All work unit nodes in the DAG.
        edges: All directed dependency edges (from_unit_id → to_unit_id).
        orphaned_unit_ids: IDs of nodes with no path to any root node.
            These are flagged (not rejected) — the Ambiguity Gate decides.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    dag_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Stable identifier for this plan DAG",
    )
    intent_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the Intent object that produced this DAG",
    )
    nodes: tuple[ModelWorkUnit, ...] = Field(
        default=(),
        description="All work unit nodes in the DAG",
    )
    edges: tuple[ModelDagEdge, ...] = Field(
        default=(),
        description="All directed dependency edges",
    )
    orphaned_unit_ids: frozenset[str] = Field(
        default=frozenset(),
        description="IDs of nodes with no path to any root node",
    )

    @model_validator(mode="after")
    def _validate_edge_references(self) -> ModelPlanDag:
        """All edge endpoints must reference nodes that exist in this DAG."""
        unit_id_list = [n.unit_id for n in self.nodes]
        duplicates = {uid for uid, count in Counter(unit_id_list).items() if count > 1}
        if duplicates:
            raise ValueError(
                f"Duplicate unit_id(s) in Plan DAG nodes: {sorted(duplicates)}"
            )
        unit_ids = set(unit_id_list)
        for edge in self.edges:
            if edge.from_unit_id not in unit_ids:
                raise ValueError(
                    f"Edge references unknown from_unit_id={edge.from_unit_id!r}"
                )
            if edge.to_unit_id not in unit_ids:
                raise ValueError(
                    f"Edge references unknown to_unit_id={edge.to_unit_id!r}"
                )
        return self

    def topological_sort(self) -> list[ModelWorkUnit]:
        """Return nodes in topological order (prerequisites first).

        Uses Kahn's algorithm.  Raises ValueError if the DAG contains a
        cycle (should not happen if constructed via the generator, but this
        is the hard enforcement point).

        Returns:
            Nodes ordered so that each node appears after all its
            prerequisites.

        Raises:
            ValueError: If a cycle is detected.
        """
        # Build adjacency: in-degree and successor list
        in_degree: dict[str, int] = {n.unit_id: 0 for n in self.nodes}
        successors: dict[str, list[str]] = {n.unit_id: [] for n in self.nodes}

        for edge in self.edges:
            in_degree[edge.to_unit_id] += 1
            successors[edge.from_unit_id].append(edge.to_unit_id)

        queue: list[str] = [uid for uid, deg in in_degree.items() if deg == 0]
        result_ids: list[str] = []

        while queue:
            current = queue.pop(0)
            result_ids.append(current)
            for successor in successors[current]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)

        if len(result_ids) != len(self.nodes):
            cycle_nodes = {uid for uid, deg in in_degree.items() if deg > 0}
            raise ValueError(
                f"Cycle detected in Plan DAG — cannot topologically sort. "
                f"Nodes in cycle: {sorted(cycle_nodes)}"
            )

        unit_map = {n.unit_id: n for n in self.nodes}
        return [unit_map[uid] for uid in result_ids]

    def roots(self) -> tuple[ModelWorkUnit, ...]:
        """Return nodes with no incoming edges (no prerequisites).

        Returns:
            Tuple of root work units (may be empty for empty DAG).
        """
        to_ids = {e.to_unit_id for e in self.edges}
        return tuple(n for n in self.nodes if n.unit_id not in to_ids)

    def leaves(self) -> tuple[ModelWorkUnit, ...]:
        """Return nodes with no outgoing edges (no dependents).

        Returns:
            Tuple of leaf work units (may be empty for empty DAG).
        """
        from_ids = {e.from_unit_id for e in self.edges}
        return tuple(n for n in self.nodes if n.unit_id not in from_ids)


__all__ = ["ModelPlanDag"]
