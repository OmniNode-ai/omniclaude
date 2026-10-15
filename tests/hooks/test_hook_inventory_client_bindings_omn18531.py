# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The hook-inventory gate reads client_bindings as the inventory of binding hooks (OMN-18531, T0.3 AC8)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/validation/validate_hook_inventory.py"
WORKFLOW = REPO / ".github/workflows/hook-inventory-gate.yml"


def _lib():
    path = REPO / "plugins/onex/hooks/lib/hook_inventory.py"
    spec = importlib.util.spec_from_file_location("_hook_inventory_omn18531", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _contract(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    contract = tmp_path / "adapter-contract.yaml"
    contract.write_text(
        yaml.safe_dump({"client_bindings": {"claude_code": {"bindings": rows}}})
    )
    return contract


ROW = {"name": "delegation", "hook_event": "tool.call", "matcher_tool": "Agent"}


def _record(tmp_path: Path, **body: object) -> Path:
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(body))
    return path


def test_the_shipped_tree_is_clean() -> None:
    lib = _lib()
    assert lib.client_binding_findings(lib.resolve_adapter_contract()) == ()


def test_the_adapter_contract_resolves_from_the_installed_omnimarket_or_not_at_all() -> (
    None
):
    resolved = _lib().resolve_adapter_contract()
    assert resolved is None or resolved.name == "contract.yaml"
    assert resolved is None or resolved.parent.name == (
        "node_claude_code_hook_adapter_effect"
    )


def test_no_contract_declares_no_bindings_so_any_installed_binding_is_undeclared(
    tmp_path,
) -> None:
    record = _record(
        tmp_path,
        render_sha256="0" * 64,
        bindings=["delegation"],
        events=[{"event": "tool.call", "matcher": "Agent"}],
    )
    codes = {f.code for f in _lib().client_binding_findings(None, (record,))}
    assert codes == {"INSTALLED_BINDING_UNDECLARED", "INSTALLED_EVENT_UNDECLARED"}


def test_an_installed_record_naming_a_declared_event_is_clean(tmp_path) -> None:
    contract = _contract(tmp_path, [ROW])
    record = _record(
        tmp_path,
        render_sha256="0" * 64,
        bindings=["delegation"],
        events=[{"event": "tool.call", "matcher": "Agent"}],
    )
    assert _lib().client_binding_findings(contract, (record,)) == ()


def test_ac8_an_installed_event_absent_from_client_bindings_is_a_finding(
    tmp_path,
) -> None:
    contract = _contract(tmp_path, [ROW])
    record = _record(
        tmp_path,
        render_sha256="0" * 64,
        bindings=["delegation"],
        events=[{"event": "session.compact", "matcher": None}],
    )
    codes = [f.code for f in _lib().client_binding_findings(contract, (record,))]
    assert codes == ["INSTALLED_EVENT_UNDECLARED"]


def test_ac8_a_settings_registration_of_an_undeclared_binding_is_a_finding(
    tmp_path,
) -> None:
    contract = _contract(tmp_path, [ROW])
    settings = _record(
        tmp_path,
        hooks={
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "onex-claude-code-hook --binding session_start",
                        }
                    ]
                }
            ]
        },
    )
    codes = {f.code for f in _lib().client_binding_findings(contract, (settings,))}
    assert codes == {"INSTALLED_BINDING_UNDECLARED", "INSTALLED_EVENT_UNDECLARED"}


def test_a_malformed_or_duplicated_row_is_a_finding(tmp_path) -> None:
    contract = _contract(tmp_path, [ROW, ROW, {"name": "", "hook_event": ""}])
    codes = sorted(f.code for f in _lib().client_binding_findings(contract))
    assert codes == ["CLIENT_BINDING_DUPLICATE", "CLIENT_BINDING_MALFORMED"]


def _run_gate(contract: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(REPO),
            "--adapter-contract",
            str(contract),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_ac8_the_gate_exits_1_on_the_undeclared_installed_binding_and_0_without(
    tmp_path,
) -> None:
    contract = _contract(tmp_path, [ROW])
    clean = _run_gate(contract)
    assert clean.returncode == 0, clean.stderr
    record = _record(
        tmp_path,
        render_sha256="0" * 64,
        bindings=["ghost"],
        events=[{"event": "tool.call", "matcher": "Agent"}],
    )
    dirty = _run_gate(contract, "--installed-binding-artifact", str(record))
    assert dirty.returncode == 1
    assert "INSTALLED_BINDING_UNDECLARED: ghost" in dirty.stderr


def test_ac8_the_required_hook_inventory_workflow_runs_this_gate() -> None:
    text = WORKFLOW.read_text()
    assert "scripts/validation/validate_hook_inventory.py" in text
