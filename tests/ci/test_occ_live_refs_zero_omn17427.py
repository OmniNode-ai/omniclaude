# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""omniclaude has no live onex_change_control reference left (OMN-17427).

``queue-status --occ-refs-only`` counts a reference as live when it is a workflow
file or step, a dependency or pin, or a non-docstring Python string or name that
locates the repository. This file pins two of the three sources that still carried
one after the OMN-20074 passes (the third, the ``onex-change-control`` dependency in
``pyproject.toml`` and ``uv.lock``, is dropped by its own change):

* the two minting reusables ``call-occ-autobind-reusable.yml`` and
  ``call-occ-companion-effect-reusable.yml`` (a workflow file named for an OCC job);
* the Done-flip guard's clone path and the PR-body stamp guard's repository slug,
  both of which read the change-control repository.

Comments and docstrings that narrate the retirement are mentions, not uses.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
OCC_RE = re.compile(r"onex[_-]change[_-]control", re.IGNORECASE)
OCC_WORKFLOW_RE = re.compile(r"^(?:call-)?occ-[a-z0-9-]+\.ya?ml$")

GUARD_MODULES = (
    "plugins/onex/hooks/lib/done_flip_guard.py",
    "plugins/onex/hooks/lib/no_pr_bound_evidence.py",
    "plugins/onex/hooks/lib/pr_body_stamp_guard.py",
)


def _live_python_lines(source: str) -> list[int]:
    """Lines where a name, an import or a non-docstring string names the repository."""
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            docstrings.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if OCC_RE.search(node.value) and node.lineno not in docstrings:
                lines.append(node.lineno)
        elif (isinstance(node, ast.Name) and OCC_RE.search(node.id)) or (
            isinstance(node, ast.Attribute) and OCC_RE.search(node.attr)
        ):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom | ast.Import):
            names = [a.name for a in node.names]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            if any(OCC_RE.search(n) for n in names):
                lines.append(node.lineno)
    return sorted(set(lines))


def test_positive_control_the_matcher_sees_a_live_string_and_an_import() -> None:
    assert _live_python_lines('x = home / "onex_change_control"\n') == [1]
    assert _live_python_lines("import onex_change_control\n") == [1]
    assert _live_python_lines('"""onex_change_control"""\nimport os\n') == []


def test_no_workflow_file_is_named_for_an_occ_job() -> None:
    present = sorted(
        path.name
        for path in (REPO_ROOT / ".github" / "workflows").iterdir()
        if OCC_WORKFLOW_RE.match(path.name)
    )
    assert not present, present


@pytest.mark.parametrize("relative", GUARD_MODULES)
def test_guard_module_does_not_read_the_change_control_repository(
    relative: str,
) -> None:
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert _live_python_lines(source) == []
