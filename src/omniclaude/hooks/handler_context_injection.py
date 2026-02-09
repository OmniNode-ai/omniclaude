# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Handler for context injection - all business logic lives here.

This handler performs:
1. Database query to load patterns
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
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from omniclaude.hooks.cohort_assignment import (
    CONTRACT_DEFAULT_CONTROL_PERCENTAGE,
    CONTRACT_DEFAULT_SALT,
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
    ModelInjectionRecord,
)
from omniclaude.hooks.schemas import ContextSource, ModelHookContextInjectedPayload

if TYPE_CHECKING:
    import asyncpg
    from omnibase_core.models.contracts import ModelDbRepositoryContract
    from omnibase_core.types.type_json import StrictJsonPrimitive  # noqa: TC004
    from omnibase_infra.runtime.db import PostgresRepositoryRuntime


# Exception classes for graceful degradation
class PatternPersistenceError(Exception):
    """Base error for pattern persistence operations."""

    pass


class PatternConnectionError(PatternPersistenceError):
    """Error when persistence backend connection fails."""

    pass


# =============================================================================
# Type Coercion Helpers
# =============================================================================


def _safe_str(val: StrictJsonPrimitive, default: str = "") -> str:
    """Convert value to string, returning default if None."""
    return str(val) if val is not None else default


def _safe_float(val: StrictJsonPrimitive, default: float = 0.0) -> float:
    """Convert value to float, returning default if None."""
    return float(val) if val is not None else default


def _safe_int(val: StrictJsonPrimitive, default: int = 0) -> int:
    """Convert value to int, returning default if None."""
    return int(val) if val is not None else default


logger = logging.getLogger(__name__)


# =============================================================================
# Lazy Import for Emit Event
# =============================================================================

# Lazy import for emit_event to avoid circular dependencies
_emit_event_func: Callable[..., bool] | None = None


def _get_emit_event() -> Callable[..., bool]:
    """Get emit_event function with lazy import.

    Caches the import at module level to avoid repeated import overhead.
    The import is deferred to avoid circular dependencies during hook
    subprocess initialization.

    Returns:
        The emit_event function from emit_client_wrapper.
    """
    global _emit_event_func
    if _emit_event_func is None:
        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

        _emit_event_func = emit_event
    return _emit_event_func


def _reset_emit_event_cache() -> None:
    """Reset the emit_event cache for testing.

    This allows tests to patch the underlying module and have the patch
    take effect. Should only be used in test code.
    """
    global _emit_event_func
    _emit_event_func = None


# =============================================================================
# Data Models
# =============================================================================


@dataclass(frozen=True)
class PatternRecord:
    """API transfer model for learned patterns.

    This is the canonical API model with 10 core fields, used for:
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
        lifecycle_state: Lifecycle state of the pattern ("validated" or "provisional").
            Defaults to None for backward compatibility. None is treated as validated
            (no dampening applied). Provisional patterns are annotated differently
            in context injection output.
        evidence_tier: Measurement quality tier (UNMEASURED, MEASURED, VERIFIED).
            Defaults to None for backward compatibility. None is treated as UNMEASURED.
            MEASURED and VERIFIED patterns display quality badges in context injection.

    See Also:
        - DbPatternRecord: Database model (12 fields) in repository_patterns.py
        - PatternRecord (CLI): CLI model (10 fields) in plugins/onex/hooks/lib/pattern_types.py
    """

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

    # Valid lifecycle states for pattern records
    VALID_LIFECYCLE_STATES = frozenset({"validated", "provisional", None})
    # Valid evidence tiers for measurement quality
    VALID_EVIDENCE_TIERS = frozenset({"UNMEASURED", "MEASURED", "VERIFIED", None})

    def __post_init__(self) -> None:
        """Validate fields after initialization (runs before instance is frozen)."""
        if self.lifecycle_state not in self.VALID_LIFECYCLE_STATES:
            raise ValueError(
                f"lifecycle_state must be one of {{'validated', 'provisional', None}}, "
                f"got {self.lifecycle_state!r}"
            )
        if self.evidence_tier not in self.VALID_EVIDENCE_TIERS:
            raise ValueError(
                f"evidence_tier must be one of {{'UNMEASURED', 'MEASURED', 'VERIFIED', None}}, "
                f"got {self.evidence_tier!r}"
            )
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
    injection_id: str | None = None
    cohort: str | None = None


