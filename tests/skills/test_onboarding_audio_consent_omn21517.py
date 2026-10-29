# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21517: the audio consent is requested in phase 0, not by the finish step.

macOS raises a permission dialog the first time a Terminal uses the speech
synthesis audio session. Phase 0 is where the run already asks the developer
for things, so it makes the one synthesis call there, after a notice that the
dialog is coming. The finish step then plays recorded clips and makes no
synthesis call. A refused dialog costs only the synthesised clip: the recorded
clips still play and the step still succeeds.

These tests run the setup handler's own functions with stub ``afplay``, ``say``
and ``id`` binaries and read back what was called.
"""

from __future__ import annotations

import array
import re
import subprocess
import wave
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "plugins/onex/skills/_bin/lab-onboarding.sh"
HANDLER = (
    REPO
    / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
    / "handler_onboarding_preflight.sh"
)
NOTICE = "NOTICE>"


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


def _run(
    tmp_path: Path,
    steps: list[str],
    *,
    synthesis_fails: bool = False,
    preflight_only: int = 0,
    finish_sound_env: str = "1",
) -> tuple[list[str], int]:
    clips, bin_dir, calls = tmp_path / "clips", tmp_path / "bin", tmp_path / "calls"
    played = tmp_path / "played"
    clips.mkdir()
    bin_dir.mkdir()
    played.mkdir()
    digests = " ".join(
        f"{c}:{_clip(clips / f'{c}.wav')}" for c in ("welcome", "to-omninode")
    )
    _stub(
        bin_dir,
        "afplay",
        f'echo "afplay $*" >> "{calls}"\n'
        f'python3 -c "import sys,wave; print(\'frames\', wave.open(sys.argv[1]).getnframes())" "$1" >> "{calls}"',
    )
    if synthesis_fails:
        say_body = f'echo "say $*" >> "{calls}"\nexit 1'
    else:
        say_body = (
            f'echo "say $*" >> "{calls}"\n'
            f'while [ $# -gt 0 ]; do [ "$1" = -o ] && cp "{clips}/welcome.wav" "$2"; shift; done'
        )
    _stub(bin_dir, "say", say_body)
    _stub(
        bin_dir,
        "id",
        '[ "$1" = -F ] && { echo "alice example"; exit 0; }; exec /usr/bin/id "$@"',
    )
    home_dir = tmp_path / "home" / "admin"
    home_dir.mkdir(parents=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    snippet = (
        f'say() {{ printf \'{NOTICE}%s\\n\' "$*" >> "{calls}"; }}\nlog() {{ :; }}\n'
        'os_name() { echo "${ONBOARD_TEST_OS:-$(uname -s)}"; }\n'
        f'RUN_DIR="{run_dir}"\nPREFLIGHT_ONLY={preflight_only}\n'
        + "\n".join(
            line
            for line in HANDLER.read_text().splitlines()
            if line.startswith("FINISH_CLIP_")
        )
        + f'\nFINISH_CLIP_BASE="file://{clips}"\nFINISH_CLIP_DIGESTS="{digests}"\n'
        + _functions(
            "finish_name_like", "finish_name", "finish_sound_consent", "finish_sound"
        )
        + "\n"
        + "\n".join(steps)
        + "\n"
    )
    env = {
        "HOME": str(home_dir),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "ONBOARD_TEST_OS": "Darwin",
        "ONBOARD_FINISH_SOUND": finish_sound_env,
    }
    done = subprocess.run(
        ["/bin/bash", "-c", snippet],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    return (calls.read_text().splitlines() if calls.exists() else []), done.returncode


def _synth(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("say ")]


def test_ac1_phase0_makes_the_synthesis_call_and_finish_makes_none(
    tmp_path: Path,
) -> None:
    (tmp_path / "p0").mkdir()
    asked, rc = _run(tmp_path / "p0", ["finish_sound_consent"])
    assert rc == 0 and len(_synth(asked)) == 1, asked
    assert not [c for c in asked if c.startswith("afplay ")], asked
    both, rc = _run(tmp_path, ["finish_sound_consent", "finish_sound"])
    assert rc == 0, both
    # The finish step added no synthesis call to the one phase 0 made.
    assert len(_synth(both)) == 1, both


def test_ac1_finish_step_alone_makes_no_synthesis_call(tmp_path: Path) -> None:
    calls, rc = _run(tmp_path, ["finish_sound"])
    assert rc == 0, calls
    assert not _synth(calls), calls
    assert [c for c in calls if c.startswith("afplay ")], calls


def test_ac1_phase0_calls_the_consent_before_the_questions() -> None:
    body = _functions("phase0")
    assert "finish_sound_consent" in body
    assert body.index("finish_sound_consent") < body.index("settle_models"), body


def test_ac1_preflight_only_and_opt_out_ask_nothing(tmp_path: Path) -> None:
    calls, rc = _run(tmp_path, ["finish_sound_consent"], preflight_only=1)
    assert rc == 0 and calls == []
    off = tmp_path / "off"
    off.mkdir()
    calls, rc = _run(off, ["finish_sound_consent"], finish_sound_env="0")
    assert rc == 0 and calls == []


def test_ac2_the_notice_comes_before_the_synthesis_call(tmp_path: Path) -> None:
    calls, rc = _run(tmp_path, ["finish_sound_consent"])
    assert rc == 0, calls
    notices = [i for i, c in enumerate(calls) if c.startswith(NOTICE)]
    synth = [i for i, c in enumerate(calls) if c.startswith("say ")]
    assert len(notices) == 1 and len(synth) == 1, calls
    assert notices[0] < synth[0], calls
    text = calls[notices[0]].lower()
    assert "macos" in text and "ask" in text and "audio" in text, text


def test_ac3_a_refused_synthesis_still_plays_both_clips_and_succeeds(
    tmp_path: Path,
) -> None:
    calls, rc = _run(
        tmp_path, ["finish_sound_consent", "finish_sound"], synthesis_fails=True
    )
    assert rc == 0, calls
    assert [c for c in calls if c.startswith(NOTICE)], calls
    played = [c for c in calls if c.startswith("afplay ")]
    assert played, calls
    frames = [int(m.group(1)) for c in calls if (m := re.match(r"frames (\d+)", c))]
    # Both recorded clips (8000 samples each) are in what was played.
    assert sum(frames) >= 15000, calls
    assert len(_synth(calls)) == 1, calls
