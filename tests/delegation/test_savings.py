# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the delegation savings calculator.

Tests verify:
- Local model: savings == full baseline cost (actual = 0)
- Cloud cheap model: savings == baseline - cheap rate
- Estimated tokens: provenance = "estimated"
- Measured tokens: provenance = "measured"
- Offline / unknown model: savings_method = "offline_unavailable", costs None
- Round-trip Pydantic serialization
"""

import json
from pathlib import Path

import pytest
import yaml

from omniclaude.delegation.savings import (
    EnumSavingsMethod,
    EnumTokenProvenance,
    ModelSavingsEstimate,
    SavingsCalculator,
)


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    manifest = {
        "schema_version": "1.0.0-test",
        "models": {
            # baseline cloud model
            "claude-opus-4-6": {
                "input_cost_per_1k": 0.015,
                "output_cost_per_1k": 0.075,
            },
            # cheap cloud model
            "claude-haiku-3-5": {
                "input_cost_per_1k": 0.0008,
                "output_cost_per_1k": 0.004,
            },
            # local model (zero cost)
            "qwen3-coder-30b-a3b": {
                "input_cost_per_1k": 0.0,
                "output_cost_per_1k": 0.0,
            },
        },
    }
    p = tmp_path / "pricing_manifest.yaml"
    p.write_text(yaml.dump(manifest))
    return p


@pytest.fixture
def calculator(manifest_path: Path) -> SavingsCalculator:
    return SavingsCalculator(
        manifest_path=manifest_path, baseline_model="claude-opus-4-6"
    )


def test_local_model_savings_equals_baseline_cost(
    calculator: SavingsCalculator,
) -> None:
    estimate = calculator.calculate(
        session_id="sess-001",
        correlation_id="corr-001",
        model_local="qwen3-coder-30b-a3b",
        prompt_tokens=1000,
        completion_tokens=500,
        token_provenance="measured",
    )

    assert estimate.savings_method is EnumSavingsMethod.ZERO_MARGINAL_API_COST
    assert estimate.local_cost_usd == 0.0
    # cloud_cost = (1000/1000)*0.015 + (500/1000)*0.075 = 0.015 + 0.0375 = 0.0525
    assert estimate.cloud_cost_usd == pytest.approx(0.0525)
    assert estimate.savings_usd == pytest.approx(0.0525)


def test_cheap_cloud_model_savings_is_delta(calculator: SavingsCalculator) -> None:
    estimate = calculator.calculate(
        session_id="sess-002",
        correlation_id="corr-002",
        model_local="claude-haiku-3-5",
        prompt_tokens=1000,
        completion_tokens=500,
        token_provenance="measured",
    )

    assert estimate.savings_method is EnumSavingsMethod.PRICING_MANIFEST_DELTA
    # local = (1000/1000)*0.0008 + (500/1000)*0.004 = 0.0008 + 0.002 = 0.0028
    assert estimate.local_cost_usd == pytest.approx(0.0028)
    # cloud baseline same as above = 0.0525
    assert estimate.cloud_cost_usd == pytest.approx(0.0525)
    assert estimate.savings_usd == pytest.approx(0.0525 - 0.0028)


def test_estimated_token_provenance_preserved(calculator: SavingsCalculator) -> None:
    estimate = calculator.calculate(
        session_id="sess-003",
        correlation_id="corr-003",
        model_local="qwen3-coder-30b-a3b",
        prompt_tokens=800,
        completion_tokens=200,
        token_provenance="estimated",
    )

    assert estimate.token_provenance is EnumTokenProvenance.ESTIMATED


def test_measured_token_provenance_preserved(calculator: SavingsCalculator) -> None:
    estimate = calculator.calculate(
        session_id="sess-004",
        correlation_id="corr-004",
        model_local="qwen3-coder-30b-a3b",
        prompt_tokens=800,
        completion_tokens=200,
        token_provenance="measured",
    )

    assert estimate.token_provenance is EnumTokenProvenance.MEASURED


def test_offline_model_returns_unavailable(calculator: SavingsCalculator) -> None:
    estimate = calculator.calculate(
        session_id="sess-005",
        correlation_id="corr-005",
        model_local="unknown-model-xyz",
        prompt_tokens=1000,
        completion_tokens=500,
        token_provenance="unknown",
    )

    assert estimate.savings_method is EnumSavingsMethod.OFFLINE_UNAVAILABLE
    assert estimate.local_cost_usd is None
    assert estimate.cloud_cost_usd is None
    assert estimate.savings_usd is None
    assert estimate.token_provenance is EnumTokenProvenance.UNKNOWN


def test_negative_token_counts_are_rejected(
    calculator: SavingsCalculator,
) -> None:
    with pytest.raises(
        ValueError, match="prompt_tokens and completion_tokens must be non-negative"
    ):
        calculator.calculate(
            session_id="sess-negative",
            correlation_id="corr-negative",
            model_local="qwen3-coder-30b-a3b",
            prompt_tokens=-1,
            completion_tokens=500,
            token_provenance=EnumTokenProvenance.MEASURED,
        )


def test_unknown_baseline_returns_unavailable(
    calculator: SavingsCalculator,
) -> None:
    estimate = calculator.calculate(
        session_id="sess-baseline",
        correlation_id="corr-baseline",
        model_local="qwen3-coder-30b-a3b",
        prompt_tokens=1000,
        completion_tokens=500,
        token_provenance=EnumTokenProvenance.MEASURED,
        baseline_model="unknown-baseline",
    )

    assert estimate.savings_method is EnumSavingsMethod.OFFLINE_UNAVAILABLE
    assert estimate.local_cost_usd is None
    assert estimate.cloud_cost_usd is None
    assert estimate.savings_usd is None
    assert estimate.baseline_model == "unknown-baseline"


def test_round_trip_serialization(calculator: SavingsCalculator) -> None:
    estimate = calculator.calculate(
        session_id="sess-006",
        correlation_id="corr-006",
        model_local="qwen3-coder-30b-a3b",
        prompt_tokens=1000,
        completion_tokens=500,
        token_provenance="measured",
    )

    serialized = estimate.model_dump_json()
    restored = ModelSavingsEstimate.model_validate(json.loads(serialized))
    assert restored == estimate


def test_manifest_version_recorded(manifest_path: Path) -> None:
    calc = SavingsCalculator(manifest_path=manifest_path)
    assert calc.manifest_version == "1.0.0-test"

    estimate = calc.calculate(
        session_id="sess-007",
        correlation_id="corr-007",
        model_local="qwen3-coder-30b-a3b",
        prompt_tokens=100,
        completion_tokens=50,
        token_provenance="measured",
    )
    assert estimate.pricing_manifest_version == "1.0.0-test"


def test_custom_baseline_model(manifest_path: Path) -> None:
    calc = SavingsCalculator(
        manifest_path=manifest_path, baseline_model="claude-haiku-3-5"
    )
    estimate = calc.calculate(
        session_id="sess-008",
        correlation_id="corr-008",
        model_local="qwen3-coder-30b-a3b",
        prompt_tokens=1000,
        completion_tokens=1000,
        token_provenance="measured",
    )

    assert estimate.baseline_model == "claude-haiku-3-5"
    assert estimate.model_cloud_baseline == "claude-haiku-3-5"
    # cloud_cost = (1000/1000)*0.0008 + (1000/1000)*0.004 = 0.0048
    assert estimate.cloud_cost_usd == pytest.approx(0.0048)
    assert estimate.savings_usd == pytest.approx(0.0048)
