# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The runtime contract's service_endpoints overlay feeds the Valkey cache and embeddings (OMN-21727)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from omniclaude.lib.core import intelligence_cache
from omniclaude.lib.core.intelligence_cache import IntelligenceCache
from omniclaude.lib.core.manifest_injector import ManifestInjector
from omniclaude.models.model_service_endpoint_defaults import (
    ModelServiceEndpointDefaults,
)

pytestmark = pytest.mark.unit

_FIXTURE_VALKEY = "redis://fixture-valkey:6390/2"
_FIXTURE_EMBEDDINGS = "http://fixture-embeddings:9000/v1/embeddings"


def test_overlay_env_reaches_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_SERVICE_URL", _FIXTURE_EMBEDDINGS)
    monkeypatch.setenv("OMNICLAUDE_VALKEY_DEFAULT_URL", _FIXTURE_VALKEY)
    defaults = ModelServiceEndpointDefaults.from_contract()
    assert defaults.embedding_service_url == _FIXTURE_EMBEDDINGS
    assert defaults.valkey_default_url == _FIXTURE_VALKEY


def test_unset_overlay_falls_back_to_contract_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EMBEDDING_SERVICE_URL", raising=False)
    monkeypatch.delenv("OMNICLAUDE_VALKEY_DEFAULT_URL", raising=False)
    defaults = ModelServiceEndpointDefaults.from_contract()
    assert defaults.embedding_service_url == ""
    assert defaults.valkey_default_url.startswith("redis://")


def test_password_is_added_as_the_url_credential() -> None:
    defaults = ModelServiceEndpointDefaults(valkey_default_url=_FIXTURE_VALKEY)
    assert defaults.valkey_url_with_password("") == _FIXTURE_VALKEY
    assert (
        defaults.valkey_url_with_password("p@ss")
        == "redis://:p%40ss@fixture-valkey:6390/2"
    )


def test_cache_falls_back_to_the_injected_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intelligence_cache.settings, "enable_intelligence_cache", True)
    monkeypatch.setattr(intelligence_cache.settings, "valkey_url", None)
    monkeypatch.setenv("VALKEY_PASSWORD", "fixture-pw")
    cache = IntelligenceCache(
        endpoint_defaults=ModelServiceEndpointDefaults(
            valkey_default_url=_FIXTURE_VALKEY
        )
    )
    assert cache.redis_url == "redis://:fixture-pw@fixture-valkey:6390/2"


@pytest.mark.asyncio
async def test_embed_text_posts_to_the_injected_endpoint() -> None:
    posted: list[str] = []

    class _Response:
        status = 200

        async def __aenter__(self) -> _Response:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def json(self) -> dict[str, Any]:
            return {"data": [{"embedding": [0.5]}]}

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        def post(self, url: str, **_: object) -> _Response:
            posted.append(url)
            return _Response()

    injector = ManifestInjector(
        enable_intelligence=False,
        enable_storage=False,
        enable_cache=False,
        service_endpoint_defaults=ModelServiceEndpointDefaults(
            embedding_service_url=_FIXTURE_EMBEDDINGS
        ),
    )
    with patch("aiohttp.ClientSession", _Session):
        assert await injector._embed_text("hello") == [0.5]
    assert posted == [_FIXTURE_EMBEDDINGS]
