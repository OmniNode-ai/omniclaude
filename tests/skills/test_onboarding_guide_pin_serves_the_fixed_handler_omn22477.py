# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22477: the commit the PARTICIPANT PAGE pins serves the fixed handler.

There are two pins in this chain and they move in separate pull requests.
``plugins/onex/ONBOARDING.md`` pins the commit a participant downloads
``lab-onboarding.sh`` from; that script in turn pins the commit it curls the
onboarding handler from. #3194 moved the second one to the commit the
``model_config`` PYTHONPATH fix merged as, and nothing a participant downloads
reached it, because the page still named ``ad5d6ef8`` -- whose script curls the
handler from ``6596b867``, the one that derives PYTHONPATH from its own
location. So the fix had merged and every participant following the emailed
command still could not set up Ollama.

``test_onboarding_guide_pin_omn21261`` cannot catch that. It asserts the page's
own commit and checksum against two constants that move in the same commit as
the page, so it passes whatever the page points at. These tests walk the chain
instead, out of git rather than out of the page's own claims: page -> the script
served at that commit -> the handler that script serves -> that handler's
PYTHONPATH. Agreement between the page's two digests is not enough, because
agreement holds for any self-consistent pin, including one whose handler still
has the fault.
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
GUIDE = REPO / "plugins" / "onex" / "ONBOARDING.md"
SCRIPT_REL = "plugins/onex/skills/_bin/lab-onboarding.sh"
HANDLER_REL = (
    "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator/"
    "handler_onboarding_preflight.sh"
)

# The commit the model_config PYTHONPATH fix merged as. A page pinned at a commit
# whose script serves anything else is the defect this file exists to catch.
HANDLER_FIX = "149fbe854d8f40e54ae90e8aa776ffe3506a3a4b"


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        check=False,
        env=scrub_git_location_env(os.environ),
    )


def _blob(commit: str, rel: str) -> bytes:
    """The bytes of ``rel`` at ``commit``, fetching the commit if it is absent."""
    if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        _git("fetch", "--no-tags", "--depth=1", "origin", commit)
    shown = _git("show", f"{commit}:{rel}")
    assert shown.returncode == 0, shown.stderr.decode(errors="replace")
    return shown.stdout


def _page_pin() -> tuple[str, str]:
    """The commit and sha256 the participant page tells a participant to fetch."""
    guide = GUIDE.read_text(encoding="utf-8")
    url = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/"
        r"([0-9a-f]{40})/" + re.escape(SCRIPT_REL),
        guide,
    )
    checksum = re.search(r'echo "([0-9a-f]{64})  lab-onboarding\.sh"', guide)
    assert url, "the page names no pinned download URL for lab-onboarding.sh"
    assert checksum, "the page names no sha256 for lab-onboarding.sh"
    return url.group(1), checksum.group(1)


def test_the_page_checksum_is_the_bytes_at_the_commit_the_page_pins() -> None:
    """The page's own two claims agree with each other AND with git.

    This is the weaker half, and it is here as the control: it holds for any
    self-consistent pin, which is exactly why the test below is needed.
    """
    commit, claimed = _page_pin()
    assert hashlib.sha256(_blob(commit, SCRIPT_REL)).hexdigest() == claimed, (
        f"the page claims sha256 {claimed} for {SCRIPT_REL} at {commit}, "
        "but that is not what the commit holds"
    )


def test_the_script_the_page_pins_serves_the_fixed_handler() -> None:
    commit, _ = _page_pin()
    script = _blob(commit, SCRIPT_REL).decode(errors="replace")
    served = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/"
        r"([0-9a-f]{40})/\$rel",
        script,
    )
    assert served, (
        f"the script at the page's pin {commit} names no handler download URL"
    )
    assert served.group(1) == HANDLER_FIX, (
        f"the page pins {commit}, whose script curls the onboarding handler from "
        f"{served.group(1)} rather than {HANDLER_FIX}. A participant downloading "
        "the page's command gets that handler, whatever the page's own digests say."
    )


def test_the_handler_a_downloaded_run_gets_reads_pythonpath_from_the_workspace() -> (
    None
):
    """The end of the chain, which is the behaviour the ticket is about.

    Naming the commit is not the claim; what that commit's handler does is. At
    ``6596b867`` ``model_config`` derives PYTHONPATH from ``${BASH_SOURCE[0]}``,
    which a downloaded run writes into the run directory, so ``import
    omniclaude`` dies inside the dispatch venv before phase 3 can set up a
    local model.
    """
    commit, _ = _page_pin()
    script = _blob(commit, SCRIPT_REL).decode(errors="replace")
    served = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/"
        r"([0-9a-f]{40})/\$rel",
        script,
    )
    assert served
    handler = _blob(served.group(1), HANDLER_REL).decode(errors="replace")
    model_config = re.search(
        r"^model_config\(\)\s*\{(.*?)^\}", handler, re.DOTALL | re.MULTILINE
    )
    assert model_config, "the served handler defines no model_config"
    body = model_config.group(1)
    assert 'PYTHONPATH="$WORKSPACE/omniclaude/src' in body, (
        "the handler a downloaded run gets does not take PYTHONPATH from the "
        f"workspace clone; model_config at {served.group(1)} reads: {body.strip()[:400]}"
    )
    assert "BASH_SOURCE" not in body, (
        "model_config still derives PYTHONPATH from the handler's own location, "
        "which is where a downloaded run cannot import omniclaude"
    )
