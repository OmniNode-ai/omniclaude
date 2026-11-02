# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Endpoint URLs and registry references declared in ``contract_endpoint_policy.yaml`` (OMN-21798).

The values used to be string literals at their call sites. They are declared in
``contracts/contract_endpoint_policy.yaml`` with the ``${env.VAR:default}`` overlay
convention and reach their callers as a :class:`ModelEndpointPolicy`. No field carries a
default here: a field the contract does not declare fails to load.
"""

from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ModelEndpointPolicy"]

_ENV_REF = re.compile(
    r"\$\{env\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<default>[^}]*))?\}"
)

_CONTRACT = (
    Path(__file__).resolve().parents[1] / "contracts" / "contract_endpoint_policy.yaml"
)


def _expand_env_refs(value: str) -> str:
    """Expand ``${env.VAR}`` / ``${env.VAR:default}``; a set but empty variable counts as unset."""

    def _sub(match: re.Match[str]) -> str:
        default = match.group("default")
        return os.environ.get(match.group("name")) or (
            default if default is not None else ""
        )

    return _ENV_REF.sub(_sub, value)


@cache
def _load_section(contract_path: Path) -> dict[str, str]:
    with contract_path.open(encoding="utf-8") as contract_file:
        raw = yaml.safe_load(contract_file)
    section = raw.get("endpoints") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        raise ValueError(
            f"contract {contract_path} must declare an 'endpoints' mapping"
        )
    return {str(name): str(declared) for name, declared in section.items()}


class ModelEndpointPolicy(BaseModel):
    """Endpoints and registry references that scripts and library code read from the contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    linear_graphql_url: str = Field(min_length=1)
    github_web_base: str = Field(min_length=1)
    github_ssh_base: str = Field(min_length=1)
    omninode_github_org_base: str = Field(min_length=1)

    @classmethod
    def from_contract(cls, contract_path: Path | None = None) -> ModelEndpointPolicy:
        """Load every field from the contract ``endpoints`` section.

        A field the section does not declare raises ``ValueError`` (pydantic's validation
        error), never a silent default.
        """
        section = _load_section(contract_path or _CONTRACT)
        return cls.model_validate(
            {name: _expand_env_refs(declared) for name, declared in section.items()}
        )
