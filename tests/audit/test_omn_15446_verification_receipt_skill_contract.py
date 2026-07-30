# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-15446: verification-receipt skill and backing-node input must align."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "plugins/onex/skills/verification_receipt_generator/SKILL.md"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def test_skill_requires_exact_owner_repo_identity_for_ci() -> None:
    text = _skill_text()

    assert "exact `OWNER/REPO`" in text
    assert "--repo OmniNode-ai/omniclaude" in text
    assert "--repo omniclaude" not in text


def test_dispatch_examples_encode_ci_and_test_only_inputs_without_placeholders() -> (
    None
):
    text = _skill_text()

    assert '"repo":"OmniNode-ai/omniclaude"' in text
    assert '"pr_number":567' in text
    assert '"verify_ci":true' in text
    assert '"repo":null' in text
    assert '"pr_number":null' in text
    assert '"verify_ci":false' in text
    assert '"verify_tests":true' in text
    assert '"repo":"<repo>"' not in text


def test_skill_names_the_actual_typed_output_contract() -> None:
    text = _skill_text()

    assert "`ModelVerificationReceipt`:" in text
    assert "ModelVerificationReceiptResponse" not in text
