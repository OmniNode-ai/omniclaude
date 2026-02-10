# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration test for evidence-driven injection (OMN-2092).

Tests the full feedback loop:
save_gate → FileEvidenceResolver → select_patterns_for_injection → verify outcome
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class MockPatternRecord:
    """Mock PatternRecord for testing without importing handler module."""

    pattern_id: str
    domain: str
    title: str
    description: str
    confidence: float
    usage_count: int
    success_rate: float
    example_reference: str | None = None
    lifecycle_state: str | None = None
    evidence_tier: str | None = None


def make_pattern(
    pattern_id: str = "pat-001",
    domain: str = "testing",
    title: str = "Test Pattern",
    description: str = "A test pattern description",
    confidence: float = 0.9,
    usage_count: int = 10,
    success_rate: float = 0.8,
    example_reference: str | None = None,
    lifecycle_state: str | None = None,
    evidence_tier: str | None = None,
) -> MockPatternRecord:
    """Create a mock pattern with defaults."""
    return MockPatternRecord(
        pattern_id=pattern_id,
        domain=domain,
        title=title,
        description=description,
        confidence=confidence,
        usage_count=usage_count,
        success_rate=success_rate,
        example_reference=example_reference,
        lifecycle_state=lifecycle_state,
        evidence_tier=evidence_tier,
    )


class TestEvidenceDrivenInjectionIntegration:
    """Integration test for evidence-driven injection feedback loop."""

    def test_full_loop_save_resolve_select(self, tmp_path: Path) -> None:
        """Test full loop: save gates → create resolver → run selection → verify.

        This test verifies the complete feedback loop:
        1. Save promotion gates for different patterns with different results
        2. Create FileEvidenceResolver pointing at saved gates
        3. Run select_patterns_for_injection with evidence_policy="boost"
        4. Verify patterns are reranked according to evidence
        5. Verify evidence_policy="require" filters correctly
        """
        from omnibase_spi.contracts.measurement.contract_measurement_context import (
            ContractMeasurementContext,
        )
        from omnibase_spi.contracts.measurement.contract_promotion_gate import (
            ContractPromotionGate,
        )

        from omniclaude.hooks.injection_limits import (
            InjectionLimitsConfig,
            select_patterns_for_injection,
        )
        from plugins.onex.hooks.lib.file_evidence_resolver import FileEvidenceResolver
        from plugins.onex.hooks.lib.metrics_aggregator import save_gate

        # Step 1: Save gates for 2 patterns
        ctx_a = ContractMeasurementContext(
            ticket_id="T1", pattern_id="pat-a", repo_id="r"
        )
        gate_a = ContractPromotionGate(
            run_id="r1",
            gate_result="pass",
            baseline_key="k",
            sufficient_count=3,
            total_count=3,
            required_dimensions=["duration", "tokens", "tests"],
        )
        save_gate(gate_a, ctx_a, baselines_root=tmp_path)

        ctx_b = ContractMeasurementContext(
            ticket_id="T1", pattern_id="pat-b", repo_id="r"
        )
        gate_b = ContractPromotionGate(
            run_id="r1",
            gate_result="fail",
            baseline_key="k",
            sufficient_count=1,
            total_count=3,
            required_dimensions=["duration", "tokens", "tests"],
        )
        save_gate(gate_b, ctx_b, baselines_root=tmp_path)

        # Step 2: Create resolver pointing at tmp_path
        resolver = FileEvidenceResolver(baselines_root=tmp_path)

        # Step 3: Create patterns matching gate pattern_ids
        patterns = [
            make_pattern(pattern_id="pat-a"),
            make_pattern(pattern_id="pat-b"),
            make_pattern(pattern_id="pat-c"),  # no gate
        ]

        # Step 4: Test with boost policy
        limits_boost = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            evidence_policy="boost",
        )
        result_boost = select_patterns_for_injection(
            patterns, limits_boost, evidence_resolver=resolver
        )  # type: ignore[arg-type]
        ids_boost = [p.pattern_id for p in result_boost]

        # Verify: pat-a (boosted) should be first, pat-b (penalized) should be last
        assert ids_boost[0] == "pat-a", "Pattern with pass gate should be first"
        assert ids_boost[-1] == "pat-b", "Pattern with fail gate should be last"

        # Step 5: Test with require policy
        limits_require = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            evidence_policy="require",
        )
        result_require = select_patterns_for_injection(
            patterns, limits_require, evidence_resolver=resolver
        )  # type: ignore[arg-type]

        # Verify: only pat-a should pass the filter
        assert len(result_require) == 1, "Only pass patterns should be selected"
        assert result_require[0].pattern_id == "pat-a"
