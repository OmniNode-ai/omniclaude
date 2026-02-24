# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Plan DAG Generator node — Stage 3 of the NL Intent-Plan-Ticket Compiler.

Converts a typed Intent object into a Plan DAG: a directed acyclic graph
of work units with explicit dependency edges.
"""

from omniclaude.nodes.node_plan_dag_generator.node import NodePlanDagGeneratorCompute

__all__ = ["NodePlanDagGeneratorCompute"]
