"""Unit tests for context_enrichment_runner.py (OMN-2267).

Tests cover:
- Feature flag gating (outer + inner flags)
- Parallel execution with mock handlers
- Per-enrichment timeout (150ms)
- Total timeout (200ms) cancels all
- Token cap with priority-based drop policy
- Graceful degradation when handlers are None (not installed)
- stdin-to-stdout JSON interface as subprocess

All tests run without network access or external services.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path setup: plugin lib modules live outside the normal package tree
# ---------------------------------------------------------------------------
_LIB_PATH = str(
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

import context_enrichment_runner as cer

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


def _make_test_env(**overrides: str) -> dict[str, str]:
    """Create a test environment merging overrides into the parent env.

    Preserves PYTHONPATH and other variables needed for subprocess imports.
    """
    env = os.environ.copy()
    env.update(overrides)
    return env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeEnrichmentResult:
    """Mimics ModelEnrichmentResult protocol."""

    def __init__(
        self,
        markdown: str = "## Section\n\nContent.",
        tokens: int = 50,
        success: bool = True,
    ) -> None:
        self.markdown = markdown
        self.tokens = tokens
        self.success = success


def _make_handler(
    markdown: str = "## Section\n\nContent.",
    tokens: int = 50,
    success: bool = True,
    delay_s: float = 0.0,
) -> MagicMock:
    """Build a mock handler with an async enrich() method."""
    handler = MagicMock()

    async def _enrich(**kwargs: Any) -> _FakeEnrichmentResult:
        if delay_s > 0:
            await asyncio.sleep(delay_s)
        return _FakeEnrichmentResult(markdown=markdown, tokens=tokens, success=success)

    handler.enrich = _enrich
    return handler


def _invoke_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stdin_data: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Invoke cer.main(), catching SystemExit, return parsed JSON stdout."""
    env = env or {}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: stdin_data))

    with pytest.raises(SystemExit) as exc_info:
        cer.main()

    assert exc_info.value.code == 0, f"Expected exit 0, got {exc_info.value.code}"
    captured = capsys.readouterr()
    return json.loads(captured.out)


# ---------------------------------------------------------------------------
# 1. Feature flag tests
# ---------------------------------------------------------------------------


class TestFeatureFlags:
    """Feature flag gating prevents execution when flags are off."""

    def test_feature_flags_disabled_returns_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When both flags are off, returns {success: false} immediately."""
        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.delenv("ENABLE_LOCAL_ENRICHMENT", raising=False)

        result = _invoke_main(monkeypatch, capsys, stdin_data="{}")
        assert result["success"] is False
        assert result["enrichment_count"] == 0
        assert result["tokens_used"] == 0
        assert result["enrichment_context"] == ""

    def test_feature_flag_inference_disabled_returns_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When ENABLE_LOCAL_INFERENCE_PIPELINE=false, returns {success: false}."""
        monkeypatch.delenv("ENABLE_LOCAL_ENRICHMENT", raising=False)
        result = _invoke_main(
            monkeypatch,
            capsys,
            stdin_data="{}",
            env={
                "ENABLE_LOCAL_INFERENCE_PIPELINE": "false",
                "ENABLE_LOCAL_ENRICHMENT": "true",
            },
        )
        assert result["success"] is False

    def test_feature_flag_enrichment_disabled_returns_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When ENABLE_LOCAL_ENRICHMENT=false, returns {success: false}."""
        result = _invoke_main(
            monkeypatch,
            capsys,
            stdin_data="{}",
            env={
                "ENABLE_LOCAL_INFERENCE_PIPELINE": "true",
                "ENABLE_LOCAL_ENRICHMENT": "false",
            },
        )
        assert result["success"] is False

    def test_both_flags_true_no_handlers_returns_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When both flags are true but no handlers installed, returns {success: false}."""
        input_json = json.dumps(
            {
                "prompt": "test",
                "session_id": "sid",
                "project_path": "/tmp",
            }
        )
        with (
            patch.object(cer, "HandlerCodeAnalysisEnrichment", None),
            patch.object(cer, "HandlerSimilarityEnrichment", None),
            patch.object(cer, "HandlerSummarizationEnrichment", None),
        ):
            result = _invoke_main(
                monkeypatch,
                capsys,
                stdin_data=input_json,
                env={
                    "ENABLE_LOCAL_INFERENCE_PIPELINE": "true",
                    "ENABLE_LOCAL_ENRICHMENT": "true",
                },
            )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# 2. Parallel execution with mock handlers
