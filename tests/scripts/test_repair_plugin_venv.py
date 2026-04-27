# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from pathlib import Path


def test_repair_script_pins_brew_python_313():
    script = Path("scripts/repair-plugin-venv.sh").read_text()
    assert "/opt/homebrew/bin/python3.13" in script, (
        "repair-plugin-venv.sh must pin /opt/homebrew/bin/python3.13 (per macOS LAN grant policy)"
    )
    assert (
        "uv venv --python /opt/homebrew/bin/python3.13" in script
        or 'uv venv --python "$BREW_PYTHON"' in script
        or "uv venv --python ${BREW_PYTHON}" in script
    ), "venv creation must use --python /opt/homebrew/bin/python3.13"


def test_repair_script_handles_hollow_dir():
    script = Path("scripts/repair-plugin-venv.sh").read_text()
    assert "rm -rf" in script and ".venv" in script, (
        "script must rm -rf hollow .venv before recreating (uv refuses to rebuild over empty dir)"
    )
    assert '[[ -e "${LIB_DIR}/.venv" || -L "${LIB_DIR}/.venv" ]]' in script, (
        "script must remove stale .venv paths even when they are regular files or dangling symlinks"
    )


def test_repair_script_fails_fast_if_python_missing():
    script = Path("scripts/repair-plugin-venv.sh").read_text()
    assert "BREW_PYTHON" in script, "script must define BREW_PYTHON variable"
    assert "exit 1" in script, "script must exit 1 when brew python is missing"
    # Ensure the fail-fast guard references BREW_PYTHON
    lines = script.splitlines()
    has_guard = any(
        "BREW_PYTHON" in line
        and ("exit" in line or "!" in line or "-f" in line or "-x" in line)
        for line in lines
    )
    assert has_guard, "script must have a fail-fast guard checking BREW_PYTHON exists"
