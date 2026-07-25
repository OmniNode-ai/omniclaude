# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression: the deprecated delegation orchestrator must not own a contract."""

from __future__ import annotations

from pathlib import Path


def test_deprecated_delegation_orchestrator_contract_absent() -> None:
    contract_path = (
        Path(__file__).parents[3]
        / "src/omniclaude/nodes/node_delegation_orchestrator/contract.yaml"
    )

    assert not contract_path.exists(), (
        "omniclaude must not ship a node_delegation_orchestrator contract. "
        "OMN-14584 removed that duplicate node contract because omnimarket "
        "owns the delegation orchestrator route and infra delegation topics."
    )