# ---------------------------------------------------------------------------


class TestParallelExecution:
    """Tests for parallel enrichment execution and result combination."""

    def test_parallel_execution_with_mock_handlers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Mock all three handlers; verify parallel execution returns combined markdown."""
        mock_summary_cls = MagicMock(
            return_value=_make_handler(
                markdown="## Summary\n\nA brief summary.", tokens=10
            )
        )
        mock_code_cls = MagicMock(
            return_value=_make_handler(
                markdown="## Code Analysis\n\nComplexity: low.", tokens=10
            )
        )
        mock_sim_cls = MagicMock(
            return_value=_make_handler(
                markdown="## Similarity\n\nSimilar: none.", tokens=10
            )
        )

        input_json = json.dumps(
            {
                "prompt": "What does this code do?",
                "session_id": "test-session",
                "project_path": "/tmp/project",
            }
        )

        with (
            patch.object(cer, "HandlerSummarizationEnrichment", mock_summary_cls),
            patch.object(cer, "HandlerCodeAnalysisEnrichment", mock_code_cls),
            patch.object(cer, "HandlerSimilarityEnrichment", mock_sim_cls),
        ):
            result = _invoke_main(
                monkeypatch,
                capsys,
                stdin_data=input_json,
                env={
                    "ENABLE_LOCAL_INFERENCE_PIPELINE": "true",
                    "ENABLE_LOCAL_ENRICHMENT": "true",
                },
            )

        assert result["success"] is True
        assert result["enrichment_count"] == 3
        assert result["tokens_used"] > 0
        assert "## Enrichments" in result["enrichment_context"]
        # All three sections should appear
        assert "Summary" in result["enrichment_context"]
        assert "Code Analysis" in result["enrichment_context"]
        assert "Similarity" in result["enrichment_context"]

    def test_single_handler_produces_enrichment(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When only one handler is available, it still produces output."""
        mock_summary_cls = MagicMock(
            return_value=_make_handler(
                markdown="## Summary\n\nSingle result.", tokens=15
            )
        )

        input_json = json.dumps(
            {
                "prompt": "test",
                "session_id": "sid",
                "project_path": "/tmp",
            }
        )

        with (
            patch.object(cer, "HandlerSummarizationEnrichment", mock_summary_cls),
            patch.object(cer, "HandlerCodeAnalysisEnrichment", None),
            patch.object(cer, "HandlerSimilarityEnrichment", None),
        ):
            result = _invoke_main(
                monkeypatch,
                capsys,
                stdin_data=input_json,
                env={
                    "ENABLE_LOCAL_INFERENCE_PIPELINE": "true",
                    "ENABLE_LOCAL_ENRICHMENT": "true",
                },
            )

        assert result["success"] is True
        assert result["enrichment_count"] == 1
        assert "Single result" in result["enrichment_context"]


# ---------------------------------------------------------------------------
# 3. Per-enrichment timeout (150ms)
# ---------------------------------------------------------------------------


