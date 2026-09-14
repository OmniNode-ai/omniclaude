# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the session-intent resolver [OMN-18368].

``plugins/onex/lib/intent.sh`` is the third resolution axis beside
``lib/mode.sh``. Mode answers "how much of this plugin applies here"; intent
answers "what was this session opened to do", which mode cannot express: a
session opened only to re-authenticate a tool server resolves to ``full`` mode
(its working directory is the workspace) and still wants no status output.

Three intents and no more:

* ``quiet`` — opened to re-authenticate, to check connectivity, or to do one
  thing that is not this workspace's process. Prints nothing but a blocker.
* ``normal`` — ordinary interactive work.
* ``tick`` — a scheduled or dispatched workflow opened this session.

Resolution order, highest first:

1. an explicit argument, which is how the preflight skill passes ``--intent``;
2. the ``OMNICLAUDE_SESSION_INTENT`` environment variable;
3. a per-session marker file, which is how a scheduled tick declares itself,
   honoured only while it is fresh;
4. the persistent preference file, the sibling of ``~/.config/omniclaude/mode``;
5. the default, ``normal``.

The invariant that matters more than the order is **inference never resolves to
quiet**. Every fall-through lands on ``normal``, and an unreadable or invalid
value at any layer falls through rather than being honoured. A wrongly-quiet
session hides a blocker; a wrongly-normal session costs one line.

Hermetic: every case runs the real script in a subprocess with its own ``HOME``
and its own state directory. Nothing reads the developer's config.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INTENT_SH = _REPO_ROOT / "plugins" / "onex" / "lib" / "intent.sh"
_MODE_SH = _REPO_ROOT / "plugins" / "onex" / "lib" / "mode.sh"


def _resolve(
    tmp_path: Path,
    *,
    explicit: str | None = None,
    env_intent: str | None = None,
    marker: str | None = None,
    marker_age_seconds: int = 0,
    preference: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Source the resolver and print what it resolves.

    Every layer is supplied independently so a precedence case can set two at
    once and assert which one won.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)

    env = os.environ.copy()
    env.pop("OMNICLAUDE_SESSION_INTENT", None)
    env["HOME"] = str(home)
    env["ONEX_HOOKS_STATE_DIR"] = str(state)
    if env_intent is not None:
        env["OMNICLAUDE_SESSION_INTENT"] = env_intent

    if marker is not None:
        marker_file = state / "session-intent"
        marker_file.write_text(marker + "\n")
        if marker_age_seconds:
            past = time.time() - marker_age_seconds
            os.utime(marker_file, (past, past))

    if preference is not None:
        pref_dir = home / ".config" / "omniclaude"
        pref_dir.mkdir(parents=True, exist_ok=True)
        (pref_dir / "session-intent").write_text(preference + "\n")

    arg = "" if explicit is None else f' "{explicit}"'
    script = f'. "{_INTENT_SH}"; omniclaude_session_intent{arg}'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )


def _intent(tmp_path: Path, **kwargs: object) -> str:
    result = _resolve(tmp_path, **kwargs)  # type: ignore[arg-type]
    assert result.returncode == 0, (
        f"The resolver must always succeed — a session that cannot resolve its "
        f"own intent is a session that runs as normal, never one that fails. "
        f"stderr:\n{result.stderr}"
    )
    return result.stdout.strip()


# --------------------------------------------------------------------------- #
# The file exists and sits beside the mode resolver
# --------------------------------------------------------------------------- #


def test_resolver_lives_beside_the_mode_resolver() -> None:
    """The plan places intent as a sibling axis, not a new hook or format."""
    assert _MODE_SH.is_file(), "precondition: the mode resolver is where it was"
    assert _INTENT_SH.is_file(), (
        f"The intent resolver must live beside the mode resolver at "
        f"{_INTENT_SH}, so the two axes are found and read together."
    )


# --------------------------------------------------------------------------- #
# Default
# --------------------------------------------------------------------------- #


def test_default_is_normal_with_nothing_set(tmp_path: Path) -> None:
    """No argument, no variable, no marker, no preference resolves to normal."""
    assert _intent(tmp_path) == "normal"


# --------------------------------------------------------------------------- #
# Each layer in isolation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("intent", ["quiet", "normal", "tick"])
def test_explicit_argument_is_honoured(tmp_path: Path, intent: str) -> None:
    """The preflight skill's --intent reaches the resolver as an argument."""
    assert _intent(tmp_path, explicit=intent) == intent


