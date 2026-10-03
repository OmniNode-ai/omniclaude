# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Resolve local LLM endpoints from the canonical bifrost routing contract.

omniclaude owns no endpoint table (OMN-17103). The one routing authority is the
omnimarket ``bifrost_delegation.yaml`` contract; each local backend in it names
the environment variable that holds its COMPLETE endpoint URL
(``endpoint_url_env``, e.g. ``BIFROST_LOCAL_CODER_ENDPOINT_URL``) or carries a
literal ``endpoint_url``. This handler reads that declaration and nothing else.

It replaces ``LocalLlmEndpointRegistry`` and the ``LLM_CODER_URL``,
``LLM_DEEPSEEK_R1_URL`` and ``LLM_GLM_URL`` variables it read. Those variables
named hosts that the contract had already superseded: the registry carried a
second, drifting copy of the routing table.

The contract leaves ``model_name`` null for local backends ("resolved at deploy
time"). The model id a local server answers to stays deploy-time configuration,
read from the ``*_MODEL_NAME`` variable the contract's endpoint variable pairs
with (``_MODEL_ENV_BY_ENDPOINT_ENV``).

Example:
    >>> resolver = HandlerContractEndpointResolver()
    >>> endpoint = resolver.resolve(EnumContractCapability.CODE_GENERATION)
    >>> if endpoint:
    ...     print(endpoint.url)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

import yaml

from omniclaude.enums.enum_contract_capability import EnumContractCapability
from omniclaude.models.model_contract_endpoint import (
    ModelContractEndpoint,
)

logger = logging.getLogger(__name__)

#: The one model-id variable each contract endpoint variable pairs with. A local
#: backend whose endpoint variable is not listed has no configured model id and
#: is not resolvable here.
_MODEL_ENV_BY_ENDPOINT_ENV: Final[dict[str, str]] = {
    "BIFROST_LOCAL_CODER_ENDPOINT_URL": "LLM_CODER_MODEL_NAME",
    "BIFROST_LOCAL_EMBEDDING_ENDPOINT_URL": "LLM_EMBEDDING_MODEL_NAME",
}

_LOCAL_PROVIDER: Final = "local"


def canonical_contract_path() -> Path:
    """Path of the canonical bifrost contract inside the installed omnimarket."""
    # Lazy: the runner module is heavy and hooks import this on a hot path.
    from omniclaude.delegation.runner import canonical_bifrost_contract_path

    return canonical_bifrost_contract_path()


def _configured_url(backend: dict[str, object]) -> str:
    """The backend's complete URL: the contract literal, else its named variable."""
    literal = backend.get("endpoint_url")
    if isinstance(literal, str) and literal:
        return literal
    env_name = backend.get("endpoint_url_env")
    if isinstance(env_name, str) and env_name:
        return os.environ.get(env_name, "").strip()
    return ""


class HandlerContractEndpointResolver:
    """Resolve local-backend endpoints from the canonical bifrost contract.

    The contract is read once per instance. Nothing here falls back to a
    hardcoded URL or model: a backend whose endpoint variable or model id is
    unset is skipped, and an unresolvable capability returns ``None``.
    """

    def __init__(self, contract_path: Path | None = None) -> None:
        self._contract_path = contract_path
        self._backends: list[dict[str, object]] | None = None

    def _load_backends(self) -> list[dict[str, object]]:
        if self._backends is None:
            path = self._contract_path or canonical_contract_path()
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                raise RuntimeError(
                    f"Unparseable bifrost delegation contract: {path}"
                ) from exc
            backends = raw.get("backends", [])
            if not isinstance(backends, list):
                raise RuntimeError(
                    f"Invalid bifrost delegation contract: {path}. "
                    "'backends' must be a list."
                )
            self._backends = [b for b in backends if isinstance(b, dict)]
        return self._backends

    def resolve(
        self, capability: EnumContractCapability | str
    ) -> ModelContractEndpoint | None:
        """Return the first ordinary-routing local backend that serves ``capability``.

        Contract order decides; a backend with no resolvable endpoint or model id
        is skipped so the next one can serve.
        """
        wanted = str(capability)
        for backend in self._load_backends():
            if backend.get("provider") != _LOCAL_PROVIDER:
                continue
            if backend.get("explicit_pin_only", False):
                continue
            caps = backend.get("capabilities", [])
            if not isinstance(caps, list) or wanted not in caps:
                continue
            endpoint = self._endpoint_for(backend)
            if endpoint is not None:
                return endpoint
        logger.debug("No contract endpoint resolvable for capability=%s", wanted)
        return None

    def resolve_backend_url(self, backend_id: str) -> str | None:
        """Return the COMPLETE endpoint URL of one named local backend, or None.

        Does not need the backend's model id; for callers that carry their own.
        """
        for backend in self._load_backends():
            if backend.get("backend_id") == backend_id:
                if backend.get("provider") != _LOCAL_PROVIDER:
                    return None
                return _configured_url(backend)
        return None

    def _endpoint_for(self, backend: dict[str, object]) -> ModelContractEndpoint | None:
        backend_id = str(backend.get("backend_id", ""))
        env_name = backend.get("endpoint_url_env")
        url = _configured_url(backend)
        if not url:
            logger.debug("backend %s: endpoint URL not configured", backend_id)
            return None

        model = backend.get("model_name")
        model_name = model if isinstance(model, str) and model else ""
        if not model_name and isinstance(env_name, str):
            model_env = _MODEL_ENV_BY_ENDPOINT_ENV.get(env_name)
            model_name = os.environ.get(model_env, "").strip() if model_env else ""
        if not model_name:
            logger.debug("backend %s: model id not configured", backend_id)
            return None
        return ModelContractEndpoint(
            backend_id=backend_id, url=url, model_name=model_name
        )
