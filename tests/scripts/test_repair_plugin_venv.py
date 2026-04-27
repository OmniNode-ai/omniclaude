# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

import re
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
    has_guard_exit = re.search(
        r'if\s+\[\[\s*!\s+-x\s+"\$BREW_PYTHON"\s*\]\];\s*then(?s:.*?)\bexit\s+1\b',
        script,
    )
    assert has_guard_exit, (
        "script must fail fast with exit 1 when BREW_PYTHON is missing"
    )
