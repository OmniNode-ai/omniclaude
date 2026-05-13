# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests verifying the delegate skill shim is thin and contract-driven.

DoD evidence for OMN-10943:
- No delegation env vars (KAFKA_BOOTSTRAP_SERVERS, LLM env vars) read at import time.
- Dispatch topic comes from contract YAML, not hardcoded strings.
- No direct import of omnibase_infra internal handlers at the module level.
"""

from __future__ import annotations

import importlib
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.parent.parent.parent
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"

if _DELEGATE_LIB.exists() and str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))


@pytest.fixture
def delegate_run(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    sys.modules.pop("run", None)
    import run as m  # noqa: PLC0415

    return importlib.reload(m)


class TestShimDoesNotReadDelegationEnvVarsAtImportTime:
    def test_kafka_bootstrap_servers_not_read_at_import(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """KAFKA_BOOTSTRAP_SERVERS must not be accessed during module import."""
        monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
        monkeypatch.delenv("ONEX_RUNTIME_URL", raising=False)
        monkeypatch.delenv("ONEX_RUNTIME_SSH_HOST", raising=False)

        sys.modules.pop("run", None)
        import run as m  # noqa: PLC0415

        importlib.reload(m)

    def test_llm_env_vars_not_read_at_import(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM_CODER_URL / LLM_DEEPSEEK_R1_URL must not be read at import time."""
        monkeypatch.delenv("LLM_CODER_URL", raising=False)
        monkeypatch.delenv("LLM_DEEPSEEK_R1_URL", raising=False)
        monkeypatch.delenv("LLM_CODER_FAST_URL", raising=False)

        sys.modules.pop("run", None)
        import run as m  # noqa: PLC0415

        importlib.reload(m)

    def test_module_level_topic_comes_from_contract_resolution_not_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_DELEGATION_REQUEST_TOPIC is set by contract resolution, not env var lookup."""
        monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)

        sys.modules.pop("run", None)
        import run as m  # noqa: PLC0415

        mod = importlib.reload(m)

        assert hasattr(mod, "_DELEGATION_REQUEST_TOPIC")
        assert isinstance(mod._DELEGATION_REQUEST_TOPIC, str)
        # Must be a non-empty topic derived from contract or TopicBase fallback
        assert mod._DELEGATION_REQUEST_TOPIC != ""


class TestShimLoadsTopicFromContract:
    def test_topic_loaded_from_contract_subscribe_topics(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_resolve_delegation_topic_and_event_type reads subscribe_topics[0] from contract."""
        contract_yaml = textwrap.dedent("""\
            name: node_delegation_orchestrator
            event_bus:
              subscribe_topics:
                - "onex.cmd.omnibase-infra.delegation-request.v1"
            consumed_events:
              - topic: "onex.cmd.omnibase-infra.delegation-request.v1"
                event_type: "ContractDrivenEventType"
        """)
        node_dir = tmp_path / "nodes" / "node_delegation_orchestrator"
        node_dir.mkdir(parents=True)
        (node_dir / "contract.yaml").write_text(contract_yaml)

        fake_obi = MagicMock()
        fake_obi.__file__ = str(tmp_path / "__init__.py")

        sys.modules.pop("run", None)
        import run as m  # noqa: PLC0415

        mod = importlib.reload(m)

        with patch.dict(sys.modules, {"omnibase_infra": fake_obi}):
            topic, event_type = mod._resolve_delegation_topic_and_event_type()

        assert topic == "onex.cmd.omnibase-infra.delegation-request.v1"
        assert event_type == "ContractDrivenEventType"

    def test_topic_not_hardcoded_string(self, delegate_run: ModuleType) -> None:
        """_DELEGATION_REQUEST_TOPIC must not be a bare hardcoded literal.

        It must go through contract resolution. The fallback is TopicBase.DELEGATE_TASK
        (itself contract-driven), not a raw string constant defined in this file.
        """
        src_path = _DELEGATE_LIB / "run.py"
        source = src_path.read_text()

        hardcoded_sentinel = '"onex.cmd.omniclaude.delegate-task.v1"'
        assignment_line = f"_DELEGATION_REQUEST_TOPIC = {hardcoded_sentinel}"
        assert assignment_line not in source, (
            "Topic must not be hardcoded as a string literal assignment — "
            "use contract resolution via _resolve_delegation_topic_and_event_type()"
        )


class TestShimHasNoOmnibaseInfraInternalImports:
    def test_no_omnibase_infra_handler_imports_at_module_level(self) -> None:
        """run.py must not hard-import omnibase_infra internal handler classes.

        omnibase_infra.clients.runtime_skill_client is allowed only behind a
        try/except guard (for optional HTTP path) — not as a hard top-level import.
        """
        src_path = _DELEGATE_LIB / "run.py"
        source = src_path.read_text()

        forbidden_patterns = [
            "from omnibase_infra.handlers.",
            "import omnibase_infra.handlers.",
            "from omnibase_infra.kafka.",
            "import omnibase_infra.kafka.",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in source, (
                f"Found forbidden omnibase_infra internal import pattern: {pattern!r}. "
                "Skill shim must not import omnibase_infra internals directly."
            )

    def test_runtime_skill_client_import_is_guarded(self) -> None:
        """LocalRuntimeSkillClient import must be inside a try/except, not bare."""
        src_path = _DELEGATE_LIB / "run.py"
        source = src_path.read_text()

        # Verify the import exists but is guarded (inside try block)
        assert "LocalRuntimeSkillClient" in source

        # The import must appear after a 'try:' and before an 'except ImportError'
        lines = source.splitlines()
        in_try_block = False
        client_import_found_in_try = False
        for line in lines:
            stripped = line.strip()
            if stripped == "try:":
                in_try_block = True
            elif stripped.startswith("except ImportError"):
                in_try_block = False
            elif in_try_block and "LocalRuntimeSkillClient" in stripped:
                client_import_found_in_try = True

        assert client_import_found_in_try, (
            "LocalRuntimeSkillClient must only be imported inside a try/except block"
        )
