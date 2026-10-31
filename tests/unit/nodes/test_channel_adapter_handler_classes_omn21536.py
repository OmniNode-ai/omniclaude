# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The Discord, Email and SMS channel adapters bind handler classes (OMN-21536).

The handler-shape validator refuses a ``handler_*.py`` made of module functions
only. These adapters' contracts already name ``Handler<Channel><Direction>``
classes; the AST checks below hold that each such class exists in the module the
contract names and that its ``handle`` takes one typed request. They parse the
source, so they run without the optional ``discord`` dependency.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

_NODES_ROOT = Path(__file__).resolve().parents[3] / "src" / "omniclaude" / "nodes"
_ADAPTERS = ("discord", "email", "sms")


def _bindings(channel: str) -> list[tuple[str, str]]:
    contract = yaml.safe_load(
        (_NODES_ROOT / f"node_channel_{channel}_adapter" / "contract.yaml").read_text()
    )
    return [
        (h["handler"]["name"], h["handler"]["module"])
        for h in contract["handler_routing"]["handlers"]
    ]


def _module_tree(module: str) -> ast.Module:
    relative = Path(*module.removeprefix("omniclaude.nodes.").split("."))
    return ast.parse((_NODES_ROOT / relative).with_suffix(".py").read_text())


@pytest.mark.unit
@pytest.mark.parametrize("channel", _ADAPTERS)
def test_contract_names_resolve_to_classes_with_typed_handle(channel: str) -> None:
    bindings = _bindings(channel)
    assert len(bindings) == 2
    for name, module in bindings:
        classes = {
            node.name: node
            for node in _module_tree(module).body
            if isinstance(node, ast.ClassDef)
        }
        assert name in classes, f"{module} defines no class {name}"
        handles = [
            m
            for m in classes[name].body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            and m.name == "handle"
        ]
        assert len(handles) == 1, f"{name} needs exactly one handle"
        params = [a for a in handles[0].args.args if a.arg != "self"]
        assert [a.arg for a in params] == ["request"], f"{name}.handle(request)"
        assert params[0].annotation is not None
        assert "Model" in ast.unparse(params[0].annotation)
        assert handles[0].args.kwarg is None


@pytest.mark.unit
@pytest.mark.parametrize("channel", _ADAPTERS)
def test_handler_modules_hold_no_public_module_function(channel: str) -> None:
    for _name, module in _bindings(channel):
        public = [
            node.name
            for node in _module_tree(module).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        ]
        assert public == [], f"{module} still holds module functions {public}"
