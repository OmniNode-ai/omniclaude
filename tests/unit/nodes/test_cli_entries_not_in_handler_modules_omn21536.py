# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A process entry lives in a ``runtime_*.py`` module, never in a ``handler_*.py`` (OMN-21536).

The handler-shape validator (omnibase_core ``ValidatorHandlerShape``) refuses a
``handler_*.py`` made of module functions only. These three nodes held a CLI
``main`` in their handler directory; the entry now sits in a ``runtime_*.py``
module and the handler module holds a handler class.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

NODES = Path(__file__).resolve().parents[3] / "src/omniclaude/nodes"
HANDLER_DIRS = [
    NODES / "node_linear_effect/handlers",
    NODES / "node_lane_github_read_guard_effect/handlers",
    NODES / "node_pr_ownership_guard_effect/handlers",
]
RUNTIME_ENTRIES = [
    NODES / "node_linear_effect/runtime_done_closeout_instructions.py",
    NODES / "node_lane_github_read_guard_effect/runtime_lane_github_read.py",
    NODES / "node_pr_ownership_guard_effect/runtime_pr_ownership.py",
]


def _top_level_functions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


@pytest.mark.parametrize("handler_dir", HANDLER_DIRS, ids=lambda p: p.parent.name)
def test_no_handler_module_defines_a_cli_main(handler_dir: Path) -> None:
    offenders = [
        path.name
        for path in sorted(handler_dir.glob("handler_*.py"))
        if "main" in _top_level_functions(path)
    ]
    assert offenders == []


@pytest.mark.parametrize("entry", RUNTIME_ENTRIES, ids=lambda p: p.name)
def test_runtime_entry_defines_main(entry: Path) -> None:
    assert "main" in _top_level_functions(entry)
