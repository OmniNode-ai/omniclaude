# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for ModelDelegationOutcome CLI fields — OMN-10135 Task 7."""

from __future__ import annotations


def test_delegation_outcome_accepts_cli_fields() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.enums.enum_cli_recipient import (
        EnumCliRecipient,
    )
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_result import (
        ModelDelegationOutcome,
    )

    o = ModelDelegationOutcome(
        delegation_success=True,
        quality_gate_result="passed",
        cli_recipient=EnumCliRecipient.CLAUDE,
        cli_stdout="done",
        cli_exit_code=0,
        cli_runtime_seconds=1.5,
    )
    assert o.cli_recipient == EnumCliRecipient.CLAUDE
    assert o.cli_stdout == "done"


def test_delegation_outcome_cli_fields_default_preserves_existing_callers() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_result import (
        ModelDelegationOutcome,
    )

    o = ModelDelegationOutcome(delegation_success=True, quality_gate_result="passed")
    assert o.cli_stdout == ""
    assert o.cli_exit_code is None
    assert o.cli_files_modified == []
    assert o.cli_recipient is None
