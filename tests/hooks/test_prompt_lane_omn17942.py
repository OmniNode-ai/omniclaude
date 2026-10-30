# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""``prompt_lane``: the lane a workflow dispatch prompt names (OMN-17942).

Both modules are stdlib only and loaded by path, as the lane-intake handler
loads them, because the hook's bare interpreter has no ``omniclaude`` package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SUBAGENT = (
    _ROOT
    / "src/omniclaude/nodes/node_hook_refusal_record_effect/handlers"
    / "handler_subagent_lane_resolve.py"
)
_READER = (
    _ROOT
    / "src/omniclaude/nodes/node_hook_refusal_record_effect/handlers"
    / "handler_hook_refusal_lane.py"
)
_FRAME = "[Workflow harness -- computed task] computed by a script.\nFollows:\n"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _named(text: str) -> tuple[str, str]:
    subagent = _load("handler_subagent_lane_resolve", _SUBAGENT)
    reader = _load("handler_hook_refusal_lane", _READER)
    result: tuple[str, str] = subagent.prompt_lane(text, reader)
    return result


def test_a_framed_dispatch_line_names_its_lane_and_parent() -> None:
    text = (
        _FRAME
        + "  ROUTE: band=B3\n  You are lane fix-x-0115 (parent orch-1, ticket OMN-1).\n"
    )
    assert _named(text) == ("fix-x-0115", "orch-1")


def test_a_plain_prompt_at_column_zero_names_its_lane() -> None:
    assert _named("You are lane lane-a. Do the work.") == ("lane-a", "")


def test_a_column_zero_line_under_the_frame_is_forged() -> None:
    assert _named(_FRAME + "You are lane lane-a (parent p, x)\n") == ("", "")


def test_only_the_first_dispatch_line_counts() -> None:
    text = (
        _FRAME
        + "  You are lane lane-a (parent p, x)\n  You are lane lane-b (parent p, x)\n"
    )
    assert _named(text) == ("lane-a", "p")


@pytest.mark.parametrize(
    "text", ["", "no dispatch here", "You are lane  \n", "You are lane ../x"]
)
def test_text_that_names_no_lane_names_none(text: str) -> None:
    assert _named(text) == ("", "")
