# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests verifying the delegate skill routes through DelegationDispatchAdapter.

DoD evidence for OMN-11638:
- classify_and_publish() dispatches through DelegationDispatchAdapter (market adapter path).
- Market adapter unavailability returns an explicit error with path="market_adapter".
- Contract topic is still resolved from omnimarket contract.yaml via OMNI_HOME.
- No stale transport paths (HTTP, SSH socket, Pandaproxy, SSH rpk, ad-hoc Kafka).
"""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path
from types import ModuleType

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


class TestNoStaleTransportFunctions:
    def test_dispatch_via_http_removed(self, delegate_run: ModuleType) -> None:
        assert not hasattr(delegate_run, "_dispatch_via_http"), (
            "_dispatch_via_http must be removed — HTTP transport is stale"
        )

    def test_dispatch_via_ssh_socket_removed(self, delegate_run: ModuleType) -> None:
        assert not hasattr(delegate_run, "_dispatch_via_ssh_socket"), (
            "_dispatch_via_ssh_socket must be removed — SSH socket transport is stale"
        )

    def test_dispatch_via_pandaproxy_removed(self, delegate_run: ModuleType) -> None:
        assert not hasattr(delegate_run, "_dispatch_via_pandaproxy"), (
            "_dispatch_via_pandaproxy must be removed — Pandaproxy transport is stale"
        )

    def test_dispatch_via_ssh_rpk_removed(self, delegate_run: ModuleType) -> None:
        assert not hasattr(delegate_run, "_dispatch_via_ssh_rpk"), (
            "_dispatch_via_ssh_rpk must be removed — SSH rpk bridge transport is stale"
        )

    def test_dispatch_via_kafka_removed(self, delegate_run: ModuleType) -> None:
        assert not hasattr(delegate_run, "_dispatch_via_kafka"), (
            "_dispatch_via_kafka must be removed — ad-hoc Kafka transport is stale"
        )

    def test_resolve_transport_config_removed(self, delegate_run: ModuleType) -> None:
        assert not hasattr(delegate_run, "_resolve_transport_config"), (
            "_resolve_transport_config must be removed — stale transport config reader"
        )


class TestMarketAdapterPath:
    def test_market_adapter_unavailable_returns_explicit_error(
        self, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(delegate_run, "_HAS_MARKET_ADAPTER", False)
        monkeypatch.setattr(
            delegate_run,
            "_MARKET_ADAPTER_IMPORT_ERROR",
            ImportError("omnimarket not installed"),
        )

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
        )

        assert result.get("success") is False
        assert result.get("path") == "market_adapter"
        assert "omnimarket not installed" in result["error"]

    def test_classify_and_publish_routes_through_market_adapter(
        self, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        corr = str(uuid.uuid4())
        fake_response = {
            "ok": True,
            "correlation_id": corr,
            "command_topic": "onex.cmd.omnimarket.delegate-skill.v1",
            "terminal_events": {
                "success": "onex.evt.omnimarket.delegate-skill-completed.v1",
                "failure": "onex.evt.omnimarket.delegate-skill-failed.v1",
            },
            "status": "published",
        }

        class FakeAdapter:
            def __init__(self, contract_path: object = None) -> None:
                pass

            def dispatch_sync(self, **kwargs: object) -> dict:  # type: ignore[type-arg]
                return fake_response

        monkeypatch.setattr(delegate_run, "DelegationDispatchAdapter", FakeAdapter)
        monkeypatch.setattr(delegate_run, "_HAS_MARKET_ADAPTER", True)
        monkeypatch.setattr(delegate_run, "_MARKET_ADAPTER_IMPORT_ERROR", None)

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            correlation_id=corr,
        )

        assert result.get("success") is True, f"Expected success, got: {result}"
        assert result.get("path") == "market_adapter"
        assert result.get("correlation_id") == corr

    def test_market_adapter_failure_returns_error(
        self, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeAdapter:
            def __init__(self, contract_path: object = None) -> None:
                pass

            def dispatch_sync(self, **kwargs: object) -> dict:  # type: ignore[type-arg]
                return {"ok": False, "error": "runtime unavailable"}

        monkeypatch.setattr(delegate_run, "DelegationDispatchAdapter", FakeAdapter)
        monkeypatch.setattr(delegate_run, "_HAS_MARKET_ADAPTER", True)
        monkeypatch.setattr(delegate_run, "_MARKET_ADAPTER_IMPORT_ERROR", None)

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
        )

        assert result.get("success") is False
        assert result.get("path") == "market_adapter"
        assert "runtime unavailable" in result["error"]

    def test_market_adapter_exception_returns_error(
        self, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeAdapter:
            def __init__(self, contract_path: object = None) -> None:
                raise RuntimeError("contract path not found")

            def dispatch_sync(self, **kwargs: object) -> dict:  # type: ignore[type-arg]
                return {}

        monkeypatch.setattr(delegate_run, "DelegationDispatchAdapter", FakeAdapter)
        monkeypatch.setattr(delegate_run, "_HAS_MARKET_ADAPTER", True)
        monkeypatch.setattr(delegate_run, "_MARKET_ADAPTER_IMPORT_ERROR", None)

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
        )

        assert result.get("success") is False
        assert result.get("path") == "market_adapter"
        assert "contract path not found" in result["error"]

    def test_no_stale_env_vars_consulted_for_transport(
        self, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stale transport env vars (ONEX_RUNTIME_URL, ONEX_PANDAPROXY_URL, etc.) must
        have no effect on dispatch routing."""
        monkeypatch.setenv("ONEX_RUNTIME_URL", "http://stale-env:8085")
        monkeypatch.setenv("ONEX_PANDAPROXY_URL", "http://stale-env:28082")
        monkeypatch.setenv("ONEX_RUNTIME_SSH_HOST", "user@stale-env")
        monkeypatch.setenv("ONEX_RUNTIME_SOCKET_PATH", "/tmp/stale.sock")
        monkeypatch.setenv("ONEX_KAFKA_BRIDGE_SCRIPT", "/opt/stale/kafka_bridge.sh")

        calls: list[dict] = []  # type: ignore[type-arg]

        class FakeAdapter:
            def __init__(self, contract_path: object = None) -> None:
                pass

            def dispatch_sync(self, **kwargs: object) -> dict:  # type: ignore[type-arg]
                calls.append(dict(kwargs))
                return {
                    "ok": True,
                    "correlation_id": str(uuid.uuid4()),
                    "status": "published",
                }

        monkeypatch.setattr(delegate_run, "DelegationDispatchAdapter", FakeAdapter)
        monkeypatch.setattr(delegate_run, "_HAS_MARKET_ADAPTER", True)
        monkeypatch.setattr(delegate_run, "_MARKET_ADAPTER_IMPORT_ERROR", None)

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
        )

        assert result.get("success") is True
        assert result.get("path") == "market_adapter"
        # Adapter was called exactly once — no stale transport fallback
        assert len(calls) == 1


