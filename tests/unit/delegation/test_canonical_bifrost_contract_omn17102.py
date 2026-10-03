# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""omniclaude resolves the canonical bifrost delegation contract, not a fork (OMN-17102).

omniclaude shipped ``src/omniclaude/delegation/bifrost_delegation.yaml`` at
config_version 1.1.0 while the canonical omnimarket contract was at 2.8.0. The fork
still named ``cloud-sonnet`` and ``cloud-haiku`` (deleted from the canonical contract
by OMN-13351, no Anthropic key policy), and ``quorum.py`` mapped every non-gemini
frontier backend to ``ModelProvider.OPENAI``, a provider this org holds no key for.

These tests pin the three loading modules (``runner.py``, ``task_classifier.py``,
``quorum.py``) to the contract the rest of the platform uses.
"""

from __future__ import annotations

import importlib
import importlib.resources
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FORK_PATH = (
    _REPO_ROOT / "src" / "omniclaude" / "delegation" / "bifrost_delegation.yaml"
)
_DELETED_BACKENDS = ("cloud-sonnet", "cloud-haiku")

# (module, attribute naming the contract path the module loads)
_LOADERS = [
    ("omniclaude.delegation.runner", "_DEFAULT_BIFROST_CONTRACT_PATH"),
    ("omniclaude.lib.task_classifier", "_BIFROST_YAML_PATH"),
    ("omniclaude.lib.utils.consensus.quorum", "_BIFROST_YAML_PATH"),
]


def _canonical_path() -> Path:
    resource = (
        importlib.resources.files("omnimarket") / "configs" / "bifrost_delegation.yaml"
    )
    return Path(str(resource))


def _read(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _loaded_path(module_name: str, attr: str) -> Path:
    return Path(getattr(importlib.import_module(module_name), attr))


@pytest.mark.unit
def test_forked_contract_is_deleted() -> None:
    assert not _FORK_PATH.exists(), f"forked routing table still shipped: {_FORK_PATH}"


@pytest.mark.unit
@pytest.mark.parametrize(("module_name", "attr"), _LOADERS)
def test_loader_resolves_the_canonical_contract(module_name: str, attr: str) -> None:
    assert _loaded_path(module_name, attr).resolve() == _canonical_path().resolve()


@pytest.mark.unit
@pytest.mark.parametrize(("module_name", "attr"), _LOADERS)
def test_loader_config_version_matches_canonical(module_name: str, attr: str) -> None:
    loaded = _loaded_path(module_name, attr)
    assert loaded.is_file(), f"{module_name} points at a missing contract: {loaded}"
    assert _read(loaded)["config_version"] == _read(_canonical_path())["config_version"]


@pytest.mark.unit
@pytest.mark.parametrize(("module_name", "attr"), _LOADERS)
def test_loader_backend_list_names_no_deleted_backend(
    module_name: str, attr: str
) -> None:
    loaded = _loaded_path(module_name, attr)
    assert loaded.is_file(), f"{module_name} points at a missing contract: {loaded}"
    backend_ids = {b["backend_id"] for b in _read(loaded)["backends"]}
    canonical_ids = {b["backend_id"] for b in _read(_canonical_path())["backends"]}
    for deleted in _DELETED_BACKENDS:
        assert deleted not in backend_ids
    assert backend_ids <= canonical_ids, sorted(backend_ids - canonical_ids)


@pytest.mark.unit
def test_quorum_default_models_cannot_select_deleted_or_openai() -> None:
    from omniclaude.lib.utils.consensus.quorum import AIQuorum, ModelProvider

    canonical_ids = {b["backend_id"] for b in _read(_canonical_path())["backends"]}
    names = {m.name for m in AIQuorum.DEFAULT_MODELS}
    assert names, "quorum must build at least one model from the canonical contract"
    assert names <= canonical_ids, sorted(names - canonical_ids)
    for deleted in _DELETED_BACKENDS:
        assert deleted not in names
    assert all(m.provider is not ModelProvider.OPENAI for m in AIQuorum.DEFAULT_MODELS)


@pytest.mark.unit
def test_quorum_refuses_a_frontier_backend_instead_of_mapping_to_openai() -> None:
    from omniclaude.lib.utils.consensus import quorum

    refusal = getattr(quorum, "QuorumUnconfiguredProviderError", None)
    assert refusal is not None, "quorum must define a typed refusal"
    assert issubclass(refusal, Exception)
    with pytest.raises(refusal):
        quorum._provider_for_backend("cloud-sonnet", provider="anthropic")
    with pytest.raises(refusal):
        quorum._provider_for_backend(
            "openrouter-north-mini-code", provider="openrouter"
        )


@pytest.mark.unit
def test_quorum_builder_never_returns_a_model_for_an_unkeyed_provider(
    tmp_path: Path,
) -> None:
    from omniclaude.lib.utils.consensus.quorum import (
        ModelProvider,
        _build_default_models_from_bifrost,
    )

    contract = tmp_path / "bifrost_delegation.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "config_version": "9.9.9",
                "backends": [
                    {
                        "backend_id": "local-coder",
                        "provider": "local",
                        "tier": "local",
                        "capabilities": ["code_generation"],
                    },
                    {
                        "backend_id": "cloud-sonnet",
                        "provider": "anthropic",
                        "tier": "frontier_api",
                        "capabilities": ["code_generation", "reasoning"],
                    },
                    {
                        "backend_id": "openrouter-x",
                        "provider": "openrouter",
                        "tier": "cheap_frontier",
                        "capabilities": ["code_generation", "reasoning"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    models = _build_default_models_from_bifrost(contract)
    assert [m.name for m in models] == ["local-coder"]
    assert all(m.provider is not ModelProvider.OPENAI for m in models)


@pytest.mark.unit
def test_runner_built_config_serves_only_keyless_canonical_backends(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from omniclaude.delegation.runner import _build_env_config

    overlay = tmp_path / "bifrost_overrides.yaml"
    overlay.write_text(
        "backends:\n"
        "  - backend_id: local-coder\n"
        '    endpoint_url: "http://lab.invalid:8000/v1/chat/completions"\n'
        '    model_name: "configured-coder"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("BIFROST_CONTRACT_PATH", raising=False)
    monkeypatch.setenv("BIFROST_OVERLAY_PATH", str(overlay))

    cfg = _build_env_config()

    assert cfg is not None
    assert set(cfg.backends) == {"local-coder"}
    for deleted in _DELETED_BACKENDS:
        assert deleted not in cfg.backends
