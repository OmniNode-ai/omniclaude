# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""ONEX Effect node for pattern retrieval - file I/O only.

This node performs ONE side effect: reading pattern files from disk.
Pure operations (formatting, filtering, sorting) are NOT performed here.
Event emission is NOT performed by this node.

The node returns raw patterns; filtering/sorting/limiting is the
handler's responsibility to maintain effect node purity.

Part of OMN-1403: Context injection for session enrichment.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


@dataclass(frozen=True)
class ModelPatternRecord:
    """A single learned pattern from persistence.

    This is a frozen dataclass to ensure immutability after loading.
    The effect node returns these records as-is; filtering/sorting
    is performed by the handler layer.

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


# =============================================================================
# Contracts
# =============================================================================


class ModelContextRetrievalContract(BaseModel):
    """Input contract for context retrieval effect node.

    This contract specifies the parameters for pattern file retrieval.
    Note: The domain field is metadata only - the effect node does NOT
    filter by domain (that's the handler's responsibility).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_root: str | None = Field(
        default=None,
        description="Project root path for pattern files. If None, only user-level patterns are loaded.",
    )
    domain: str = Field(
        default="",
        description="Domain filter hint (NOT applied by node - just metadata for handlers).",
    )


class ModelContextRetrievalResult(BaseModel):
    """Output contract for context retrieval effect node.

    Contains raw patterns from disk I/O. No filtering, sorting, or
    limiting has been applied - handlers perform those operations.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    success: bool = Field(
        description="Whether file I/O retrieval succeeded.",
    )
    patterns: list[ModelPatternRecord] = Field(
        default_factory=list,
        description="Retrieved patterns (raw, unsorted, unfiltered from disk).",
    )
    source: str = Field(
        default="none",
        description="Path of file patterns were loaded from, 'none' if no files, 'error' on failure.",
    )
    retrieval_ms: int = Field(
        default=0,
        ge=0,
        description="Time spent on file I/O in milliseconds.",
    )
    error_message: str | None = Field(
        default=None,
        description="Error details if retrieval failed. None on success.",
    )


# =============================================================================
# Effect Node
# =============================================================================


class NodeContextInjectionEffect:
    """ONEX Effect node for pattern retrieval.

    This node performs ONE side effect: reading pattern files from disk.
    Pure operations (formatting, filtering, sorting) are NOT performed here.
    Event emission is NOT performed by this node.

    The node returns raw patterns; filtering/sorting/limiting is the
    handler's responsibility to maintain effect node purity.

    ONEX Node Classification:
        - Type: Effect
        - Side Effect: File system reads
        - Purity: Impure (I/O)
        - Idempotent: Yes (read-only)

    Usage:
        >>> node = NodeContextInjectionEffect()
        >>> contract = ModelContextRetrievalContract(project_root="/workspace/project")
        >>> result = await node.execute_effect(contract)
        >>> if result.success:
        ...     # Handler applies filtering/sorting to result.patterns
        ...     pass
    """

    # TEMP_BOOTSTRAP: node_id should be injected by runtime in production.
    # TODO(OMN-XXXX): Accept node_id via constructor once runtime supports it.
    _BOOTSTRAP_NODE_ID = "context-injection-effect-bootstrap"

    def __init__(
        self,
        node_id: str | None = None,
    ) -> None:
        """Initialize the effect node.

        Args:
            node_id: Optional node identifier. If None, uses bootstrap default.
                     In production, the ONEX runtime injects this.
        """
        self._node_id = node_id or self._BOOTSTRAP_NODE_ID

    @property
    def node_id(self) -> str:
        """Return the node identifier."""
        return self._node_id

    @property
    def node_type(self) -> str:
        """Return the ONEX node type classification."""
        return "effect"

    async def execute_effect(
        self,
        contract: ModelContextRetrievalContract,
    ) -> ModelContextRetrievalResult:
        """Execute pattern retrieval (file I/O).

        Returns raw patterns - NO filtering/sorting/limiting applied.
        The only data manipulation is deduplication when merging multiple
        files (an I/O concern, not a business rule).

        Args:
            contract: Input contract specifying retrieval parameters.

        Returns:
            Result containing raw patterns from disk. On failure, returns
            success=False with error_message populated.
        """
        start_time = time.monotonic()

        try:
            # SIDE EFFECT: Read from file system (wrapped for async safety)
            patterns = await asyncio.to_thread(
                self._load_patterns_from_files,
                contract.project_root,
            )

            retrieval_ms = int((time.monotonic() - start_time) * 1000)

            # Determine source path
            project_root = (
                Path(contract.project_root) if contract.project_root else None
            )
            source = self._get_source_path(project_root)

            return ModelContextRetrievalResult(
                success=True,
                patterns=patterns,
                source=source,
                retrieval_ms=retrieval_ms,
                error_message=None,
            )
        except Exception as e:
            retrieval_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(f"Pattern retrieval failed: {e}")
            return ModelContextRetrievalResult(
                success=False,
                patterns=[],
                source="error",
                retrieval_ms=retrieval_ms,
                error_message=str(e),
            )

    # =========================================================================
    # Internal I/O Methods
    # =========================================================================

    def _load_patterns_from_files(
        self,
        project_root: str | None,
    ) -> list[ModelPatternRecord]:
        """Load patterns from persistence files (synchronous I/O).

        Finds and parses all pattern files, deduplicating by pattern_id
        when multiple files contain the same pattern.

        Args:
            project_root: Optional project root path.

        Returns:
            List of unique pattern records from all found files.
        """
        all_patterns: list[ModelPatternRecord] = []

        # Find pattern files in standard locations
        pattern_files = self._find_pattern_files(
            Path(project_root) if project_root else None
        )

        if not pattern_files:
            logger.debug("No pattern files found")
            return []

        # Parse each file
        for file_path in pattern_files:
            try:
                patterns = self._parse_pattern_file(file_path)
                all_patterns.extend(patterns)
                logger.debug(f"Loaded {len(patterns)} patterns from {file_path}")
            except Exception as e:
                logger.warning(f"Failed to parse {file_path}: {e}")
                continue

        # Deduplicate by pattern_id (keep first occurrence)
        # This is an I/O deduplication concern when merging multiple files,
        # NOT a business filtering operation
        seen_ids: set[str] = set()
        unique_patterns: list[ModelPatternRecord] = []
        for pattern in all_patterns:
            if pattern.pattern_id not in seen_ids:
                seen_ids.add(pattern.pattern_id)
                unique_patterns.append(pattern)

        return unique_patterns

    def _find_pattern_files(self, project_root: Path | None) -> list[Path]:
        """Find learned pattern files in standard locations.

        Searches in order:
        1. Project-specific: {project_root}/.claude/learned_patterns.json
        2. User-level: ~/.claude/learned_patterns.json

        Args:
            project_root: Optional project root directory.

        Returns:
            List of existing pattern file paths (may be empty).
        """
        candidates: list[Path] = []

        # Project-specific patterns (higher priority)
        if project_root and project_root.is_dir():
            project_file = project_root / ".claude" / "learned_patterns.json"
            if project_file.exists():
                candidates.append(project_file)

        # User-level patterns (lower priority)
        home = Path.home()
        user_file = home / ".claude" / "learned_patterns.json"
        if user_file.exists():
            candidates.append(user_file)

        return candidates

    def _parse_pattern_file(self, file_path: Path) -> list[ModelPatternRecord]:
        """Parse a learned_patterns.json file.

        Args:
            file_path: Path to the pattern file.

        Returns:
            List of ModelPatternRecord objects.

        Raises:
            ValueError: If file format is invalid.
            FileNotFoundError: If file does not exist.
            json.JSONDecodeError: If JSON is malformed.
        """
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # Validate top-level structure
        if not isinstance(data, dict):
            raise ValueError(
                f"Pattern file must be a JSON object, got {type(data).__name__}"
            )

        patterns_data = data.get("patterns", [])
        if not isinstance(patterns_data, list):
            raise ValueError(
                f"'patterns' must be a list, got {type(patterns_data).__name__}"
            )

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

    def _get_source_path(self, project_root: Path | None) -> str:
        """Return which file was used as primary source.

        Args:
            project_root: Optional project root directory.

        Returns:
            Path string of the first pattern file found, or "none" if no files.
        """
        pattern_files = self._find_pattern_files(project_root)
        if pattern_files:
            return str(pattern_files[0])
        return "none"


__all__ = [
    "ModelPatternRecord",
    "ModelContextRetrievalContract",
    "ModelContextRetrievalResult",
    "NodeContextInjectionEffect",
]
