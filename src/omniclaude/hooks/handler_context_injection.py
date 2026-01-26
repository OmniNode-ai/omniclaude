"""Handler for context injection - orchestration layer.

This handler:
1. Calls the effect node (I/O) - returns raw patterns
2. Applies filtering/sorting/limiting (post-I/O processing)
3. Formats results (pure helper)
4. Emits events (omniclaude publish helper)

NOTE: emit_hook_event() is omniclaude's handler-layer plumbing for
publishing to Kafka. It is NOT a true ONEX runtime primitive.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.handler_event_emitter import emit_hook_event
from omniclaude.hooks.node_context_injection_effect import (
    ModelContextRetrievalContract,
    ModelPatternRecord,
    NodeContextInjectionEffect,
)
from omniclaude.hooks.schemas import ContextSource, ModelHookContextInjectedPayload

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelInjectionResult:
    """Final result for hook consumption."""

    success: bool
    context_markdown: str
    pattern_count: int
    context_size_bytes: int
    source: str
    retrieval_ms: int


def _format_patterns_markdown(
    patterns: list[ModelPatternRecord],
    max_patterns: int,
) -> str:
    """
    Pure function: Format patterns as markdown.
    NOT a node operation - just a helper function.
    """
    if not patterns:
        return ""

    patterns_to_format = patterns[:max_patterns]

    lines: list[str] = [
        "## Learned Patterns (Auto-Injected)",
        "",
        "The following patterns have been learned from previous sessions:",
        "",
    ]

    for pattern in patterns_to_format:
        confidence_pct = f"{pattern.confidence * 100:.0f}%"
        success_pct = f"{pattern.success_rate * 100:.0f}%"

        lines.append(f"### {pattern.title}")
        lines.append("")
        lines.append(f"- **Domain**: {pattern.domain}")
        lines.append(f"- **Confidence**: {confidence_pct}")
        lines.append(f"- **Success Rate**: {success_pct} ({pattern.usage_count} uses)")
        lines.append("")
        lines.append(pattern.description)
        lines.append("")

        if pattern.example_reference:
            lines.append(f"*Example: `{pattern.example_reference}`*")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Remove trailing separator
    if lines[-2:] == ["---", ""]:
        lines = lines[:-2]

    return "\n".join(lines)


def _derive_deterministic_session_id(
    correlation_id: str,
    project_root: str | None,
) -> UUID:
    """
    Derive a deterministic UUID when session_id is missing.
    """
    seed = f"{correlation_id}:{project_root or 'global'}"
    hash_bytes = hashlib.sha256(seed.encode()).hexdigest()[:32]
    return UUID(hash_bytes)


async def inject_patterns(
    *,
    project_root: str | None = None,
    agent_domain: str = "",
    session_id: str = "",
    correlation_id: str = "",
    config: ContextInjectionConfig | None = None,
    emit_event: bool = True,
) -> ModelInjectionResult:
    """
    Orchestrate context injection.

    1. Call effect node (I/O) - returns raw patterns
    2. Apply filtering/sorting/limiting (handler's job)
    3. Format result (pure)
    4. Emit event (omniclaude publish helper)
    """
    cfg = config or ContextInjectionConfig.from_env()

    if not cfg.enabled:
        return ModelInjectionResult(
            success=True,
            context_markdown="",
            pattern_count=0,
            context_size_bytes=0,
            source="disabled",
            retrieval_ms=0,
        )

    # Step 1: Effect node (I/O) - returns RAW patterns
    node = NodeContextInjectionEffect()
    result = await node.execute_effect(
        ModelContextRetrievalContract(
            project_root=project_root,
            domain=agent_domain,
        )
    )

    if not result.success:
        return ModelInjectionResult(
            success=True,  # Graceful degradation
            context_markdown="",
            pattern_count=0,
            context_size_bytes=0,
            source="error",
            retrieval_ms=result.retrieval_ms,
        )

    # Step 2: Filtering/sorting/limiting (handler's job, not node's)
    patterns = list(result.patterns)

    # Filter by domain if specified
    if agent_domain:
        patterns = [
            p for p in patterns if p.domain == agent_domain or p.domain == "general"
        ]

    # Filter by confidence threshold
    patterns = [p for p in patterns if p.confidence >= cfg.min_confidence]

    # Sort by confidence (descending)
    patterns = sorted(patterns, key=lambda p: p.confidence, reverse=True)

    # Limit to max_patterns
    patterns = patterns[: cfg.max_patterns]

    # Step 3: Pure formatting (helper function, not node)
    context_markdown = _format_patterns_markdown(patterns, cfg.max_patterns)
    context_size_bytes = len(context_markdown.encode("utf-8"))

    # Step 4: Event emission (omniclaude publish helper)
    if emit_event and patterns:
        # Derive deterministic entity_id if session_id missing
        if session_id:
            try:
                entity_id = UUID(session_id)
            except ValueError:
                entity_id = _derive_deterministic_session_id(
                    correlation_id or str(uuid4()), project_root
                )
        elif correlation_id:
            entity_id = _derive_deterministic_session_id(correlation_id, project_root)
        else:
            # Cannot derive meaningful entity_id - skip emission
            emit_event = False

        if emit_event:
            try:
                payload = ModelHookContextInjectedPayload(
                    entity_id=entity_id,
                    session_id=session_id or str(entity_id),
                    correlation_id=UUID(correlation_id)
                    if correlation_id
                    else entity_id,
                    causation_id=uuid4(),
                    emitted_at=datetime.now(UTC),
                    context_source=ContextSource.PERSISTENCE_FILE,
                    pattern_count=len(patterns),
                    context_size_bytes=context_size_bytes,
                    agent_domain=agent_domain or None,
                    min_confidence_threshold=cfg.min_confidence,
                    retrieval_duration_ms=result.retrieval_ms,
                )
                await emit_hook_event(payload)
                logger.debug(
                    f"Context injection event emitted: {len(patterns)} patterns"
                )
            except Exception as e:
                # Log but don't fail - event emission is observability
                logger.warning(f"Failed to emit context injection event: {e}")

    return ModelInjectionResult(
        success=True,
        context_markdown=context_markdown,
        pattern_count=len(patterns),
        context_size_bytes=context_size_bytes,
        source=result.source,
        retrieval_ms=result.retrieval_ms,
    )


def inject_patterns_sync(**kwargs) -> ModelInjectionResult:
    """
    Synchronous wrapper for shell scripts.

    Handles nested event loop detection to avoid RuntimeError when
    called from contexts that already have a running loop.
    """
    try:
        asyncio.get_running_loop()
        # Already in async context - use thread pool to run async function
        logger.warning("inject_patterns_sync called from async context")
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, inject_patterns(**kwargs))
            return future.result()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(inject_patterns(**kwargs))


__all__ = [
    "ModelInjectionResult",
    "inject_patterns",
    "inject_patterns_sync",
]
