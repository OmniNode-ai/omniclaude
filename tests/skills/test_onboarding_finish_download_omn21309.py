# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21309: a downloaded onboarding script fetches a handler with the finish step.

A downloaded copy of lab-onboarding.sh sources the setup handler from the dev
commit its raw URL names, checked against download_digest. Until that commit
carries finish_sound, a downloaded copy (the VM walk) never runs the finish step.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "plugins/onex/skills/_bin/lab-onboarding.sh"
HANDLER_REL = (
    "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator/"
    "handler_onboarding_preflight.sh"
)


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, check=False
    )


def test_downloaded_handler_carries_the_finish_step() -> None:
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
    assert b"finish_sound() {" in served.stdout
