# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for reject-deploy-gate-skip-token.sh — OMN-10414.

Advisory-only hook: verifies that [skip-receipt-gate:] is rejected alongside
[skip-deploy-gate:] unless paired with # skip-token-allowed: <id>.
Receipt-gate (omnibase_core/src/omnibase_core/validation/receipt_gate.py) is
the sole enforcement authority.
"""

import subprocess
from pathlib import Path

import pytest

HOOK = (
    Path(__file__).parent.parent.parent
    / ".pre-commit-hooks"
    / "reject-deploy-gate-skip-token.sh"
)
FIXTURES = Path(__file__).parent / "fixtures" / "skip_token"


def run_hook(fixture_file: Path) -> int:
    result = subprocess.run(
        ["bash", str(HOOK), str(fixture_file)],
        capture_output=True,
        check=False,
        text=True,
    )
    return result.returncode


@pytest.mark.unit
def test_rejects_skip_receipt_gate_free_text() -> None:
    """[skip-receipt-gate: <free-text>] without allowlist receipt must be rejected."""
    rc = run_hook(FIXTURES / "reject_skip_receipt_gate_free_text.md")
    assert rc != 0, "Expected hook to reject free-text skip-receipt-gate token"


@pytest.mark.unit
def test_accepts_skip_receipt_gate_with_allowlist() -> None:
    """[skip-receipt-gate:] paired with # skip-token-allowed: <id> must be accepted."""
    rc = run_hook(FIXTURES / "accept_skip_receipt_gate_with_allowlist.md")
    assert rc == 0, (
        "Expected hook to accept skip-receipt-gate paired with allowlist receipt"
    )


@pytest.mark.unit
def test_rejects_skip_deploy_gate_bare() -> None:
    """[skip-deploy-gate: <free-text>] without allowlist receipt must be rejected (regression)."""
    rc = run_hook(FIXTURES / "reject_skip_deploy_gate_bare.md")
    assert rc != 0, "Expected hook to reject bare skip-deploy-gate token"


@pytest.mark.unit
def test_accepts_clean_pr_body() -> None:
    """A PR body with no skip tokens must pass unconditionally."""
    rc = run_hook(FIXTURES / "accept_clean_pr_body.md")
    assert rc == 0, "Expected hook to accept clean PR body"


@pytest.mark.unit
def test_self_test_passes() -> None:
    """Hook --self-test mode must exit 0 (all built-in cases pass)."""
    result = subprocess.run(
        ["bash", str(HOOK), "--self-test"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, (
        f"Self-test failed:\n{result.stdout}\n{result.stderr}"
    )
