# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for contract-driven local endpoint resolution (OMN-17103).

The registry these replace read ``LLM_CODER_URL`` / ``LLM_DEEPSEEK_R1_URL`` /
``LLM_GLM_URL``. The resolver reads the endpoint variable the canonical bifrost
contract names for each local backend, and nothing else.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from omniclaude.enums.enum_contract_capability import EnumContractCapability
from omniclaude.handlers.handler_contract_endpoint_resolver import (
    HandlerContractEndpointResolver,
    canonical_contract_path,
)
from omniclaude.models.model_contract_endpoint import base_url_of

_CODER_ENV = "BIFROST_LOCAL_CODER_ENDPOINT_URL"
_CHAT_URL = "http://lab-host:8000/v1/chat/completions"


@pytest.fixture
def contract(tmp_path: Path) -> Path:
    path = tmp_path / "bifrost.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "backends": [
                    {
                        "backend_id": "local-coder",
                        "provider": "local",
                        "endpoint_url_env": _CODER_ENV,
                        "capabilities": ["code_generation", "documentation"],
                    },
                    {
                        "backend_id": "local-heavy-reasoning",
                        "provider": "local",
                        "endpoint_url_env": _CODER_ENV,
                        "capabilities": ["reasoning", "classification"],
                    },
                    {
                        "backend_id": "pinned-local",
                        "provider": "local",
                        "explicit_pin_only": True,
                        "endpoint_url": "http://pinned:1/v1/chat/completions",
                        "model_name": "pinned-model",
                        "capabilities": ["reasoning"],
                    },
                    {
                        "backend_id": "cloud-glm",
                        "provider": "glm",
                        "endpoint_url": "https://api.example/v1/chat/completions",
                        "model_name": "glm-x",
                        "capabilities": ["code_generation"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_CODER_ENV, raising=False)
    monkeypatch.delenv("LLM_CODER_MODEL_NAME", raising=False)


@pytest.mark.unit
def test_resolves_url_and_model_from_the_variables_the_contract_names(
    contract: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_CODER_ENV, _CHAT_URL)
    monkeypatch.setenv("LLM_CODER_MODEL_NAME", "coder-model")
    endpoint = HandlerContractEndpointResolver(contract).resolve(
        EnumContractCapability.CODE_GENERATION
    )
    assert endpoint is not None
    assert endpoint.backend_id == "local-coder"
    assert endpoint.url == _CHAT_URL
    assert endpoint.model_name == "coder-model"
    assert endpoint.base_url == "http://lab-host:8000"


@pytest.mark.unit
def test_legacy_registry_variables_are_not_read(
    contract: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_CODER_URL", "http://legacy:8000")
    monkeypatch.setenv("LLM_DEEPSEEK_R1_URL", "http://legacy:8101")
    monkeypatch.setenv("LLM_GLM_URL", "http://legacy:9")
    monkeypatch.setenv("LLM_CODER_MODEL_NAME", "coder-model")
    resolver = HandlerContractEndpointResolver(contract)
    assert resolver.resolve(EnumContractCapability.CODE_GENERATION) is None
    assert resolver.resolve(EnumContractCapability.REASONING) is None


@pytest.mark.unit
def test_unset_variable_or_model_resolves_nothing(
    contract: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = HandlerContractEndpointResolver(contract)
    assert resolver.resolve(EnumContractCapability.CODE_GENERATION) is None
    monkeypatch.setenv(_CODER_ENV, _CHAT_URL)  # URL set, model id still unset
    assert resolver.resolve(EnumContractCapability.CODE_GENERATION) is None


@pytest.mark.unit
def test_pinned_and_non_local_backends_are_not_resolved(
    contract: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_CODER_ENV, _CHAT_URL)
    monkeypatch.setenv("LLM_CODER_MODEL_NAME", "coder-model")
    resolver = HandlerContractEndpointResolver(contract)
    reasoning = resolver.resolve(EnumContractCapability.REASONING)
    assert reasoning is not None
    assert reasoning.backend_id == "local-heavy-reasoning"  # not pinned-local
    assert resolver.resolve_backend_url("cloud-glm") is None
    assert resolver.resolve_backend_url("no-such-backend") is None
    assert resolver.resolve_backend_url("local-coder") == _CHAT_URL


@pytest.mark.unit
def test_base_url_requires_the_openai_chat_suffix() -> None:
    assert base_url_of("http://h:1/v1/chat/completions/") == "http://h:1"
    assert base_url_of("http://h:1/chat/completions") is None
    assert base_url_of("http://h:1") is None


@pytest.mark.unit
def test_canonical_contract_names_the_variables_the_resolver_and_cron_depend_on() -> (
    None
):
    """Pins the contract fact this module and cron-closeout.sh are built on."""
    raw = yaml.safe_load(canonical_contract_path().read_text(encoding="utf-8"))
    by_id = {b["backend_id"]: b for b in raw["backends"]}
    assert by_id["local-coder"]["endpoint_url_env"] == _CODER_ENV
    assert by_id["local-heavy-reasoning"]["provider"] == "local"
    cron = Path(__file__).resolve().parents[3] / "scripts" / "cron-closeout.sh"
    text = cron.read_text(encoding="utf-8")
    assert _CODER_ENV in text
    assert re.search(r"\bLLM_CODER_URL\b", text) is None


@pytest.mark.unit
def test_retired_variables_survive_nowhere_in_source() -> None:
    """The three retired variables are read by no source file (OMN-17103)."""
    root = Path(__file__).resolve().parents[3]
    pattern = re.compile(r"\b(LLM_CODER_URL|LLM_DEEPSEEK_R1_URL|LLM_GLM_URL)\b")
    offenders = [
        str(p.relative_to(root))
        for base in ("src", "plugins", "scripts")
        for p in (root / base).rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".sh", ".md", ".yaml", ".yml", ".example"}
        and p.resolve() != Path(__file__).resolve()
        and "handler_contract_endpoint_resolver.py" not in p.name
        and pattern.search(p.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert offenders == []