@dataclass(frozen=True)
class ModelLoadPatternsResult:
    """Result from loading patterns including source attribution.

    Attributes:
        patterns: List of unique pattern records.
        source_files: List of files that contributed at least one pattern.
        warnings: Operational warnings (e.g., silent fallbacks). Empty if none.
    """

    patterns: list[ModelPatternRecord]
    source_files: list[Path]
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# Handler Implementation
# =============================================================================


class HandlerContextInjection:
    """Handler for context injection from learned patterns.

    This handler implements the full context injection workflow:
    1. Load patterns from database
    2. Filter by domain and confidence threshold
    3. Sort by confidence descending
    4. Limit to max patterns
    5. Format as markdown
    6. Emit event to Kafka

    Following ONEX patterns from omnibase_infra:
    - Handlers own all business logic
    - Database-backed storage
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
        runtime: PostgresRepositoryRuntime | None = None,
    ) -> None:
        """Initialize the handler.

        Args:
            config: Optional configuration. If None, loads from environment at init time.
            runtime: Optional PostgresRepositoryRuntime for contract-driven database access.
                If None, creates one from config when db_enabled is True.
                When provided externally, lifecycle is managed by caller.
        """
        self._config = (
            config if config is not None else ContextInjectionConfig.from_env()
        )
        self._runtime: PostgresRepositoryRuntime | None = runtime
        self._pool: asyncpg.Pool | None = None
        self._contract: ModelDbRepositoryContract | None = None
        # Track whether we created the runtime (and thus should close pool)
        self._runtime_owned = runtime is None

    @property
    def handler_id(self) -> str:
        """Return the handler identifier."""
        return "handler-context-injection"

    async def close(self) -> None:
        """Close database connections.

        Should be called when the handler is no longer needed to release
        database pool resources. Safe to call multiple times.

        Only closes resources if the runtime was created internally
        (not provided externally via constructor).
        """
        if self._pool is not None and self._runtime_owned:
            try:
                await self._pool.close()
            except Exception as e:
                logger.warning(f"Error closing database pool: {e}")
            self._pool = None
        # Clear references regardless of ownership to allow GC and prevent stale state
        self._runtime = None
        self._contract = None

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
        effective_control_percentage: int = CONTRACT_DEFAULT_CONTROL_PERCENTAGE,
        effective_salt: str = CONTRACT_DEFAULT_SALT,
    ) -> bool:
        """Emit injection record via emit daemon.

        Non-blocking, returns True on success, False on failure.
        Uses emit daemon for durability (not asyncio.create_task).

        Uses ModelInjectionRecord for Pydantic validation before emission.
        Stamps effective config values for auditability/replay.
        """
        try:
            emit_event = _get_emit_event()

            # Use Pydantic model for validation
            record = ModelInjectionRecord(
                injection_id=injection_id,
                session_id_raw=session_id_raw,
                pattern_ids=pattern_ids,
                injection_context=injection_context,
                source=source,
                cohort=cohort,
                assignment_seed=assignment_seed,
                injected_content=injected_content,
                injected_token_count=injected_token_count,
                correlation_id=correlation_id,
                effective_control_percentage=effective_control_percentage,
                effective_salt=effective_salt,
            )

            # Serialize with by_alias=True to output "session_id" instead of "session_id_raw"
            # mode='json' ensures enums are serialized to their string values
            payload = record.model_dump(mode="json", by_alias=True)

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
            cohort_assignment = assign_cohort(session_id, config=cfg.cohort)

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
                    effective_control_percentage=cfg.cohort.control_percentage,
                    effective_salt=cfg.cohort.salt,
                )
                logger.info(f"Session {session_id[:8]}... assigned to control cohort")
                return ModelInjectionResult(
                    success=True,
                    context_markdown="",
                    pattern_count=0,
                    context_size_bytes=0,
                    source="control_cohort",
                    retrieval_ms=0,
                    injection_id=str(injection_id),
                    cohort=cohort_assignment.cohort.value,
                )

        if not cfg.enabled:
            return ModelInjectionResult(
                success=True,
                context_markdown="",
                pattern_count=0,
                context_size_bytes=0,
                source="disabled",
                retrieval_ms=0,
                injection_id=None,
                cohort=None,
            )

        # Step 1: Load patterns from database
        start_time = time.monotonic()
        timeout_seconds = cfg.timeout_ms / 1000.0
        patterns: list[ModelPatternRecord] = []
        source = "none"
        context_source = ContextSource.DATABASE  # Default for events

        try:
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
                    for w in db_result.warnings:
                        logger.warning("Pattern loading warning: %s", w)
                    logger.debug(f"Loaded {len(patterns)} patterns from database")
                except TimeoutError:
                    raise  # Let outer handler report timeout with detail
                except Exception as db_err:
                    logger.warning(f"Database pattern loading failed: {db_err}")
                    context_source = ContextSource.NONE

            retrieval_ms = int((time.monotonic() - start_time) * 1000)

        except Exception as e:
            retrieval_ms = int((time.monotonic() - start_time) * 1000)
            is_timeout = isinstance(e, TimeoutError)
            if is_timeout:
                logger.warning(f"Pattern loading timed out after {cfg.timeout_ms}ms")
                error_source = "timeout"
            else:
                logger.warning(f"Pattern loading failed: {e}")
                error_source = "error"
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
                    effective_control_percentage=cfg.cohort.control_percentage,
                    effective_salt=cfg.cohort.salt,
                )
            return ModelInjectionResult(
                success=True,  # Graceful degradation
                context_markdown="",
                pattern_count=0,
                context_size_bytes=0,
                source=error_source,
                retrieval_ms=retrieval_ms,
                injection_id=str(injection_id) if cohort_assignment else None,
                cohort=cohort_assignment.cohort.value if cohort_assignment else None,
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

            token_count = count_tokens(context_markdown)
            self._emit_injection_record(
                injection_id=injection_id,
                session_id_raw=session_id,
                pattern_ids=[p.pattern_id for p in patterns],
                injection_context=injection_context,
                source=injection_source,
                cohort=cohort_assignment.cohort,
                assignment_seed=cohort_assignment.assignment_seed,
                injected_content=context_markdown,
                injected_token_count=token_count,
                correlation_id=correlation_id,
                effective_control_percentage=cfg.cohort.control_percentage,
                effective_salt=cfg.cohort.salt,
            )

        # Step 7: Emit event
        if emit_event and patterns:
            emitted_at = datetime.now(UTC)
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
                emitted_at=emitted_at,
            )

        return ModelInjectionResult(
            success=True,
            context_markdown=context_markdown,
            pattern_count=len(patterns),
            context_size_bytes=context_size_bytes,
            source=source,
            retrieval_ms=retrieval_ms,
            injection_id=str(injection_id) if cohort_assignment else None,
            cohort=cohort_assignment.cohort.value if cohort_assignment else None,
        )

    # =========================================================================
    # Database Methods
    # =========================================================================

    async def _get_repository_runtime(self) -> PostgresRepositoryRuntime:
        """Get or create the contract-driven repository runtime.

        Creates a PostgresRepositoryRuntime using the learned_patterns contract.
        This is the contract-driven approach from OMN-1779 - no adapter classes,
        just runtime + contract.

        Returns:
            Initialized PostgresRepositoryRuntime.

        Raises:
            PatternConnectionError: If connection fails or contract loading fails.
        """
        if self._runtime is not None:
            return self._runtime

        # Lazy import to avoid circular dependencies
        try:
            import asyncpg
            import yaml
            from omnibase_core.models.contracts import ModelDbRepositoryContract
            from omnibase_infra.runtime.db import PostgresRepositoryRuntime
            from pydantic import ValidationError
        except ImportError as e:
            raise PatternConnectionError(
                f"Contract runtime unavailable - dependencies not installed: {e}"
            ) from e

        cfg = self._config

        # Load contract YAML
        try:
            if cfg.db_contract_path:
                contract_path = Path(cfg.db_contract_path)
            else:
                # Use bundled contract
                contract_path = (
                    Path(__file__).parent
                    / "contracts"
                    / "repository_learned_patterns.yaml"
                )

            if not contract_path.exists():
                raise PatternConnectionError(
                    f"Contract file not found: {contract_path}"
                )

            with contract_path.open() as f:
                contract_data = yaml.safe_load(f)

            self._contract = ModelDbRepositoryContract.model_validate(contract_data)
        except ValidationError as e:
            # Preserve field-level validation errors from Pydantic
            raise PatternConnectionError(
                f"Contract validation failed for {contract_path}: {e.error_count()} errors - {e}"
            ) from e
        except Exception as e:
            raise PatternConnectionError(
                f"Failed to load repository contract: {e}"
            ) from e

        # Create asyncpg pool
        try:
            dsn = cfg.get_db_dsn()  # noqa: secrets - DSN from config, not hardcoded
            self._pool = await asyncpg.create_pool(
                dsn,
                min_size=cfg.db_pool_min_size,
                max_size=cfg.db_pool_max_size,
                command_timeout=cfg.timeout_ms / 1000.0,
            )
        except Exception as e:
            # Clear contract to ensure clean state for retry
            self._contract = None
            raise PatternConnectionError(f"Failed to create database pool: {e}") from e

        # Create runtime - wrap in try/except to handle partial initialization
        try:
            self._runtime = PostgresRepositoryRuntime(self._pool, self._contract)
        except Exception as e:
            # Close pool on runtime creation failure to prevent resource leak
            if self._pool is not None:
                await self._pool.close()
            self._pool = None
            self._contract = None
            raise PatternConnectionError(f"Failed to create runtime: {e}") from e

        return self._runtime

    async def _load_patterns_from_database(
        self,
        domain: str | None = None,
        project_scope: str | None = None,
    ) -> ModelLoadPatternsResult:
        """Load patterns from the database using contract-driven runtime.

        Uses PostgresRepositoryRuntime with the learned_patterns contract.
        This is the contract-driven approach from OMN-1779.

        Args:
            domain: Domain to filter by (None = all domains).
            project_scope: Project scope to filter by (currently unused).

        Returns:
            ModelLoadPatternsResult with patterns and source attribution.

        Raises:
            PatternConnectionError: If database connection fails.
            PatternPersistenceError: If query fails.
        """
        cfg = self._config
        runtime = await self._get_repository_runtime()

        # Get extra patterns for filtering (will be filtered by confidence/domain later)
        # Use limits config to stay synchronized with select_patterns_for_injection
        limit = cfg.limits.max_patterns_per_injection * 2
        warnings: list[str] = []

        try:
            # Determine which operation to call based on include_provisional config (OMN-2042)
            include_provisional = cfg.limits.include_provisional

            if include_provisional and not domain:
                # Use graduated injection query that includes validated + provisional
                rows = await runtime.call(
                    "list_injectable_patterns",
                    limit,  # positional arg
                )
            elif domain:
                if include_provisional:
                    msg = (
                        f"include_provisional=True ignored: domain filter '{domain}' "
                        f"is active but domain-filtered graduated injection is not yet "
                        f"implemented (see OMN-2042 follow-up). Returning VALIDATED "
                        f"patterns only."
                    )
                    logger.warning(msg)
                    warnings.append(msg)
                # Use domain-filtered operation (validated only; graduated domain query is a follow-up)
                rows = await runtime.call(
                    "list_patterns_by_domain",
                    domain,  # positional arg
                    limit,  # positional arg
                )
            else:
                rows = await runtime.call(
                    "list_validated_patterns",
                    limit,  # positional arg
                )
        except Exception as e:
            raise PatternPersistenceError(f"Pattern query failed: {e}") from e

        # Convert row dicts to PatternRecord objects
        patterns: list[ModelPatternRecord] = []
        if rows:
            for row in rows:
                try:
                    pattern_id = row.get("pattern_id")
                    if not pattern_id:
                        logger.warning("Skipping row with missing pattern_id")
                        continue

                    # Map lifecycle_state from DB (OMN-2042)
                    # list_injectable_patterns returns status as lifecycle_state;
                    # list_validated_patterns does not include it (defaults to None/"validated")
                    raw_lifecycle = row.get("lifecycle_state")
                    lifecycle_state = (
                        str(raw_lifecycle) if raw_lifecycle is not None else None
                    )

                    # Map evidence_tier from DB (OMN-2044)
                    raw_evidence_tier = row.get("evidence_tier")
                    evidence_tier = (
                        str(raw_evidence_tier)
                        if raw_evidence_tier is not None
                        else None
                    )

                    patterns.append(
                        PatternRecord(
                            pattern_id=str(pattern_id),
                            domain=_safe_str(row.get("domain")),
                            title=_safe_str(row.get("title")),
                            description=_safe_str(row.get("description")),
                            confidence=_safe_float(row.get("confidence")),
                            usage_count=_safe_int(row.get("usage_count")),
                            success_rate=_safe_float(row.get("success_rate")),
                            example_reference=row.get("example_reference"),
                            lifecycle_state=lifecycle_state,
                            evidence_tier=evidence_tier,
                        )
                    )
                except (ValueError, TypeError) as e:
                    logger.warning(f"Skipping invalid pattern row: {e}")
                    continue

        # Build source attribution
        source = f"database:contract:{cfg.db_host}:{cfg.db_port}/{cfg.db_name}"
        return ModelLoadPatternsResult(
            patterns=patterns,
            source_files=[Path(source)],
            warnings=warnings,
        )

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

            # Annotate provisional patterns with badge (OMN-2042)
            # Annotate evidence tier with quality badge (OMN-2044)
            badges: list[str] = []
            if pattern.lifecycle_state == "provisional":
                badges.append("[Provisional]")
            if pattern.evidence_tier == "MEASURED":
                badges.append("[Measured]")
            elif pattern.evidence_tier == "VERIFIED":
                badges.append("[Verified]")
            title_suffix = (" " + " ".join(badges)) if badges else ""
            lines.append(f"### {pattern.title}{title_suffix}")
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
        context_source: ContextSource = ContextSource.DATABASE,
        emitted_at: datetime,
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
                emitted_at=emitted_at,
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
    injection_context: EnumInjectionContext = EnumInjectionContext.USER_PROMPT_SUBMIT,
) -> ModelInjectionResult:
    """Convenience function for context injection.

    Creates a handler and invokes it. For repeated calls, consider
    creating a HandlerContextInjection instance directly to manage
    the database connection pool lifecycle.

    Args:
        project_root: Optional project root path for pattern files.
        agent_domain: Domain to filter patterns by (empty = all).
        session_id: Session identifier for event emission.
        correlation_id: Correlation ID for distributed tracing.
        config: Optional configuration override.
        emit_event: Whether to emit Kafka event.
        injection_context: Hook event that triggered injection (for A/B tracking).

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
                injection_context=injection_context,
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
            injection_context=injection_context,
        )


def inject_patterns_sync(
    *,
    project_root: str | None = None,
    agent_domain: str = "",
    session_id: str = "",
    correlation_id: str = "",
    config: ContextInjectionConfig | None = None,
    emit_event: bool = True,
    injection_context: EnumInjectionContext = EnumInjectionContext.USER_PROMPT_SUBMIT,
) -> ModelInjectionResult:
    """Synchronous wrapper for shell scripts.

    Args:
        project_root: Optional project root path for pattern files.
        agent_domain: Domain to filter patterns by (empty = all).
        session_id: Session identifier for event emission.
        correlation_id: Correlation ID for distributed tracing.
        config: Optional configuration override.
        emit_event: Whether to emit Kafka event.
        injection_context: Hook event that triggered injection (for A/B tracking).

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
                    injection_context=injection_context,
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
                injection_context=injection_context,
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
