# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Verify the omniclaude runtime service contract exists and declares OMNICLAUDE_CONTRACTS_ROOT.

Uses string-contains checks deliberately (no yaml import) to avoid relying on
a transitive PyYAML dependency. Schema validity gated by seed-infisical dry-run below.
"""

from pathlib import Path

import pytest

_RUNTIME_CONTRACT = Path("src/omniclaude/contracts/contract_omniclaude_runtime.yaml")


@pytest.mark.unit
def test_runtime_contract_exists() -> None:
    assert _RUNTIME_CONTRACT.exists(), "Runtime service contract must exist"


@pytest.mark.unit
def test_runtime_contract_declares_contracts_root() -> None:
    content = _RUNTIME_CONTRACT.read_text()
    assert "OMNICLAUDE_CONTRACTS_ROOT" in content, (
        "Runtime contract must mention OMNICLAUDE_CONTRACTS_ROOT"
    )
    assert "environment" in content, (
        "Runtime contract must declare an environment dependency type"
    )
