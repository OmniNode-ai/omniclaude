# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""node_claude_code_binding_render_compute: the rendered mod module (OMN-18531, T0.3 AC1-AC5, AC11)."""

from __future__ import annotations

import re

import pytest

from omniclaude.nodes.node_claude_code_binding_render_compute.handlers.handler_binding_render import (
    HandlerClaudeCodeBindingRender,
)
from omniclaude.nodes.node_claude_code_binding_render_compute.models import (
    ModelBindingRenderRequest,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.binding_render_error import (
    BindingRenderError,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.enums import (
    EnumClientMaxMode,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelClientArgument,
)

from .conftest import make_binding

pytestmark = pytest.mark.unit

_STRING = re.compile(r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')""")
_COMMENT = re.compile(r"//[^\n]*")
_BRANCH_TOKENS = re.compile(
    r"\b(?:if|else|switch|case|for|while|do|try|throw|eval|Function)\b|\?|&&|\|\||\?\?"
)


def _render(*bindings, max_mode=EnumClientMaxMode.REQUIRED):
    return HandlerClaudeCodeBindingRender().handle(
        ModelBindingRenderRequest(bindings=tuple(bindings), max_mode=max_mode)
    )


def _code_residue(module_text: str) -> str:
    """The module with comments and every string literal blanked."""
    return _STRING.sub('""', _COMMENT.sub("", module_text))


def test_ac1_command_is_exactly_the_adapter_entry_with_the_binding_name() -> None:
    out = _render(make_binding())
    assert "['onex-claude-code-hook', '--binding', 'delegation']" in out.module_text, (
        out.module_text
    )
    assert "stdin: JSON.stringify(e)" in out.module_text


def test_ac2_required_host_maps_never_started_to_deny() -> None:
    text = _render(make_binding(), max_mode=EnumClientMaxMode.REQUIRED).module_text
    assert "never_started: () => ({ deny:" in text
    assert "never_started: (next, e) => next(e)" not in text


@pytest.mark.parametrize(
    "mode", [EnumClientMaxMode.OBSERVE, EnumClientMaxMode.SELECTIVE]
)
def test_ac2_observe_and_selective_map_never_started_to_native(mode) -> None:
    text = _render(make_binding(), max_mode=mode).module_text
    assert "never_started: (next, e) => next(e)" in text
    assert "never_started: () => ({ deny:" not in text


def test_ac2_changing_the_maximum_changes_only_the_failure_table_literal() -> None:
    req = _render(make_binding(), max_mode=EnumClientMaxMode.REQUIRED).module_text
    obs = _render(make_binding(), max_mode=EnumClientMaxMode.OBSERVE).module_text
    changed = [
        (a, b)
        for a, b in zip(req.splitlines(), obs.splitlines(), strict=True)
        if a != b
    ]
    assert changed, "the maximum must change the table"
    assert all(
        "never_started" in a or "other:" in a or "maximum mode" in a for a, _ in changed
    )


def test_ac3_render_is_byte_identical() -> None:
    first = _render(make_binding())
    second = _render(make_binding())
    assert first.module_text == second.module_text
    assert first.module_sha256 == second.module_sha256


def test_ac3_changing_one_deadline_changes_only_that_literal() -> None:
    a = _render(make_binding(deadline_ms=30000)).module_text.splitlines()
    b = _render(make_binding(deadline_ms=45000)).module_text.splitlines()
    diff = [(x, y) for x, y in zip(a, b, strict=True) if x != y]
    assert len(a) == len(b)
    assert len(diff) == 1
    assert "30000" in diff[0][0] and "45000" in diff[0][1]
    assert diff[0][0].replace("30000", "45000") == diff[0][1]


def test_ac4_no_branching_beyond_the_two_tables() -> None:
    residue = _code_residue(_render(make_binding()).module_text)
    assert _BRANCH_TOKENS.findall(residue) == [], residue


def test_ac4_a_data_field_carrying_code_is_a_string_literal() -> None:
    hostile = "x'); process.exit(1); if (e) { throw e } ('"
    benign = "x"
    h = _render(
        make_binding(deny_text=hostile, never_started_pattern="a|b'); if(1){")
    ).module_text
    b = _render(make_binding(deny_text=benign, never_started_pattern="a|b")).module_text
    assert _code_residue(h) == _code_residue(b)
    assert _BRANCH_TOKENS.findall(_code_residue(h)) == []


def test_ac5_an_argument_not_drawn_from_the_hook_input_fails_the_render() -> None:
    bad = make_binding(
        arguments=(ModelClientArgument(name="mode", source="observe"),),
    )
    with pytest.raises(BindingRenderError, match="mode"):
        _render(bad)


def test_ac5_the_argv_carries_nothing_but_the_binding_name() -> None:
    text = _render(make_binding()).module_text
    argvs = re.findall(r"ARGV_\w+ = (\[.*\])", text)
    assert argvs == ["['onex-claude-code-hook', '--binding', 'delegation']"]


def test_a_binding_name_with_shell_or_code_characters_fails_the_render() -> None:
    with pytest.raises(BindingRenderError):
        _render(make_binding(name="x'); evil('"))


def test_ac11_additive_row_renders_one_registration_with_the_exact_command(
    additive_binding,
) -> None:
    out = _render(additive_binding)
    assert out.registrations == _render(additive_binding).registrations
    (reg,) = out.registrations
    assert reg.event == "SessionStart"
    assert reg.command == "onex-claude-code-hook --binding session_start"
    assert "session_start" not in out.module_text


def test_catch_handler_never_throws_for_a_replacing_binding() -> None:
    text = _render(make_binding(), max_mode=EnumClientMaxMode.REQUIRED).module_text
    assert ".catch(($, e, next) => FAILURE.other(next, e))" in text
    assert "other: () => ({ deny:" in text
