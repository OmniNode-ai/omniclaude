# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for reject-evidence-ui-claims.sh — OMN-13025 (A-3).

Evidence-language guard: rejects docs/evidence/** files that contain
UI/e2e claims ("UI POST", "click", "full chain live", "end-to-end")
without a Playwright artifact referenced in the same document.

Root cause: PROCESS_FAILURE_RETRO.md §3.A — top-10 failure #1.
The 19:27Z evidence doc claimed "UI POST → full chain live" when only
curl was run.

DoD: commit blocked on overstated evidence prose.
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
    / "reject-evidence-ui-claims.sh"
)
FIXTURES = Path(__file__).parent / "fixtures" / "evidence_language"


def run_hook(fixture_file: Path, fake_path: str) -> tuple[int, str]:
    """Run the hook against a fixture file at a spoofed path.

    The hook path-matches on docs/evidence/**, so we copy the fixture
    content into a temp directory tree that mirrors the expected structure,
    then invoke the hook with that path.
    """
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
def test_rejects_ui_post_without_playwright() -> None:
    """docs/evidence/** with 'UI POST' claim and no Playwright artifact must be rejected."""
    rc, stderr = run_hook(
        FIXTURES / "reject_ui_post_no_playwright.md",
        fake_path="docs/evidence/2026-06-11-omn-99999.md",
    )
    assert rc != 0, "Expected hook to reject UI POST claim without Playwright artifact"
    assert "EVIDENCE_UI_CLAIM_UNVERIFIED" in stderr


@pytest.mark.unit
def test_rejects_click_without_playwright() -> None:
    """docs/evidence/** with 'click' claim and no Playwright artifact must be rejected."""
    rc, stderr = run_hook(
        FIXTURES / "reject_click_no_playwright.md",
        fake_path="docs/evidence/2026-06-11-omn-99998.md",
    )
    assert rc != 0, "Expected hook to reject 'click' claim without Playwright artifact"
    assert "EVIDENCE_UI_CLAIM_UNVERIFIED" in stderr


@pytest.mark.unit
def test_rejects_end_to_end_without_playwright() -> None:
    """docs/evidence/** with 'end-to-end' / 'full chain live' and no Playwright must be rejected."""
    rc, stderr = run_hook(
        FIXTURES / "reject_end_to_end_no_playwright.md",
        fake_path="docs/evidence/2026-06-11-omn-99997.md",
    )
    assert rc != 0, (
        "Expected hook to reject 'end-to-end'/'full chain live' without Playwright artifact"
    )
    assert "EVIDENCE_UI_CLAIM_UNVERIFIED" in stderr


@pytest.mark.unit
def test_accepts_ui_post_with_playwright_reference() -> None:
    """docs/evidence/** with UI claim backed by a Playwright artifact reference must pass."""
    rc, _ = run_hook(
        FIXTURES / "accept_ui_post_with_playwright.md",
        fake_path="docs/evidence/2026-06-11-omn-99996.md",
    )
    assert rc == 0, (
        "Expected hook to accept UI claim when Playwright artifact is referenced"
    )


@pytest.mark.unit
def test_accepts_evidence_doc_with_no_ui_claims() -> None:
    """docs/evidence/** with no UI/e2e claims must pass unconditionally."""
    rc, _ = run_hook(
        FIXTURES / "accept_no_ui_claims.md",
        fake_path="docs/evidence/2026-06-11-omn-99995.md",
    )
    assert rc == 0, "Expected hook to accept evidence doc with no UI claims"


@pytest.mark.unit
def test_ignores_non_evidence_docs() -> None:
    """Non-docs/evidence/** files with UI claims must be silently ignored."""
    rc, _ = run_hook(
        FIXTURES / "accept_non_evidence_ui_claims.md",
        fake_path="docs/architecture/overview.md",
    )
    assert rc == 0, "Expected hook to ignore non-evidence docs regardless of claims"


@pytest.mark.unit
def test_ignores_non_markdown_evidence_files() -> None:
    """Non-.md files in docs/evidence/** must be silently ignored."""
    rc, _ = run_hook(
        FIXTURES / "reject_ui_post_no_playwright.md",
        fake_path="docs/evidence/2026-06-11-omn-99999.yaml",
    )
    assert rc == 0, "Expected hook to ignore non-markdown files"


@pytest.mark.unit
def test_hook_script_exists() -> None:
    """Verify the hook script is present and executable."""
    assert HOOK.exists(), f"Hook script not found: {HOOK}"
    assert os.access(HOOK, os.X_OK), f"Hook script not executable: {HOOK}"
