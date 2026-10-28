# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21465: a downloaded onboarding script fetches the probing handler.

A downloaded copy of lab-onboarding.sh sources the setup handler from the dev
commit its raw URL names, checked against download_digest. Until that commit
carries probe_listed, a downloaded copy (the VM walk) still offers every listed
model, deprecated ones included.
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


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        check=False,
        env=scrub_git_location_env(os.environ),
    )


def test_downloaded_handler_probes_each_model_before_the_menu() -> None:
    text = SCRIPT.read_text()
    commit = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/([0-9a-f]{40})/\$rel",
        text,
    )
    pinned = re.search(r'download_digest="([0-9a-f:]{79})"', text)
    assert commit and pinned
    if _git("cat-file", "-e", f"{commit.group(1)}^{{commit}}").returncode != 0:
        _git("fetch", "--no-tags", "--depth=1", "origin", commit.group(1))
    served = _git("show", f"{commit.group(1)}:{HANDLER_REL}")
    assert served.returncode == 0, served.stderr.decode(errors="replace")
    assert hashlib.sha256(served.stdout).hexdigest() == pinned.group(1).replace(":", "")
    assert b"probe_listed() {" in served.stdout
