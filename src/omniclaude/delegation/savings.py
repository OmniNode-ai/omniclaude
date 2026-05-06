# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Savings estimation for ONEX model delegation.

Computes counterfactual savings vs a cloud baseline (default: Claude Opus).
Savings are ESTIMATES, not measured cash — the token counts and pricing
are approximations and must carry explicit provenance labels.

Provenance labels:
  measured   — token counts came from a live API usage response
  estimated  — token counts were inferred (e.g. from a character-count heuristic)
  unknown    — token counts could not be determined

Savings method labels:
  zero_marginal_api_cost  — local model; actual API cost = 0
  pricing_manifest_delta  — cloud-cheap model; delta from manifest pricing
  offline_unavailable     — savings could not be computed (model offline or unrecognized)
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent.parent.parent.parent
    / "omnibase_infra"
    / "src"
    / "omnibase_infra"
    / "configs"
    / "pricing_manifest.yaml"
)

_DEFAULT_BASELINE_MODEL = "claude-opus-4-6"


class EnumTokenProvenance(StrEnum):
    MEASURED = "measured"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class EnumSavingsMethod(StrEnum):
    ZERO_MARGINAL_API_COST = "zero_marginal_api_cost"
    PRICING_MANIFEST_DELTA = "pricing_manifest_delta"
    OFFLINE_UNAVAILABLE = "offline_unavailable"


class ModelSavingsEstimate(BaseModel):
    """Counterfactual savings estimate for one delegation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    correlation_id: str
    model_local: str
    model_cloud_baseline: str
    local_cost_usd: float | None
    cloud_cost_usd: float | None
    savings_usd: float | None
    baseline_model: str
    pricing_manifest_version: str
    savings_method: EnumSavingsMethod
    token_provenance: EnumTokenProvenance
    prompt_tokens: int
    completion_tokens: int


class SavingsCalculator:
    """Compute counterfactual savings vs a cloud baseline model.

    Loads pricing from a manifest YAML at construction time so the version
    is pinned for the lifetime of the instance.
    """

    def __init__(
        self,
        manifest_path: Path | None = None,
        baseline_model: str = _DEFAULT_BASELINE_MODEL,
    ) -> None:
        path = manifest_path or _MANIFEST_PATH
        with open(path) as f:
            raw = yaml.safe_load(f)
        self._manifest_version: str = raw.get("schema_version", "unknown")
        self._models: dict[str, dict[str, float]] = raw.get("models", {})
        self._baseline_model = baseline_model

    @property
    def manifest_version(self) -> str:
        return self._manifest_version

    def _model_is_local(self, model_id: str) -> bool:
        entry = self._models.get(model_id, {})
        return (
            entry.get("input_cost_per_1k", -1.0) == 0.0
            and entry.get("output_cost_per_1k", -1.0) == 0.0
        )

    def _cost_usd(
        self, model_id: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        entry = self._models.get(model_id)
        if entry is None:
            raise KeyError(model_id)
        input_rate = entry["input_cost_per_1k"]
        output_rate = entry["output_cost_per_1k"]
        return (prompt_tokens / 1000.0) * input_rate + (
            completion_tokens / 1000.0
        ) * output_rate

    def calculate(
        self,
        *,
        session_id: str,
        correlation_id: str,
        model_local: str,
        prompt_tokens: int,
        completion_tokens: int,
        token_provenance: EnumTokenProvenance,
        baseline_model: str | None = None,
    ) -> ModelSavingsEstimate:
        """Return a savings estimate for a single delegation.

        If the local model is unknown or offline, savings_method is set to
        `offline_unavailable` and the cost/savings fields are None.
        """
        if prompt_tokens < 0 or completion_tokens < 0:
            raise ValueError("prompt_tokens and completion_tokens must be non-negative")

        effective_baseline = baseline_model or self._baseline_model

        if model_local not in self._models or effective_baseline not in self._models:
            return ModelSavingsEstimate(
                session_id=session_id,
                correlation_id=correlation_id,
                model_local=model_local,
                model_cloud_baseline=effective_baseline,
                local_cost_usd=None,
                cloud_cost_usd=None,
                savings_usd=None,
                baseline_model=effective_baseline,
                pricing_manifest_version=self._manifest_version,
                savings_method=EnumSavingsMethod.OFFLINE_UNAVAILABLE,
                token_provenance=token_provenance,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        cloud_cost = self._cost_usd(
            effective_baseline, prompt_tokens, completion_tokens
        )

        if self._model_is_local(model_local):
            local_cost: float = 0.0
            method = EnumSavingsMethod.ZERO_MARGINAL_API_COST
        else:
            local_cost = self._cost_usd(model_local, prompt_tokens, completion_tokens)
            method = EnumSavingsMethod.PRICING_MANIFEST_DELTA

        return ModelSavingsEstimate(
            session_id=session_id,
            correlation_id=correlation_id,
            model_local=model_local,
            model_cloud_baseline=effective_baseline,
            local_cost_usd=local_cost,
            cloud_cost_usd=cloud_cost,
            savings_usd=cloud_cost - local_cost,
            baseline_model=effective_baseline,
            pricing_manifest_version=self._manifest_version,
            savings_method=method,
            token_provenance=token_provenance,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
