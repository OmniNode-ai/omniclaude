# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21309: a completed onboarding run plays the finish sound on macOS.

The walk runs on a VM over ssh, with no terminal on stdin, so the sound must
play there too: afplay plays on the Mac's own audio output. These tests run the
setup handler's own ``finish_sound`` with stub ``afplay``, ``say`` and ``id`` and with
the clips served from a local directory, then read back what was played.
"""

from __future__ import annotations

import array
import os
import subprocess
import wave
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "_bin"
    / "lab-onboarding.sh"
)
HANDLER = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "omniclaude"
    / "nodes"
    / "node_skill_omninode_dev_setup_orchestrator"
    / "handler_onboarding_preflight.sh"
)


def _functions(*names: str) -> str:
    out, keep = [], False
    for line in (SCRIPT.read_text() + HANDLER.read_text()).splitlines():
        if any(line.startswith(f"{n}() {{") for n in names):
            keep = True
        if keep:
            out.append(line)
            if line == "}":
                keep = False
    return "\n".join(out)


def _clip(path: Path) -> str:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(array.array("h", [0, 4000, -4000, 4000] * 2000).tobytes())
    done = subprocess.run(
        ["shasum", "-a", "256", str(path)], capture_output=True, text=True, check=True
    )
    return done.stdout.split()[0]


def _stub(bin_dir: Path, name: str, body: str) -> None:
    (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n")
    (bin_dir / name).chmod(0o755)


def _run(tmp_path: Path, *, os_name: str, fullname: str, home: str) -> list[str]:
    clips, bin_dir, calls = tmp_path / "clips", tmp_path / "bin", tmp_path / "calls"
    clips.mkdir()
    bin_dir.mkdir()
    digests = " ".join(
        f"{c}:{_clip(clips / f'{c}.wav')}" for c in ("welcome", "to-omninode")
    )
    _stub(bin_dir, "afplay", f'echo "afplay $*" >> "{calls}"')
    _stub(
        bin_dir,
        "say",
        f'echo "say $*" >> "{calls}"\n'
        f'while [ $# -gt 0 ]; do [ "$1" = -o ] && cp "{clips}/welcome.wav" "$2"; shift; done',
    )
    _stub(
        bin_dir,
        "id",
        f'[ "$1" = -F ] && {{ echo "{fullname}"; exit 0; }}; exec /usr/bin/id "$@"',
    )
    home_dir = tmp_path / "homes" / home
    home_dir.mkdir(parents=True)
    snippet = (
        "say() { printf '%s\\n' \"$*\"; }\nlog() { :; }\n"
        f'RUN_DIR="{tmp_path}"\nPREFLIGHT_ONLY=0\n'
        'os_name() { echo "${ONBOARD_TEST_OS:-$(uname -s)}"; }\n'
        + "\n".join(
            line
            for line in HANDLER.read_text().splitlines()
            if line.startswith("FINISH_CLIP_")
        )
        + f'\nFINISH_CLIP_BASE="file://{clips}"\nFINISH_CLIP_DIGESTS="{digests}"\n'
        + _functions(
            "finish_name_like", "finish_name", "finish_sound_consent", "finish_sound"
        )
        # OMN-21517: phase 0 makes the synthesis call, then the finish step plays.
        + "\nfinish_sound_consent\nfinish_sound\n"
    )
    env = {
        "HOME": str(home_dir),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "ONBOARD_TEST_OS": os_name,
        "SSH_CONNECTION": "203.0.113.1 50000 203.0.113.2 22",
    }
    subprocess.run(
        ["/bin/bash", "-c", snippet],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )
    return calls.read_text().splitlines() if calls.exists() else []


def test_plays_over_ssh_with_no_terminal(tmp_path: Path) -> None:
    calls = _run(tmp_path, os_name="Darwin", fullname="alice example", home="admin")
    assert [c for c in calls if c.startswith("say ")] == [
        next(c for c in calls if c.startswith("say ") and c.endswith(" Alice"))
    ]
    played = [c for c in calls if c.startswith("afplay ")]
    assert len(played) == 1 and played[0].endswith("/finish.wav"), calls


def test_plays_without_a_name_and_never_asks(tmp_path: Path) -> None:
    calls = _run(tmp_path, os_name="Darwin", fullname="", home="admin")
    assert not [c for c in calls if c.startswith("say ")], calls
    assert len([c for c in calls if c.startswith("afplay ")]) == 1, calls


def test_skipped_off_macos(tmp_path: Path) -> None:
    assert _run(tmp_path, os_name="Linux", fullname="alice example", home="bob") == []


def test_main_plays_it_after_a_completed_run() -> None:
    body = _functions("main")
    assert body.index("result=COMPLETE") < body.index("finish_sound"), body
    assert os.access(SCRIPT, os.X_OK)
