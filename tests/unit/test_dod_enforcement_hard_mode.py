# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for DoD enforcement hard mode graduation (OMN-6117).

Verifies that dod-pre-push-check.sh exits non-zero in hard mode when
DoD evidence is missing, and exits zero when evidence exists and passes.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

SCRIPT_PATH = str(
    Path(__file__).resolve().parents[2] / "scripts" / "dod-pre-push-check.sh"
)


def _run_check(
    *,
    enforcement: str,
    branch: str,
    evidence_dir: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run dod-pre-push-check.sh with controlled environment."""
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(Path.home()),
        "DOD_ENFORCEMENT": enforcement,
        "GITHUB_HEAD_REF": branch,
    }
    if evidence_dir:
        env["ONEX_STATE_DIR"] = evidence_dir
    else:
        env["ONEX_STATE_DIR"] = "/tmp/nonexistent-onex-state"

    return subprocess.run(
        ["bash", SCRIPT_PATH],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
        # Use /tmp as cwd to avoid git rev-parse finding a real branch
        cwd="/tmp",
    )


@pytest.mark.unit
class TestDodEnforcementHardMode:
    """OMN-6117: Verify hard mode blocks on missing DoD evidence."""

    def test_hard_mode_fails_on_missing_evidence(self) -> None:
        """Hard mode exits 1 when no evidence receipt exists."""
        result = _run_check(
            enforcement="hard",
            branch="jonah/omn-9999-test-branch",
        )
        assert result.returncode == 1, (
            f"Expected exit 1 in hard mode with missing evidence, "
            f"got {result.returncode}. stderr={result.stderr}"
        )

    def test_advisory_mode_passes_on_missing_evidence(self) -> None:
        """Advisory mode exits 0 even when evidence is missing."""
        result = _run_check(
            enforcement="advisory",
            branch="jonah/omn-9999-test-branch",
        )
        assert result.returncode == 0

    def test_hard_mode_passes_with_valid_evidence(self) -> None:
        """Hard mode exits 0 when evidence exists and passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / "evidence" / "OMN-9999"
            evidence_dir.mkdir(parents=True)
            receipt = evidence_dir / "dod_report.json"
            receipt.write_text(json.dumps({"result": {"failed": 0, "passed": 3}}))

            result = _run_check(
                enforcement="hard",
                branch="jonah/omn-9999-test-branch",
                evidence_dir=tmpdir,
            )
            assert result.returncode == 0, (
                f"Expected exit 0 with valid evidence, got {result.returncode}. "
                f"stderr={result.stderr}"
            )

    def test_hard_mode_fails_with_failed_evidence(self) -> None:
        """Hard mode exits 1 when evidence has failed checks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / "evidence" / "OMN-9999"
            evidence_dir.mkdir(parents=True)
            receipt = evidence_dir / "dod_report.json"
            receipt.write_text(json.dumps({"result": {"failed": 2, "passed": 1}}))

            result = _run_check(
                enforcement="hard",
                branch="jonah/omn-9999-test-branch",
                evidence_dir=tmpdir,
            )
            assert result.returncode == 1, (
                f"Expected exit 1 with failed evidence, got {result.returncode}. "
                f"stderr={result.stderr}"
            )

    def test_no_ticket_in_branch_always_passes(self) -> None:
        """Branches without ticket IDs always pass regardless of mode."""
        result = _run_check(
            enforcement="hard",
            branch="main",
        )
        assert result.returncode == 0