@pytest.mark.parametrize("intent", ["quiet", "normal", "tick"])
def test_environment_variable_is_honoured(tmp_path: Path, intent: str) -> None:
    """Whoever opens the session can declare its intent in the environment."""
    assert _intent(tmp_path, env_intent=intent) == intent


@pytest.mark.parametrize("intent", ["quiet", "tick"])
def test_fresh_marker_file_is_honoured(tmp_path: Path, intent: str) -> None:
    """A scheduled tick writes a marker rather than editing anyone's env."""
    assert _intent(tmp_path, marker=intent) == intent


@pytest.mark.parametrize("intent", ["quiet", "tick"])
def test_preference_file_is_honoured(tmp_path: Path, intent: str) -> None:
    """The persistent preference is the sibling of ~/.config/omniclaude/mode."""
    assert _intent(tmp_path, preference=intent) == intent


# --------------------------------------------------------------------------- #
# Precedence
# --------------------------------------------------------------------------- #


def test_explicit_argument_beats_environment(tmp_path: Path) -> None:
    assert _intent(tmp_path, explicit="quiet", env_intent="normal") == "quiet"


def test_environment_beats_marker(tmp_path: Path) -> None:
    assert _intent(tmp_path, env_intent="normal", marker="quiet") == "normal"


def test_marker_beats_preference(tmp_path: Path) -> None:
    """A tick's own declaration outranks a standing preference."""
    assert _intent(tmp_path, marker="tick", preference="quiet") == "tick"


def test_preference_beats_default(tmp_path: Path) -> None:
    assert _intent(tmp_path, preference="quiet") == "quiet"


# --------------------------------------------------------------------------- #
# Fail-closed: every unusable value falls through, and never to quiet
# --------------------------------------------------------------------------- #


def test_stale_marker_is_ignored(tmp_path: Path) -> None:
    """A marker outlives the session that wrote it; a stale one must not silence
    the next session that happens to open on the same host."""
    assert _intent(tmp_path, marker="quiet", marker_age_seconds=3600) == "normal"


def test_stale_marker_does_not_block_the_preference(tmp_path: Path) -> None:
    """Ignoring the marker means falling to the next layer, not to the default."""
    assert (
        _intent(tmp_path, marker="quiet", marker_age_seconds=3600, preference="tick")
        == "tick"
    )


@pytest.mark.parametrize("bad", ["silent", "QUIET", "", "quiet extra", "full"])
def test_invalid_environment_value_falls_through(tmp_path: Path, bad: str) -> None:
    """An unrecognised value is not an error and is not honoured."""
    assert _intent(tmp_path, env_intent=bad) == "normal"


@pytest.mark.parametrize("bad", ["silent", "lite", ""])
def test_invalid_explicit_argument_falls_through(tmp_path: Path, bad: str) -> None:
    assert _intent(tmp_path, explicit=bad) == "normal"


def test_invalid_explicit_argument_falls_through_to_the_next_layer(
    tmp_path: Path,
) -> None:
    """Falling through means consulting the next source, not jumping to default."""
    assert _intent(tmp_path, explicit="silent", env_intent="tick") == "tick"


def test_invalid_marker_content_falls_through(tmp_path: Path) -> None:
    assert _intent(tmp_path, marker="please be quiet") == "normal"


def test_unreadable_preference_file_does_not_fail(tmp_path: Path) -> None:
    """A directory where the preference file should be is unreadable, not fatal."""
    home = tmp_path / "home"
    (home / ".config" / "omniclaude" / "session-intent").mkdir(parents=True)
    result = _resolve(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "normal"


def test_nothing_infers_quiet(tmp_path: Path) -> None:
    """The one-way property: quiet is only ever declared, never deduced.

    Every fall-through path in the resolver is exercised above and every one of
    them lands on ``normal``. This test states the property directly so a future
    auto-detection branch that resolves downward fails here rather than silently
    hiding a blocker in somebody's session.
    """
    body = _INTENT_SH.read_text()
    inference_markers = ("$PWD", "${PWD", "pwd)", "uname", "hostname")
    offending = [
        line
        for line in body.splitlines()
        if "quiet" in line and any(marker in line for marker in inference_markers)
    ]
    assert not offending, (
        "No inference branch may resolve to quiet. Offending lines:\n"
        + "\n".join(offending)
    )
