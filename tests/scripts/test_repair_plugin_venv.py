# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from pathlib import Path


def test_repair_script_delegates_to_session_start_builder():
    script = Path("scripts/repair-plugin-venv.sh").read_text()
    assert "ensure-plugin-venv.sh" in script, (
        "repair-plugin-venv.sh must delegate venv creation to the SessionStart builder"
    )
    assert "uv venv" not in script, (
        "repair-plugin-venv.sh must not duplicate venv construction logic"
    )


def test_repair_script_forces_rebuild_by_clearing_marker():
    script = Path("scripts/repair-plugin-venv.sh").read_text()
    assert 'VENV_DIR="${CLAUDE_PLUGIN_DATA}/.venv"' in script
    assert 'rm -f "${VENV_DIR}/.built-from"' in script, (
        "repair-plugin-venv.sh must clear the marker so ensure-plugin-venv.sh rebuilds"
    )


def test_session_start_builder_owns_python_pin_and_cleanup():
    script = Path("plugins/onex/hooks/scripts/ensure-plugin-venv.sh").read_text()
    assert 'BREW_PY="/opt/homebrew/bin/python3.13"' in script, (
        "ensure-plugin-venv.sh must pin /opt/homebrew/bin/python3.13"
    )
    assert 'uv venv --python "$BREW_PY"' in script, (
        "venv creation must use the pinned Homebrew Python"
    )
    assert 'rm -rf "$VENV_DIR"' in script, (
        "ensure-plugin-venv.sh must remove stale or hollow .venv before recreating"
    )


def test_session_start_builder_fails_fast_if_python_missing():
    script = Path("plugins/onex/hooks/scripts/ensure-plugin-venv.sh").read_text()
    assert '[[ ! -x "$BREW_PY" ]]' in script
    assert "brew install python@3.13" in script
    assert "exit 1" in script, (
        "ensure-plugin-venv.sh must fail fast when the pinned Python is missing"
    )
