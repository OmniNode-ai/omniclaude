# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Handler for context injection - all business logic lives here.

This handler performs:
1. File I/O to load patterns from disk
2. Filtering/sorting/limiting of patterns
3. Markdown formatting
4. Event emission to Kafka

Following ONEX patterns from omnibase_infra: handlers own all business logic.
No separate node is needed for simple file-read operations.

Part of OMN-1403: Context injection for session enrichment.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.handler_event_emitter import emit_hook_event
from omniclaude.hooks.schemas import ContextSource, ModelHookContextInjectedPayload

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================

# NOTE: ModelPatternRecord is the canonical definition. A standalone copy (PatternRecord)
# exists in plugins/onex/hooks/lib/learned_pattern_injector.py for CLI independence.
# If the schema changes, update BOTH files.


@dataclass(frozen=True)
class ModelPatternRecord:
    """A single learned pattern from persistence.

    Frozen dataclass to ensure immutability after loading.

    Note: This is the canonical definition. A standalone copy (PatternRecord with
    validation) exists in plugins/onex/hooks/lib/learned_pattern_injector.py
    for CLI independence. Keep both in sync if schema changes.

    Attributes:
        pattern_id: Unique identifier for the pattern.
        domain: Domain/category of the pattern (e.g., "code_review", "testing").
        title: Human-readable title for the pattern.
        description: Detailed description of what the pattern represents.
        confidence: Confidence score from 0.0 to 1.0.
        usage_count: Number of times this pattern has been applied.
        success_rate: Success rate from 0.0 to 1.0.
        example_reference: Optional reference to an example (e.g., "path/to/file.py:42").
    """

    pattern_id: str
    domain: str
    title: str
    description: str
    confidence: float
    usage_count: int
    success_rate: float
    example_reference: str | None = None


@dataclass(frozen=True)
class ModelInjectionResult:
    """Final result for hook consumption."""

    success: bool
    context_markdown: str
    pattern_count: int
    context_size_bytes: int
    source: str
    retrieval_ms: int


@dataclass(frozen=True)
class ModelLoadPatternsResult:
    """Result from loading patterns including source attribution.

    Attributes:
        patterns: List of unique pattern records.
        source_files: List of files that contributed at least one pattern.
    """

    patterns: list[ModelPatternRecord]
    source_files: list[Path]


# =============================================================================
# Handler Implementation
# =============================================================================


