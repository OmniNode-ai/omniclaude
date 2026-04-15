# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests asserting hooks.json registration and contract file existence (OMN-8930)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_HOOKS_JSON = (
    Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "hooks.json"
)
_CONTRACTS_DIR = (
    Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "contracts"
)


def _load_hooks() -> dict:  # type: ignore[type-arg]
    return json.loads(_HOOKS_JSON.read_text())


@pytest.mark.unit
def test_dispatch_claim_pretool_registered_in_pretooluse() -> None:
    data = _load_hooks()
    pretool_entries = data["hooks"].get("PreToolUse", [])
    scripts = [
        e["hooks"][0]["command"]
        for e in pretool_entries
        if e.get("hooks") and e["hooks"][0].get("command")
    ]
    assert any("hook_dispatch_claim_pretool" in s for s in scripts), (
        "hook_dispatch_claim_pretool.sh not found in PreToolUse hooks"
    )


@pytest.mark.unit
def test_dispatch_claim_posttool_registered_in_posttooluse() -> None:
    data = _load_hooks()
    posttool_entries = data["hooks"].get("PostToolUse", [])
    scripts = [
        e["hooks"][0]["command"]
        for e in posttool_entries
        if e.get("hooks") and e["hooks"][0].get("command")
    ]
    assert any("hook_dispatch_claim_posttool" in s for s in scripts), (
        "hook_dispatch_claim_posttool.sh not found in PostToolUse hooks"
    )


@pytest.mark.unit
def test_idle_notification_ratelimit_registered_in_pretooluse() -> None:
    data = _load_hooks()
    pretool_entries = data["hooks"].get("PreToolUse", [])
    scripts = [
        e["hooks"][0]["command"]
        for e in pretool_entries
        if e.get("hooks") and e["hooks"][0].get("command")
    ]
    assert any("hook_idle_notification_ratelimit" in s for s in scripts), (
        "hook_idle_notification_ratelimit.sh not found in PreToolUse hooks"
    )


@pytest.mark.unit
def test_verifier_role_guard_registered_in_pretooluse() -> None:
    data = _load_hooks()
    pretool_entries = data["hooks"].get("PreToolUse", [])
    scripts = [
        e["hooks"][0]["command"]
        for e in pretool_entries
        if e.get("hooks") and e["hooks"][0].get("command")
    ]
    assert any("hook_verifier_role_guard" in s for s in scripts), (
        "hook_verifier_role_guard.sh not found in PreToolUse hooks"
    )


@pytest.mark.unit
def test_all_four_contract_yaml_files_exist() -> None:
    expected = [
        "hook_dispatch_claim_pretool.yaml",
        "hook_dispatch_claim_posttool.yaml",
        "hook_idle_notification_ratelimit.yaml",
        "hook_verifier_role_guard.yaml",
    ]
    missing = [f for f in expected if not (_CONTRACTS_DIR / f).exists()]
    assert not missing, f"Missing contract YAMLs: {missing}"


@pytest.mark.unit
def test_contract_yamls_have_golden_path_and_dod_evidence() -> None:
    import yaml  # type: ignore[import-untyped]

    for fname in _CONTRACTS_DIR.glob("hook_*.yaml"):
        data = yaml.safe_load(fname.read_text())
        assert "golden_path" in data, f"{fname.name} missing golden_path"
        assert "dod_evidence" in data, f"{fname.name} missing dod_evidence"
        assert isinstance(data["dod_evidence"], list), (
            f"{fname.name} dod_evidence must be a list"
        )
        assert len(data["dod_evidence"]) >= 1, (
            f"{fname.name} dod_evidence must have at least 1 entry"
        )
