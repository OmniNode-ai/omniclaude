#!/usr/bin/env python3
"""CLI wrapper for local enrichment pipeline (OMN-2267).

Runs three enrichments in parallel (code analysis, similarity, summarization)
using asyncio.gather with per-enrichment and total timeouts. Applies a token
cap with priority-based drop policy.

IMPORTANT: Always exits with code 0 for hook compatibility.
Any errors result in empty enrichment_context, not failures.

Feature flags (both must be set to "true"):
    ENABLE_LOCAL_INFERENCE_PIPELINE  -- outer gate
    ENABLE_LOCAL_ENRICHMENT          -- inner gate

Usage:
    echo '{"prompt": "...", "session_id": "uuid", "project_path": "/path"}' \\
        | python context_enrichment_runner.py

Input JSON:
    {
        "prompt": "user prompt text",
        "session_id": "uuid",
        "project_path": "/path/to/project"
    }

Output JSON:
    {
        "success": true,
        "enrichment_context": "## Enrichments\\n\\n...",
        "tokens_used": 450,
        "enrichment_count": 2
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Logging — stderr only; stdout is reserved for JSON output
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional handler imports — graceful degradation when omnibase_infra absent
# ---------------------------------------------------------------------------
import os as _os

if _os.environ.get("OMNICLAUDE_NO_HANDLERS") == "1":
    # Test isolation guard: skip all handler imports to prevent import-time
    # blocking when omnibase_infra handlers try to connect to services.
    HandlerCodeAnalysisEnrichment = None
    HandlerSimilarityEnrichment = None
    HandlerSummarizationEnrichment = None
else:
    try:
        from omnibase_infra.nodes.node_llm_inference_effect.handlers.handler_code_analysis_enrichment import (  # type: ignore[no-redef]  # noqa: E501
            HandlerCodeAnalysisEnrichment,
        )
    except ImportError:
        HandlerCodeAnalysisEnrichment = None

    try:
        from omnibase_infra.nodes.node_llm_embedding_effect.handlers.handler_similarity_enrichment import (  # type: ignore[no-redef]  # noqa: E501
            HandlerSimilarityEnrichment,
        )
    except ImportError:
        HandlerSimilarityEnrichment = None

    try:
        from omnibase_infra.nodes.node_llm_inference_effect.handlers.handler_summarization_enrichment import (  # type: ignore[no-redef]  # noqa: E501
            HandlerSummarizationEnrichment,
        )
    except ImportError:
        HandlerSummarizationEnrichment = None

# ---------------------------------------------------------------------------
# Optional observability emitter — graceful degradation when unavailable
# ---------------------------------------------------------------------------
try:
    from enrichment_observability_emitter import (
        emit_enrichment_events as _emit_enrichment_events,
    )
except ImportError:
    _emit_enrichment_events = None

# Optional emit client reset — graceful degradation when unavailable
try:
    from emit_client_wrapper import reset_client as _reset_emit_client
except ImportError:
    _reset_emit_client = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_PER_ENRICHMENT_TIMEOUT_S: float = 0.150  # 150ms
_TOTAL_TIMEOUT_S: float = 0.200  # 200ms
_TOKEN_CAP: int = 2000

# Priority order: highest-priority first (drop lowest first when over cap)
# Index 0 = highest priority
_PRIORITY_ORDER: list[str] = ["summarization", "code_analysis", "similarity"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_float(value: Any) -> float | None:
    """Convert value to float, returning None on any failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Token counting helper (no tiktoken dependency)
# ---------------------------------------------------------------------------
def _count_tokens(text: str) -> int:
    """Approximate token count using word-split heuristic.

    Approximation: len(text.split()) * 1.3, rounded up.
    """
    return int(len(text.split()) * 1.3) + 1


# ---------------------------------------------------------------------------
# Enrichment result container
# ---------------------------------------------------------------------------
class _EnrichmentResult:
    """Holds the result from a single enrichment handler."""

    def __init__(
        self,
        name: str,
        markdown: str,
        tokens: int,
        success: bool,
        *,
        latency_ms: float = 0.0,
        model_used: str = "",
        relevance_score: float | None = None,
        fallback_used: bool = False,
        prompt_version: str = "",
    ) -> None:
        self.name = name
        self.markdown = markdown
        self.tokens = tokens
        self.success = success
        # Observability fields (OMN-2274)
        self.latency_ms = latency_ms
        self.model_used = model_used
        self.relevance_score = relevance_score
        self.fallback_used = fallback_used
        self.prompt_version = prompt_version


