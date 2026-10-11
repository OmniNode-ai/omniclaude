# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for reject-deploy-gate-skip-token.sh — OMN-10414.

Verifies that [skip-receipt-gate:] is rejected alongside [skip-deploy-gate:],
and that no receipt-id comment rescues either (OMN-20074: the approvals
registry is retired and there is no escape hatch).
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
def test_rejects_skip_receipt_gate_even_with_a_receipt_comment() -> None:
    """A skip token is rejected whatever receipt-id comment accompanies it."""
    rc = run_hook(FIXTURES / "reject_skip_receipt_gate_with_receipt_comment.md")
    assert rc == 1, "Expected hook to reject a skip token with a receipt-id comment"


@pytest.mark.unit
def test_rejects_every_case_variant_of_the_receipt_comment(tmp_path: Path) -> None:
    for comment in (
        "# skip-token-allowed: R-1",
        "#   SKIP-TOKEN-ALLOWED: R-2",
        "# Skip-Token-Allowed: R-3",
    ):
        body = tmp_path / "body.md"
        body.write_text(f"[skip-deploy-gate: x]\n{comment}\n", encoding="utf-8")
        assert run_hook(body) == 1, comment


@pytest.mark.unit
def test_commit_message_with_receipt_comment_is_rejected(tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "fix: x [skip-receipt-gate: y]\n\n# skip-token-allowed: R-9\n",
        encoding="utf-8",
    )
    assert run_hook(msg) == 1


@pytest.mark.unit
def test_rejects_skip_deploy_gate_bare() -> None:
    """[skip-deploy-gate: <free-text>] without allowlist receipt must be rejected (regression)."""
    rc = run_hook(FIXTURES / "reject_skip_deploy_gate_bare.md")
    assert rc != 0, "Expected hook to reject bare skip-deploy-gate token"


@pytest.mark.unit
def test_rejects_session_evidence_json_skip_token(tmp_path: Path) -> None:
    """OMN-12696: committed .onex_state/evidence JSON is in scanner scope."""
    evidence = tmp_path / ".onex_state" / "evidence" / "session.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        '{"claim": "[skip-receipt-gate: no receipt]"}',
        encoding="utf-8",
    )

    rc = run_hook(evidence)
    assert rc != 0, "Expected hook to reject skip token in session evidence JSON"


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
