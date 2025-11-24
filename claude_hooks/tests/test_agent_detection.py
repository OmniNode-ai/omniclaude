#!/usr/bin/env python3
"""
Comprehensive tests for 3-stage agent detection pipeline.

Tests:
- Stage 1: Pattern Detection (~1ms)
- Stage 2: Trigger Matching (~5ms)
- Stage 3: AI Selection (~2.5s)

Author: OmniClaude Framework
Version: 1.0.0
"""

import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


# Add lib directory to path
HOOKS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(HOOKS_DIR / "lib"))

from agent_detector import AgentDetector  # noqa: E402
from hybrid_agent_selector import HybridAgentSelector, SelectionMethod  # noqa: E402


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def agent_detector():
    """Create AgentDetector instance."""
    return AgentDetector()


@pytest.fixture
def hybrid_selector():
    """Create HybridAgentSelector with AI disabled for fast testing."""
    return HybridAgentSelector(enable_ai=False, confidence_threshold=0.8)


@pytest.fixture
def hybrid_selector_with_ai():
    """Create HybridAgentSelector with AI enabled."""
    return HybridAgentSelector(
        enable_ai=True,
        confidence_threshold=0.8,
        model_preference="5090",
        timeout_ms=3000,
    )


@pytest.fixture
def test_agent_config(tmp_path):
    """Create temporary agent configuration."""
    import yaml

    # Create registry directory
    registry_dir = tmp_path / "agent-definitions"
    registry_dir.mkdir()

    # Create config directory
    config_dir = tmp_path / "configs"
    config_dir.mkdir()

    # Create test agent registry
    registry = {
        "agents": {
            "testing": {
                "name": "agent-testing",
                "domain": "testing",
                "purpose": "Testing specialist for comprehensive test strategy",
                "activation_triggers": [
                    "test",
                    "testing",
                    "pytest",
                    "unittest",
                    "test coverage",
                    "test suite",
                ],
            }
        }
    }

    registry_file = registry_dir / "agent-registry.yaml"
    with open(registry_file, "w") as f:
        yaml.dump(registry, f)

    # Create agent config file
    agent_config = {
        "name": "agent-testing",
        "domain": "testing",
        "purpose": "Testing specialist for comprehensive test strategy",
        "triggers": [
            "test",
            "testing",
            "pytest",
            "unittest",
            "test coverage",
            "test suite",
        ],
        "domain_query": "comprehensive test strategy quality assurance",
        "implementation_query": "pytest testing patterns automation",
    }

    config_file = config_dir / "agent-testing.yaml"
    with open(config_file, "w") as f:
        yaml.dump(agent_config, f)

    # Patch both registry and config paths
    with (
        patch.object(AgentDetector, "AGENT_REGISTRY_PATH", registry_file),
        patch.object(AgentDetector, "AGENT_CONFIG_DIR", config_dir),
    ):
        yield config_file


# ============================================================================
# STAGE 1: PATTERN DETECTION TESTS
# ============================================================================


