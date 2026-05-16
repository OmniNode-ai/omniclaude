# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Hook activation contract tests for OMN-11083."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from omnibase_core.enums.enum_hook_bit import (
    _DEFAULT_MASK,
    _DISABLED_BY_DEFAULT,
    EnumHookBit,
)
from omnibase_core.models.contracts.subcontracts.model_hook_activation import (
    ModelHookActivation,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO / "src/omniclaude/contracts/hook_activations.yaml"
HOOK_BITS_PATH = REPO / "plugins/onex/hooks/lib/hook_bits.sh"
HOOK_GATE_PATH = REPO / "plugins/onex/hooks/scripts/hook-gate.sh"
_OPT_IN_GATES = frozenset({"AISLOP_GATE", "STOP_QUALITY_GATE", "INLINE_REVIEW_GATE"})


@pytest.fixture(scope="module")
def activations() -> list[ModelHookActivation]:
    raw = yaml.safe_load(CONTRACT_PATH.read_text())
    entries = raw.get("hook_activations", [])
    assert isinstance(entries, list)
    return [ModelHookActivation.model_validate(entry) for entry in entries]


def test_hook_activations_contract_covers_every_enum_member(
    activations: list[ModelHookActivation],
) -> None:
    contract_names = {activation.hook_bit.name for activation in activations}
    enum_names = {member.name for member in EnumHookBit}
    assert contract_names == enum_names
    assert len(activations) == 63


def test_omn_11083_gates_are_opt_in(
    activations: list[ModelHookActivation],
) -> None:
    by_name = {activation.hook_bit.name: activation for activation in activations}
    assert _DISABLED_BY_DEFAULT == _OPT_IN_GATES
    for name in _OPT_IN_GATES:
        assert by_name[name].enabled_by_default is False


def test_existing_bits_remain_enabled_by_default(
    activations: list[ModelHookActivation],
) -> None:
    for activation in activations:
        if activation.hook_bit.name not in _OPT_IN_GATES:
            assert activation.enabled_by_default is True


def test_generated_hook_bits_default_mask_matches_core_default() -> None:
    content = HOOK_BITS_PATH.read_text()
    match = re.search(r"^HOOK_BITS_DEFAULT_MASK=(0x[0-9a-f]+)$", content, re.M)
    assert match is not None
    assert int(match.group(1), 16) == _DEFAULT_MASK


def test_generated_hook_bits_knows_opt_in_gate_names() -> None:
    content = HOOK_BITS_PATH.read_text()
    for name in _OPT_IN_GATES:
        assert f"{name}) echo 0x{int(EnumHookBit[name]):x} ;;" in content


def test_default_gate_mask_skips_opt_in_gate() -> None:
    script = (
        f'source "{HOOK_GATE_PATH}" && '
        "if onex_hook_gate AISLOP_GATE; then exit 42; else exit 0; fi"
    )
    env = os.environ.copy()
    env.pop("ONEX_HOOKS_MASK", None)
    result = subprocess.run(["bash", "-c", script], check=False, env=env)
    assert result.returncode == 0


def test_default_gate_mask_allows_existing_gate() -> None:
    script = (
        f'source "{HOOK_GATE_PATH}" && '
        "if onex_hook_gate WORKTREE_GUARD; then exit 0; else exit 42; fi"
    )
    env = os.environ.copy()
    env.pop("ONEX_HOOKS_MASK", None)
    result = subprocess.run(["bash", "-c", script], check=False, env=env)
    assert result.returncode == 0
