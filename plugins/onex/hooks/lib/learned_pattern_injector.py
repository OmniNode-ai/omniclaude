#!/usr/bin/env python3
"""
Learned Pattern Injector - Inject learned patterns into Claude Code sessions.

This module reads learned patterns from persistence files and formats them
for injection into Claude Code sessions via hooks. It provides context
enrichment based on domain-specific patterns discovered through the
learning loop.

Part of OMN-1403: Context injection for session enrichment.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict, cast

# Configure logging to stderr (stdout reserved for JSON output)
logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class PatternRecord:
    """
    Represents a single learned pattern from the persistence store.

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

    def __post_init__(self) -> None:
        """Validate fields after initialization."""
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


@dataclass
class PatternFile:
    """
    Represents the structure of a learned_patterns.json file.

    Attributes:
        version: Schema version of the pattern file.
        last_updated: ISO-8601 timestamp of last update.
        patterns: List of pattern records.
    """

    version: str
    last_updated: str
    patterns: list[PatternRecord] = field(default_factory=list)


# =============================================================================
# TypedDicts for JSON Interface
# =============================================================================


class InjectorInput(TypedDict):
    """
    Input schema for the pattern injector.

    Attributes:
        agent_name: Name of the agent requesting patterns.
        domain: Domain to filter patterns by (empty string for all domains).
        session_id: Current session identifier.
        project: Project root path.
        correlation_id: Correlation ID for tracing.
        max_patterns: Maximum number of patterns to include.
        min_confidence: Minimum confidence threshold for pattern inclusion.
    """

    agent_name: str
    domain: str
    session_id: str
    project: str
    correlation_id: str
    max_patterns: int
    min_confidence: float


class InjectorOutput(TypedDict):
    """
    Output schema for the pattern injector.

    Attributes:
        success: Whether pattern loading succeeded.
        patterns_context: Formatted markdown context for injection.
        pattern_count: Number of patterns included.
        source: Source of patterns (file path or "none").
        retrieval_ms: Time taken to retrieve and format patterns.
    """

    success: bool
    patterns_context: str
    pattern_count: int
    source: str
    retrieval_ms: int


# =============================================================================
# Pattern Loading
# =============================================================================


def _find_pattern_files(project_root: Path | None) -> list[Path]:
    """
    Find learned pattern files in standard locations.

    Searches in order:
    1. Project-specific: {project_root}/.claude/learned_patterns.json
    2. User-level: ~/.claude/learned_patterns.json

    Args:
        project_root: Optional project root directory.

    Returns:
        List of existing pattern file paths.
    """
    candidates: list[Path] = []

    # Project-specific patterns
    if project_root:
        project_file = project_root / ".claude" / "learned_patterns.json"
        if project_file.exists():
            candidates.append(project_file)

    # User-level patterns
    home = Path.home()
    user_file = home / ".claude" / "learned_patterns.json"
    if user_file.exists():
        candidates.append(user_file)

    return candidates


def _parse_pattern_file(file_path: Path) -> list[PatternRecord]:
    """
    Parse a learned_patterns.json file.

    Args:
        file_path: Path to the pattern file.

    Returns:
        List of PatternRecord objects.

    Raises:
        ValueError: If file format is invalid.
        FileNotFoundError: If file does not exist.
        json.JSONDecodeError: If JSON is malformed.
    """
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Validate structure
    if not isinstance(data, dict):
        raise ValueError(
            f"Pattern file must be a JSON object, got {type(data).__name__}"
        )

    patterns_data = data.get("patterns", [])
    if not isinstance(patterns_data, list):
        raise ValueError(
            f"'patterns' must be a list, got {type(patterns_data).__name__}"
        )

    records: list[PatternRecord] = []
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
            logger.warning(f"Skipping invalid pattern at index {idx}: {e}")
            continue

    return records