class TestPerEnrichmentTimeout:
    """Tests for per-enrichment 150ms timeout."""

    def test_per_enrichment_timeout_150ms_excludes_slow_handler(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A handler that sleeps 200ms is cancelled and excluded from results."""
        # Fast handler (included)
        mock_fast_cls = MagicMock(
            return_value=_make_handler(
                markdown="## Summary\n\nFast result.", tokens=10, delay_s=0.0
            )
        )
        # Slow handler that exceeds per-enrichment timeout (excluded)
        mock_slow_cls = MagicMock(
            return_value=_make_handler(
                markdown="## Code Analysis\n\nSlow result.", tokens=10, delay_s=0.170
            )
        )

        input_json = json.dumps(
            {
                "prompt": "test",
                "session_id": "sid",
                "project_path": "/tmp",
            }
        )

        with (
            patch.object(cer, "HandlerSummarizationEnrichment", mock_fast_cls),
            patch.object(cer, "HandlerCodeAnalysisEnrichment", mock_slow_cls),
            patch.object(cer, "HandlerSimilarityEnrichment", None),
        ):
            result = _invoke_main(
                monkeypatch,
                capsys,
                stdin_data=input_json,
                env={
                    "ENABLE_LOCAL_INFERENCE_PIPELINE": "true",
                    "ENABLE_LOCAL_ENRICHMENT": "true",
                },
            )

        # The fast handler should be included; the slow one excluded
        assert result["success"] is True
        assert result["enrichment_count"] == 1
        assert "Fast result" in result["enrichment_context"]
        # The slow handler's content should NOT appear
        assert "Slow result" not in result["enrichment_context"]

    def test_run_single_enrichment_timeout_returns_empty(self) -> None:
        """_run_single_enrichment cancels a slow handler and returns empty result."""

        async def _slow_enrich(**kwargs: Any) -> _FakeEnrichmentResult:
            await asyncio.sleep(1.0)
            return _FakeEnrichmentResult(markdown="slow", tokens=5, success=True)

        slow_handler = MagicMock()
        slow_handler.enrich = _slow_enrich

        result = asyncio.run(
            cer._run_single_enrichment(
                name="test_handler",
                handler=slow_handler,
                prompt="test",
                project_path="/tmp",
            )
        )
        assert result.success is False
        assert result.markdown == ""


# ---------------------------------------------------------------------------
# 4. Total timeout (200ms) cancels all
# ---------------------------------------------------------------------------


class TestTotalTimeout:
    """Tests for 200ms total timeout that cancels all pending tasks."""

    def test_total_timeout_200ms_returns_partial_or_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """All handlers sleep 300ms; total timeout fires, returns partial/empty."""
        # All handlers take 300ms — well past 200ms total budget
        mock_sum_cls = MagicMock(
            return_value=_make_handler(
                markdown="## Summary\n\nSlow.", tokens=10, delay_s=0.300
            )
        )
        mock_code_cls = MagicMock(
            return_value=_make_handler(
                markdown="## Code Analysis\n\nSlow.", tokens=10, delay_s=0.300
            )
        )
        mock_sim_cls = MagicMock(
            return_value=_make_handler(
                markdown="## Similarity\n\nSlow.", tokens=10, delay_s=0.300
            )
        )

        input_json = json.dumps(
            {
                "prompt": "test",
                "session_id": "sid",
                "project_path": "/tmp",
            }
        )

        with (
            patch.object(cer, "HandlerSummarizationEnrichment", mock_sum_cls),
            patch.object(cer, "HandlerCodeAnalysisEnrichment", mock_code_cls),
            patch.object(cer, "HandlerSimilarityEnrichment", mock_sim_cls),
        ):
            result = _invoke_main(
                monkeypatch,
                capsys,
                stdin_data=input_json,
                env={
                    "ENABLE_LOCAL_INFERENCE_PIPELINE": "true",
                    "ENABLE_LOCAL_ENRICHMENT": "true",
                },
            )

        # No handler completes within 200ms total → empty/no success
        assert result["success"] is False
        assert result["enrichment_count"] == 0

    def test_run_all_enrichments_total_timeout(self) -> None:
        """_run_all_enrichments respects 200ms total budget."""

        async def _slow_enrich(**kwargs: Any) -> _FakeEnrichmentResult:
            await asyncio.sleep(1.0)
            return _FakeEnrichmentResult(markdown="slow", tokens=5, success=True)

        slow_handler = MagicMock()
        slow_handler.enrich = _slow_enrich
        slow_cls = MagicMock(return_value=slow_handler)

        with (
            patch.object(cer, "HandlerSummarizationEnrichment", slow_cls),
            patch.object(cer, "HandlerCodeAnalysisEnrichment", None),
            patch.object(cer, "HandlerSimilarityEnrichment", None),
        ):
            results = asyncio.run(
                cer._run_all_enrichments(prompt="test", project_path="/tmp")
            )

        # All tasks timed out → empty results
        assert results == [] or all(not r.success for r in results)


# ---------------------------------------------------------------------------
# 5. Token cap with priority-based drop policy
# ---------------------------------------------------------------------------


class TestTokenCap:
    """Tests for 2000-token cap with priority-based drop policy."""

    def test_token_cap_drops_lowest_priority_first(self) -> None:
        """Results exceeding 2000 tokens drop similarity (lowest priority) first."""
        # Create results that together exceed the cap
        # Priority: summarization > code_analysis > similarity
        # Each ~1000 tokens, total ~3000 → similarity must be dropped
        results = [
            cer._EnrichmentResult(
                name="summarization",
                markdown="s" * 100,
                tokens=1000,
                success=True,
            ),
            cer._EnrichmentResult(
                name="code_analysis",
                markdown="c" * 100,
                tokens=1000,
                success=True,
            ),
            cer._EnrichmentResult(
                name="similarity",
                markdown="m" * 100,
                tokens=1000,
                success=True,
            ),
        ]

        kept = cer._apply_token_cap(results)

        # Similarity is dropped (lowest priority)
        kept_names = {r.name for r in kept}
        assert "similarity" not in kept_names
        assert "summarization" in kept_names
        assert "code_analysis" in kept_names
        # Total tokens within cap
        assert sum(r.tokens for r in kept) <= cer._TOKEN_CAP

    def test_token_cap_preserves_all_when_under_limit(self) -> None:
        """Results within the token cap are all preserved."""
        results = [
            cer._EnrichmentResult(
                name="summarization", markdown="short", tokens=100, success=True
            ),
            cer._EnrichmentResult(
                name="code_analysis", markdown="short", tokens=100, success=True
            ),
            cer._EnrichmentResult(
                name="similarity", markdown="short", tokens=100, success=True
            ),
        ]

        kept = cer._apply_token_cap(results)
        assert len(kept) == 3

    def test_token_cap_drops_code_analysis_before_summarization(self) -> None:
        """When code_analysis and similarity both fit but combined exceed cap:
        code_analysis (priority 2) is kept over similarity (priority 3)."""
        # Just two results, both near cap — code_analysis priority > similarity
        results = [
            cer._EnrichmentResult(
                name="code_analysis", markdown="c", tokens=1200, success=True
            ),
            cer._EnrichmentResult(
                name="similarity", markdown="s", tokens=1200, success=True
            ),
        ]

        kept = cer._apply_token_cap(results)
        # Only one can fit (each is 1200, cap is 2000)
        assert len(kept) == 1
        assert kept[0].name == "code_analysis"

    def test_token_cap_filters_out_failed_results(self) -> None:
        """Failed enrichments (success=False) are excluded before cap check."""
        results = [
            cer._EnrichmentResult(
                name="summarization", markdown="ok", tokens=10, success=True
            ),
            cer._EnrichmentResult(
                name="code_analysis", markdown="", tokens=0, success=False
            ),
        ]

        kept = cer._apply_token_cap(results)
        assert len(kept) == 1
        assert kept[0].name == "summarization"

    def test_apply_token_cap_main_integration(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Integration: a single oversized enrichment is still included (nothing to drop)."""
        # Build a handler returning ~2500 tokens worth of markdown
        # The cap drops whole enrichments; with only one enrichment it stays
        big_markdown = "word " * 1925  # ~2500 tokens (1925 * 1.3)
        mock_cls = MagicMock(
            return_value=_make_handler(
                markdown=f"## Summary\n\n{big_markdown}",
                tokens=2500,
                success=True,
            )
        )

        input_json = json.dumps(
            {"prompt": "test", "session_id": "s", "project_path": "/tmp"}
        )

        with (
            patch.object(cer, "HandlerSummarizationEnrichment", mock_cls),
            patch.object(cer, "HandlerCodeAnalysisEnrichment", None),
            patch.object(cer, "HandlerSimilarityEnrichment", None),
        ):
            result = _invoke_main(
                monkeypatch,
                capsys,
                stdin_data=input_json,
                env={
                    "ENABLE_LOCAL_INFERENCE_PIPELINE": "true",
                    "ENABLE_LOCAL_ENRICHMENT": "true",
                },
            )

        # Single enrichment > cap means it still gets included (nothing to drop)
        # The cap drops whole enrichments, not truncates within one
        assert result["success"] is True
        assert result["enrichment_count"] == 1


# ---------------------------------------------------------------------------
# 6. Graceful degradation when all handlers are None
# ---------------------------------------------------------------------------


class TestMissingHandlers:
    """Tests for graceful degradation when omnibase_infra is not installed."""

    def test_missing_handlers_graceful_degradation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """All handlers import as None; returns {success: false} gracefully."""
        input_json = json.dumps(
            {
                "prompt": "test",
                "session_id": "sid",
                "project_path": "/tmp",
            }
        )

        with (
            patch.object(cer, "HandlerCodeAnalysisEnrichment", None),
            patch.object(cer, "HandlerSimilarityEnrichment", None),
            patch.object(cer, "HandlerSummarizationEnrichment", None),
        ):
            result = _invoke_main(
                monkeypatch,
                capsys,
                stdin_data=input_json,
                env={
                    "ENABLE_LOCAL_INFERENCE_PIPELINE": "true",
                    "ENABLE_LOCAL_ENRICHMENT": "true",
                },
            )

        assert result["success"] is False
        assert result["enrichment_count"] == 0
        assert result["enrichment_context"] == ""

    def test_run_all_enrichments_returns_empty_with_no_handlers(self) -> None:
        """_run_all_enrichments returns [] when all handler classes are None."""
        with (
            patch.object(cer, "HandlerCodeAnalysisEnrichment", None),
            patch.object(cer, "HandlerSimilarityEnrichment", None),
            patch.object(cer, "HandlerSummarizationEnrichment", None),
        ):
            results = asyncio.run(
                cer._run_all_enrichments(prompt="test", project_path="/tmp")
            )
        assert results == []


# ---------------------------------------------------------------------------
# 7. stdin-to-stdout JSON interface as subprocess
# ---------------------------------------------------------------------------


class TestSubprocessInterface:
    """Tests for the CLI JSON interface when run as a subprocess."""

    def test_stdin_to_stdout_json_interface_flags_disabled(self) -> None:
        """Run as subprocess with both flags disabled; verify JSON stdout."""
        runner_path = _LIB_PATH + "/context_enrichment_runner.py"
        input_data = json.dumps(
            {
                "prompt": "test prompt",
                "session_id": "sess-123",
                "project_path": "/tmp/project",
            }
        )

        proc = subprocess.run(
            [sys.executable, runner_path],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=_make_test_env(
                ENABLE_LOCAL_INFERENCE_PIPELINE="false",
                ENABLE_LOCAL_ENRICHMENT="false",
                OMNICLAUDE_NO_HANDLERS="1",
            ),
        )

        assert proc.returncode == 0
        result = json.loads(proc.stdout)
        assert result["success"] is False
        assert result["enrichment_count"] == 0

    def test_stdin_to_stdout_json_interface_with_malformed_input(self) -> None:
        """Run as subprocess with malformed JSON; verify safe JSON stdout."""
        runner_path = _LIB_PATH + "/context_enrichment_runner.py"

        proc = subprocess.run(
            [sys.executable, runner_path],
            input="{bad json",
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=_make_test_env(
                ENABLE_LOCAL_INFERENCE_PIPELINE="true",
                ENABLE_LOCAL_ENRICHMENT="true",
                OMNICLAUDE_NO_HANDLERS="1",
            ),
        )

        assert proc.returncode == 0
        result = json.loads(proc.stdout)
        assert result["success"] is False

    def test_stdin_to_stdout_json_interface_with_empty_input(self) -> None:
        """Run as subprocess with empty stdin; verify safe JSON stdout."""
        runner_path = _LIB_PATH + "/context_enrichment_runner.py"

        proc = subprocess.run(
            [sys.executable, runner_path],
            input="",
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=_make_test_env(
                ENABLE_LOCAL_INFERENCE_PIPELINE="true",
                ENABLE_LOCAL_ENRICHMENT="true",
                OMNICLAUDE_NO_HANDLERS="1",
            ),
        )

        assert proc.returncode == 0
        result = json.loads(proc.stdout)
        assert result["success"] is False

    def test_output_json_always_has_required_keys(self) -> None:
        """Every code path produces JSON with the four required keys."""
        runner_path = _LIB_PATH + "/context_enrichment_runner.py"
        required_keys = {
            "success",
            "enrichment_context",
            "tokens_used",
            "enrichment_count",
        }

        test_cases = [
            ("", {}),  # empty stdin, flags off
            ("{}", {"ENABLE_LOCAL_INFERENCE_PIPELINE": "false"}),  # flags off
            (
                '{"prompt":"test"}',
                {  # flags on, no handlers available (no omnibase_infra)
                    "ENABLE_LOCAL_INFERENCE_PIPELINE": "true",
                    "ENABLE_LOCAL_ENRICHMENT": "true",
                },
            ),
        ]

        for stdin_data, extra_env in test_cases:
            proc = subprocess.run(
                [sys.executable, runner_path],
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                env=_make_test_env(**extra_env, OMNICLAUDE_NO_HANDLERS="1"),
            )
            assert proc.returncode == 0, f"Non-zero exit for stdin={stdin_data!r}"
            result = json.loads(proc.stdout)
            assert required_keys <= set(result.keys()), (
                f"Missing keys for stdin={stdin_data!r}: "
                f"{required_keys - set(result.keys())}"
            )


# ---------------------------------------------------------------------------
# 8. Token counting helper
# ---------------------------------------------------------------------------


class TestTokenCounting:
    """Tests for the _count_tokens() approximation function."""

    def test_count_tokens_empty_string(self) -> None:
        """Empty string returns 1 (minimum from +1 bias)."""
        assert cer._count_tokens("") == 1

    def test_count_tokens_single_word(self) -> None:
        """Single word approximates to ~1.3 tokens, rounded up to 2."""
        result = cer._count_tokens("hello")
        assert result == 2  # int(1 * 1.3) + 1 = 1 + 1 = 2

    def test_count_tokens_proportional_to_words(self) -> None:
        """More words → more tokens, monotonically."""
        short = cer._count_tokens("one two three")
        long = cer._count_tokens(" ".join(["word"] * 100))
        assert long > short

    def test_count_tokens_approximation_factor(self) -> None:
        """100-word text approximates to ~130+ tokens."""
        text = " ".join(["word"] * 100)
        result = cer._count_tokens(text)
        assert result >= 130


# ---------------------------------------------------------------------------
# 9. Context building
# ---------------------------------------------------------------------------


class TestBuildEnrichmentContext:
    """Tests for _build_enrichment_context()."""

    def test_empty_results_returns_empty_string(self) -> None:
        """No results → empty string."""
        assert cer._build_enrichment_context([]) == ""

    def test_single_result_includes_header(self) -> None:
        """Single result gets the ## Enrichments header."""
        result = cer._EnrichmentResult(
            name="summarization",
            markdown="## Summary\n\nTest.",
            tokens=10,
            success=True,
        )
        context = cer._build_enrichment_context([result])
        assert context.startswith("## Enrichments")
        assert "## Summary" in context

    def test_multiple_results_separated_by_newlines(self) -> None:
        """Multiple results are joined with double newline."""
        results = [
            cer._EnrichmentResult("summarization", "## A\n\nFoo.", 5, True),
            cer._EnrichmentResult("code_analysis", "## B\n\nBar.", 5, True),
        ]
        context = cer._build_enrichment_context(results)
        assert "## A" in context
        assert "## B" in context
        assert "Foo" in context
        assert "Bar" in context
