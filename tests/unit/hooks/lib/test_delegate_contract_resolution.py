# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for contract-driven command-topic resolution in the delegate skill.

DoD evidence for OMN-11638:
- _resolve_command_topic() reads the delegate skill orchestrator subscribe topic
  from the omnimarket contract rooted at OMNI_HOME.
- Missing OMNI_HOME or missing contract produces an empty topic so runtime
  dispatch can fail explicitly instead of silently falling back.
"""

from __future__ import annotations

import importlib
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.parent.parent.parent
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"

if _DELEGATE_LIB.exists() and str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))


@pytest.fixture
def delegate_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    contract_dir = (
        tmp_path
        / "omnimarket"
        / "src"
        / "omnimarket"
        / "nodes"
        / "node_delegate_skill_orchestrator"
    )
    contract_dir.mkdir(parents=True)
    (contract_dir / "contract.yaml").write_text(
        textwrap.dedent("""\
            name: node_delegate_skill_orchestrator
            event_bus:
              subscribe_topics:
                - "onex.cmd.omnimarket.delegate-skill.v1"
        """),
        encoding="utf-8",
    )
    monkeypatch.setenv("OMNI_HOME", str(tmp_path))
    sys.modules.pop("run", None)
    import run as m  # noqa: PLC0415

    return importlib.reload(m)


class TestResolveCommandTopic:
    def test_uses_omnimarket_contract_topic(self, delegate_run: ModuleType) -> None:
        assert (
            delegate_run._resolve_command_topic()
            == "onex.cmd.omnimarket.delegate-skill.v1"
        )

    def test_returns_empty_string_when_omni_home_missing(
        self, monkeypatch: pytest.MonkeyPatch, delegate_run: ModuleType
    ) -> None:
        monkeypatch.delenv("OMNI_HOME", raising=False)

        assert delegate_run._resolve_command_topic() == ""

    def test_module_level_topic_uses_contract(self, delegate_run: ModuleType) -> None:
        assert (
            delegate_run._DELEGATION_REQUEST_TOPIC
            == "onex.cmd.omnimarket.delegate-skill.v1"
        )
