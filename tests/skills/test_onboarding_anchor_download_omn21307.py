# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21307: a downloaded onboarding script gets the anchor functions.

``lab-onboarding.sh`` downloaded on its own runs the handler at the commit its raw
GitHub URL names, so that commit's handler must define the functions the anchored
phase 2 calls, with the bytes ``download_digest`` checks.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import scrub_git_location_env

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "plugins/onex/skills/_bin/lab-onboarding.sh"
HANDLER = (
    REPO
    / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator/handler_onboarding_preflight.sh"
)

ANCHOR_FUNCTIONS = (
    "proven_pin",
    "anchor_time",
    "anchored_commit",
    "checkout_anchored",
    "clone_at_anchor",
)


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        check=False,
        env=scrub_git_location_env(os.environ),
    )


def _download_commit() -> str:
    match = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/([0-9a-f]{40})/\$rel",
        SCRIPT.read_text(),
    )
    assert match
    commit = match.group(1)
    if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        _git("fetch", "--no-tags", "--depth=1", "origin", commit)
    return commit


def _handler_bytes(commit: str) -> bytes:
    rel = HANDLER.relative_to(REPO).as_posix()
    result = _git("show", f"{commit}:{rel}")
    assert result.returncode == 0, (
        f"git show {commit}:{rel} failed: {result.stderr.decode('utf-8', errors='replace')}"
    )
    return result.stdout


def _download_digest() -> str:
    match = re.search(r'download_digest\s*=\s*"([0-9a-fA-F:]+)"', SCRIPT.read_text())
    assert match, "download_digest was not found in lab-onboarding.sh"
    return match.group(1)


def test_a_downloaded_script_fetches_a_handler_that_defines_the_anchor_functions() -> (
    None
):
    commit = _download_commit()
    handler = _handler_bytes(commit)
    text = handler.decode("utf-8", errors="replace")

    missing = [
        name
        for name in ANCHOR_FUNCTIONS
        if not re.search(rf"^{name}\(\) \{{", text, re.MULTILINE)
    ]

    assert not missing, (
        f"commit {commit} handler is missing anchor functions: {', '.join(missing)}"
    )


def test_the_downloaded_handler_has_the_bytes_download_digest_checks() -> None:
    commit = _download_commit()
    handler = _handler_bytes(commit)

    expected = _download_digest().replace(":", "").lower()
    actual = hashlib.sha256(handler).hexdigest()

    assert actual == expected, (
        f"handler sha256 {actual} does not match download_digest {expected} for commit {commit}"
    )
