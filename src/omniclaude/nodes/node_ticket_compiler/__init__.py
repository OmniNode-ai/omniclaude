# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Ticket Compiler node — Stage 4 of the NL Intent-Plan-Ticket Compiler.

Compiles each Plan DAG work unit into an executable Linear ticket with:
- IDL (Interface Definition Language spec): input schema, output schema, side effects
- Test contract: verifiable acceptance criteria
- Policy envelope: validators, permission scope, sandbox constraints
"""

from omniclaude.nodes.node_ticket_compiler.node import NodeTicketCompilerCompute

__all__ = ["NodeTicketCompilerCompute"]
