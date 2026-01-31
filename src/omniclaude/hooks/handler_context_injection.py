# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Handler for context injection - all business logic lives here.

This handler performs:
1. Database query to load patterns (primary source)
2. Optional file I/O fallback if database unavailable
3. Filtering/sorting/limiting of patterns
4. Markdown formatting
5. Event emission to Kafka

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
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from omniclaude.hooks.cohort_assignment import (
    CohortAssignment,
    EnumCohort,
    assign_cohort,
)
from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.handler_event_emitter import emit_hook_event
from omniclaude.hooks.injection_limits import (
    INJECTION_HEADER,
    count_tokens,
    select_patterns_for_injection,
)
from omniclaude.hooks.models_injection_tracking import (
    EnumInjectionContext,
    EnumInjectionSource,
)
from omniclaude.hooks.schemas import ContextSource, ModelHookContextInjectedPayload

if TYPE_CHECKING:
    from omniclaude.nodes.node_pattern_persistence_effect.protocols import (
        ProtocolPatternPersistence,
    )


# Exception classes for graceful degradation
class PatternPersistenceError(Exception):
    """Base error for pattern persistence operations."""

    pass


class PatternConnectionError(PatternPersistenceError):
    """Error when persistence backend connection fails."""

    pass


logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


@dataclass(frozen=True)
class PatternRecord:
    """API transfer model for learned patterns.

    This is the canonical API model with 8 core fields, used for:
    - Context injection into Claude Code sessions
    - JSON serialization in API responses
    - Data transfer between components

    Frozen to ensure immutability after creation. Validation happens
    in __post_init__ before the instance is frozen.

    Architecture Note:
        This class is intentionally duplicated in plugins/onex/hooks/lib/pattern_types.py
        for CLI subprocess independence. Both definitions MUST stay in sync.
        See tests/hooks/test_pattern_sync.py for sync verification.

        For database persistence, use NodePatternPersistenceEffect with
        ProtocolPatternPersistence from omniclaude.nodes.node_pattern_persistence_effect.

    Attributes:
        pattern_id: Unique identifier for the pattern.
        domain: Domain/category of the pattern (e.g., "code_review", "testing").
        title: Human-readable title for the pattern.
        description: Detailed description of what the pattern represents.
        confidence: Confidence score from 0.0 to 1.0.
        usage_count: Number of times this pattern has been applied.
        success_rate: Success rate from 0.0 to 1.0.
        example_reference: Optional reference to an example.

    See Also:
        - DbPatternRecord: Database model (12 fields) in repository_patterns.py
        - PatternRecord (CLI): CLI model (8 fields) in plugins/onex/hooks/lib/pattern_types.py
    """

    pattern_id: str
    domain: str
    title: str
    description: str
    confidence: float
    usage_count: int
    success_rate: float
    example_reference: str | None = None

    def __post_init__(self) -> None:
        """Validate fields after initialization (runs before instance is frozen)."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
        if not 0.0 <= self.success_rate <= 1.0:
            raise ValueError(
                f"success_rate must be between 0.0 and 1.0, got {self.success_rate}"
            )
        if self.usage_count < 0:
            raise ValueError(
                f"usage_count must be non-negative, got {self.usage_count}"
            )


# Alias for backward compatibility with tests and exports
ModelPatternRecord = PatternRecord


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
    1. Load patterns from database (primary) or files (fallback)
    2. Filter by domain and confidence threshold
    3. Sort by confidence descending
    4. Limit to max patterns
    5. Format as markdown
    6. Emit event to Kafka

    Following ONEX patterns from omnibase_infra:
    - Handlers own all business logic
    - Database-backed storage with file fallback
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
        persistence: ProtocolPatternPersistence | None = None,
    ) -> None:
        """Initialize the handler.

        Args:
            config: Optional configuration. If None, loads from environment at init time.
            persistence: Optional ProtocolPatternPersistence implementation for
                database access. If None, creates one from config when db_enabled
                is True. When provided externally, lifecycle is managed by caller.
        """
        self._config = (
            config if config is not None else ContextInjectionConfig.from_env()
        )
        self._persistence = persistence
        # Track whether we created the persistence handler (and thus should close it)
        self._persistence_owned = persistence is None

    @property
    def handler_id(self) -> str:
        """Return the handler identifier."""
        return "handler-context-injection"

    async def close(self) -> None:
        """Close database connections.

        Should be called when the handler is no longer needed to release
        database pool resources. Safe to call multiple times.

        Only closes resources if the persistence handler was created internally
        (not provided externally via constructor).
        """
        if self._persistence is not None and self._persistence_owned:
            # Check if persistence handler has a close method
            if hasattr(self._persistence, "close"):
                try:
                    await self._persistence.close()
                except Exception as e:
                    logger.warning(f"Error closing persistence handler: {e}")
            self._persistence = None
        elif self._persistence is not None:
            # Persistence was provided externally, just clear our reference
            self._persistence = None

    def _emit_injection_record(
        self,
        *,
        injection_id: UUID,
        session_id_raw: str,
        pattern_ids: list[str],
        injection_context: EnumInjectionContext,
        source: EnumInjectionSource,
        cohort: EnumCohort,
        assignment_seed: int,
        injected_content: str,
        injected_token_count: int,
        correlation_id: str = "",
    ) -> bool:
        """Emit injection record via emit daemon.

        Non-blocking, returns True on success, False on failure.
        Uses emit daemon for durability (not asyncio.create_task).
        """
        try:
            # Lazy import to avoid circular dependencies in hook subprocess
            from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

            payload = {
                "injection_id": str(injection_id),
                "session_id": session_id_raw,
                "pattern_ids": pattern_ids,
                "injection_context": injection_context.value,
                "source": source.value,
                "cohort": cohort.value,
                "assignment_seed": assignment_seed,
                "injected_content": injected_content,
                "injected_token_count": injected_token_count,
                "correlation_id": correlation_id,
            }

            return emit_event("injection.recorded", payload)
        except Exception as e:
            logger.warning(f"Failed to emit injection record: {e}")
            return False

    async def handle(
        self,
        *,
        project_root: str | None = None,
        agent_domain: str = "",
        session_id: str = "",
        correlation_id: str = "",
        emit_event: bool = True,
        injection_context: EnumInjectionContext = EnumInjectionContext.USER_PROMPT_SUBMIT,
    ) -> ModelInjectionResult:
        """Execute context injection workflow.

        Args:
            project_root: Optional project root path for pattern files.
            agent_domain: Domain to filter patterns by (empty = all).
            session_id: Session identifier for event emission.
            correlation_id: Correlation ID for distributed tracing.
            emit_event: Whether to emit Kafka event.
            injection_context: Hook event that triggered injection (for A/B tracking).

        Returns:
            ModelInjectionResult with formatted context markdown.
        """
        cfg = self._config

        # Generate injection_id at start (for ALL attempts, including control/error)
        injection_id = uuid4()

        # Cohort assignment (before any work)
        cohort_assignment: CohortAssignment | None = None
        if session_id:
            cohort_assignment = assign_cohort(session_id)

            # Control cohort: record and return early (no pattern injection)
            if cohort_assignment.cohort == EnumCohort.CONTROL:
                self._emit_injection_record(
                    injection_id=injection_id,
                    session_id_raw=session_id,
                    pattern_ids=[],
                    injection_context=injection_context,
                    source=EnumInjectionSource.CONTROL_COHORT,
                    cohort=cohort_assignment.cohort,
                    assignment_seed=cohort_assignment.assignment_seed,
                    injected_content="",
                    injected_token_count=0,
                    correlation_id=correlation_id,
                )
                logger.info(f"Session {session_id[:8]}... assigned to control cohort")
                return ModelInjectionResult(
                    success=True,
                    context_markdown="",
                    pattern_count=0,
                    context_size_bytes=0,
                    source="control_cohort",
                    retrieval_ms=0,
                )

        if not cfg.enabled:
            return ModelInjectionResult(
                success=True,
                context_markdown="",
                pattern_count=0,
                context_size_bytes=0,
                source="disabled",
                retrieval_ms=0,
            )

        # Step 1: Load patterns (database primary, file fallback)
        start_time = time.monotonic()
        timeout_seconds = cfg.timeout_ms / 1000.0
        patterns: list[ModelPatternRecord] = []
        source = "none"
        context_source = ContextSource.PERSISTENCE_FILE  # Default for events

        try:
            # Try database first if enabled
            if cfg.db_enabled:
                try:
                    db_result = await asyncio.wait_for(
                        self._load_patterns_from_database(
                            domain=agent_domain,
                            project_scope=project_root,
                        ),
                        timeout=timeout_seconds,
                    )
                    patterns = db_result.patterns
                    source = self._format_source_attribution(db_result.source_files)
                    context_source = ContextSource.DATABASE
                    logger.debug(f"Loaded {len(patterns)} patterns from database")
                except Exception as db_err:
                    logger.warning(f"Database pattern loading failed: {db_err}")
                    # Fall through to file fallback if enabled

            # File fallback if no patterns from DB and fallback enabled
            if not patterns and (cfg.file_fallback_enabled or not cfg.db_enabled):
                load_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._load_patterns_from_files,
                        project_root,
                    ),
                    timeout=timeout_seconds,
                )
                patterns = load_result.patterns
                source = self._format_source_attribution(load_result.source_files)
                context_source = ContextSource.PERSISTENCE_FILE
                logger.debug(f"Loaded {len(patterns)} patterns from files")

            retrieval_ms = int((time.monotonic() - start_time) * 1000)

        except TimeoutError:
            retrieval_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(f"Pattern loading timed out after {cfg.timeout_ms}ms")
            # Record error attempt (if cohort was assigned)
            if cohort_assignment:
                self._emit_injection_record(
                    injection_id=injection_id,
                    session_id_raw=session_id,
                    pattern_ids=[],
                    injection_context=injection_context,
                    source=EnumInjectionSource.ERROR,
                    cohort=cohort_assignment.cohort,
                    assignment_seed=cohort_assignment.assignment_seed,
                    injected_content="",
                    injected_token_count=0,
                    correlation_id=correlation_id,
                )
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
            # Record error attempt (if cohort was assigned)
            if cohort_assignment:
                self._emit_injection_record(
                    injection_id=injection_id,
                    session_id_raw=session_id,
                    pattern_ids=[],
                    injection_context=injection_context,
                    source=EnumInjectionSource.ERROR,
                    cohort=cohort_assignment.cohort,
                    assignment_seed=cohort_assignment.assignment_seed,
                    injected_content="",
                    injected_token_count=0,
                    correlation_id=correlation_id,
                )
            return ModelInjectionResult(
                success=True,  # Graceful degradation
                context_markdown="",
                pattern_count=0,
                context_size_bytes=0,
                source="error",
                retrieval_ms=retrieval_ms,
            )

        # Step 2: Filter by domain (pre-filter before selection)
        if agent_domain:
            patterns = [
                p for p in patterns if p.domain == agent_domain or p.domain == "general"
            ]

        # Step 3: Filter by confidence threshold (pre-filter)
        patterns = [p for p in patterns if p.confidence >= cfg.min_confidence]

        # Step 4-5: Apply injection limits with new selector (OMN-1671)
        # This replaces simple sort/limit with:
        # - Effective score ranking (confidence * success_rate * usage_factor)
        # - Domain caps (max_per_domain)
        # - Token budget (max_tokens_injected)
        # - Deterministic ordering
        patterns = select_patterns_for_injection(patterns, cfg.limits)

        # Step 6: Format as markdown
        context_markdown = self._format_patterns_markdown(
            patterns, cfg.limits.max_patterns_per_injection
        )
        context_size_bytes = len(context_markdown.encode("utf-8"))

        # Record injection to database via emit daemon
        if cohort_assignment:
            if not patterns:
                injection_source = EnumInjectionSource.NO_PATTERNS
            else:
                injection_source = EnumInjectionSource.INJECTED

            self._emit_injection_record(
                injection_id=injection_id,
                session_id_raw=session_id,
                pattern_ids=[p.pattern_id for p in patterns],
                injection_context=injection_context,
                source=injection_source,
                cohort=cohort_assignment.cohort,
                assignment_seed=cohort_assignment.assignment_seed,
                injected_content=context_markdown,
                injected_token_count=count_tokens(context_markdown),
                correlation_id=correlation_id,
            )

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
                context_source=context_source,
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
    # Database Methods
    # =========================================================================

    async def _get_persistence_handler(self) -> ProtocolPatternPersistence:
        """Get or create the pattern persistence handler.

        Creates a persistence handler implementation from the node module.
        Falls back to the PostgreSQL handler directly if available.

        Returns:
            Initialized ProtocolPatternPersistence implementation.

        Raises:
            PatternConnectionError: If connection fails or dependencies not installed.
        """
        if self._persistence is not None:
            return self._persistence

        # Lazy import to avoid circular dependencies and allow graceful degradation
        try:
            # Verify node module is available (imports needed for handler below)
            import omniclaude.nodes.node_pattern_persistence_effect.protocols  # noqa: F401
        except ImportError as e:
            raise PatternConnectionError(
                f"Pattern persistence unavailable - node module not installed: {e}"
            ) from e

        cfg = self._config

        # Check if handler module is available using importlib
        import importlib.util

        handler_spec = importlib.util.find_spec(
            "omniclaude.handlers.pattern_storage_postgres"
        )
        if handler_spec is None:
            raise PatternConnectionError(
                "Pattern persistence handler not available - "
                "omniclaude.handlers.pattern_storage_postgres module not found"
            )

        # NOTE: HandlerPatternStoragePostgres requires a ModelONEXContainer for
        # dependency injection (to resolve HandlerDb). For standalone usage without
        # a container, the caller should provide a pre-configured ProtocolPatternPersistence
        # via the constructor: HandlerContextInjection(persistence=handler)
        #
        # This code path is a placeholder for future container integration.
        raise PatternConnectionError(
            "Pattern persistence handler requires container-based initialization. "
            "HandlerPatternStoragePostgres expects ModelONEXContainer, not DSN/timeout. "
            "Configure CONTEXT_DB_ENABLED=false or provide a pre-configured "
            "ProtocolPatternPersistence handler via HandlerContextInjection(persistence=...)."
        )

    async def _load_patterns_from_database(
        self,
        domain: str | None = None,
        project_scope: str | None = None,
    ) -> ModelLoadPatternsResult:
        """Load patterns from the database using the protocol.

        Args:
            domain: Domain to filter by (None = all domains).
            project_scope: Project scope to filter by (currently unused - add when
                schema supports it).

        Returns:
            ModelLoadPatternsResult with patterns and source attribution.

        Raises:
            PatternConnectionError: If database connection fails.
            PatternPersistenceError: If query fails.
        """
        from uuid import uuid4

        from omniclaude.nodes.node_pattern_persistence_effect.models import (
            ModelLearnedPatternQuery,
        )

        cfg = self._config
        persistence = await self._get_persistence_handler()

        # Build query using the new model
        query = ModelLearnedPatternQuery(
            domain=domain if domain else None,
            min_confidence=cfg.min_confidence,
            include_general=True,
            limit=cfg.max_patterns * 2,  # Get extra for filtering
            offset=0,
        )

        # Query patterns using the protocol method
        correlation_id = uuid4()
        result = await persistence.query_patterns(query, correlation_id=correlation_id)

        if not result.success:
            raise PatternPersistenceError(
                f"Pattern query failed: {result.error or 'Unknown error'}"
            )

        # Convert ModelLearnedPatternRecord to handler's ModelPatternRecord
        patterns: list[ModelPatternRecord] = []
        for record in result.records:
            patterns.append(
                PatternRecord(
                    pattern_id=record.pattern_id,
                    domain=record.domain,
                    title=record.title,
                    description=record.description,
                    confidence=record.confidence,
                    usage_count=record.usage_count,
                    success_rate=record.success_rate,
                    example_reference=record.example_reference,
                )
            )

        # Build source attribution from backend type
        source = (
            f"database:{result.backend_type}:{cfg.db_host}:{cfg.db_port}/{cfg.db_name}"
        )
        return ModelLoadPatternsResult(patterns=patterns, source_files=[Path(source)])

    # =========================================================================
    # File I/O Methods (Fallback)
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
                record = PatternRecord(
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
        """Format patterns as markdown for context injection.

        Uses INJECTION_HEADER from injection_limits.py as the single source of
        truth for the header format. This ensures token counting during pattern
        selection matches the actual output format.
        """
        if not patterns:
            return ""

        patterns_to_format = patterns[:max_patterns]

        # Start with the header from injection_limits (single source of truth)
        # INJECTION_HEADER ends with "\n\n", split gives [..., "", ""], but we need
        # exactly one trailing "" for proper spacing before pattern content
        lines: list[str] = INJECTION_HEADER.rstrip("\n").split("\n") + [""]

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
        context_source: ContextSource = ContextSource.PERSISTENCE_FILE,
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
            logger.debug(
                "Skipping event emission: no session_id or correlation_id provided"
            )
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
                context_source=context_source,
                pattern_count=len(patterns),
                context_size_bytes=context_size_bytes,
                agent_domain=agent_domain or None,
                min_confidence_threshold=min_confidence,
                retrieval_duration_ms=retrieval_ms,
            )
            await emit_hook_event(payload)
            logger.debug(
                f"Context injection event emitted: {len(patterns)} patterns from {context_source.value}"
            )
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


# Module-level handler for convenience functions
_default_handler: HandlerContextInjection | None = None


def _get_default_handler() -> HandlerContextInjection:
    """Get or create default handler instance.

    Note: Unlike the previous lru_cache version, this creates a handler
    that may need cleanup. For long-running processes, consider creating
    and managing handlers explicitly.
    """
    global _default_handler
    if _default_handler is None:
        _default_handler = HandlerContextInjection()
    return _default_handler


async def cleanup_handler() -> None:
    """Clean up the default handler's database connections.

    Call this when your application is shutting down to properly
    release database pool resources. Safe to call multiple times.
    """
    global _default_handler
    if _default_handler is not None:
        await _default_handler.close()
        _default_handler = None


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
    creating a HandlerContextInjection instance directly to manage
    the database connection pool lifecycle.

    Note: When using custom config, cleanup is handled automatically.
    When using default handler, call cleanup_handler() when done.
    """
    if config:
        # Custom config - create and cleanup handler
        handler = HandlerContextInjection(config=config)
        try:
            return await handler.handle(
                project_root=project_root,
                agent_domain=agent_domain,
                session_id=session_id,
                correlation_id=correlation_id,
                emit_event=emit_event,
            )
        finally:
            await handler.close()
    else:
        # Use default handler (caller should call cleanup_handler when done)
        handler = _get_default_handler()
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
    # Exceptions
    "PatternPersistenceError",
    "PatternConnectionError",
    # Convenience functions
    "inject_patterns",
    "inject_patterns_sync",
    "cleanup_handler",
]