def load_patterns(
    project_root: Path | None,
    domain: str,
    min_confidence: float,
) -> list[PatternRecord]:
    """
    Load patterns from persistence files with filtering.

    Searches for pattern files in project and home directories,
    filters by domain and minimum confidence, and returns sorted
    by confidence descending.

    Args:
        project_root: Optional project root directory.
        domain: Domain to filter by (empty string for all domains).
        min_confidence: Minimum confidence threshold (0.0 to 1.0).

    Returns:
        List of PatternRecord objects matching criteria, sorted by confidence.
        Returns empty list if no files found or on parse errors.
    """
    all_patterns: list[PatternRecord] = []

    # Find and parse pattern files
    pattern_files = _find_pattern_files(project_root)

    if not pattern_files:
        logger.debug("No pattern files found")
        return []

    for file_path in pattern_files:
        try:
            patterns = _parse_pattern_file(file_path)
            all_patterns.extend(patterns)
            logger.debug(f"Loaded {len(patterns)} patterns from {file_path}")
        except (json.JSONDecodeError, ValueError, FileNotFoundError) as e:
            logger.warning(f"Failed to parse {file_path}: {e}")
            continue

    # Deduplicate by pattern_id (keep first occurrence)
    seen_ids: set[str] = set()
    unique_patterns: list[PatternRecord] = []
    for pattern in all_patterns:
        if pattern.pattern_id not in seen_ids:
            seen_ids.add(pattern.pattern_id)
            unique_patterns.append(pattern)

    # Filter by domain
    if domain:
        unique_patterns = [p for p in unique_patterns if p.domain == domain]

    # Filter by minimum confidence
    unique_patterns = [p for p in unique_patterns if p.confidence >= min_confidence]

    # Sort by confidence descending
    unique_patterns.sort(key=lambda p: p.confidence, reverse=True)

    return unique_patterns


# =============================================================================
# Markdown Formatting
# =============================================================================


def format_patterns_markdown(
    patterns: list[PatternRecord],
    max_patterns: int,
) -> str:
    """
    Format patterns as markdown for context injection.

    Creates a markdown section with learned patterns including
    title, domain, confidence, success rate, and description.

    Args:
        patterns: List of patterns to format.
        max_patterns: Maximum number of patterns to include.

    Returns:
        Formatted markdown string. Empty string if no patterns.
    """
    if not patterns:
        return ""

    # Limit to max_patterns
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


# =============================================================================
# CLI Entry Point
# =============================================================================


def _create_empty_output(source: str = "none", retrieval_ms: int = 0) -> InjectorOutput:
    """Create an empty output for cases with no patterns."""
    return InjectorOutput(
        success=True,
        patterns_context="",
        pattern_count=0,
        source=source,
        retrieval_ms=retrieval_ms,
    )


def _create_error_output(retrieval_ms: int = 0) -> InjectorOutput:
    """Create an output for error cases (still returns success for hook compatibility)."""
    return InjectorOutput(
        success=True,  # Always success for hook compatibility
        patterns_context="",
        pattern_count=0,
        source="error",
        retrieval_ms=retrieval_ms,
    )


def main() -> None:
    """
    CLI entry point for pattern injection.

    Reads JSON input from stdin, loads and formats patterns,
    and writes JSON output to stdout.

    IMPORTANT: Always exits with code 0 for hook compatibility.
    Any errors result in empty patterns_context, not failures.
    """
    start_time = time.monotonic()

    try:
        # Read input from stdin
        input_data = sys.stdin.read().strip()

        if not input_data:
            logger.debug("Empty input received")
            output = _create_empty_output()
            print(json.dumps(output))
            sys.exit(0)

        # Parse input JSON
        try:
            input_json = cast("InjectorInput", json.loads(input_data))
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON input: {e}")
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            output = _create_error_output(retrieval_ms=elapsed_ms)
            print(json.dumps(output))
            sys.exit(0)

        # Extract input parameters with defaults
        project_path = input_json.get("project", "")
        domain = input_json.get("domain", "")
        max_patterns = int(input_json.get("max_patterns", 5))
        min_confidence = float(input_json.get("min_confidence", 0.7))

        # Convert project to Path
        project_root: Path | None = None
        if project_path:
            project_root = Path(project_path)
            if not project_root.is_dir():
                logger.debug(f"Project path is not a directory: {project_path}")
                project_root = None

        # Load patterns
        patterns = load_patterns(
            project_root=project_root,
            domain=domain,
            min_confidence=min_confidence,
        )

        # Determine source
        if patterns:
            pattern_files = _find_pattern_files(project_root)
            source = str(pattern_files[0]) if pattern_files else "memory"
        else:
            source = "none"

        # Format markdown
        patterns_context = format_patterns_markdown(patterns, max_patterns)

        # Calculate elapsed time
        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Build output
        output = InjectorOutput(
            success=True,
            patterns_context=patterns_context,
            pattern_count=len(patterns[:max_patterns]),
            source=source,
            retrieval_ms=elapsed_ms,
        )

        print(json.dumps(output))
        sys.exit(0)

    except Exception as e:
        # Catch-all for any unexpected errors
        # CRITICAL: Always exit 0 for hook compatibility
        logger.error(f"Unexpected error in pattern injector: {e}")
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        output = _create_error_output(retrieval_ms=elapsed_ms)
        print(json.dumps(output))
        sys.exit(0)


if __name__ == "__main__":
    main()
