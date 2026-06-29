# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for check-defect-anchor.sh — OMN-13029 (retro A-11).

Verifies that evidence documents containing BLOCKER/UNFIXED/defect markers
without an OMN-XXXX ticket reference are rejected, that files with a
corresponding ticket reference pass, that the file-level escape hatch works,
that files with no defect markers pass regardless, and that non-evidence docs
are ignored. Failure class: PROCESS_FAILURE_RETRO.md §3.A (unanchored defects
strand diagnosis without queue presence or close signal).
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

HOOK = (
    Path(__file__).parent.parent.parent / ".pre-commit-hooks" / "check-defect-anchor.sh"
)
FIXTURES = Path(__file__).parent / "fixtures" / "defect_anchor"


def run_hook(fixture_file: Path, fake_path: str) -> tuple[int, str]:
    """Run the hook against a fixture file at a spoofed repo-relative path."""
    tmp_dir = tempfile.mkdtemp()
    try:
        spoof_path = Path(tmp_dir) / fake_path
        spoof_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(fixture_file, spoof_path)
        result = subprocess.run(
            ["bash", str(HOOK), str(spoof_path)],
            capture_output=True,
            check=False,
            text=True,
            env={**os.environ, "GIT_DIR": "/dev/null"},
        )
        return result.returncode, result.stderr
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.unit
def test_rejects_blocker_without_ticket() -> None:
    """A BLOCKER marker in an evidence doc with no OMN-XXXX ref must be rejected."""
    rc, stderr = run_hook(
        FIXTURES / "invalid_blocker_no_ticket.md",
        fake_path="docs/evidence/2026-06-12-integration/notes.md",
    )
    assert rc != 0, "Expected hook to reject BLOCKER with no ticket reference"
    assert "DEFECT_ANCHOR_MISSING" in stderr


@pytest.mark.unit
def test_rejects_unfixed_without_ticket() -> None:
    """An UNFIXED marker in an evidence doc with no OMN-XXXX ref must be rejected."""
    rc, stderr = run_hook(
        FIXTURES / "invalid_unfixed_no_ticket.md",
        fake_path="docs/evidence/2026-06-15-sweep/notes.md",
    )
    assert rc != 0, "Expected hook to reject UNFIXED with no ticket reference"
    assert "DEFECT_ANCHOR_MISSING" in stderr


@pytest.mark.unit
def test_passes_blocker_with_ticket_reference() -> None:
    """A BLOCKER marker paired with an OMN-XXXX reference must pass."""
    rc, stderr = run_hook(
        FIXTURES / "valid_blocker_with_ticket.md",
        fake_path="docs/evidence/2026-06-14-delegation/verify.md",
    )
    assert rc == 0, f"Expected pass (ticket ref present), got stderr: {stderr}"


@pytest.mark.unit
def test_passes_escape_hatch_suppresses_finding() -> None:
    """A file with 'defect-anchor-ok:' anywhere is exempt even with BLOCKER/UNFIXED."""
    rc, stderr = run_hook(
        FIXTURES / "valid_escape_hatch.md",
        fake_path="docs/evidence/2026-06-16-triage/dump.md",
    )
    assert rc == 0, f"Expected escape hatch to pass, got stderr: {stderr}"


@pytest.mark.unit
def test_passes_evidence_doc_with_no_defect_markers() -> None:
    """Evidence docs with no defect markers pass unconditionally."""
    rc, stderr = run_hook(
        FIXTURES / "valid_no_defect_markers.md",
        fake_path="docs/evidence/2026-06-13-bus-integration/notes.md",
    )
    assert rc == 0, f"Expected clean evidence doc to pass, got stderr: {stderr}"


@pytest.mark.unit
def test_ignores_non_evidence_docs() -> None:
    """Docs outside docs/evidence/ are not in scope even with BLOCKER markers."""
    rc, _ = run_hook(
        FIXTURES / "invalid_blocker_no_ticket.md",
        fake_path="docs/handoffs/2026-06-12-handoff.md",
    )
    assert rc == 0, "Expected out-of-scope doc to pass"


@pytest.mark.unit
def test_ignores_architecture_docs() -> None:
    """Architecture docs with BLOCKER prose are not in scope."""
    rc, _ = run_hook(
        FIXTURES / "invalid_blocker_no_ticket.md",
        fake_path="docs/architecture/design-notes.md",
    )
    assert rc == 0, "Expected architecture doc to be out of scope"


@pytest.mark.unit
def test_ignores_non_markdown_files() -> None:
    """Non-markdown files are ignored even if their path matches docs/evidence/."""
    rc, _ = run_hook(
        FIXTURES / "invalid_blocker_no_ticket.md",
        fake_path="docs/evidence/notes.txt",
    )
    assert rc == 0, "Expected .txt file to be ignored"


@pytest.mark.unit
def test_rejects_regression_without_ticket() -> None:
    """A REGRESSION marker in an evidence doc with no OMN-XXXX ref must be rejected."""
    rc, stderr = run_hook(
        FIXTURES / "invalid_regression_no_ticket.md",
        fake_path="docs/evidence/2026-06-20-stability/notes.md",
    )
    assert rc != 0, "Expected hook to reject REGRESSION with no ticket reference"
    assert "DEFECT_ANCHOR_MISSING" in stderr


@pytest.mark.unit
def test_hook_is_executable() -> None:
    """The hook script must carry the executable bit (pre-commit language: script)."""
    assert os.access(HOOK, os.X_OK), f"{HOOK} is not executable"
