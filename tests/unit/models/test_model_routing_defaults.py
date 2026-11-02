# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The runtime contract's model_routing overlay feeds savings and the manifest (OMN-21780)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omniclaude.delegation.savings import SavingsCalculator
from omniclaude.lib.core.manifest_injector import ManifestInjector
from omniclaude.models.model_model_routing_defaults import ModelModelRoutingDefaults

pytestmark = pytest.mark.unit

_QUORUM = [
    {
        "name": "Fixture Member",
        "model": "fixture-quorum-model",
        "provider": "fixture",
        "weight": 1.5,
        "use_case": "fixture",
    }
]


def test_unset_overlay_resolves_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OMNICLAUDE_SAVINGS_BASELINE_MODEL",
        "OMNICLAUDE_GEMINI_TIER_MODELS_JSON",
        "OMNICLAUDE_ZAI_TIER_MODELS_JSON",
        "OMNICLAUDE_INTELLIGENCE_MODELS_JSON",
    ):
        monkeypatch.delenv(name, raising=False)
    defaults = ModelModelRoutingDefaults.from_contract()
    assert defaults.savings_baseline_model == ""
    assert defaults.gemini_tier_models == {}
    assert defaults.intelligence_models == []


def test_overlay_env_reaches_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMNICLAUDE_SAVINGS_BASELINE_MODEL", "fixture-baseline")
    monkeypatch.setenv("OMNICLAUDE_ZAI_TIER_MODELS_JSON", '{"haiku": "fixture-zai"}')
    monkeypatch.setenv("OMNICLAUDE_INTELLIGENCE_MODELS_JSON", json.dumps(_QUORUM))
    defaults = ModelModelRoutingDefaults.from_contract()
    assert defaults.savings_baseline_model == "fixture-baseline"
    assert defaults.zai_tier_models == {"haiku": "fixture-zai"}
    assert defaults.intelligence_models[0].model == "fixture-quorum-model"


def test_savings_baseline_comes_from_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "pricing.yaml"
    manifest.write_text("schema_version: '1'\nmodels: {}\n")
    monkeypatch.setenv("OMNICLAUDE_SAVINGS_BASELINE_MODEL", "fixture-baseline")
    assert SavingsCalculator(manifest_path=manifest)._baseline_model == (
        "fixture-baseline"
    )
    injected = SavingsCalculator(manifest_path=manifest, baseline_model="injected")
    assert injected._baseline_model == "injected"


@pytest.mark.asyncio
async def test_manifest_models_come_from_injected_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults = ModelModelRoutingDefaults.model_validate(
        {
            "gemini_tier_models": {"haiku": "injected-gemini"},
            "intelligence_models": _QUORUM,
        }
    )
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    injector = ManifestInjector(
        enable_intelligence=False,
        enable_storage=False,
        enable_cache=False,
        model_routing_defaults=defaults,
    )
    result = await injector._query_models("cid")
    assert result["ai_models"]["gemini"]["models"] == {"haiku": "injected-gemini"}
    assert [m["model"] for m in result["intelligence_models"]] == [
        "fixture-quorum-model"
    ]
