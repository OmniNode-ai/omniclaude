# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21261 AC5, AC6: what the participant guide tells a participant to run.

``plugins/onex/ONBOARDING.md`` downloads the onboarding script from one commit, checks
its sha256, and runs it natively with ``--no-containers``. These tests pin the
corrected script's commit and checksum and the documented run command, so the guide
cannot fall back to the earlier script or drop the flag unnoticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

GUIDE = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "ONBOARDING.md"
SCRIPT_COMMIT = "edc3286935f5500187c1957efcbf7d46fad55843"
SCRIPT_SHA256 = "40c83f09d8dd4d007feb786d9b0ec41e0b2c80d818fcb27a4eac0d2f0710a1d1"

pytestmark = pytest.mark.unit


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def test_ac5_the_guide_downloads_the_corrected_script_at_its_commit() -> None:
    url = (
        "https://raw.githubusercontent.com/OmniNode-ai/omniclaude/"
        f"{SCRIPT_COMMIT}/plugins/onex/skills/_bin/lab-onboarding.sh"
    )
    assert url in _guide()


def test_ac5_the_guide_checks_the_corrected_scripts_checksum() -> None:
    check = f'echo "{SCRIPT_SHA256}  lab-onboarding.sh" | shasum -a 256 -c -'
    assert check in _guide()


def test_ac6_the_run_command_passes_no_containers_and_says_phase_4_is_skipped() -> None:
    guide = _guide()
    assert "\nbash lab-onboarding.sh --no-containers\n" in guide
    assert "phase 4 is skipped" in guide
    assert "Drop the flag to be asked" in guide
