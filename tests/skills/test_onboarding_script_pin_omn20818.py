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


# OMN-20844 AC3 (amended): the pinned script names no OpenRouter model; phase 3
# asks onex for the default its overlay declares, so the guide never goes stale
# on a model id.
# OMN-21059: the call takes the provider as an argument, for every keyed provider.
OVERLAY_DEFAULT_MODEL_CALL = "models_cmd default-model"


def test_pinned_script_takes_the_openrouter_model_from_the_overlay() -> None:
    pinned = _pinned_commit()
    _require_commit(pinned)
    shown = _git("show", f"{pinned}:{SCRIPT_PATH}")
    assert shown.returncode == 0, shown.stderr.decode(errors="replace")
    text = shown.stdout.decode()
    assert OVERLAY_DEFAULT_MODEL_CALL in text, (
        f"ONBOARDING.md pins {pinned}, whose script does not ask onex for the "
        "overlay's default OpenRouter model"
    )
    assert "OPENROUTER_MODEL=" not in text


# The merge commit of omniclaude#2789, the second half of OMN-21087: a Mac that
# ran an earlier setup is surveyed and its leftovers set aside before installing.
RETURNING_MACHINE_SCRIPT_COMMIT = "467e0c2c0d21d23e3bc479d558e38d70851ee2f0"


def test_pin_carries_the_returning_machine_fixes() -> None:
    pinned = _pinned_commit()
    _require_commit(pinned)
    _require_commit(RETURNING_MACHINE_SCRIPT_COMMIT)
    assert _is_ancestor(RETURNING_MACHINE_SCRIPT_COMMIT, pinned), (
        f"ONBOARDING.md pins {pinned}, which does not contain "
        f"{RETURNING_MACHINE_SCRIPT_COMMIT} (omniclaude#2789, OMN-21087)"
    )


# OMN-21163 AC3: the guide names the local model server choice, its flags, and
# that it asks for no key.
def test_guide_names_the_local_model_server_choice() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    assert "A local model server by URL" in text
    assert "`--local-url URL`" in text
    assert "`--local-model NAME`" in text
    assert "`gemini`, `openrouter`, `openai`, `ollama` or `local`" in text


# OMN-21163 AC3: the merge commit of omniclaude#2834, the first commit whose
# script offers a local model server by URL on the download path too (#2830 added
# the choice; #2834 points the download at the handler that carries it).
LOCAL_URL_SCRIPT_COMMIT = "2265616f6ca81e76e117671acca57fd5161b39b5"


def test_pin_carries_the_local_model_server_choice() -> None:
    pinned = _pinned_commit()
    _require_commit(pinned)
    _require_commit(LOCAL_URL_SCRIPT_COMMIT)
    assert _is_ancestor(LOCAL_URL_SCRIPT_COMMIT, pinned), (
        f"ONBOARDING.md pins {pinned}, which does not contain "
        f"{LOCAL_URL_SCRIPT_COMMIT} (omniclaude#2834, OMN-21163)"
    )
    shown = _git("show", f"{pinned}:{SCRIPT_PATH}")
    assert shown.returncode == 0, shown.stderr.decode(errors="replace")
    assert b"--local-url" in shown.stdout
    assert b"local_url_add_args" in shown.stdout


# OMN-21059 AC3: the merge commit of omniclaude#2909, the first script that passes a
# model for every key it registers (a key with no chosen model is refused), from
# `onex models default-model <provider>` with the key on stdin.
EVERY_KEY_MODEL_SCRIPT_COMMIT = "e64119d6bb8bb35de633029c8753ae72de2ca5f2"


def test_pin_carries_every_keys_default_model() -> None:
    pinned = _pinned_commit()
    _require_commit(pinned)
    _require_commit(EVERY_KEY_MODEL_SCRIPT_COMMIT)
    assert _is_ancestor(EVERY_KEY_MODEL_SCRIPT_COMMIT, pinned), (
        f"ONBOARDING.md pins {pinned}, which does not contain "
        f"{EVERY_KEY_MODEL_SCRIPT_COMMIT} (omniclaude#2909, OMN-21059)"
    )
    shown = _git("show", f"{pinned}:{SCRIPT_PATH}")
    assert shown.returncode == 0, shown.stderr.decode(errors="replace")
    assert b"default_model() { # provider key" in shown.stdout
    assert b'models_cmd default-model "$1"' in shown.stdout


# OMN-21058 AC5 and AC10: the guide says every key and Ollama ask for models, in
# order, from a list, and that nothing is picked for the developer. The pin to
# the script that does follows once that script is on dev.
def test_guide_says_every_key_and_ollama_ask_for_models_in_order() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    assert "**Your models, for each key and for Ollama, in order.**" in text
    assert "you pick one or\n   more by number in the order to try them" in text
    assert "OpenRouter lists its free models" in text
    assert "Ollama\n   lists the models this Mac has the memory for" in text
    assert "Nothing is picked for you" in text
    assert "marked recommended" in text
    assert "overlay declares" not in text
