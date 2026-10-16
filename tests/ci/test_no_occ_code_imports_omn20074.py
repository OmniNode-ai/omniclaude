# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20074: no Python module in omniclaude imports the change-control package.

The workflow half of the cut-over is pinned by ``test_no_occ_callers_omn20074``.
This half pins the code: once nothing imports ``onex_change_control``, the
dependency can be dropped without breaking a hook, a skill library or a test.
The scan reads the parsed import statements, so a docstring or a comment that
names the package cannot trip it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "onex_change_control"
SCANNED_ROOTS = ("src", "plugins", "scripts", "tests")


def _imports_package(source: str) -> list[int]:
    """Line numbers of every import statement that names the package."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        if any(name.split(".", 1)[0] == PACKAGE for name in names):
            lines.append(node.lineno)
    return lines


def test_detector_flags_plain_and_from_imports() -> None:
    """Positive control: the scan fires on the shapes the repo used to carry."""
    assert _imports_package("import onex_change_control\n") == [1]
    assert _imports_package("from onex_change_control import ModelDayOpen\n") == [1]
    assert _imports_package(
        "def f():\n    from onex_change_control.scripts.x import y\n"
    ) == [2]
    assert _imports_package('"""onex_change_control"""\nimport os\n') == []


def test_no_python_module_imports_the_change_control_package() -> None:
    offenders: list[str] = []
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(REPO_ROOT)
            if any(
                part.startswith(".") or part == "node_modules" for part in rel.parts
            ):
                continue
            try:
                source = path.read_text(encoding="utf-8")
                found = _imports_package(source)
            except (SyntaxError, UnicodeDecodeError):
                continue
            offenders.extend(f"{rel}:{line}" for line in found)
    assert not offenders, offenders
