# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests asserting hook contract file existence and shape (OMN-8930).

The hook contract YAMLs are the durable spec for the dispatch-claim,
idle-notification and verifier-role-guard hooks. They are asserted here
independently of hooks.json registration: under the OMN-13244 measurement
baseline hooks.json carries an empty ``hooks`` object, so the per-hook
"registered in hooks.json" assertions do not apply. Re-add those assertions
when the hooks are re-registered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_CONTRACTS_DIR = (
    Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "contracts"
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
