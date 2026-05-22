# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for contract-driven command-topic resolution in the delegate skill.

DoD evidence for OMN-10604:
- _resolve_command_topic() reads the delegate skill orchestrator subscribe topic
  from the omnimarket contract rooted at OMNI_HOME.
- Missing OMNI_HOME or missing contract produces an empty topic so runtime
  dispatch can fail explicitly instead of silently falling back.
- Kafka envelopes use the runtime-owned delegate skill event type.
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
    sys.modules.pop("handler_delegate_skill", None)
    import handler_delegate_skill as m  # noqa: PLC0415

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


class TestKafkaEnvelopeUsesContractEventType:
    def test_kafka_envelope_uses_resolved_event_type(
        self, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_dispatch_via_kafka must use the runtime-owned delegate skill event type."""
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
                topic="onex.cmd.omnimarket.delegate-skill.v1",
                task_type="test",
            )

        assert result["success"] is True
        assert len(captured) == 1
        assert captured[0]["event_type"] == "omnimarket.delegate-skill"
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
