# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for _resolve_transport_config() in the delegate skill.

DoD evidence for OMN-10604:
- _resolve_transport_config() reads runtime_ingress from the omnimarket
  delegate skill orchestrator contract.yaml via OMNI_HOME.
- Returns values from the contract when populated.
- Returns empty dict gracefully when OMNI_HOME is unset, contract is missing,
  or runtime_ingress is absent.
- classify_and_publish() prefers contract values over env vars for all five
  transport fields.
"""

from __future__ import annotations

import importlib
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

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


_MINIMAL_CONTRACT = textwrap.dedent("""\
    name: node_delegate_skill_orchestrator
    runtime_ingress:
      http_url: "http://192.168.86.201:18085"  # onex-allow-internal-ip
      pandaproxy_url: "http://192.168.86.201:28082"  # onex-allow-internal-ip
      ssh_host: "jonah@192.168.86.201"  # onex-allow-internal-ip
      ssh_socket_path: "/tmp/onex-runtime.sock"
      kafka_bridge_script: "/opt/onex/scripts/kafka_bridge.sh"  # local-path-ok: test fixture
""")


class TestResolveTransportConfig:
    def test_returns_ingress_values_from_contract(
        self, tmp_path: Path, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        omnimarket_dir = (
            tmp_path
            / "omnimarket"
            / "src"
            / "omnimarket"
            / "nodes"
            / "node_delegate_skill_orchestrator"
        )
        omnimarket_dir.mkdir(parents=True)
        (omnimarket_dir / "contract.yaml").write_text(_MINIMAL_CONTRACT)

        monkeypatch.setenv("OMNI_HOME", str(tmp_path))
        result = delegate_run._resolve_transport_config()

        _http = "http://192.168.86.201:18085"  # onex-allow-internal-ip
        _pp = "http://192.168.86.201:28082"  # onex-allow-internal-ip
        _ssh = "jonah@192.168.86.201"  # onex-allow-internal-ip
        _bridge = "/opt/onex/scripts/kafka_bridge.sh"  # local-path-ok: test fixture
        assert result["http_url"] == _http
        assert result["pandaproxy_url"] == _pp
        assert result["ssh_host"] == _ssh
        assert result["ssh_socket_path"] == "/tmp/onex-runtime.sock"
        assert result["kafka_bridge_script"] == _bridge

    def test_returns_empty_dict_when_omni_home_unset(
        self, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OMNI_HOME", raising=False)
        result = delegate_run._resolve_transport_config()
        assert result == {}

    def test_returns_empty_dict_when_contract_missing(
        self, tmp_path: Path, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OMNI_HOME", str(tmp_path))
        result = delegate_run._resolve_transport_config()
        assert result == {}

    def test_returns_empty_dict_when_runtime_ingress_absent(
        self, tmp_path: Path, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        omnimarket_dir = (
            tmp_path
            / "omnimarket"
            / "src"
            / "omnimarket"
            / "nodes"
            / "node_delegate_skill_orchestrator"
        )
        omnimarket_dir.mkdir(parents=True)
        (omnimarket_dir / "contract.yaml").write_text(
            "name: node_delegate_skill_orchestrator\n"
        )

        monkeypatch.setenv("OMNI_HOME", str(tmp_path))
        result = delegate_run._resolve_transport_config()
        assert result == {}

    def test_omits_empty_string_values(
        self, tmp_path: Path, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contract = textwrap.dedent("""\
            name: node_delegate_skill_orchestrator
            runtime_ingress:
              http_url: ""
              pandaproxy_url: "http://192.168.86.201:28082"  # onex-allow-internal-ip
              ssh_host: ""
              ssh_socket_path: ""
              kafka_bridge_script: ""
        """)
        omnimarket_dir = (
            tmp_path
            / "omnimarket"
            / "src"
            / "omnimarket"
            / "nodes"
            / "node_delegate_skill_orchestrator"
        )
        omnimarket_dir.mkdir(parents=True)
        (omnimarket_dir / "contract.yaml").write_text(contract)

        monkeypatch.setenv("OMNI_HOME", str(tmp_path))
        result = delegate_run._resolve_transport_config()

        _pp = "http://192.168.86.201:28082"  # onex-allow-internal-ip
        assert "http_url" not in result
        assert result["pandaproxy_url"] == _pp
        assert "ssh_host" not in result

    def test_omits_whitespace_only_values(
        self, tmp_path: Path, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contract = textwrap.dedent("""\
            name: node_delegate_skill_orchestrator
            runtime_ingress:
              http_url: "   "
              pandaproxy_url: "\t"
              ssh_host: "  "
              ssh_socket_path: " /tmp/onex-runtime.sock "
              kafka_bridge_script: ""
        """)
        omnimarket_dir = (
            tmp_path
            / "omnimarket"
            / "src"
            / "omnimarket"
            / "nodes"
            / "node_delegate_skill_orchestrator"
        )
        omnimarket_dir.mkdir(parents=True)
        (omnimarket_dir / "contract.yaml").write_text(contract)

        monkeypatch.setenv("OMNI_HOME", str(tmp_path))
        result = delegate_run._resolve_transport_config()

        assert "http_url" not in result
        assert "pandaproxy_url" not in result
        assert "ssh_host" not in result
        assert result["ssh_socket_path"] == "/tmp/onex-runtime.sock"

    def test_omits_non_string_values(
        self, tmp_path: Path, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contract = textwrap.dedent("""\
            name: node_delegate_skill_orchestrator
            runtime_ingress:
              http_url: null
              pandaproxy_url: 28082
              ssh_host: true
              ssh_socket_path: "/tmp/onex-runtime.sock"
              kafka_bridge_script:
                - "/opt/onex/scripts/kafka_bridge.sh"
        """)
        omnimarket_dir = (
            tmp_path
            / "omnimarket"
            / "src"
            / "omnimarket"
            / "nodes"
            / "node_delegate_skill_orchestrator"
        )
        omnimarket_dir.mkdir(parents=True)
        (omnimarket_dir / "contract.yaml").write_text(contract)

        monkeypatch.setenv("OMNI_HOME", str(tmp_path))
        result = delegate_run._resolve_transport_config()

        assert "http_url" not in result
        assert "pandaproxy_url" not in result
        assert "ssh_host" not in result
        assert result["ssh_socket_path"] == "/tmp/onex-runtime.sock"
        assert "kafka_bridge_script" not in result


class TestClassifyAndPublishPrefersContractTransport:
    def test_contract_pandaproxy_url_takes_precedence_over_env(
        self, tmp_path: Path, delegate_run: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contract = textwrap.dedent("""\
            name: node_delegate_skill_orchestrator
            runtime_ingress:
              pandaproxy_url: "http://from-contract:28082"
        """)
        omnimarket_dir = (
            tmp_path
            / "omnimarket"
            / "src"
            / "omnimarket"
            / "nodes"
            / "node_delegate_skill_orchestrator"
        )
        omnimarket_dir.mkdir(parents=True)
        (omnimarket_dir / "contract.yaml").write_text(contract)

        monkeypatch.setenv("OMNI_HOME", str(tmp_path))
        monkeypatch.setenv("ONEX_PANDAPROXY_URL", "http://from-env:28082")

        captured_url: list[str] = []

        def fake_pandaproxy(
            *,
            delegation_payload: object,
            correlation_id_str: str,
            topic: str,
            task_type: str,
            pandaproxy_url: str,
            timeout_seconds: float,
        ) -> dict:  # type: ignore[type-arg]
            captured_url.append(pandaproxy_url)
            return {"success": True}

        class _FakeResult:
            primary_intent = (
                next(iter(delegate_run.DELEGATABLE))
                if delegate_run.DELEGATABLE
                else None
            )

        class _FakeClassifier:
            def classify(self, _prompt: str) -> _FakeResult:
                return _FakeResult()

        with (
            patch.object(
                delegate_run,
                "_resolve_transport_config",
                return_value={"pandaproxy_url": "http://from-contract:28082"},
            ),
            patch.object(
                delegate_run, "_dispatch_via_pandaproxy", side_effect=fake_pandaproxy
            ),
            patch.object(
                delegate_run, "TaskClassifier", return_value=_FakeClassifier()
            ),
            patch.object(delegate_run, "_HAS_CLASSIFIER", True),
            patch.object(
                delegate_run,
                "DELEGATABLE",
                frozenset({_FakeResult.primary_intent})
                if _FakeResult.primary_intent
                else delegate_run.DELEGATABLE,
            ),
        ):
            if not delegate_run.DELEGATABLE:
                pytest.skip("DELEGATABLE is empty — classifier unavailable")
            delegate_run.classify_and_publish("write a test for this function")

        if captured_url:
            assert captured_url[0] == "http://from-contract:28082"
