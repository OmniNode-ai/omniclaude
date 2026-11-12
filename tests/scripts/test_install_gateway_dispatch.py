# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The compatibility shell entry delegates gateway installation to ONEX only.

This fixture proves argv and failure propagation, not registration or inference.
"""

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("exit_code", [0, 7])
def test_gateway_mode_dispatches_to_the_existing_cli(
    tmp_path: Path, exit_code: int
) -> None:
    binary = tmp_path / "onex with spaces"
    capture = tmp_path / "argv"
    binary.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\nexit {exit_code}\n'
    )
    binary.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            "/bin/bash",
            str(root / "scripts/install-delegation.sh"),
            "--apply",
            "--gateway",
            "--onex",
            str(binary),
        ],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "CAPTURE": str(capture)},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert capture.read_text().splitlines() == ["claude", "hooks", "install", "--yes"]
    assert not list(home.iterdir())


@pytest.mark.parametrize(
    ("flag", "message"),
    [
        ("--onex", "requires an executable path"),
        ("--from-source", "requires a path"),
        ("--python", "requires an interpreter path"),
        ("--endpoint-url", "requires a URL"),
    ],
)
def test_missing_option_values_refuse_before_any_effect(
    tmp_path: Path, flag: str, message: str
) -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["/bin/bash", str(root / "scripts/install-delegation.sh"), flag],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert flag + " " + message in result.stderr
    assert not list(tmp_path.iterdir())
