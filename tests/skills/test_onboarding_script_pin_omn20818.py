# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20818 AC12: the onboarding guide pins the multi-model script.

``plugins/onex/ONBOARDING.md`` downloads ``lab-onboarding.sh`` from a pinned commit
and checks its sha256. The pin must name the commit that introduced the multi-model
script (omniclaude#2637) or a later one, and its sha256 must be that of the script at
the pinned commit. A pin older than #2637 hands the developer the single-model script.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

REPO = Path(__file__).resolve().parents[2]
GUIDE = REPO / "plugins" / "onex" / "ONBOARDING.md"
SCRIPT_PATH = "plugins/onex/skills/_bin/lab-onboarding.sh"

# The merge commit of omniclaude#2637, the first commit that carries the multi-model script.
MULTI_MODEL_SCRIPT_COMMIT = "c15d2e31bb6bf77ea8546d06404b3a5789c6e9c6"

PIN_URL = re.compile(
    r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/"
    r"(?P<commit>[0-9a-f]{40})/" + re.escape(SCRIPT_PATH)
)
PIN_SHA256 = re.compile(r"echo \"([0-9a-f]{64})  lab-onboarding\.sh\"")

pytestmark = pytest.mark.unit


def _pinned_commit() -> str:
    urls = PIN_URL.findall(GUIDE.read_text(encoding="utf-8"))
    assert len(urls) == 1, (
        f"expected one pinned script URL in {GUIDE.name}, found {urls}"
    )
    return urls[0]


def _pinned_digest() -> str:
    digests = PIN_SHA256.findall(GUIDE.read_text(encoding="utf-8"))
    assert len(digests) == 1, (
        f"expected one pinned sha256 in {GUIDE.name}, found {digests}"
    )
    return digests[0]


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        check=False,
        env=scrub_git_location_env(os.environ),
    )


def _has_commit(commit: str) -> bool:
    return _git("cat-file", "-e", f"{commit}^{{commit}}").returncode == 0


def _require_commit(commit: str) -> None:
    # CI checks out at depth 1, so the pinned commit is usually absent. Fetch
    # it by sha rather than skip: a test that skips on every pull request run
    # never executes, and the skip-count ratchet refuses it (OMN-18776).
    if not _has_commit(commit):
        _git("fetch", "--no-tags", "--depth=1", "origin", commit)
    if not _has_commit(commit):
        pytest.skip(f"{commit} is not in this checkout's history")


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    if _git("merge-base", "--is-ancestor", ancestor, descendant).returncode == 0:
        return True
    shallow = _git("rev-parse", "--is-shallow-repository").stdout.strip()
    if shallow != b"true":
        return False
    # A depth-1 fetch cuts the history between two distinct commits, so an
    # ancestry answer from a shallow checkout is not an answer. Unshallow once.
    _git("fetch", "--no-tags", "--unshallow", "origin")
    return _git("merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def test_guide_pins_the_script_at_a_full_commit_and_digest() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", _pinned_commit())
    assert re.fullmatch(r"[0-9a-f]{64}", _pinned_digest())


def test_pin_is_not_older_than_the_multi_model_script() -> None:
    pinned = _pinned_commit()
    _require_commit(pinned)
    _require_commit(MULTI_MODEL_SCRIPT_COMMIT)
    assert _is_ancestor(MULTI_MODEL_SCRIPT_COMMIT, pinned), (
        f"ONBOARDING.md pins {pinned}, which does not contain "
        f"{MULTI_MODEL_SCRIPT_COMMIT} (omniclaude#2637, the multi-model script)"
    )


def test_pinned_digest_is_the_script_at_the_pinned_commit() -> None:
    pinned = _pinned_commit()
    _require_commit(pinned)
    shown = _git("show", f"{pinned}:{SCRIPT_PATH}")
    assert shown.returncode == 0, shown.stderr.decode(errors="replace")
    assert hashlib.sha256(shown.stdout).hexdigest() == _pinned_digest()


# OMN-21075 AC5: the pinned script sets up OpenRouter on the fixed model, so a
# developer following the guide is never asked to choose one.
FIXED_OPENROUTER_MODEL_LINE = 'OPENROUTER_MODEL="qwen/qwen3.8-27b"'


def test_pinned_script_sets_up_openrouter_on_the_fixed_model() -> None:
    pinned = _pinned_commit()
    _require_commit(pinned)
    shown = _git("show", f"{pinned}:{SCRIPT_PATH}")
    assert shown.returncode == 0, shown.stderr.decode(errors="replace")
    assert FIXED_OPENROUTER_MODEL_LINE in shown.stdout.decode().splitlines(), (
        f"ONBOARDING.md pins {pinned}, whose script does not carry "
        f"{FIXED_OPENROUTER_MODEL_LINE}"
    )
