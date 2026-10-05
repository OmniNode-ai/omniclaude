# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The runtime_profiles gate is a plain check with no allowlist (OMN-20560).

Positive controls: a command-consuming contract with no ``runtime_profiles``
fails the wrapper, including when a file at the old repo allowlist path (or at
the validator's walk-up discovery path) names it.
"""

from __future__ import annotations

import importlib.util
import pathlib
import textwrap
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

_CONTRACT = """
name: node_planted_effect
node_type: EFFECT_GENERIC
event_bus:
  subscribe_topics:
    - "onex.cmd.omniclaude.planted-command.v1"
  publish_topics: []
"""

_ALLOWLIST = """
allowlist:
  - node_id: node_planted_effect
    reason: planted exemption that must not be honoured
"""


def _wrapper() -> ModuleType:
    path = REPO_ROOT / "scripts" / "ci" / "run_runtime_profiles_validator.py"
    spec = importlib.util.spec_from_file_location("_runtime_profiles_wrapper", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plant(root: pathlib.Path, *, with_profile: bool) -> None:
    node = root / "src" / "pkg" / "nodes" / "node_planted_effect"
    node.mkdir(parents=True)
    body = textwrap.dedent(_CONTRACT)
    if with_profile:
        body += "runtime_profiles: [main]\n"
    (node / "contract.yaml").write_text(body, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'pkg'\n", encoding="utf-8")


def test_wrapper_passes_on_the_real_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    assert _wrapper().main() == 0


def test_missing_runtime_profiles_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(tmp_path, with_profile=False)
    monkeypatch.chdir(tmp_path)
    assert _wrapper().main() == 1


def test_declared_runtime_profiles_passes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(tmp_path, with_profile=True)
    monkeypatch.chdir(tmp_path)
    assert _wrapper().main() == 0


def test_no_allowlist_file_can_exempt_a_node(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(tmp_path, with_profile=False)
    for rel in (
        "scripts/validation/runtime_profiles_allowlist.yaml",
        "validation/runtime_profiles_allowlist.yaml",
    ):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(_ALLOWLIST), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert _wrapper().main() == 1


def test_repo_carries_no_runtime_profiles_allowlist() -> None:
    for rel in (
        "scripts/validation/runtime_profiles_allowlist.yaml",
        "validation/runtime_profiles_allowlist.yaml",
    ):
        assert not (REPO_ROOT / rel).exists(), rel