class HandlerContextInjection:
    """Handler for context injection from learned patterns.

    This handler implements the full context injection workflow:
    1. Load patterns from persistence files (I/O)
    2. Filter by domain and confidence threshold
    3. Sort by confidence descending
    4. Limit to max patterns
    5. Format as markdown
    6. Emit event to Kafka

    Following ONEX patterns from omnibase_infra:
    - Handlers own all business logic
    - No separate node needed for simple file-read operations
    - Stateless and async-safe

    Usage:
        >>> handler = HandlerContextInjection()
        >>> result = await handler.handle(project_root="/workspace/project")
        >>> if result.success:
        ...     print(result.context_markdown)
    """

    def __init__(
        self,
        config: ContextInjectionConfig | None = None,
    ) -> None:
        """Initialize the handler.

        Args:
            config: Optional configuration. If None, loads from environment at init time.
        """
        self._config = (
            config if config is not None else ContextInjectionConfig.from_env()
        )

    @property
    def handler_id(self) -> str:
        """Return the handler identifier."""
        return "handler-context-injection"

    async def handle(
        self,
        *,
        project_root: str | None = None,
        agent_domain: str = "",
        session_id: str = "",
        correlation_id: str = "",
        emit_event: bool = True,
    ) -> ModelInjectionResult:
        """Execute context injection workflow.

        Args:
            project_root: Optional project root path for pattern files.
            agent_domain: Domain to filter patterns by (empty = all).
            session_id: Session identifier for event emission.
            correlation_id: Correlation ID for distributed tracing.
            emit_event: Whether to emit Kafka event.

        Returns:
            ModelInjectionResult with formatted context markdown.
        """
        cfg = self._config

        if not cfg.enabled:
            return ModelInjectionResult(
                success=True,
                context_markdown="",
                pattern_count=0,
                context_size_bytes=0,
                source="disabled",
                retrieval_ms=0,
            )

        # Step 1: Load patterns from files (I/O) with configured timeout
        start_time = time.monotonic()
        timeout_seconds = cfg.timeout_ms / 1000.0
        try:
            load_result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._load_patterns_from_files,
                    project_root,
                ),
                timeout=timeout_seconds,
            )
            patterns = load_result.patterns
            retrieval_ms = int((time.monotonic() - start_time) * 1000)
            source = self._format_source_attribution(load_result.source_files)
        except TimeoutError:
            retrieval_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(f"Pattern loading timed out after {cfg.timeout_ms}ms")
            return ModelInjectionResult(
                success=True,  # Graceful degradation
                context_markdown="",
                pattern_count=0,
                context_size_bytes=0,
                source="timeout",
                retrieval_ms=retrieval_ms,
            )
        except Exception as e:
            retrieval_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(f"Pattern loading failed: {e}")
            return ModelInjectionResult(
                success=True,  # Graceful degradation
                context_markdown="",
                pattern_count=0,
                context_size_bytes=0,
                source="error",
                retrieval_ms=retrieval_ms,
            )

        # Step 2: Filter by domain
        if agent_domain:
            patterns = [
                p for p in patterns if p.domain == agent_domain or p.domain == "general"
            ]

        # Step 3: Filter by confidence threshold
        patterns = [p for p in patterns if p.confidence >= cfg.min_confidence]

        # Step 4: Sort by confidence descending
        patterns = sorted(patterns, key=lambda p: p.confidence, reverse=True)

        # Step 5: Limit to max patterns
        patterns = patterns[: cfg.max_patterns]

        # Step 6: Format as markdown
        context_markdown = self._format_patterns_markdown(patterns, cfg.max_patterns)
        context_size_bytes = len(context_markdown.encode("utf-8"))

        # Step 7: Emit event
        if emit_event and patterns:
            await self._emit_event(
                patterns=patterns,
                context_size_bytes=context_size_bytes,
                retrieval_ms=retrieval_ms,
                session_id=session_id,
                correlation_id=correlation_id,
                project_root=project_root,
                agent_domain=agent_domain,
                min_confidence=cfg.min_confidence,
            )

        return ModelInjectionResult(
            success=True,
            context_markdown=context_markdown,
            pattern_count=len(patterns),
            context_size_bytes=context_size_bytes,
            source=source,
            retrieval_ms=retrieval_ms,
        )

    # =========================================================================
    # File I/O Methods
    # =========================================================================

    def _load_patterns_from_files(
        self,
        project_root: str | None,
    ) -> ModelLoadPatternsResult:
        """Load patterns from persistence files.

        Finds and parses all pattern files, deduplicating by pattern_id.
        Tracks which files contributed at least one pattern for accurate
        source attribution.

        Args:
            project_root: Optional project root path.

        Returns:
            ModelLoadPatternsResult with unique patterns and contributing source files.
        """
        all_patterns: list[ModelPatternRecord] = []
        contributing_files: list[Path] = []

        # Find pattern files using config's persistence_file path
        pattern_files = self._find_pattern_files(
            Path(project_root) if project_root else None,
            self._config.persistence_file,
        )

        if not pattern_files:
            logger.debug("No pattern files found")
            return ModelLoadPatternsResult(patterns=[], source_files=[])

        # Parse each file
        for file_path in pattern_files:
            try:
                patterns = self._parse_pattern_file(file_path)
                if patterns:  # Only track files that contributed patterns
                    all_patterns.extend(patterns)
                    contributing_files.append(file_path)
                logger.debug(f"Loaded {len(patterns)} patterns from {file_path}")
            except Exception as e:
                logger.warning(f"Failed to parse {file_path}: {e}")
                continue

        # Deduplicate by pattern_id (keep first occurrence)
        seen_ids: set[str] = set()
        unique_patterns: list[ModelPatternRecord] = []
        for pattern in all_patterns:
            if pattern.pattern_id not in seen_ids:
                seen_ids.add(pattern.pattern_id)
                unique_patterns.append(pattern)

        return ModelLoadPatternsResult(
            patterns=unique_patterns, source_files=contributing_files
        )

    def _find_pattern_files(
        self, project_root: Path | None, persistence_file: str
    ) -> list[Path]:
        """Find learned pattern files in standard locations.

        Searches:
        1. Project-specific: {project_root}/{persistence_file}
        2. User-level: ~/.claude/learned_patterns.json (standard fallback)

        Args:
            project_root: Optional project root path.
            persistence_file: Relative path to patterns file from config
                (e.g., ".claude/learned_patterns.json").
        """
        candidates: list[Path] = []

        # Project-specific patterns (uses configurable persistence_file)
        if project_root and project_root.is_dir():
            project_file = project_root / persistence_file
            if project_file.exists():
                candidates.append(project_file)

        # User-level patterns (uses filename from persistence_file config)
        persistence_filename = Path(persistence_file).name
        user_file = Path.home() / ".claude" / persistence_filename
        if user_file.exists():
            candidates.append(user_file)

        return candidates

    def _parse_pattern_file(self, file_path: Path) -> list[ModelPatternRecord]:
        """Parse a learned_patterns.json file."""
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("Pattern file must be a JSON object")

        patterns_data = data.get("patterns", [])
        if not isinstance(patterns_data, list):
            raise ValueError("'patterns' must be a list")

        records: list[ModelPatternRecord] = []
        for idx, item in enumerate(patterns_data):
            try:
                record = ModelPatternRecord(
                    pattern_id=item["pattern_id"],
                    domain=item["domain"],
                    title=item["title"],
                    description=item["description"],
                    confidence=float(item["confidence"]),
                    usage_count=int(item["usage_count"]),
                    success_rate=float(item["success_rate"]),
                    example_reference=item.get("example_reference"),
                )
                records.append(record)
            except (KeyError, TypeError, ValueError) as e:
                logger.debug(f"Skipping invalid pattern at index {idx}: {e}")
                continue

        return records

    def _format_source_attribution(self, source_files: list[Path]) -> str:
        """Format source file paths for accurate attribution.

        When patterns come from multiple files, lists all contributing files
        to avoid misleading attribution.

        Args:
            source_files: List of files that contributed patterns.

        Returns:
            Formatted source string (single path or comma-separated list).
        """
        if not source_files:
            return "none"
        if len(source_files) == 1:
            return str(source_files[0])
        # Multiple sources - list all to avoid misleading attribution
        return ", ".join(str(f) for f in source_files)

    # =========================================================================
    # Formatting Methods
    # =========================================================================

    def _format_patterns_markdown(
        self,
        patterns: list[ModelPatternRecord],
        max_patterns: int,
    ) -> str:
        """Format patterns as markdown for context injection."""
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
            lines.append(
                f"- **Success Rate**: {success_pct} ({pattern.usage_count} uses)"
            )
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

    # =========================================================================
    # Event Emission
    # =========================================================================

    async def _emit_event(
        self,
        *,
        patterns: list[ModelPatternRecord],
        context_size_bytes: int,
        retrieval_ms: int,
        session_id: str,
        correlation_id: str,
        project_root: str | None,
        agent_domain: str,
        min_confidence: float,
    ) -> None:
        """Emit context injection event to Kafka."""
        # Derive entity_id
        if session_id:
            try:
                entity_id = UUID(session_id)
            except ValueError:
                entity_id = self._derive_deterministic_id(
                    correlation_id or str(uuid4()), project_root
                )
        elif correlation_id:
            entity_id = self._derive_deterministic_id(correlation_id, project_root)
        else:
            # Cannot derive meaningful entity_id - skip
            return

        # Resolve correlation_id to UUID, handling non-UUID values gracefully
        resolved_correlation_id: UUID
        if correlation_id:
            try:
                resolved_correlation_id = UUID(correlation_id)
            except ValueError:
                # Non-UUID correlation_id - derive deterministic UUID to preserve traceability
                logger.warning(
                    f"Non-UUID correlation_id '{correlation_id[:50]}...' - deriving deterministic UUID"
                )
                resolved_correlation_id = self._derive_deterministic_id(
                    correlation_id, project_root
                )
        else:
            resolved_correlation_id = entity_id

        try:
            payload = ModelHookContextInjectedPayload(
                entity_id=entity_id,
                session_id=session_id or str(entity_id),
                correlation_id=resolved_correlation_id,
                causation_id=uuid4(),
                emitted_at=datetime.now(UTC),
                context_source=ContextSource.PERSISTENCE_FILE,
                pattern_count=len(patterns),
                context_size_bytes=context_size_bytes,
                agent_domain=agent_domain or None,
                min_confidence_threshold=min_confidence,
                retrieval_duration_ms=retrieval_ms,
            )
            await emit_hook_event(payload)
            logger.debug(f"Context injection event emitted: {len(patterns)} patterns")
        except Exception as e:
            logger.warning(f"Failed to emit context injection event: {e}")

    def _derive_deterministic_id(
        self,
        correlation_id: str,
        project_root: str | None,
    ) -> UUID:
        """Derive a deterministic UUID from correlation_id and project."""
        seed = f"{correlation_id}:{project_root or 'global'}"
        hash_bytes = hashlib.sha256(seed.encode()).hexdigest()[:32]
        return UUID(hash_bytes)