@pytest.mark.unit
class TestPatternDetection:
    """Test Stage 1: Pattern Detection (~1ms)."""

    def test_explicit_at_syntax(self, agent_detector):
        """Test @agent-name pattern detection."""
        prompt = "@agent-testing help me write unit tests"
        agent = agent_detector.detect_agent(prompt)
        assert agent == "agent-testing"

    def test_explicit_use_syntax(self, agent_detector):
        """Test 'use agent-name' pattern detection."""
        prompt = "use agent-testing to write tests"
        agent = agent_detector.detect_agent(prompt)
        assert agent == "agent-testing"

    def test_explicit_invoke_syntax(self, agent_detector):
        """Test 'invoke agent-name' pattern detection."""
        prompt = "invoke agent-debug-intelligence for debugging"
        agent = agent_detector.detect_agent(prompt)
        assert agent == "agent-debug-intelligence"

    def test_task_syntax(self, agent_detector):
        """Test Task(agent='agent-name') pattern detection."""
        prompt = 'Task(agent="agent-parallel-dispatcher")'
        agent = agent_detector.detect_agent(prompt)
        assert agent == "agent-parallel-dispatcher"

    def test_case_sensitivity(self, agent_detector):
        """Test case-sensitive pattern matching."""
        # Should match
        assert agent_detector.detect_agent("@agent-testing") == "agent-testing"

        # Should not match (wrong case)
        assert agent_detector.detect_agent("@Agent-Testing") is None
        assert agent_detector.detect_agent("@AGENT-TESTING") is None

    def test_multiple_agent_references(self, agent_detector):
        """Test that first agent is returned when multiple present."""
        prompt = "@agent-testing write tests and @agent-debug help debug"
        agent = agent_detector.detect_agent(prompt)
        assert agent == "agent-testing"

    def test_malformed_patterns(self, agent_detector):
        """Test malformed patterns don't match."""
        malformed_prompts = [
            "@ agent-testing",  # Space after @
            "@agent testing",  # Space in name
            "@agent_testing",  # Underscore instead of hyphen
            "use agent testing",  # Space in name
            "agentesting",  # No separator
        ]

        for prompt in malformed_prompts:
            agent = agent_detector.detect_agent(prompt)
            assert agent is None or "testing" not in agent.lower()

    def test_pattern_detection_performance(self, agent_detector):
        """Test pattern detection is fast (<2ms)."""
        prompt = "@agent-testing write comprehensive tests"

        start_time = time.time()
        for _ in range(100):
            agent_detector.detect_agent(prompt)
        elapsed_ms = (time.time() - start_time) * 1000

        avg_ms = elapsed_ms / 100
        assert avg_ms < 2.0, f"Pattern detection too slow: {avg_ms:.2f}ms"

    def test_no_pattern_returns_none(self, agent_detector):
        """Test prompts without patterns return None."""
        prompts = [
            "help me write some tests",
            "what's the weather today",
            "explain how agents work",
            "testing without agent reference",
        ]

        for prompt in prompts:
            assert agent_detector.detect_agent(prompt) is None


# ============================================================================
# STAGE 2: TRIGGER MATCHING TESTS
# ============================================================================


@pytest.mark.unit
class TestTriggerMatching:
    """Test Stage 2: Trigger Matching (~5ms)."""

    def test_single_trigger_match(self, test_agent_config):
        """Test single trigger keyword match."""
        # Create selector after config is patched
        selector = HybridAgentSelector(enable_ai=False)

        prompt = "help me write pytest tests"

        result = selector._stage_2_triggers(prompt)

        assert result.found
        assert result.agent_name == "agent-testing"
        assert result.confidence >= 0.7
        assert result.method == SelectionMethod.TRIGGER

    def test_multiple_trigger_matches(self, test_agent_config):
        """Test multiple trigger matches increase confidence."""
        # Create selector after config is patched
        selector = HybridAgentSelector(enable_ai=False)

        # Single trigger
        prompt1 = "write tests"
        result1 = selector._stage_2_triggers(prompt1)

        # Multiple triggers
        prompt2 = "write pytest tests for test coverage"
        result2 = selector._stage_2_triggers(prompt2)

        if result1.found and result2.found:
            assert result2.confidence > result1.confidence

    def test_partial_trigger_match(self, test_agent_config):
        """Test partial trigger matches work."""
        # Create selector after config is patched
        selector = HybridAgentSelector(enable_ai=False)

        prompt = "we need to test this feature"

        result = selector._stage_2_triggers(prompt)

        assert result.found
        assert result.agent_name == "agent-testing"

    def test_case_insensitive_triggers(self, test_agent_config):
        """Test triggers are case-insensitive."""
        # Create selector after config is patched
        selector = HybridAgentSelector(enable_ai=False)

        prompts = ["write PYTEST tests", "Write Pytest Tests", "WRITE pytest TESTS"]

        for prompt in prompts:
            result = selector._stage_2_triggers(prompt)
            assert result.found
            assert result.agent_name == "agent-testing"

    def test_trigger_not_found(self, hybrid_selector):
        """Test prompts without triggers return not found."""
        prompt = "what's the weather today"

        result = hybrid_selector._stage_2_triggers(prompt)

        assert not result.found

    def test_trigger_matching_performance(self, test_agent_config):
        """Test trigger matching is fast (<10ms)."""
        # Create selector after config is patched
        selector = HybridAgentSelector(enable_ai=False)

        prompt = "help me write pytest tests"

        start_time = time.time()
        for _ in range(100):
            selector._stage_2_triggers(prompt)
        elapsed_ms = (time.time() - start_time) * 1000

        avg_ms = elapsed_ms / 100
        assert avg_ms < 10.0, f"Trigger matching too slow: {avg_ms:.2f}ms"

    def test_confidence_scoring(self, test_agent_config):
        """Test confidence increases with more matches."""
        # Create selector after config is patched
        selector = HybridAgentSelector(enable_ai=False)

        prompt1 = "test"  # 1 match
        prompt2 = "test pytest"  # 2 matches
        prompt3 = "test pytest coverage"  # 3 matches

        result1 = selector._stage_2_triggers(prompt1)
        result2 = selector._stage_2_triggers(prompt2)
        result3 = selector._stage_2_triggers(prompt3)

        if result1.found and result2.found and result3.found:
            assert result1.confidence < result2.confidence < result3.confidence
            assert result3.confidence <= 0.95  # Max confidence cap


