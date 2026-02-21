# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Default Plan DAG Generator handler.

Converts a typed Intent object into a Plan DAG.  The mapping from intent
type → work units is template-driven: each intent type has a canonical
set of work units and their dependency order.

Design decisions:
- Pure transformation: Intent → DAG, no I/O or side effects (COMPUTE node)
- OmniMemory cache hit path: if omnimemory_pattern_id is provided, use
  the pattern template directly (short-circuit full generation)
- Cycle detection is enforced by ModelPlanDag.topological_sort()
- Orphaned nodes are flagged on the DAG but not rejected here
"""

from __future__ import annotations

import logging
import uuid

from omniclaude.nodes.node_plan_dag_generator.enums.enum_work_unit_type import (
    EnumWorkUnitType,
)
from omniclaude.nodes.node_plan_dag_generator.models.model_dag_edge import ModelDagEdge
from omniclaude.nodes.node_plan_dag_generator.models.model_plan_dag import ModelPlanDag
from omniclaude.nodes.node_plan_dag_generator.models.model_plan_dag_request import (
    ModelPlanDagRequest,
)
from omniclaude.nodes.node_plan_dag_generator.models.model_work_unit import (
    ModelWorkUnit,
)
from omniclaude.nodes.node_plan_dag_generator.protocol_pattern_cache import (
    PatternCacheProtocol,
)
from omniclaude.nodes.node_plan_dag_generator.protocol_promoted_pattern import (
    PromotedPatternProtocol,
)

__all__ = ["HandlerPlanDagDefault"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent type → work unit template definitions
# ---------------------------------------------------------------------------
# Each entry is a list of (local_id, title, unit_type, estimated_scope).
# Dependencies are expressed as (from_local_id, to_local_id) tuples below.

_WorkUnitSpec = tuple[str, str, EnumWorkUnitType, str]
_DepSpec = tuple[str, str]

# Templates: (work_units, dependencies)
_INTENT_TEMPLATES: dict[str, tuple[list[_WorkUnitSpec], list[_DepSpec]]] = {
    "FEATURE": (
        [
            ("design", "Design feature interface", EnumWorkUnitType.INVESTIGATION, "S"),
            ("impl", "Implement feature", EnumWorkUnitType.FEATURE_IMPLEMENTATION, "M"),
            (
                "tests",
                "Write unit and integration tests",
                EnumWorkUnitType.TEST_SUITE,
                "S",
            ),
            ("docs", "Update documentation", EnumWorkUnitType.DOCUMENTATION, "XS"),
        ],
        [("design", "impl"), ("impl", "tests"), ("tests", "docs")],
    ),
    "BUG_FIX": (
        [
            (
                "investigate",
                "Investigate root cause",
                EnumWorkUnitType.INVESTIGATION,
                "S",
            ),
            ("fix", "Implement fix", EnumWorkUnitType.BUG_FIX, "S"),
            ("tests", "Add regression test", EnumWorkUnitType.TEST_SUITE, "XS"),
        ],
        [("investigate", "fix"), ("fix", "tests")],
    ),
    "REFACTOR": (
        [
            ("scope", "Define refactoring scope", EnumWorkUnitType.INVESTIGATION, "XS"),
            ("refactor", "Implement refactoring", EnumWorkUnitType.REFACTORING, "M"),
            ("tests", "Verify test coverage", EnumWorkUnitType.TEST_SUITE, "S"),
        ],
        [("scope", "refactor"), ("refactor", "tests")],
    ),
    "TESTING": (
        [
            ("audit", "Audit existing coverage", EnumWorkUnitType.INVESTIGATION, "XS"),
            ("tests", "Implement test suite", EnumWorkUnitType.TEST_SUITE, "M"),
        ],
        [("audit", "tests")],
    ),
    "DOCUMENTATION": (
        [
            ("draft", "Draft documentation", EnumWorkUnitType.DOCUMENTATION, "M"),
            ("review", "Review and publish", EnumWorkUnitType.CODE_REVIEW, "XS"),
        ],
        [("draft", "review")],
    ),
    "SECURITY": (
        [
            ("audit", "Security audit", EnumWorkUnitType.INVESTIGATION, "M"),
            ("patch", "Implement security patch", EnumWorkUnitType.SECURITY_PATCH, "M"),
            (
                "tests",
                "Add security regression tests",
                EnumWorkUnitType.TEST_SUITE,
                "S",
            ),
        ],
        [("audit", "patch"), ("patch", "tests")],
    ),
    "REVIEW": (
        [
            ("review", "Code review", EnumWorkUnitType.CODE_REVIEW, "S"),
        ],
        [],
    ),
    "DEBUGGING": (
        [
            ("investigate", "Investigate issue", EnumWorkUnitType.INVESTIGATION, "M"),
            ("fix", "Apply fix if found", EnumWorkUnitType.BUG_FIX, "S"),
        ],
        [("investigate", "fix")],
    ),
    "INFRASTRUCTURE": (
        [
            ("design", "Infrastructure design", EnumWorkUnitType.INVESTIGATION, "S"),
            (
                "impl",
                "Implement infrastructure change",
                EnumWorkUnitType.INFRASTRUCTURE,
                "L",
            ),
            ("tests", "Validate and test", EnumWorkUnitType.TEST_SUITE, "M"),
        ],
        [("design", "impl"), ("impl", "tests")],
    ),
    "EPIC_DECOMPOSITION": (
        [
            ("epic", "Create parent epic ticket", EnumWorkUnitType.EPIC_TICKET, "S"),
            (
                "decompose",
                "Decompose into sub-tickets",
                EnumWorkUnitType.INVESTIGATION,
                "M",
            ),
        ],
        [("epic", "decompose")],
    ),
    "CODE": (
        [
            (
                "impl",
                "Implement code changes",
                EnumWorkUnitType.FEATURE_IMPLEMENTATION,
                "M",
            ),
            ("tests", "Write tests", EnumWorkUnitType.TEST_SUITE, "S"),
        ],
        [("impl", "tests")],
    ),
}

# Default template for unknown / GENERAL / UNKNOWN intent types
_DEFAULT_TEMPLATE: tuple[list[_WorkUnitSpec], list[_DepSpec]] = (
    [("task", "Implement requested change", EnumWorkUnitType.GENERIC, "M")],
    [],
)


class HandlerPlanDagDefault:
    """Default handler for Intent → Plan DAG generation.

    Produces a Plan DAG by mapping the intent type to a canonical work-unit
    template and optionally logging an OmniMemory cache hit.
    """

    @property
    def handler_key(self) -> str:
        """Registry key for handler lookup."""
        return "default"

    def generate_plan_dag(
        self,
        request: ModelPlanDagRequest,
        *,
        pattern_cache: PatternCacheProtocol | None = None,
    ) -> ModelPlanDag:
        """Generate a Plan DAG from a typed Intent request.

        Args:
            request: DAG generation request with intent type and metadata.
            pattern_cache: Optional OmniMemory pattern cache for cache-hit
                short-circuit (OMN-2506 integration).

        Returns:
            Typed ModelPlanDag (frozen, JSON/YAML serializable).
        """
        dag_id = str(uuid.uuid4())

        # 1. OmniMemory cache hit path
        if pattern_cache is not None and request.omnimemory_pattern_id is not None:
            cached = pattern_cache.get_pattern(request.omnimemory_pattern_id)
            if cached is not None:
                logger.info(
                    "OmniMemory pattern cache hit: pattern_id=%s (intent_id=%s)",
                    request.omnimemory_pattern_id,
                    request.intent_id,
                )
                return _instantiate_pattern(
                    dag_id=dag_id,
                    intent_id=request.intent_id,
                    pattern=cached,
                    intent_summary=request.intent_summary,
                )

        if pattern_cache is not None:
            logger.debug(
                "OmniMemory pattern cache miss for intent_type=%s (intent_id=%s)",
                request.intent_type,
                request.intent_id,
            )

        # 2. Full template-based DAG generation
        template = _INTENT_TEMPLATES.get(request.intent_type.upper(), _DEFAULT_TEMPLATE)
        return _build_dag_from_template(
            dag_id=dag_id,
            intent_id=request.intent_id,
            intent_summary=request.intent_summary,
            unit_specs=template[0],
            dep_specs=template[1],
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_dag_from_template(
    *,
    dag_id: str,
    intent_id: str,
    intent_summary: str,
    unit_specs: list[_WorkUnitSpec],
    dep_specs: list[_DepSpec],
) -> ModelPlanDag:
    """Build a ModelPlanDag from template specs.

    Args:
        dag_id: New DAG identifier.
        intent_id: Source intent identifier.
        intent_summary: Human-readable summary for node descriptions.
        unit_specs: List of (local_id, title, type, scope) tuples.
        dep_specs: List of (from_local_id, to_local_id) dependency pairs.

    Returns:
        Validated ModelPlanDag.

    Raises:
        ValueError: If a cycle exists or edge references unknown unit IDs.
    """
    # Map local IDs → stable UUIDs
    local_to_uuid: dict[str, str] = {
        local_id: str(uuid.uuid4()) for local_id, _, _, _ in unit_specs
    }

    nodes = tuple(
        ModelWorkUnit(
            unit_id=local_to_uuid[local_id],
            title=title,
            description=f"{title} — {intent_summary}"[:4000]
            if intent_summary
            else title,
            unit_type=unit_type,
            estimated_scope=scope,
        )
        for local_id, title, unit_type, scope in unit_specs
    )

    edges = tuple(
        ModelDagEdge(
            from_unit_id=local_to_uuid[from_local],
            to_unit_id=local_to_uuid[to_local],
        )
        for from_local, to_local in dep_specs
    )

    dag = ModelPlanDag(
        dag_id=dag_id,
        intent_id=intent_id,
        nodes=nodes,
        edges=edges,
        orphaned_unit_ids=_find_orphaned_nodes(nodes, edges),
    )

    # Eagerly validate: topological sort raises on cycle
    dag.topological_sort()
    return dag


def _find_orphaned_nodes(
    nodes: tuple[ModelWorkUnit, ...],
    edges: tuple[ModelDagEdge, ...],
) -> frozenset[str]:
    """Find nodes that have no path to any root node.

    A node is orphaned if it has incoming edges but those incoming edges
    form a cycle, making it unreachable from any root.  In practice with
    the template builder this is empty, but the validation is required
    per OMN-2502 R2.

    Args:
        nodes: All nodes in the DAG.
        edges: All directed edges.

    Returns:
        Frozenset of unit_ids for orphaned nodes.
    """
    if not edges:
        return frozenset()

    # A node is a root if it has no incoming edges
    has_incoming = {e.to_unit_id for e in edges}
    roots = {n.unit_id for n in nodes if n.unit_id not in has_incoming}

    if not roots:
        # All nodes have incoming edges — all are part of a cycle (orphaned)
        return frozenset(n.unit_id for n in nodes)

    # BFS from roots to find all reachable nodes
    successors: dict[str, list[str]] = {n.unit_id: [] for n in nodes}
    for edge in edges:
        successors[edge.from_unit_id].append(edge.to_unit_id)

    reachable: set[str] = set()
    queue = list(roots)
    while queue:
        current = queue.pop(0)
        if current in reachable:
            continue
        reachable.add(current)
        queue.extend(successors[current])

    all_ids = {n.unit_id for n in nodes}
    return frozenset(all_ids - reachable)


def _instantiate_pattern(
    *,
    dag_id: str,
    intent_id: str,
    pattern: PromotedPatternProtocol,
    intent_summary: str,
) -> ModelPlanDag:
    """Instantiate a Plan DAG from a promoted OmniMemory pattern.

    Args:
        dag_id: New DAG identifier.
        intent_id: Source intent identifier.
        pattern: Promoted pattern from OmniMemory.
        intent_summary: Human-readable intent summary.

    Returns:
        ModelPlanDag built from the pattern's work unit template.
    """
    return _build_dag_from_template(
        dag_id=dag_id,
        intent_id=intent_id,
        intent_summary=intent_summary,
        unit_specs=list(pattern.unit_specs),
        dep_specs=list(pattern.dep_specs),
    )


# PatternCacheProtocol and PromotedPatternProtocol are defined in their own
# files (protocol_pattern_cache.py, protocol_promoted_pattern.py) and
# imported at the top of this module.
