# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19915: the handler a downloaded onboarding script fetches defines every function the script calls.

A clean-VM walk downloaded lab-onboarding.sh and failed in phase 3 with
``lab-onboarding.sh: line 344: place_local_url_on_ladder: command not found``
(and ``line 1430: retire_lab_model_overrides: command not found``): the script
sourced the handler at a dev commit older than the functions the script calls.
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
HANDLER_REL = (
    "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator/"
    "handler_onboarding_preflight.sh"
)
# The functions the walk's phase 3 failed to find in the downloaded handler.
WALK_MISSING_FUNCTIONS = ("place_local_url_on_ladder", "retire_lab_model_overrides")


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        check=False,
        env=scrub_git_location_env(os.environ),
    )


def _served_handler() -> tuple[bytes, str]:
    text = SCRIPT.read_text()
    commit = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/([0-9a-f]{40})/\$rel",
        text,
    )
    download = re.search(r'download_digest="([0-9a-f:]{79})"', text)
    assert commit and download
    if _git("cat-file", "-e", f"{commit.group(1)}^{{commit}}").returncode != 0:
        _git("fetch", "--no-tags", "--depth=1", "origin", commit.group(1))
    served = _git("show", f"{commit.group(1)}:{HANDLER_REL}")
    assert served.returncode == 0, served.stderr.decode(errors="replace")
    return served.stdout, download.group(1).replace(":", "")


def test_downloaded_handler_defines_functions_the_walk_could_not_find() -> None:
    body, download_digest = _served_handler()
    assert hashlib.sha256(body).hexdigest() == download_digest
    for name in WALK_MISSING_FUNCTIONS:
        assert re.search(rf"^{name}\(\) \{{", body.decode(), re.MULTILINE), name