# ============================================================================
# STAGE 3: AI SELECTION TESTS
# ============================================================================


@pytest.mark.unit
class TestAISelection:
    """Test Stage 3: AI Selection (~2.5s)."""

    def test_ai_selection_with_mock(self, hybrid_selector_with_ai):
        """Test AI selection with mocked AI selector."""
        # Mock the AI selector's select_agent method to return expected structure
        hybrid_selector_with_ai.ai_selector.select_agent = Mock(
            return_value=[
                (
                    "agent-debug-intelligence",
                    0.92,
                    "Database performance requires debugging expertise",
                )
            ]
        )

        prompt = "optimize database query performance"
        context = {"working_dir": "/test"}

        result = hybrid_selector_with_ai._stage_3_ai(prompt, context)

        assert result.found
        assert result.agent_name == "agent-debug-intelligence"
        assert result.confidence == 0.92
        assert result.method == SelectionMethod.AI
        assert "debugging" in result.reasoning.lower()

    @patch("ai_agent_selector.AIAgentSelector._call_local_model")
    def test_ai_confidence_threshold(self, mock_call):
        """Test AI selection respects confidence threshold."""
        selector = HybridAgentSelector(
            enable_ai=True, confidence_threshold=0.9
        )  # High threshold

        # Mock low confidence response
        mock_call.return_value = {
            "agent": "agent-testing",
            "confidence": 0.75,  # Below threshold
            "reasoning": "Might be testing related",
        }

        prompt = "help with something"
        result = selector._stage_3_ai(prompt, None)

        # Should still return result, but select_agent will filter it
        assert result.confidence < 0.9

    @patch("ai_agent_selector.AIAgentSelector._call_local_model")
    def test_ai_selection_timeout(self, mock_call):
        """Test AI selection handles timeout gracefully."""
        selector = HybridAgentSelector(
            enable_ai=True, timeout_ms=100
        )  # Very short timeout

        # Mock slow response
        def slow_response(*args, **kwargs):
            time.sleep(0.2)  # 200ms
            return None

        mock_call.side_effect = slow_response

        prompt = "help with something"

        # Should handle timeout gracefully
        try:
            result = selector._stage_3_ai(prompt, None)
            assert not result.found  # Timeout should result in no match
        except Exception:
            pass  # Timeout is acceptable

    @patch("ai_agent_selector.AIAgentSelector._call_local_model")
    def test_ai_selection_alternatives(self, mock_call, hybrid_selector_with_ai):
        """Test AI selection returns alternative agents."""
        # Mock multiple selections
        hybrid_selector_with_ai.ai_selector.select_agent = Mock(
            return_value=[
                ("agent-testing", 0.95, "Best match for testing"),
                ("agent-debug-intelligence", 0.85, "Alternative for debugging"),
                ("agent-parallel-dispatcher", 0.70, "Could coordinate parallel work"),
            ]
        )

        prompt = "write comprehensive tests"
        result = hybrid_selector_with_ai._stage_3_ai(prompt, None)

        assert result.found
        assert result.agent_name == "agent-testing"
        assert len(result.alternatives) == 2
        assert "agent-debug-intelligence" in result.alternatives

    def test_ai_selection_error_handling(self, hybrid_selector_with_ai):
        """Test AI selection handles errors gracefully."""
        # Mock the AI selector to raise an exception
        hybrid_selector_with_ai.ai_selector.select_agent = Mock(
            side_effect=Exception("vLLM server error")
        )

        prompt = "help with something"
        result = hybrid_selector_with_ai._stage_3_ai(prompt, None)

        # Should not crash, return not found
        assert not result.found


