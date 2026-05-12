# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for merge_sweep/_lib/run.py runtime ingress dispatch."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_OMNICLAUDE_ROOT = Path(__file__).resolve().parents[4]
_LIB_RUN = (
    _OMNICLAUDE_ROOT / "plugins" / "onex" / "skills" / "merge_sweep" / "_lib" / "run.py"
)
_OMNI_HOME = _OMNICLAUDE_ROOT.parent
_OMNIMARKET_CONTRACT = (
    _OMNI_HOME
    / "omnimarket"
    / "src"
    / "omnimarket"
    / "nodes"
    / "node_pr_lifecycle_orchestrator"
    / "contract.yaml"
)
_EXPECTED_TOPIC = "onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1"


def _import_lib_run():
    """Import _lib/run.py via importlib to avoid sys.path pollution."""
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("merge_sweep_run", _LIB_RUN)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.mark.unit
def test_lib_run_file_exists() -> None:
    """_lib/run.py must exist as a real file."""
    assert _LIB_RUN.is_file(), f"missing _lib/run.py at {_LIB_RUN}"


@pytest.mark.unit
def test_resolve_command_topic_reads_from_contract(monkeypatch) -> None:
    """_resolve_command_topic() must return the subscribe topic from contract.yaml."""
    if not _OMNIMARKET_CONTRACT.is_file():
        pytest.skip(f"omnimarket contract not found at {_OMNIMARKET_CONTRACT}")

    mod = _import_lib_run()
    monkeypatch.setenv("OMNI_HOME", str(_OMNI_HOME))

    topic = mod._resolve_command_topic()
    assert topic == _EXPECTED_TOPIC, (
        f"Expected {_EXPECTED_TOPIC!r}, got {topic!r} — "
        "contract.yaml event_bus.subscribe_topics may have changed"
    )


@pytest.mark.unit
def test_resolve_command_topic_returns_empty_without_omni_home(monkeypatch) -> None:
    """_resolve_command_topic() must return empty string when OMNI_HOME is unset."""
    mod = _import_lib_run()
    monkeypatch.delenv("OMNI_HOME", raising=False)

    topic = mod._resolve_command_topic()
    assert topic == ""


@pytest.mark.unit
def test_dispatch_merge_sweep_kafka_missing_bootstrap(monkeypatch) -> None:
    """When KAFKA_BOOTSTRAP_SERVERS is unset and no SSH/HTTP transports are set,
    dispatch fails with a clear error rather than silently dropping."""
    mod = _import_lib_run()
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    monkeypatch.delenv("ONEX_RUNTIME_SSH_HOST", raising=False)
    monkeypatch.delenv("ONEX_RUNTIME_SOCKET_PATH", raising=False)
    monkeypatch.delenv("ONEX_RUNTIME_URL", raising=False)
    monkeypatch.setattr(mod, "_resolve_command_topic", lambda: _EXPECTED_TOPIC)

    result = mod.dispatch_merge_sweep(
        run_id="test-run",
        dry_run=True,
    )
    assert result["success"] is False
    assert "KAFKA_BOOTSTRAP_SERVERS" in result["error"]
    assert result["path"] == "kafka"


@pytest.mark.unit
def test_dispatch_merge_sweep_http_dispatches_correct_payload(monkeypatch) -> None:
    """HTTP transport must send node_pr_lifecycle_orchestrator with the correct payload."""
    mod = _import_lib_run()
    monkeypatch.delenv("ONEX_RUNTIME_SSH_HOST", raising=False)
    monkeypatch.delenv("ONEX_RUNTIME_SOCKET_PATH", raising=False)
    monkeypatch.setenv("ONEX_RUNTIME_URL", "http://runtime.test:8085")
    monkeypatch.setattr(mod, "_resolve_command_topic", lambda: _EXPECTED_TOPIC)

    captured: list[dict] = []

    def fake_dispatch_via_http(request, runtime_url, timeout_seconds):
        captured.append(
            {
                "command_name": request.command_name,
                "payload": dict(request.payload),
                "runtime_url": runtime_url,
            }
        )
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.correlation_id = uuid.UUID(request.payload["correlation_id"])
        mock_resp.command_name = request.command_name
        mock_resp.command_topic = _EXPECTED_TOPIC
        mock_resp.terminal_event = (
            "onex.evt.omnimarket.pr-lifecycle-orchestrator-completed.v1"
        )
        mock_resp.dispatch_result = MagicMock(status="dispatched")
        mock_resp.output_payloads = None
        return mock_resp

    monkeypatch.setattr(mod, "_dispatch_via_http", fake_dispatch_via_http)

    result = mod.dispatch_merge_sweep(
        run_id="http-test-run",
        dry_run=True,
        inventory_only=True,
        repos="OmniNode-ai/omniclaude",
        max_parallel_polish=5,
    )

    assert result["success"] is True
    assert result["path"] == "http"
    assert len(captured) == 1

    req = captured[0]
    assert req["command_name"] == "node_pr_lifecycle_orchestrator"
    assert req["runtime_url"] == "http://runtime.test:8085"
    p = req["payload"]
    assert p["run_id"] == "http-test-run"
    assert p["dry_run"] is True
    assert p["inventory_only"] is True
    assert p["repos"] == "OmniNode-ai/omniclaude"
    assert p["max_parallel_polish"] == 5


