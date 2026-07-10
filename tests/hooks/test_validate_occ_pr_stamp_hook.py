# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for validate-occ-pr-stamp.sh — OMN-14190.

Thin shim over `onex occ validate` (omnibase_infra.cli.cli_occ). The shim owns
no stamp logic; these tests verify its behavior contract:

* occ-INDEPENDENT (asserted unconditionally, incl. CI before the omnibase-infra
  pin carries `onex occ`):
    - a file with no Evidence line is skipped (exit 0) — arbitrary markdown is
      never required to carry a stamp;
    - an OCC artifact staged while `onex occ` is unavailable HARD-FAILS
      (exit 1) — a missing validator is a config error, not a silent pass.
* occ-DEPENDENT (skipped until `onex occ` resolves): a complete stamp passes and
  an incomplete/malformed stamp fails, delegated to the real CLI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

HOOK = (
    Path(__file__).parent.parent.parent
    / ".pre-commit-hooks"
    / "validate-occ-pr-stamp.sh"
)

_COMPLETE_STAMP = (
    "Summary paragraph.\n\nEvidence-Ticket: OMN-14190\nEvidence-Source: OCC#1408\n"
)
_MISSING_SOURCE = "Summary.\n\nEvidence-Ticket: OMN-14190\n"
_NON_ARTIFACT = "Just a plain readme with no stamp.\n"

# Stripped environment that guarantees `onex occ` cannot resolve, so the
# missing-validator hard-fail path is deterministic regardless of the host.
_NO_ONEX_ENV = {"PATH": "/usr/bin:/bin"}


def _run_hook(
    target: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK), str(target)],
        capture_output=True,
        check=False,
        text=True,
        env=env,
    )


def _occ_available() -> bool:
    """True when `onex occ` resolves the same way the shim resolves it."""
    probe = (
        "command -v onex >/dev/null 2>&1 && onex occ --help >/dev/null 2>&1 "
        "|| uv run --no-sync onex occ --help >/dev/null 2>&1"
    )
    return subprocess.run(["bash", "-c", probe], check=False).returncode == 0


# ---------------------------------------------------------------------------
# occ-independent behaviors — asserted unconditionally
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_non_artifact_file_passes(tmp_path: Path) -> None:
    """A .md file with no Evidence line is not an OCC artifact → exit 0."""
    f = tmp_path / "readme.md"
    f.write_text(_NON_ARTIFACT, encoding="utf-8")
    # Even with no onex available, a non-artifact must not require validation.
    assert _run_hook(f, env=_NO_ONEX_ENV).returncode == 0


@pytest.mark.unit
def test_non_md_file_is_ignored(tmp_path: Path) -> None:
    """Non-.md/.txt files are ignored regardless of content."""
    f = tmp_path / "code.py"
    f.write_text(_COMPLETE_STAMP, encoding="utf-8")
    assert _run_hook(f, env=_NO_ONEX_ENV).returncode == 0


@pytest.mark.unit
def test_artifact_without_validator_hard_fails(tmp_path: Path) -> None:
    """An OCC artifact staged while `onex occ` is unavailable must hard-fail."""
    f = tmp_path / "pr_body.md"
    f.write_text(_COMPLETE_STAMP, encoding="utf-8")
    result = _run_hook(f, env=_NO_ONEX_ENV)
    assert result.returncode == 1
    assert "onex occ" in result.stderr
    assert "OMN-14190" in result.stderr


# ---------------------------------------------------------------------------
# occ-dependent behaviors — require the onex occ CLI (skipped until released)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_complete_stamp_passes(tmp_path: Path) -> None:
    if not _occ_available():
        pytest.skip("onex occ CLI unavailable (bump omnibase-infra pin, OMN-14190)")
    f = tmp_path / "pr_body.md"
    f.write_text(_COMPLETE_STAMP, encoding="utf-8")
    assert _run_hook(f).returncode == 0


@pytest.mark.unit
def test_incomplete_stamp_fails(tmp_path: Path) -> None:
    if not _occ_available():
        pytest.skip("onex occ CLI unavailable (bump omnibase-infra pin, OMN-14190)")
    f = tmp_path / "pr_body.md"
    f.write_text(_MISSING_SOURCE, encoding="utf-8")
    result = _run_hook(f)
    assert result.returncode == 1
    assert "Evidence-Source" in result.stderr


@pytest.mark.unit
def test_self_test_passes() -> None:
    """--self-test exits 0 (all cases pass, or self-skips when occ is absent)."""
    result = subprocess.run(
        ["bash", str(HOOK), "--self-test"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, (
        f"Self-test failed:\n{result.stdout}\n{result.stderr}"
    )