# ---------------------------------------------------------------------------
# Async enrichment runner
# ---------------------------------------------------------------------------
async def _run_single_enrichment(
    name: str,
    handler: Any,
    prompt: str,
    project_path: str,
) -> _EnrichmentResult:
    """Run a single enrichment handler with a per-enrichment timeout."""
    t0 = asyncio.get_running_loop().time()
    try:
        result = await asyncio.wait_for(
            handler.enrich(prompt=prompt, project_path=project_path),
            timeout=_PER_ENRICHMENT_TIMEOUT_S,
        )
        latency_ms = (asyncio.get_running_loop().time() - t0) * 1000.0
        if result.success:
            tokens = _count_tokens(result.markdown)  # noqa: secrets
            return _EnrichmentResult(
                name=name,
                markdown=result.markdown,
                tokens=tokens,
                success=True,
                latency_ms=latency_ms,
                model_used=str(getattr(result, "model_used", "") or ""),
                relevance_score=_safe_float(getattr(result, "relevance_score", None)),
                fallback_used=bool(getattr(result, "fallback_used", False)),
                prompt_version=str(getattr(result, "prompt_version", "") or ""),
            )
        latency_ms = (asyncio.get_running_loop().time() - t0) * 1000.0
        return _EnrichmentResult(
            name=name, markdown="", tokens=0, success=False, latency_ms=latency_ms
        )
    except Exception as exc:
        latency_ms = (asyncio.get_running_loop().time() - t0) * 1000.0
        if isinstance(exc, TimeoutError):
            logger.debug("Enrichment %r timed out: %s", name, exc)
        else:
            logger.warning("Enrichment %r failed unexpectedly: %s", name, exc)
        return _EnrichmentResult(
            name=name, markdown="", tokens=0, success=False, latency_ms=latency_ms
        )


async def _run_all_enrichments(
    prompt: str,
    project_path: str,
) -> list[_EnrichmentResult]:
    """Run all available enrichments in parallel within the total budget.

    Applies a 200ms outer timeout. Any tasks still pending when the budget
    expires are cancelled.
    """
    # Build task list for available handlers only
    tasks: list[asyncio.Task[_EnrichmentResult]] = []

    handler_map: list[tuple[str, Any]] = [
        ("summarization", HandlerSummarizationEnrichment),
        ("code_analysis", HandlerCodeAnalysisEnrichment),
        ("similarity", HandlerSimilarityEnrichment),
    ]

    for name, cls in handler_map:
        if cls is not None:
            handler_instance = cls()
            task = asyncio.create_task(
                _run_single_enrichment(name, handler_instance, prompt, project_path)
            )
            tasks.append(task)

    if not tasks:
        return []

    results: list[_EnrichmentResult] = []
    try:
        gathered = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=_TOTAL_TIMEOUT_S,
        )
        for item in gathered:
            if isinstance(item, BaseException):
                # Individual task raised an exception — treat as empty
                continue
            results.append(item)
    except TimeoutError:
        logger.debug(
            "Total enrichment budget (%sms) expired", int(_TOTAL_TIMEOUT_S * 1000)
        )
        # Cancel any still-pending tasks
        for task in tasks:
            if not task.done():
                task.cancel()
        # Collect whatever finished before timeout
        for task in tasks:
            if task.done() and not task.cancelled():
                exc = task.exception()
                if exc is None:
                    results.append(task.result())

    return results


# ---------------------------------------------------------------------------
# Token cap with priority-based drop policy
# ---------------------------------------------------------------------------
def _apply_token_cap(results: list[_EnrichmentResult]) -> list[_EnrichmentResult]:
    """Drop lowest-priority enrichments first until total tokens <= _TOKEN_CAP.

    Priority order (highest first): summarization > code_analysis > similarity
    """
    # Keep only successful results
    successful = [r for r in results if r.success and r.markdown]
    if not successful:
        return []

    total_tokens = sum(r.tokens for r in successful)
    if total_tokens <= _TOKEN_CAP:
        return successful

    # Sort by priority descending (highest priority first)
    def _priority_key(r: _EnrichmentResult) -> int:
        try:
            # Lower index = higher priority; invert for sort
            return _PRIORITY_ORDER.index(r.name)
        except ValueError:
            return len(_PRIORITY_ORDER)  # Unknown → lowest priority

    sorted_results = sorted(successful, key=_priority_key)

    # Greedily keep highest-priority items within token cap.
    # Always include at least the highest-priority item — if we have enrichments
    # but none fit the cap, the highest-priority one is still more useful than nothing.
    kept: list[_EnrichmentResult] = []
    running_tokens = 0
    for r in sorted_results:
        if running_tokens + r.tokens <= _TOKEN_CAP:
            kept.append(r)
            running_tokens += r.tokens
        # Skip (drop) this enrichment — over budget

    # If nothing fit (every single enrichment exceeds the cap), keep the highest-priority one.
    if not kept and sorted_results:
        kept = [sorted_results[0]]

    return kept


