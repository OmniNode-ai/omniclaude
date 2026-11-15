# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-23769 AC2: the hook's route rows equal the core rows of the installed omnibase_core.

The Mac hook is stdlib-only and cannot import core, so it carries the two rows of
``ticket_creation.validation.yaml`` (``create_route`` and ``contract_block_edit``,
OMN-23764) in ``ticket_creation_policy.json``. This reads the rows from the installed
package and compares them; a row changed on one side only turns the test red. (The
omnimarket ``ticket_guard_parity.py`` compares guard files, not this core YAML.)
"""

from __future__ import annotations

import copy
import json
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_POLICY = (
    Path(__file__).resolve().parents[2]
    / "plugins/onex/hooks/config/ticket_creation_policy.json"
)
_ROW_IDS = ("create_route", "contract_block_edit")


def _core_rows() -> dict[str, dict[str, Any]]:
    """The route rows' parameters, read from the installed ``omnibase_core``."""
    path = (
        resources.files("omnibase_core.validation")
        / "contracts"
        / "ticket_creation.validation.yaml"
    )
    document = yaml.safe_load(path.read_text(encoding="utf-8"))

    def rules(node: Any) -> list[dict[str, Any]]:
        if isinstance(node, dict):
            if isinstance(node.get("rules"), list):
                return node["rules"]
            for value in node.values():
                found = rules(value)
                if found:
                    return found
        return []

    return {r["rule_id"]: r["parameters"] for r in rules(document)}


def _hook_rows() -> dict[str, dict[str, Any]]:
    return json.loads(_POLICY.read_text(encoding="utf-8"))["route_rows"]


def _differences(
    hook: dict[str, dict[str, Any]], core: dict[str, dict[str, Any]]
) -> list[str]:
    return [row for row in _ROW_IDS if hook.get(row) != core.get(row)]


def test_hook_route_rows_match_core() -> None:
    core = _core_rows()
    for row in _ROW_IDS:
        assert row in core, f"the installed omnibase_core carries no {row} row"
    assert _differences(_hook_rows(), core) == []


@pytest.mark.parametrize("row", _ROW_IDS)
def test_hook_route_rows_match_core_fails_when_one_row_changes_on_one_side(
    row: str,
) -> None:
    """Control: the comparison is not vacuous -- one changed string on the hook side is caught."""
    hook = copy.deepcopy(_hook_rows())
    key = next(k for k in hook[row] if k in {"fix", "message"})
    hook[row][key] += " (edited)"
    assert _differences(hook, _core_rows()) == [row]
