# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for contract-driven Kafka delegation transport (OMN-10834).

Covers:
  - _dispatch_via_kafka fails fast when KAFKA_BOOTSTRAP_SERVERS is unset
  - _dispatch_via_kafka returns success when producer delivers message
  - _dispatch_via_kafka returns error when delivery callback reports failure
  - delegation __init__ no longer exports transport.py symbols
"""

from __future__ import annotations

import sys
import types

# ---------------------------------------------------------------------------
# Helpers — path setup mirrors run.py's own sys.path manipulation
# ---------------------------------------------------------------------------
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SKILL_LIB = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "delegate"
    / "_lib"
)
if str(_SKILL_LIB) not in sys.path:
    sys.path.insert(0, str(_SKILL_LIB))


def _import_dispatch_via_kafka():  # type: ignore[return]
    import importlib

    import run as _run_mod

    importlib.reload(_run_mod)
    return _run_mod._dispatch_via_kafka  # noqa: SLF001


# ---------------------------------------------------------------------------
# KAFKA_BOOTSTRAP_SERVERS missing → fail fast
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_kafka_transport_missing_bootstrap_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    fn = _import_dispatch_via_kafka()
    result = fn(
        delegation_payload={"prompt": "write tests"},
        correlation_id_str="test-cid-001",
        topic="onex.cmd.omniclaude.delegate-task.v1",
    )
    assert result["success"] is False
    assert "KAFKA_BOOTSTRAP_SERVERS" in result["error"]
    assert result["path"] == "kafka"


# ---------------------------------------------------------------------------
# confluent_kafka not installed → clear error
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_kafka_transport_confluent_kafka_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
    # Temporarily hide confluent_kafka so import fails
    original = sys.modules.get("confluent_kafka")
    sys.modules["confluent_kafka"] = None  # type: ignore[assignment]
    try:
        fn = _import_dispatch_via_kafka()
        result = fn(
            delegation_payload={"prompt": "write tests"},
            correlation_id_str="test-cid-002",
            topic="onex.cmd.omniclaude.delegate-task.v1",
        )
        assert result["success"] is False
        assert "confluent_kafka" in result["error"]
        assert result["path"] == "kafka"
    finally:
        if original is None:
            sys.modules.pop("confluent_kafka", None)
        else:
            sys.modules["confluent_kafka"] = original


# ---------------------------------------------------------------------------
# Successful delivery → success result
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_kafka_transport_successful_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")

    mock_producer = MagicMock()

    def _fake_produce(topic: str, value: bytes, key: bytes, on_delivery) -> None:  # type: ignore[type-arg]
        on_delivery(None, MagicMock())  # err=None → success

    mock_producer.produce = _fake_produce
    mock_producer.flush = MagicMock(return_value=0)

    fake_confluent = types.ModuleType("confluent_kafka")
    fake_confluent.Producer = MagicMock(return_value=mock_producer)  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {"confluent_kafka": fake_confluent}):
        fn = _import_dispatch_via_kafka()
        result = fn(
            delegation_payload={"prompt": "write tests for OMN-10834"},
            correlation_id_str="test-cid-003",
            topic="onex.cmd.omniclaude.delegate-task.v1",
        )

    assert result["success"] is True
    assert result["correlation_id"] == "test-cid-003"
    assert result["topic"] == "onex.cmd.omniclaude.delegate-task.v1"
    assert result["path"] == "kafka"
    assert result["dispatch_status"] == "published"


# ---------------------------------------------------------------------------
# Delivery callback reports error → failure result
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_kafka_transport_delivery_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")

    mock_producer = MagicMock()

    def _fake_produce(topic: str, value: bytes, key: bytes, on_delivery) -> None:  # type: ignore[type-arg]
        on_delivery("broker not available", MagicMock())

    mock_producer.produce = _fake_produce
    mock_producer.flush = MagicMock(return_value=0)

    fake_confluent = types.ModuleType("confluent_kafka")
    fake_confluent.Producer = MagicMock(return_value=mock_producer)  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {"confluent_kafka": fake_confluent}):
        fn = _import_dispatch_via_kafka()
        result = fn(
            delegation_payload={"prompt": "write tests"},
            correlation_id_str="test-cid-004",
            topic="onex.cmd.omniclaude.delegate-task.v1",
        )

    assert result["success"] is False
    assert "broker not available" in result["error"]
    assert result["path"] == "kafka"


# ---------------------------------------------------------------------------
# flush timeout (no delivery callback fired) → failure result
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_kafka_transport_flush_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")

    mock_producer = MagicMock()

    def _fake_produce_no_callback(
        topic: str, value: bytes, key: bytes, on_delivery
    ) -> None:  # type: ignore[type-arg]
        pass  # delivery callback never called — simulates flush timeout

    mock_producer.produce = _fake_produce_no_callback
    mock_producer.flush = MagicMock(return_value=1)  # 1 = messages still pending

    fake_confluent = types.ModuleType("confluent_kafka")
    fake_confluent.Producer = MagicMock(return_value=mock_producer)  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {"confluent_kafka": fake_confluent}):
        fn = _import_dispatch_via_kafka()
        result = fn(
            delegation_payload={"prompt": "write tests"},
            correlation_id_str="test-cid-005",
            topic="onex.cmd.omniclaude.delegate-task.v1",
        )

    assert result["success"] is False
    assert "timed out" in result["error"]
    assert result["path"] == "kafka"


# ---------------------------------------------------------------------------
# delegation __init__ no longer exports transport.py symbols
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_delegation_package_no_socket_transport_exports() -> None:
    # Check the __init__.py source directly rather than importing the package
    # (importing triggers omnimarket transitive dep not available in unit env).
    init_src = (
        Path(__file__).parent.parent.parent
        / "src"
        / "omniclaude"
        / "delegation"
        / "__init__.py"
    ).read_text()

    for symbol in (
        "EnumDelegationTransport",
        "DelegationTransportSelector",
        "get_delegation_transport",
        "is_daemon_available",
        "daemon_fallback",
        "transport",
    ):
        assert symbol not in init_src, (
            f"omniclaude/delegation/__init__.py should no longer reference {symbol!r} "
            "(transport.py and daemon_fallback.py deleted in OMN-10834)"
        )