# ---------------------------------------------------------------------------
# Output construction
# ---------------------------------------------------------------------------
def _build_enrichment_context(results: list[_EnrichmentResult]) -> str:
    """Combine enrichment markdowns into a single context string."""
    if not results:
        return ""

    sections: list[str] = []
    for r in results:
        if r.markdown:
            sections.append(r.markdown)

    if not sections:
        return ""

    return "## Enrichments\n\n" + "\n\n".join(sections)


def _empty_output() -> dict[str, Any]:
    return {
        "success": False,
        "enrichment_context": "",
        "tokens_used": 0,
        "enrichment_count": 0,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """CLI entry point for the enrichment pipeline.

    IMPORTANT: Always exits with code 0 for hook compatibility.
    """
    # Feature flag checks (outer and inner)
    enable_pipeline = os.environ.get("ENABLE_LOCAL_INFERENCE_PIPELINE", "false").lower()
    enable_enrichment = os.environ.get("ENABLE_LOCAL_ENRICHMENT", "false").lower()

    if enable_pipeline != "true" or enable_enrichment != "true":
        print(json.dumps(_empty_output()))
        sys.exit(0)

    # Cap the emit socket timeout to 50ms when running as a subprocess.
    # The default 5s socket timeout can cause subprocess.run(timeout=5) to
    # expire in test environments where no emit daemon is present (OMN-2344).
    os.environ.setdefault("OMNICLAUDE_EMIT_TIMEOUT", "0.05")
    if _reset_emit_client is not None:
        _reset_emit_client()

    # Check that at least one handler is available
    if all(
        cls is None
        for cls in [
            HandlerCodeAnalysisEnrichment,
            HandlerSimilarityEnrichment,
            HandlerSummarizationEnrichment,
        ]
    ):
        logger.debug("No enrichment handlers available (omnibase_infra not installed)")
        print(json.dumps(_empty_output()))
        sys.exit(0)

    try:
        raw = sys.stdin.read().strip()

        if not raw:
            logger.debug("Empty stdin received")
            print(json.dumps(_empty_output()))
            sys.exit(0)

        try:
            input_data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON input: %s", exc)
            print(json.dumps(_empty_output()))
            sys.exit(0)

        prompt: str = input_data.get("prompt", "") or ""
        session_id: str = input_data.get("session_id", "") or ""
        correlation_id: str = input_data.get("correlation_id", "") or ""
        project_path: str = input_data.get("project_path", "") or ""

        if not prompt:
            logger.debug("Empty prompt in input")
            print(json.dumps(_empty_output()))
            sys.exit(0)

        # Approximate token count of the raw prompt for tokens_saved computation
        original_prompt_token_count = _count_tokens(prompt)  # noqa: secrets

        # Run enrichments
        raw_results = asyncio.run(
            _run_all_enrichments(prompt=prompt, project_path=project_path)
        )

        # Apply token cap
        kept_results = _apply_token_cap(raw_results)

        # Emit per-enrichment observability events (OMN-2274).
        # Fire-and-forget: errors must not affect the hook output.
        if _emit_enrichment_events is not None and raw_results:
            kept_names = {r.name for r in kept_results}
            try:
                _emit_enrichment_events(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    results=raw_results,
                    kept_names=kept_names,
                    original_prompt_token_count=original_prompt_token_count,
                )
            except Exception as _obs_exc:
                logger.debug("Enrichment observability emission failed: %s", _obs_exc)

        if not kept_results:
            print(json.dumps(_empty_output()))
            sys.exit(0)

        enrichment_context = _build_enrichment_context(kept_results)
        tokens_used = sum(r.tokens for r in kept_results)  # noqa: secrets

        output: dict[str, Any] = {
            "success": True,
            "enrichment_context": enrichment_context,
            "tokens_used": tokens_used,
            "enrichment_count": len(kept_results),
        }
        print(json.dumps(output))
        sys.exit(0)

    except Exception as exc:
        # Catch-all — always exit 0 for hook compatibility
        logger.error("Unexpected error in enrichment runner: %s", exc)
        print(json.dumps(_empty_output()))
        sys.exit(0)


if __name__ == "__main__":
    main()