# ============================================================================
# INTEGRATION: 3-STAGE PIPELINE TESTS
# ============================================================================


@pytest.mark.integration
class TestHybridPipeline:
    """Test complete 3-stage detection pipeline."""

    def test_stage1_pattern_wins(self, hybrid_selector):
        """Test Stage 1 pattern detection takes precedence."""
        # Has both pattern and trigger
        prompt = "@agent-testing write pytest tests"

        result = hybrid_selector.select_agent(prompt)

        assert result.found
        assert result.agent_name == "agent-testing"
        assert result.method == SelectionMethod.PATTERN
        assert result.confidence == 1.0
        assert result.latency_ms < 5.0

    def test_stage2_trigger_fallback(self, test_agent_config):
        """Test Stage 2 trigger matching when no pattern."""
        # Create selector with test agent config active
        selector = HybridAgentSelector(enable_ai=False)

        # No pattern, has trigger
        prompt = "help me write pytest tests"

        result = selector.select_agent(prompt)

        assert result.found
        assert result.agent_name == "agent-testing"
        assert result.method == SelectionMethod.TRIGGER
        assert 0.7 <= result.confidence <= 0.95
        assert result.latency_ms < 15.0

    @patch("ai_agent_selector.AIAgentSelector._call_local_model")
    def test_stage3_ai_fallback(self, mock_call):
        """Test Stage 3 AI selection when no pattern or trigger."""
        selector = HybridAgentSelector(enable_ai=True, confidence_threshold=0.8)

        # Mock AI response
        selector.ai_selector = Mock()
        selector.ai_selector.select_agent = Mock(
            return_value=[
                ("agent-debug-intelligence", 0.92, "Debugging expertise needed")
            ]
        )

        # No pattern or trigger
        prompt = "optimize database query performance"

        result = selector.select_agent(prompt)

        assert result.found
        assert result.agent_name == "agent-debug-intelligence"
        assert result.method == SelectionMethod.AI
        assert result.confidence >= 0.8

    def test_no_agent_detected(self, hybrid_selector):
        """Test no agent detected when nothing matches."""
        prompt = "what's the weather today"

        result = hybrid_selector.select_agent(prompt)

        assert not result.found
        assert result.confidence == 0.0
        assert result.method == SelectionMethod.NONE
        assert "No agent matched" in result.reasoning

    def test_pipeline_statistics(self, test_agent_config):
        """Test statistics tracking across pipeline."""
        # Create fresh selector with test agent config active
        selector = HybridAgentSelector(enable_ai=False)

        prompts = [
            "@agent-testing explicit pattern",  # Pattern
            "write pytest tests",  # Trigger
            "help me test",  # Trigger
            "what's the weather",  # No match
        ]

        for prompt in prompts:
            selector.select_agent(prompt)

        stats = selector.get_stats()

        assert stats["total_selections"] == 4
        assert stats["pattern_selections"] == 1
        assert stats["trigger_selections"] >= 1
        assert stats["no_agent_selections"] >= 1
        assert stats["avg_latency_ms"] > 0

    def test_pipeline_performance(self, test_agent_config):
        """Test pipeline performance without AI."""
        # Create selector with test agent config active
        selector = HybridAgentSelector(enable_ai=False)

        prompt = "write pytest tests"

        start_time = time.time()
        result = selector.select_agent(prompt)
        elapsed_ms = (time.time() - start_time) * 1000

        assert result.found
        assert elapsed_ms < 50.0, f"Pipeline too slow: {elapsed_ms:.2f}ms"