# =============================================================================
# Convenience Functions (for backward compatibility)
# =============================================================================

# Global handler instance for simple usage
_default_handler: HandlerContextInjection | None = None


def _get_default_handler() -> HandlerContextInjection:
    """Get or create default handler instance."""
    global _default_handler
    if _default_handler is None:
        _default_handler = HandlerContextInjection()
    return _default_handler


async def inject_patterns(
    *,
    project_root: str | None = None,
    agent_domain: str = "",
    session_id: str = "",
    correlation_id: str = "",
    config: ContextInjectionConfig | None = None,
    emit_event: bool = True,
) -> ModelInjectionResult:
    """Convenience function for context injection.

    Creates a handler and invokes it. For repeated calls, consider
    creating a HandlerContextInjection instance directly.
    """
    handler = (
        HandlerContextInjection(config=config) if config else _get_default_handler()
    )
    return await handler.handle(
        project_root=project_root,
        agent_domain=agent_domain,
        session_id=session_id,
        correlation_id=correlation_id,
        emit_event=emit_event,
    )


def inject_patterns_sync(
    *,
    project_root: str | None = None,
    agent_domain: str = "",
    session_id: str = "",
    correlation_id: str = "",
    config: ContextInjectionConfig | None = None,
    emit_event: bool = True,
) -> ModelInjectionResult:
    """Synchronous wrapper for shell scripts.

    Handles nested event loop detection to avoid RuntimeError.
    """
    try:
        asyncio.get_running_loop()
        # Already in async context - use thread pool
        logger.warning("inject_patterns_sync called from async context")
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                inject_patterns(
                    project_root=project_root,
                    agent_domain=agent_domain,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    config=config,
                    emit_event=emit_event,
                ),
            )
            return future.result()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(
            inject_patterns(
                project_root=project_root,
                agent_domain=agent_domain,
                session_id=session_id,
                correlation_id=correlation_id,
                config=config,
                emit_event=emit_event,
            )
        )


__all__ = [
    # Models
    "ModelPatternRecord",
    "ModelInjectionResult",
    # Handler class
    "HandlerContextInjection",
    # Convenience functions
    "inject_patterns",
    "inject_patterns_sync",
]
