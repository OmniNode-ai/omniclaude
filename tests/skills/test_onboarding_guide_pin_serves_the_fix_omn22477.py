# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22477: the script the participant guide tells a participant to download
is one that can set up Ollama.

``plugins/onex/ONBOARDING.md`` is the only instruction a participant follows: it
downloads ``lab-onboarding.sh`` from one pinned commit and checks its sha256. A
self-consistent pair of pin and checksum proves nothing about what the bytes do,
so the guide sat on 2026-10-24's script for two weeks while dev carried the
model-config and Ollama-fault fixes. These tests read the bytes the pinned commit
actually serves and assert the fixes are in them, so the pin cannot be left
behind or moved back.
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


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        check=False,
        env=scrub_git_location_env(os.environ),
    )


def _guide_pin() -> tuple[str, str]:
    text = GUIDE.read_text(encoding="utf-8")
    commit = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/"
        r"([0-9a-f]{40})/plugins/onex/skills/_bin/lab-onboarding\.sh",
        text,
    )
    digest = re.search(r'echo "([0-9a-f]{64})  lab-onboarding\.sh"', text)
    assert commit, "the guide's download command names no 40-hex commit"
    assert digest, "the guide's checksum line names no sha256"
    return commit.group(1), digest.group(1)


def _served() -> bytes:
    commit, _ = _guide_pin()
    if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        _git("fetch", "--no-tags", "--depth=1", "origin", commit)
    served = _git("show", f"{commit}:{SCRIPT_REL}")
    assert served.returncode == 0, served.stderr.decode(errors="replace")
    return served.stdout


def test_the_guides_checksum_is_the_bytes_its_pin_serves() -> None:
    """The pair is self-consistent, so a participant's shasum check passes.

    This is the weak half of the pin and is asserted first because its failure
    stops a participant at the download rather than inside a phase: a checksum
    that does not match the pinned commit makes ``shasum -c`` exit nonzero and
    no run starts at all.
    """
    _, digest = _guide_pin()
    assert hashlib.sha256(_served()).hexdigest() == digest, (
        "the guide's sha256 is not the script its pinned commit serves"
    )


def test_the_served_script_reports_which_ollama_fault_it_hit() -> None:
    """The pinned script carries OLLAMA_CONFIG_ERR.

    Fails at the merge base, whose pin is ad5d6ef8: that script has one fixed
    sentence blaming the omnimarket model config, so a failed model-config call
    sends the reader to a file that needs no change (OMN-22477 AC4).
    """
    assert b"OLLAMA_CONFIG_ERR" in _served(), (
        "the script the guide serves still names the omnimarket config for "
        "every Ollama fault, including a model-config call that failed"
    )


def test_the_served_script_fetches_the_fixed_model_config_handler() -> None:
    """The pinned script's own handler pin is one whose model_config takes
    PYTHONPATH from the workspace clone.

    A downloaded run writes the handler three levels below a path that holds no
    omniclaude package, so a handler deriving PYTHONPATH from ${BASH_SOURCE[0]}
    dies with ModuleNotFoundError and no local model can be set up. Fails at the
    merge base, whose script pins 6596b867 (OMN-22477 AC2, AC5).
    """
    inner = re.search(
        rb"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/([0-9a-f]{40})/\$rel",
        _served(),
    )
    assert inner, "the served script names no handler commit"
    commit = inner.group(1).decode()
    rel = (
        "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator/"
        "handler_onboarding_preflight.sh"
    )
    if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        _git("fetch", "--no-tags", "--depth=1", "origin", commit)
    handler = _git("show", f"{commit}:{rel}")
    assert handler.returncode == 0, handler.stderr.decode(errors="replace")
    assert b'PYTHONPATH="$WORKSPACE/omniclaude/src"' in handler.stdout, (
        "the handler the guide's script would download still derives PYTHONPATH "
        "from its own location"
    )