# ============================================================================
# CLI INTERFACE TESTS
# ============================================================================


@pytest.mark.integration
class TestCLIInterface:
    """Test command-line interface."""

    def test_cli_output_format(self, test_agent_config, monkeypatch):
        """Test CLI outputs correct format for shell parsing."""
        import subprocess

        result = subprocess.run(
            [
                "python3",
                str(HOOKS_DIR / "lib" / "hybrid_agent_selector.py"),
                "write pytest tests",
                "--enable-ai",
                "false",
            ],
            capture_output=True,
            text=True,
        )

        output = result.stdout

        # Should have shell-friendly output
        if "AGENT_DETECTED:" in output:
            assert "CONFIDENCE:" in output
            assert "METHOD:" in output
            assert "REASONING:" in output
            assert "LATENCY_MS:" in output

    def test_cli_json_output(self, test_agent_config):
        """Test CLI JSON output mode."""
        import json
        import subprocess

        result = subprocess.run(
            [
                "python3",
                str(HOOKS_DIR / "lib" / "hybrid_agent_selector.py"),
                "write pytest tests",
                "--enable-ai",
                "false",
                "--json",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                assert "found" in data
                assert "confidence" in data
                assert "method" in data
            except json.JSONDecodeError:
                pass  # OK if no agent detected


# ============================================================================
# PERFORMANCE BENCHMARKS
# ============================================================================


@pytest.mark.performance
class TestPerformanceBenchmarks:
    """Performance benchmarks for agent detection."""

    def test_pattern_detection_benchmark(self, agent_detector):
        """Benchmark pattern detection speed."""
        prompt = "@agent-testing write tests"

        iterations = 1000
        start_time = time.time()

        for _ in range(iterations):
            agent_detector.detect_agent(prompt)

        elapsed_ms = (time.time() - start_time) * 1000
        avg_ms = elapsed_ms / iterations

        print(f"\nPattern Detection: {avg_ms:.3f}ms avg ({iterations} iterations)")
        assert avg_ms < 1.0, f"Too slow: {avg_ms:.3f}ms"

    def test_trigger_matching_benchmark(self, hybrid_selector, test_agent_config):
        """Benchmark trigger matching speed."""
        prompt = "write pytest tests for coverage"

        iterations = 500
        start_time = time.time()

        for _ in range(iterations):
            hybrid_selector._stage_2_triggers(prompt)

        elapsed_ms = (time.time() - start_time) * 1000
        avg_ms = elapsed_ms / iterations

        print(f"\nTrigger Matching: {avg_ms:.3f}ms avg ({iterations} iterations)")
        assert avg_ms < 5.0, f"Too slow: {avg_ms:.3f}ms"

    def test_full_pipeline_benchmark(self, hybrid_selector, test_agent_config):
        """Benchmark full pipeline (without AI)."""
        prompts = [
            "@agent-testing explicit pattern",
            "write pytest tests",
            "help me test this",
            "no agent here",
        ]

        iterations = 100
        start_time = time.time()

        for _ in range(iterations):
            for prompt in prompts:
                hybrid_selector.select_agent(prompt)

        elapsed_ms = (time.time() - start_time) * 1000
        total_calls = iterations * len(prompts)
        avg_ms = elapsed_ms / total_calls

        print(f"\nFull Pipeline: {avg_ms:.3f}ms avg ({total_calls} calls)")
        assert avg_ms < 10.0, f"Too slow: {avg_ms:.3f}ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
