# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A failed model-config call must not be reported as a missing ollama block.

OMN-22477. ``load_ollama_config`` returns 1 both when the model-config call
itself fails and when the config declares no block this Mac fits, and the caller
collapsed the two into "the omnimarket clone's model config declares no ollama
block; update it". That message is false for the first fault -- the omnimarket
config was correct throughout -- and it sends the reader to a file that needs no
change. ``OLLAMA_CONFIG_ERR`` now carries which fault was hit.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "plugins/onex/skills/_bin/lab-onboarding.sh"


def _load_ollama_config(tmp_path: Path, stub: str) -> subprocess.CompletedProcess[str]:
    """Run load_ollama_config over a stubbed ollama_config and print its reason."""
    source = SCRIPT.read_text()
    start = source.index("load_ollama_config() {")
    end = source.index("\n}\n", start) + len("\n}\n")
    script = "\n".join(
        [
            "ram_gb() { echo 16; }",
            stub,
            source[start:end],
            'load_ollama_config; echo "rc=$? err=$OLLAMA_CONFIG_ERR"',
        ]
    )
    return subprocess.run(
        ["/bin/bash", "-c", script],
        env={
            "LOG": str(tmp_path / "run.log"),
            "OLLAMA_MODEL": "",
            "PATH": os.environ["PATH"],
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_failed_model_config_call_is_not_called_a_missing_ollama_block(
    tmp_path: Path,
) -> None:
    done = _load_ollama_config(
        tmp_path,
        'ollama_config() { echo "ModuleNotFoundError: No module named '
        "'omniclaude'\" >&2; return 1; }",
    )
    assert "rc=1" in done.stdout, done.stdout + done.stderr
    assert "declares no ollama block" not in done.stdout, (
        "a failed model-config call was reported as a config fault:\n" + done.stdout
    )
    assert "the model-config call failed" in done.stdout, done.stdout
    # The call's own error is kept, so the reader can see what really happened.
    assert "ModuleNotFoundError" in (tmp_path / "run.log").read_text()


def test_a_config_with_no_block_this_mac_fits_still_says_so(tmp_path: Path) -> None:
    done = _load_ollama_config(tmp_path, "ollama_config() { echo; }")
    assert "rc=1" in done.stdout, done.stdout + done.stderr
    assert "declares no ollama block this Mac fits" in done.stdout, done.stdout


def test_a_readable_config_sets_every_field(tmp_path: Path) -> None:
    done = _load_ollama_config(
        tmp_path, 'ollama_config() { echo "11434 /api/chat qwen2.5-coder:7b 5"; }'
    )
    assert "rc=0" in done.stdout, done.stdout + done.stderr
    assert "err=" in done.stdout and "failed" not in done.stdout, done.stdout


def test_the_caller_reports_the_reason_rather_than_a_fixed_sentence() -> None:
    text = SCRIPT.read_text()
    start = text.index("setup_ollama() {")
    head = text[start : start + 400]
    assert 'LAST_ERR="$OLLAMA_CONFIG_ERR"' in head, head
    assert "declares no ollama block; update it" not in text, (
        "the collapsed sentence is back"
    )
