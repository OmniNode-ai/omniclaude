# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for check-utc-timestamp-discipline.sh — OMN-13023 (retro B-11).

Verifies that handoff/evidence documents citing Z-suffixed clock times adjacent
to file-mtime markers are rejected, that date-u-sourced timestamps pass, that
the ``utc-ok:`` escape hatch works, and that non-handoff/evidence docs are
ignored. Failure class: PROCESS_FAILURE_RETRO.md §5.1 (local-EDT mtimes
relabeled as UTC manufactured a false outage narrative on 2026-06-11).
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

HOOK = (
    Path(__file__).parent.parent.parent
    / ".pre-commit-hooks"
    / "check-utc-timestamp-discipline.sh"
)
FIXTURES = Path(__file__).parent / "fixtures" / "utc_timestamp_discipline"


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
def test_rejects_z_suffix_adjacent_to_mtime_in_handoff() -> None:
    """A Z-suffixed time on the same line as an mtime marker must be rejected."""
    rc, stderr = run_hook(
        FIXTURES / "invalid_mtime_z_suffix.md",
        fake_path="docs/handoffs/2026-06-11-evening-handoff.md",
    )
    assert rc != 0, "Expected hook to reject Z-suffixed time next to mtime citation"
    assert "UTC_MTIME_MISLABEL" in stderr


@pytest.mark.unit
def test_rejects_same_content_in_evidence_dir() -> None:
    """The same violation under docs/evidence/ must also be rejected."""
    rc, stderr = run_hook(
        FIXTURES / "invalid_mtime_z_suffix.md",
        fake_path="docs/evidence/2026-06-11-incident/timeline.md",
    )
    assert rc != 0
    assert "UTC_MTIME_MISLABEL" in stderr


@pytest.mark.unit
def test_passes_date_u_sourced_timestamps() -> None:
    """Z-suffixed times sourced from date -u with no same-line mtime marker pass."""
    rc, stderr = run_hook(
        FIXTURES / "valid_date_u_sourced.md",
        fake_path="docs/handoffs/2026-06-11-evening-handoff.md",
    )
    assert rc == 0, f"Expected pass, got stderr: {stderr}"


@pytest.mark.unit
def test_escape_hatch_utc_ok_suppresses_finding() -> None:
    """A line carrying 'utc-ok: <reason>' is exempt."""
    rc, stderr = run_hook(
        FIXTURES / "valid_escape_hatch.md",
        fake_path="docs/handoffs/2026-06-11-evening-handoff.md",
    )
    assert rc == 0, f"Expected escape hatch to pass, got stderr: {stderr}"


@pytest.mark.unit
def test_ignores_non_handoff_non_evidence_docs() -> None:
    """Docs outside docs/handoffs/ and docs/evidence/ are not in scope."""
    rc, stderr = run_hook(
        FIXTURES / "invalid_mtime_z_suffix.md",
        fake_path="docs/architecture/some-design.md",
    )
    assert rc == 0, f"Expected out-of-scope doc to pass, got stderr: {stderr}"


@pytest.mark.unit
def test_ignores_non_markdown_files() -> None:
    """Non-markdown files are ignored even under docs/handoffs/."""
    rc, _ = run_hook(
        FIXTURES / "invalid_mtime_z_suffix.md",
        fake_path="docs/handoffs/notes.txt",
    )
    assert rc == 0


@pytest.mark.unit
def test_hook_is_executable() -> None:
    """The hook script must carry the executable bit (pre-commit language: script)."""
    assert os.access(HOOK, os.X_OK), f"{HOOK} is not executable"
