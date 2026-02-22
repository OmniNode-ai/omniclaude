# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Typed error raised when the ambiguity gate rejects a work unit."""

from __future__ import annotations

from omniclaude.nodes.node_ambiguity_gate.models.model_gate_check_result import (
    ModelGateCheckResult,
)


class AmbiguityGateError(ValueError):
    """Raised when the ambiguity gate blocks ticket compilation.

    Ticket compilation is aborted for the offending work unit.
    No ticket is emitted; the caller must resolve the flagged
    ambiguities before retrying.

    Attributes:
        result: Full gate check result including all ambiguity flags.
    """

    def __init__(self, result: ModelGateCheckResult) -> None:
        self.result = result
        flag_summary = "; ".join(
            f"{f.ambiguity_type.value}: {f.description}" for f in result.ambiguity_flags
        )
        super().__init__(
            f"Ambiguity gate FAILED for work unit {result.unit_id!r} "
            f"(dag={result.dag_id!r}, intent={result.intent_id!r}): {flag_summary}"
        )


__all__ = ["AmbiguityGateError"]
