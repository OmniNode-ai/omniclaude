# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Default model ids omniclaude code uses, read from the runtime contract overlay (OMN-21780)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

_CONTRACT_PATH = (
    Path(__file__).resolve().parent.parent
    / "contracts"
    / "contract_omniclaude_runtime.yaml"
)

# ``${env.VAR}`` / ``${env.VAR:default}``: the overlay convention the runtime contract uses.
_ENV_REF = re.compile(
    r"\$\{env\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<default>[^}]*))?\}"
)


class ModelIntelligenceModelDefault(BaseModel):
    """One quorum member the manifest lists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    weight: float
    use_case: str


class ModelModelRoutingDefaults(BaseModel):
    """The ``model_routing`` section of the runtime contract, overlay-resolved.

    A value the overlay does not supply resolves empty: no model id is
    declared in the repository.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    savings_baseline_model: str = ""
    gemini_tier_models: dict[str, str] = Field(default_factory=dict)
    zai_tier_models: dict[str, str] = Field(default_factory=dict)
    intelligence_models: list[ModelIntelligenceModelDefault] = Field(
        default_factory=list
    )

    @classmethod
    def from_contract(cls, path: Path | None = None) -> ModelModelRoutingDefaults:
        """Resolve the contract's ``model_routing`` section against the overlay env."""
        with open(path or _CONTRACT_PATH, encoding="utf-8") as f:
            section = (yaml.safe_load(f) or {}).get("model_routing") or {}
        resolved = {
            key: expand_overlay_value(str(value)) for key, value in section.items()
        }
        return cls.model_validate(
            {
                "savings_baseline_model": resolved.get("savings_baseline_model", ""),
                "gemini_tier_models": _json_or(resolved.get("gemini_tier_models"), {}),
                "zai_tier_models": _json_or(resolved.get("zai_tier_models"), {}),
                "intelligence_models": _json_or(
                    resolved.get("intelligence_models"), []
                ),
            }
        )


def expand_overlay_value(value: str) -> str:
    def _sub(match: re.Match[str]) -> str:
        default = match.group("default")
        return os.environ.get(match.group("name"), default if default else "")

    return _ENV_REF.sub(_sub, value).strip()


def _json_or(raw: str | None, empty: object) -> object:
    return json.loads(raw) if raw else empty


def default_baseline_model() -> str:
    """The cloud baseline model the savings calculator compares against (empty if unset)."""
    return ModelModelRoutingDefaults.from_contract().savings_baseline_model
