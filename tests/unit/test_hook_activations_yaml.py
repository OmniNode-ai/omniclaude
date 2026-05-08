# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for hook_activations.yaml contract (OMN-9745)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from omnibase_core.enums.enum_hook_bit import EnumHookBit
from omnibase_core.models.contracts.subcontracts.model_hook_activation import (
    ModelHookActivation,
)

_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "omniclaude"
    / "contracts"
    / "hook_activations.yaml"
)


@pytest.fixture(scope="module")
def raw_contract() -> dict:  # type: ignore[type-arg]
    assert _CONTRACT_PATH.exists(), (
        f"hook_activations.yaml not found at {_CONTRACT_PATH}"
    )
    with _CONTRACT_PATH.open() as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def activations(raw_contract: dict) -> list[ModelHookActivation]:  # type: ignore[type-arg]
    entries = raw_contract.get("hook_activations", [])
    assert isinstance(entries, list), "hook_activations must be a list"
    return [ModelHookActivation(**entry) for entry in entries]


@pytest.mark.unit
def test_contract_file_exists() -> None:
    assert _CONTRACT_PATH.exists()


@pytest.mark.unit
def test_contract_has_required_top_level_keys(raw_contract: dict) -> None:  # type: ignore[type-arg]
    assert "package" in raw_contract
    assert "hook_activations" in raw_contract


@pytest.mark.unit
def test_package_is_omniclaude(raw_contract: dict) -> None:  # type: ignore[type-arg]
    assert raw_contract["package"] == "omniclaude"


@pytest.mark.unit
def test_hook_activations_is_non_empty(activations: list[ModelHookActivation]) -> None:
    assert len(activations) > 0


@pytest.mark.unit
def test_all_hook_bits_are_valid_enum_members(
    activations: list[ModelHookActivation],
) -> None:
    valid_names = {m.name for m in EnumHookBit}
    for activation in activations:
        assert activation.hook_bit.name in valid_names, (
            f"Unknown hook_bit: {activation.hook_bit!r}"
        )


@pytest.mark.unit
def test_no_duplicate_hook_bits(activations: list[ModelHookActivation]) -> None:
    bits = [a.hook_bit for a in activations]
    assert len(bits) == len(set(bits)), "Duplicate hook_bit entries found"


@pytest.mark.unit
def test_all_activations_parse_as_model_hook_activation(
    raw_contract: dict,  # type: ignore[type-arg]
) -> None:
    for entry in raw_contract.get("hook_activations", []):
        # Must not raise
        ModelHookActivation(**entry)


@pytest.mark.unit
def test_enabled_by_default_is_bool(activations: list[ModelHookActivation]) -> None:
    for activation in activations:
        assert isinstance(activation.enabled_by_default, bool)


@pytest.mark.unit
def test_description_is_str(activations: list[ModelHookActivation]) -> None:
    for activation in activations:
        assert isinstance(activation.description, str)