@pytest.mark.unit
def test_dispatch_merge_sweep_kafka_publishes_correct_envelope(monkeypatch) -> None:
    """Kafka transport must publish to the contract-resolved topic."""
    mod = _import_lib_run()
    monkeypatch.delenv("ONEX_RUNTIME_SSH_HOST", raising=False)
    monkeypatch.delenv("ONEX_RUNTIME_SOCKET_PATH", raising=False)
    monkeypatch.delenv("ONEX_RUNTIME_URL", raising=False)
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-test-broker:9092")
    monkeypatch.setattr(mod, "_resolve_command_topic", lambda: _EXPECTED_TOPIC)

    published: list[dict] = []

    def fake_kafka_dispatch(payload, correlation_id_str, topic):
        published.append(
            {"payload": payload, "correlation_id": correlation_id_str, "topic": topic}
        )
        return {
            "success": True,
            "correlation_id": correlation_id_str,
            "topic": topic,
            "path": "kafka",
            "dispatch_status": "published",
        }

    monkeypatch.setattr(mod, "_dispatch_via_kafka", fake_kafka_dispatch)

    result = mod.dispatch_merge_sweep(
        run_id="kafka-test-run",
        merge_only=True,
        enable_admin_merge_fallback=False,
    )

    assert result["success"] is True
    assert result["path"] == "kafka"
    assert len(published) == 1

    pub = published[0]
    assert pub["topic"] == _EXPECTED_TOPIC
    p = pub["payload"]
    assert p["run_id"] == "kafka-test-run"
    assert p["merge_only"] is True
    assert p["enable_admin_merge_fallback"] is False


@pytest.mark.unit
def test_dispatch_merge_sweep_kafka_fails_when_topic_unresolvable(monkeypatch) -> None:
    """When contract.yaml is not found (OMNI_HOME unset), Kafka dispatch returns a clear error."""
    mod = _import_lib_run()
    monkeypatch.delenv("ONEX_RUNTIME_SSH_HOST", raising=False)
    monkeypatch.delenv("ONEX_RUNTIME_SOCKET_PATH", raising=False)
    monkeypatch.delenv("ONEX_RUNTIME_URL", raising=False)
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-test-broker:9092")
    monkeypatch.setattr(mod, "_resolve_command_topic", lambda: "")

    result = mod.dispatch_merge_sweep(run_id="no-topic-run")
    assert result["success"] is False
    assert "contract.yaml" in result["error"] or "OMNI_HOME" in result["error"]


@pytest.mark.unit
def test_run_sh_is_thin_wrapper() -> None:
    """run.sh must delegate to _lib/run.py and not invoke onex run-node as a command."""
    run_sh = _LIB_RUN.parent.parent / "run.sh"
    assert run_sh.is_file()
    content = run_sh.read_text(encoding="utf-8")

    non_comment_lines = [
        line for line in content.splitlines() if not line.strip().startswith("#")
    ]
    non_comment_body = "\n".join(non_comment_lines)
    assert "onex run-node" not in non_comment_body, (
        "run.sh must not call onex run-node directly — delegate to _lib/run.py"
    )
    assert "_lib/run.py" in content, "run.sh must delegate to _lib/run.py"
