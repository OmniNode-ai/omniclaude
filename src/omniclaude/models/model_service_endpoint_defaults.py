# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Default service endpoints omniclaude code uses, read from the runtime contract overlay (OMN-21727)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import yaml
from pydantic import BaseModel, ConfigDict

from omniclaude.models.model_model_routing_defaults import expand_overlay_value

_CONTRACT_PATH = (
    Path(__file__).resolve().parent.parent
    / "contracts"
    / "contract_omniclaude_runtime.yaml"
)


class ModelServiceEndpointDefaults(BaseModel):
    """The ``service_endpoints`` section of the runtime contract, overlay-resolved.

    A value the overlay does not supply falls back to the default the contract
    declares for it; an entry with no declared default resolves empty.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    embedding_service_url: str = ""
    valkey_default_url: str = ""

    @classmethod
    def from_contract(cls, path: Path | None = None) -> ModelServiceEndpointDefaults:
        """Resolve the contract's ``service_endpoints`` section against the overlay env."""
        with open(path or _CONTRACT_PATH, encoding="utf-8") as f:
            section = (yaml.safe_load(f) or {}).get("service_endpoints") or {}
        return cls.model_validate(
            {key: expand_overlay_value(str(value)) for key, value in section.items()}
        )

    def valkey_url_with_password(self, password: str) -> str:
        """The default Valkey URL, carrying ``password`` as its credential when one is given."""
        if not password or not self.valkey_default_url:
            return self.valkey_default_url
        parts = urlsplit(self.valkey_default_url)
        host = parts.netloc.rsplit("@", 1)[-1]
        netloc = f":{quote(password, safe='')}@{host}"
        return urlunsplit(parts._replace(netloc=netloc))