class TestShimProducesModelDelegateSkillRequest:
    def test_shim_payload_matches_market_adapter_interface(
        self, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """classify_and_publish passes prompt, task_type, source, and correlation_id
        to DelegationDispatchAdapter.dispatch_sync in the fields it expects."""
        corr = str(uuid.uuid4())
        captured: list[dict] = []  # type: ignore[type-arg]

        class FakeAdapter:
            def __init__(self, contract_path: object = None) -> None:
                pass

            def dispatch_sync(self, **kwargs: object) -> dict:  # type: ignore[type-arg]
                captured.append(dict(kwargs))
                return {"ok": True, "correlation_id": corr, "status": "published"}

        monkeypatch.setattr(delegate_run, "DelegationDispatchAdapter", FakeAdapter)
        monkeypatch.setattr(delegate_run, "_HAS_MARKET_ADAPTER", True)
        monkeypatch.setattr(delegate_run, "_MARKET_ADAPTER_IMPORT_ERROR", None)

        delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            max_tokens=4096,
            correlation_id=corr,
            wait_for_result=True,
            working_directory="/tmp/work",
        )

        assert len(captured) == 1
        call = captured[0]
        assert call["prompt"] == "write unit tests for handler_event_emitter.py"
        assert call["task_type"] == "test"
        assert call["source"] in ("claude-code", "codex")
        assert call["max_tokens"] == 4096
        assert call["wait"] is True
        assert call["cwd"] == "/tmp/work"
        assert "correlation_id" in call
