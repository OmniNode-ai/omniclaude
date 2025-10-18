#!/usr/bin/env python3
"""
Unit tests for AI Quorum System
Tests stub mode and basic functionality for Phase 1.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from consensus.quorum import AIQuorum, QuorumScore, ModelConfig, ModelProvider


def test_stub_mode_basic():
    """Test basic stub mode functionality."""
    print("Test: Basic Stub Mode")

    quorum = AIQuorum(stub_mode=True, enable_ai_scoring=False)

    # Run async test
    async def run_test():
        score = await quorum.score_correction(
            original_prompt="implement authentication",
            corrected_prompt="implement authentication @MANDATORY_FUNCTIONS.md",
            correction_type="framework_reference",
        )

        assert isinstance(score, QuorumScore)
        assert score.consensus_score == 0.85
        assert score.confidence == 0.9
        assert score.is_approved
        assert not score.requires_human_review
        assert len(score.model_scores) == 2  # Default models

        print("  ✓ Consensus score: 0.85")
        print("  ✓ Confidence: 0.9")
        print("  ✓ Approved: True")
        print("  ✓ Model count: 2")

    asyncio.run(run_test())
    print()


def test_model_configuration():
    """Test custom model configuration."""
    print("Test: Custom Model Configuration")

    custom_models = [
        ModelConfig(name="custom-model-1", provider=ModelProvider.OLLAMA, weight=2.0),
        ModelConfig(name="custom-model-2", provider=ModelProvider.GEMINI, weight=1.0),
    ]

    quorum = AIQuorum(models=custom_models, stub_mode=True)

    async def run_test():
        score = await quorum.score_correction(
            original_prompt="test prompt",
            corrected_prompt="test prompt with correction",
            correction_type="test",
        )

        assert len(score.model_scores) == 2
        assert "custom-model-1" in score.model_scores
        assert "custom-model-2" in score.model_scores

        print("  ✓ Custom models configured correctly")
        print(f"  ✓ Model names: {list(score.model_scores.keys())}")

    asyncio.run(run_test())
    print()


def test_quorum_score_serialization():
    """Test QuorumScore to_dict serialization."""
    print("Test: QuorumScore Serialization")

    score = QuorumScore(
        consensus_score=0.85,
        confidence=0.9,
        model_scores={"model1": 0.8, "model2": 0.9},
        model_reasoning={"model1": "Good", "model2": "Excellent"},
        recommendation="APPROVE",
        requires_human_review=False,
    )

    score_dict = score.to_dict()

    assert isinstance(score_dict, dict)
    assert score_dict["consensus_score"] == 0.85
    assert score_dict["confidence"] == 0.9
    assert len(score_dict["model_scores"]) == 2
    assert score_dict["recommendation"] == "APPROVE"

    print("  ✓ Serialization successful")
    print(f"  ✓ Keys: {list(score_dict.keys())}")
    print()


def test_approval_logic():
    """Test approval logic thresholds."""
    print("Test: Approval Logic")

    # Test approved score
    score_approved = QuorumScore(
        consensus_score=0.75,
        confidence=0.7,
        model_scores={},
        model_reasoning={},
        recommendation="APPROVE",
    )

    assert score_approved.is_approved
    print("  ✓ Score 0.75, Confidence 0.7: Approved")

    # Test rejected score (low consensus)
    score_rejected_consensus = QuorumScore(
        consensus_score=0.65,
        confidence=0.7,
        model_scores={},
        model_reasoning={},
        recommendation="REJECT",
    )

    assert not score_rejected_consensus.is_approved
    print("  ✓ Score 0.65, Confidence 0.7: Rejected (low consensus)")

    # Test rejected score (low confidence)
    score_rejected_confidence = QuorumScore(
        consensus_score=0.75,
        confidence=0.5,
        model_scores={},
        model_reasoning={},
        recommendation="REVIEW",
    )

    assert not score_rejected_confidence.is_approved
    print("  ✓ Score 0.75, Confidence 0.5: Rejected (low confidence)")
    print()


def test_default_approval_mode():
    """Test default approval when AI scoring is disabled."""
    print("Test: Default Approval Mode")

    quorum = AIQuorum(stub_mode=False, enable_ai_scoring=False)

    async def run_test():
        score = await quorum.score_correction(
            original_prompt="test",
            corrected_prompt="test corrected",
            correction_type="test",
        )

        assert score.consensus_score == 1.0
        assert score.confidence == 1.0
        assert score.is_approved
        assert score.recommendation == "AUTO_APPROVED_NO_AI"

        print("  ✓ Auto-approved when AI disabled")
        print("  ✓ Consensus: 1.0, Confidence: 1.0")

    asyncio.run(run_test())
    print()


def test_correction_metadata():
    """Test passing correction metadata."""
    print("Test: Correction Metadata")

    quorum = AIQuorum(stub_mode=True)

    async def run_test():
        metadata = {
            "agent_detected": "agent-debug-intelligence",
            "framework_refs": ["@MANDATORY_FUNCTIONS.md"],
            "correction_time": "2025-09-29T12:00:00",
        }

        score = await quorum.score_correction(
            original_prompt="debug issue",
            corrected_prompt="debug issue with metadata",
            correction_type="framework_reference",
            correction_metadata=metadata,
        )

        assert score.is_approved
        print("  ✓ Metadata passed successfully")
        print(f"  ✓ Score: {score.consensus_score}")

    asyncio.run(run_test())
    print()


def test_model_provider_enum():
    """Test ModelProvider enum."""
    print("Test: ModelProvider Enum")

    assert ModelProvider.OLLAMA.value == "ollama"
    assert ModelProvider.GEMINI.value == "gemini"
    assert ModelProvider.OPENAI.value == "openai"

    print("  ✓ All providers defined")
    print(f"  ✓ Providers: {[p.value for p in ModelProvider]}")
    print()


def test_prompt_generation():
    """Test scoring prompt generation."""
    print("Test: Prompt Generation")

    quorum = AIQuorum(stub_mode=True)

    prompt = quorum._generate_scoring_prompt(
        original_prompt="test original",
        corrected_prompt="test corrected",
        correction_type="test_type",
        metadata={"key": "value"},
    )

    assert "test original" in prompt
    assert "test corrected" in prompt
    assert "test_type" in prompt
    assert "Pre-commit Hook Correction Evaluation" in prompt

    print("  ✓ Prompt generated successfully")
    print(f"  ✓ Prompt length: {len(prompt)} characters")
    print()


def test_min_model_participation():
    """Test MIN_MODEL_PARTICIPATION threshold enforcement."""
    print("Test: MIN_MODEL_PARTICIPATION Enforcement")

    # Create quorum with 5 models
    models = [ModelConfig(name=f"model-{i}", provider=ModelProvider.OLLAMA, weight=1.0) for i in range(5)]

    quorum = AIQuorum(models=models, stub_mode=False, enable_ai_scoring=True)

    # Simulate scenario with only 2/5 models responding (40% < 60% threshold)
    mock_scores = [
        (models[0], {"score": 0.8, "reasoning": "Good", "recommendation": "APPROVE"}),
        (models[1], {"score": 0.9, "reasoning": "Excellent", "recommendation": "APPROVE"}),
        Exception("Model timeout"),  # Model 2 failed
        Exception("Model timeout"),  # Model 3 failed
        Exception("Model timeout"),  # Model 4 failed
    ]

    result = quorum._calculate_consensus(mock_scores)

    # Should fail due to insufficient participation
    assert result.recommendation == "FAIL_PARTICIPATION"
    assert result.consensus_score == 0.0
    assert result.requires_human_review
    assert "Insufficient model participation" in result.model_reasoning.get("quorum_error", "")

    print("  ✓ Correctly rejected with 2/5 models (40%)")
    print(f"  ✓ Recommendation: {result.recommendation}")
    print(f"  ✓ Error message included")

    # Now test with 3/5 models responding (60% >= 60% threshold)
    mock_scores_passing = [
        (models[0], {"score": 0.8, "reasoning": "Good", "recommendation": "APPROVE"}),
        (models[1], {"score": 0.9, "reasoning": "Excellent", "recommendation": "APPROVE"}),
        (models[2], {"score": 0.85, "reasoning": "Good", "recommendation": "APPROVE"}),
        Exception("Model timeout"),  # Model 3 failed
        Exception("Model timeout"),  # Model 4 failed
    ]

    result_passing = quorum._calculate_consensus(mock_scores_passing)

    # Should pass participation threshold and calculate normally
    assert result_passing.recommendation != "FAIL_PARTICIPATION"
    assert result_passing.consensus_score > 0.0

    print("  ✓ Correctly accepted with 3/5 models (60%)")
    print(f"  ✓ Consensus score: {result_passing.consensus_score:.2f}")
    print()


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("AI Quorum System - Phase 1 Tests")
    print("=" * 60)
    print()

    tests = [
        test_stub_mode_basic,
        test_model_configuration,
        test_quorum_score_serialization,
        test_approval_logic,
        test_default_approval_mode,
        test_correction_metadata,
        test_model_provider_enum,
        test_prompt_generation,
        test_min_model_participation,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ Test failed: {e}")
            failed += 1

    print("=" * 60)
    print(f"Tests Passed: {passed}/{len(tests)}")
    if failed > 0:
        print(f"Tests Failed: {failed}/{len(tests)}")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
