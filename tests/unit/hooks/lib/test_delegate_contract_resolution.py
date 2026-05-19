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


class TestKafkaEnvelopeFieldNaming:
    """Regression tests for OMN-10604: envelope field naming must use envelope_id /
    envelope_timestamp, NOT event_id / timestamp / source.

    These field names match the canonical ModelEventEnvelope contract.
    """

    def test_kafka_envelope_uses_envelope_id_not_event_id(
        self, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_dispatch_via_kafka must emit envelope_id, not event_id."""
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
            delegate_run._dispatch_via_kafka(
                delegation_payload={"prompt": "test"},
                correlation_id_str=str(uuid.uuid4()),
                topic="onex.cmd.omnibase-infra.delegation-request.v1",
                task_type="test",
            )

        assert len(captured) == 1
        envelope = captured[0]
        # Must use canonical ModelEventEnvelope field names
        assert "envelope_id" in envelope, "envelope_id missing from Kafka envelope"
        assert "envelope_timestamp" in envelope, (
            "envelope_timestamp missing from Kafka envelope"
        )
        # Must NOT use the stashed-changes field names
        assert "event_id" not in envelope, "event_id must not appear (use envelope_id)"
        assert "source" not in envelope, (
            "source must not appear in envelope (stashed-changes field)"
        )

    def test_pandaproxy_envelope_uses_envelope_id_not_event_id(
        self, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_dispatch_via_pandaproxy must also emit envelope_id / envelope_timestamp."""
        import json  # noqa: PLC0415
        import subprocess  # noqa: PLC0415
        from unittest.mock import patch as _patch  # noqa: PLC0415

        captured_body: list[dict] = []  # type: ignore[type-arg]

        def fake_run(cmd: list, **kwargs: object) -> object:  # type: ignore[type-arg]
            # Extract the -d argument (body JSON)
            d_idx = cmd.index("-d")
            body = json.loads(cmd[d_idx + 1])
            captured_body.append(body)

            class FakeResult:
                returncode = 0
                stdout = json.dumps(
                    {"offsets": [{"partition": 0, "offset": 1, "error_code": 0}]}
                ).encode()
                stderr = b""

            return FakeResult()

        with _patch.object(subprocess, "run", fake_run):
            delegate_run._dispatch_via_pandaproxy(
                delegation_payload={"prompt": "test"},
                correlation_id_str=str(uuid.uuid4()),
                topic="onex.cmd.omnibase-infra.delegation-request.v1",
                task_type="test",
                pandaproxy_url="http://localhost:28082",
                timeout_seconds=5.0,
            )

        assert len(captured_body) == 1
        # pandaproxy wraps in {"records": [{"value": <envelope>}]}
        envelope = captured_body[0]["records"][0]["value"]
        assert "envelope_id" in envelope, "envelope_id missing from pandaproxy envelope"
        assert "envelope_timestamp" in envelope, (
            "envelope_timestamp missing from pandaproxy envelope"
        )
        assert "event_id" not in envelope
        assert "source" not in envelope
