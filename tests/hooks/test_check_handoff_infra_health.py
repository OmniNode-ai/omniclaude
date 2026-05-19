# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for check-handoff-infra-health.sh — OMN-11271.

Verifies that handoff documents missing the mandatory ## Infra Health section
are rejected, documents with the section pass, and non-handoff docs are ignored.
"""

import subprocess
from pathlib import Path

import pytest

HOOK = (
    Path(__file__).parent.parent.parent
    / ".pre-commit-hooks"
    / "check-handoff-infra-health.sh"
)
FIXTURES = Path(__file__).parent / "fixtures" / "handoff_infra_health"


def run_hook(fixture_file: Path, fake_path: str | None = None) -> tuple[int, str]:
    """Run the hook against a fixture file, optionally spoofing the filename."""
    if fake_path is not None:
        # Copy content into a temp file at the spoofed path so the hook's
        # path-pattern match fires without requiring git index staging.
        import shutil
        import tempfile

        tmp_dir = tempfile.mkdtemp()
        spoof_path = Path(tmp_dir) / fake_path
        spoof_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(fixture_file, spoof_path)
        result = subprocess.run(
            ["bash", str(HOOK), str(spoof_path)],
            capture_output=True,
            check=False,
            text=True,
            env={**__import__("os").environ, "GIT_DIR": "/dev/null"},
        )
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return result.returncode, result.stderr
    else:
        result = subprocess.run(
            ["bash", str(HOOK), str(fixture_file)],
            capture_output=True,
            check=False,
            text=True,
        )
        return result.returncode, result.stderr


@pytest.mark.unit
def test_rejects_handoff_missing_infra_health_section() -> None:
    """Handoff doc without ## Infra Health must be rejected."""
    rc, stderr = run_hook(
        FIXTURES / "invalid_missing_section.md",
        fake_path="docs/handoffs/2026-05-19-handoff.md",
    )
    assert rc != 0, "Expected hook to reject handoff missing ## Infra Health"
    assert "HANDOFF_MISSING_INFRA_HEALTH" in stderr


@pytest.mark.unit
def test_accepts_handoff_with_infra_health_section() -> None:
    """Handoff doc with ## Infra Health must pass."""
    rc, _ = run_hook(
        FIXTURES / "valid_with_section.md",
        fake_path="docs/handoffs/2026-05-19-handoff.md",
    )
    assert rc == 0, "Expected hook to accept handoff with ## Infra Health section"


@pytest.mark.unit
def test_accepts_tracking_handoff_with_section() -> None:
    """docs/tracking/*handoff*.md with ## Infra Health must pass."""
    rc, _ = run_hook(
        FIXTURES / "valid_with_section.md",
        fake_path="docs/tracking/2026-05-19-handoff.md",
    )
    assert rc == 0, "Expected hook to accept tracking handoff with ## Infra Health"


@pytest.mark.unit
def test_rejects_tracking_handoff_missing_section() -> None:
    """docs/tracking/*handoff*.md without ## Infra Health must be rejected."""
    rc, stderr = run_hook(
        FIXTURES / "invalid_missing_section.md",
        fake_path="docs/tracking/2026-05-19-handoff.md",
    )
    assert rc != 0, "Expected hook to reject tracking handoff missing ## Infra Health"
    assert "HANDOFF_MISSING_INFRA_HEALTH" in stderr


@pytest.mark.unit
def test_ignores_non_handoff_docs() -> None:
    """Non-handoff markdown docs must be silently ignored even without the section."""
    rc, _ = run_hook(
        FIXTURES / "non_handoff_doc.md",
        fake_path="docs/architecture/overview.md",
    )
    assert rc == 0, "Expected hook to ignore non-handoff docs"


@pytest.mark.unit
def test_ignores_non_markdown_files() -> None:
    """Non-.md files must be silently ignored."""
    rc, _ = run_hook(
        FIXTURES / "invalid_missing_section.md",
        fake_path="docs/handoffs/2026-05-19-handoff.yaml",
    )
    assert rc == 0, "Expected hook to ignore non-markdown files"
