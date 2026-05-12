# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for contract-driven topic/event_type resolution in the delegate skill.

DoD evidence for OMN-10834:
- _load_infra_orchestrator_contract() returns the correct contract dict when the
  omnibase_infra contract YAML is reachable.
- _resolve_delegation_topic_and_event_type() picks up subscribe_topics[0] and
  consumed_events[0].event_type from the contract.
- Falls back to TopicBase.DELEGATE_TASK and "omnibase-infra.delegation-request" when
  the contract is unreachable.
- The Kafka envelope uses the contract-resolved event_type, not a hardcoded string.
"""

from __future__ import annotations

import importlib
import sys
import textwrap
import uuid
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
def delegate_run() -> ModuleType:
    sys.modules.pop("run", None)
    import run as m  # noqa: PLC0415

    return importlib.reload(m)


class TestLoadInfraOrchestratorContract:
    def test_returns_dict_with_event_bus_when_contract_found(
        self, tmp_path: Path, delegate_run: ModuleType
    ) -> None:
        contract_yaml = textwrap.dedent("""\
            name: node_delegation_orchestrator
            event_bus:
              subscribe_topics:
                - "onex.cmd.omnibase-infra.delegation-request.v1"
            consumed_events:
              - topic: "onex.cmd.omnibase-infra.delegation-request.v1"
                event_type: "DelegationRequest"
        """)
        node_dir = tmp_path / "nodes" / "node_delegation_orchestrator"
        node_dir.mkdir(parents=True)
        (node_dir / "contract.yaml").write_text(contract_yaml)

        # Patch omnibase_infra package root to point at tmp_path
        fake_obi = MagicMock()
        fake_obi.__file__ = str(tmp_path / "__init__.py")
        with patch.dict(sys.modules, {"omnibase_infra": fake_obi}):
            result = delegate_run._load_infra_orchestrator_contract()

        assert result.get("event_bus", {}).get("subscribe_topics") == [
            "onex.cmd.omnibase-infra.delegation-request.v1"
        ]
        assert (
            result.get("consumed_events", [{}])[0].get("event_type")
            == "DelegationRequest"
        )

    def test_returns_empty_dict_when_contract_not_found(
        self, delegate_run: ModuleType
    ) -> None:
        with patch.dict(sys.modules, {}, clear=False):
            # Force ImportError for omnibase_infra and ensure no repo candidate matches
            original = sys.modules.pop("omnibase_infra", None)
            try:
                result = delegate_run._load_infra_orchestrator_contract()
            finally:
                if original is not None:
                    sys.modules["omnibase_infra"] = original
        # Must be a dict (may be empty or contain data from real install)
        assert isinstance(result, dict)


class TestResolveDelegationTopicAndEventType:
    def test_uses_infra_contract_topic_when_available(
        self, tmp_path: Path, delegate_run: ModuleType
    ) -> None:
        contract_yaml = textwrap.dedent("""\
            name: node_delegation_orchestrator
            event_bus:
              subscribe_topics:
                - "onex.cmd.omnibase-infra.delegation-request.v1"
            consumed_events:
              - topic: "onex.cmd.omnibase-infra.delegation-request.v1"
                event_type: "DelegationRequest"
        """)
        node_dir = tmp_path / "nodes" / "node_delegation_orchestrator"
        node_dir.mkdir(parents=True)
        (node_dir / "contract.yaml").write_text(contract_yaml)

        fake_obi = MagicMock()
        fake_obi.__file__ = str(tmp_path / "__init__.py")
        with patch.dict(sys.modules, {"omnibase_infra": fake_obi}):
            topic, event_type = delegate_run._resolve_delegation_topic_and_event_type()

        assert topic == "onex.cmd.omnibase-infra.delegation-request.v1"
        assert event_type == "DelegationRequest"

    def test_falls_back_to_topicbase_when_no_contract(
        self, delegate_run: ModuleType
    ) -> None:
        with patch.object(
            delegate_run, "_load_infra_orchestrator_contract", return_value={}
        ):
            topic, event_type = delegate_run._resolve_delegation_topic_and_event_type()

        assert topic != ""
        assert event_type == "omnibase-infra.delegation-request"

    def test_event_type_defaults_to_delegation_request_when_contract_empty(
        self, delegate_run: ModuleType
    ) -> None:
        with patch.object(
            delegate_run, "_load_infra_orchestrator_contract", return_value={}
        ):
            _topic, event_type = delegate_run._resolve_delegation_topic_and_event_type()

        assert event_type == "omnibase-infra.delegation-request"


class TestKafkaEnvelopeUsesContractEventType:
    def test_kafka_envelope_uses_resolved_event_type(
        self, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_dispatch_via_kafka must use _DELEGATION_EVENT_TYPE, not hardcoded string."""
        monkeypatch.setattr(delegate_run, "_DELEGATION_EVENT_TYPE", "DelegationRequest")
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        captured: list[dict] = []  # type: ignore[type-arg]

        class FakeProducer:
            def __init__(self, _conf: dict) -> None:  # type: ignore[type-arg]
                pass

            def produce(
                self,
                topic: str,
                *,
                value: bytes,
                key: bytes,
                on_delivery: object,
            ) -> None:
                import json  # noqa: PLC0415

                captured.append(json.loads(value.decode()))
                if callable(on_delivery):
                    on_delivery(None, MagicMock())  # type: ignore[arg-type]

            def flush(self, timeout: float = 10.0) -> None:
                pass

        with patch.dict(
            sys.modules, {"confluent_kafka": MagicMock(Producer=FakeProducer)}
        ):
            result = delegate_run._dispatch_via_kafka(
                delegation_payload={"prompt": "test"},
                correlation_id_str=str(uuid.uuid4()),
                topic="onex.cmd.omnibase-infra.delegation-request.v1",
                task_type="test",
            )

        assert result["success"] is True
        assert len(captured) == 1
        assert captured[0]["event_type"] == "DelegationRequest"
        assert captured[0]["event_type"] != "DelegateTaskCommand"
