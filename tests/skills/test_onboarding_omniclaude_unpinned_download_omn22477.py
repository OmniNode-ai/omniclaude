# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22477: a downloaded onboarding script fetches the handler that takes
omniclaude off the proven set.

A downloaded copy of lab-onboarding.sh sources the setup handler from the dev
commit its raw URL names, checked against download_digest. Until that commit
carries the omniclaude exclusion, a downloaded copy (the VM walk and every
participant run) still checks omniclaude out at its CI pin from 2026-10-06,
which predates the model-config handler phase 3 imports, so Ollama and the
local model server cannot be set up on any machine.
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


def test_downloaded_handler_takes_omniclaude_off_the_proven_set() -> None:
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
    assert b'if [ "$1" != omniclaude ]; then' in served.stdout


def test_each_digest_matches_the_handler_it_checks() -> None:
    """Both digests are the bytes they check, and a divergence is a real one.

    `digest` is the handler beside the entrypoint; `download_digest` is the
    handler at the commit the raw URL names. A pull request that changes the
    handler cannot name a dev commit holding its new bytes (the merge queue
    squashes, so no branch commit reaches dev), so the two differ for that one
    change and the next pull request moves the URL to the merge commit. The
    invariant that holds on every commit is this one: each digest is the
    sha256 of the handler it checks, so they agree exactly when the handler
    beside the entrypoint and the handler dev serves are the same bytes. An
    asserted equality instead refused the mid-flight state the entrypoint's
    own comment requires (OMN-22477).
    """
    text = SCRIPT.read_text()
    local = re.search(r'\bdigest="([0-9a-f:]{79})"', text)
    download = re.search(r'download_digest="([0-9a-f:]{79})"', text)
    assert local and download
    here = hashlib.sha256((REPO / HANDLER_REL).read_bytes()).hexdigest()
    assert local.group(1).replace(":", "") == here, (
        "digest is not the handler beside the entrypoint"
    )
    commit = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/([0-9a-f]{40})/\$rel",
        text,
    )
    assert commit
    if _git("cat-file", "-e", f"{commit.group(1)}^{{commit}}").returncode != 0:
        _git("fetch", "--no-tags", "--depth=1", "origin", commit.group(1))
    served = _git("show", f"{commit.group(1)}:{HANDLER_REL}")
    assert served.returncode == 0, served.stderr.decode(errors="replace")
    there = hashlib.sha256(served.stdout).hexdigest()
    assert download.group(1).replace(":", "") == there, (
        "download_digest is not the handler the raw URL serves"
    )
    # A divergence is only ever the handler genuinely moving ahead of dev.
    assert (local.group(1) == download.group(1)) == (here == there)


def test_the_downloaded_handler_carries_the_workspace_pythonpath_fix() -> None:
    """The commit the raw URL names serves a handler whose model_config reads
    PYTHONPATH from the workspace clone.

    A downloaded run writes the handler into the run directory, three levels
    below a path that holds no omniclaude package, so a handler that derives
    PYTHONPATH from ${BASH_SOURCE[0]} dies with ModuleNotFoundError and no
    model server or Ollama can be set up. Checking the digests agree is not
    enough: they agree whenever the pin is self-consistent, including at a
    commit whose handler still has the fault. This asserts the served bytes
    carry the fix, so the pin cannot be moved back to one that does not.
    """
    text = SCRIPT.read_text()
    commit = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/([0-9a-f]{40})/\$rel",
        text,
    )
    assert commit
    if _git("cat-file", "-e", f"{commit.group(1)}^{{commit}}").returncode != 0:
        _git("fetch", "--no-tags", "--depth=1", "origin", commit.group(1))
    served = _git("show", f"{commit.group(1)}:{HANDLER_REL}")
    assert served.returncode == 0, served.stderr.decode(errors="replace")
    assert b'PYTHONPATH="$WORKSPACE/omniclaude/src"' in served.stdout, (
        "the handler the raw URL serves still derives PYTHONPATH from its own "
        "location, so a downloaded run cannot import omniclaude"
    )
