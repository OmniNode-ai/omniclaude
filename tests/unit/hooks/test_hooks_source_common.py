# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Enforce that all hook scripts using Python source common.sh for venv resolution.

Policy: No hook script may use bare `PYTHON_CMD="${PYTHON_CMD:-python3}"` without
first sourcing common.sh, which provides find_python() for proper venv detection.
"""

import pathlib

import pytest

HOOKS_DIR = pathlib.Path("plugins/onex/hooks/scripts")


@pytest.mark.unit
def test_all_python_hooks_source_common() -> None:
    """Every hook that uses PYTHON_CMD must source common.sh for venv resolution."""
    violations: list[str] = []
    for sh in sorted(HOOKS_DIR.glob("*.sh")):
        if sh.name == "common.sh":
            continue
        content = sh.read_text()
        uses_python = "$PYTHON_CMD" in content or "PYTHON_CMD" in content
        sources_common = "common.sh" in content
        if uses_python and not sources_common:
            violations.append(sh.name)
    assert violations == [], (
        f"Hooks using Python without sourcing common.sh: {violations}"
    )


@pytest.mark.unit
def test_no_bare_python_cmd_override_after_common() -> None:
    """No hook should override PYTHON_CMD with bare fallback after sourcing common.sh.

    Pattern banned: `PYTHON_CMD="${PYTHON_CMD:-python3}"` appearing AFTER
    `source ... common.sh`. common.sh already provides proper venv resolution.
    """
    violations: list[str] = []
    for sh in sorted(HOOKS_DIR.glob("*.sh")):
        if sh.name == "common.sh":
            continue
        content = sh.read_text()
        lines = content.splitlines()
        sourced_common = False
        for line in lines:
            stripped = line.strip()
            if "common.sh" in stripped and stripped.startswith("source"):
                sourced_common = True
            if sourced_common and 'PYTHON_CMD="${PYTHON_CMD:-python3}"' in stripped:
                violations.append(sh.name)
                break
    assert violations == [], (
        f"Hooks overriding PYTHON_CMD after sourcing common.sh: {violations}"
    )
