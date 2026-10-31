# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Endpoint URLs and URL patterns declared in the omniclaude runtime contract (OMN-21743).

The runtime-health, Valkey, Gemini and RAG endpoints, the quirk schema
reference and the changelog sources used to be string literals at their call sites. They are declared in
``contracts/contract_omniclaude_runtime.yaml`` under ``endpoints:`` with the
``${env.VAR:default}`` overlay convention, so a per-lane operator overlay supplies the
value, and reach their callers as an injected :class:`ModelEndpointDefaults`. No field
carries a default here: a field the contract does not declare fails to load rather
than passing,.
"""

from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

# ``${env.VAR}`` / ``${env.VAR:default}`` -- the same env-overlay convention the
# aggregator and diagnostics descriptors use for the runtime contract.
_ENV_REF = re.compile(
    r"\$\{env\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<default>[^}]*))?\}"
)

_CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "contract_omniclaude_runtime.yaml"
)


def _expand_contract_env_refs(value: str) -> str:
    """Expand ``${env.VAR}`` / ``${env.VAR:default}`` -- this module's one env boundary.

    A variable that is set but empty counts as unset, so the declared default applies.
    """

    def _sub(match: re.Match[str]) -> str:
        default = match.group("default")
        return os.environ.get(match.group("name")) or (
            default if default is not None else ""
        )

    return _ENV_REF.sub(_sub, value)


@cache
def _load_endpoints_section(contract_path: Path) -> dict[str, object]:
    with contract_path.open(encoding="utf-8") as contract_file:
        raw = yaml.safe_load(contract_file)
    section = raw.get("endpoints") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        raise ValueError(
            f"contract {contract_path} must declare an 'endpoints' mapping with "
            "the runtime endpoint fields"
        )
    return section


class ModelEndpointDefaults(BaseModel):
    """Endpoints, schema references and changelog sources of the omniclaude runtime.

    Build with :meth:`from_contract`, or inject an explicit instance in a test.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    github_api_base_url: str = Field(min_length=1)
    github_https_url_prefix: str = Field(min_length=1)
    intelligence_service_url: str = Field(min_length=1)
    runtime_health_url: str = Field(min_length=1)
    valkey_default_url: str = Field(min_length=1)
    gemini_api_endpoint: str = Field(min_length=1)
    rag_base_url: str = Field(min_length=1)
    quirk_finding_schema_ref: str = Field(min_length=1)
    changelog_sources: dict[str, str] = Field(min_length=1)

    @classmethod
    def from_contract(cls, contract_path: Path | None = None) -> ModelEndpointDefaults:
        """Load every field from the contract ``endpoints`` section.

        A field the section does not declare raises ``ValueError`` (pydantic's
        validation error), never a silent default.
        """
        section = _load_endpoints_section(contract_path or _CONTRACT)
        values = {
            name: _expand_contract_env_refs(declared)
            if isinstance(declared, str)
            else declared
            for name, declared in section.items()
        }
        return cls.model_validate(values)


__all__ = ["ModelEndpointDefaults"]
