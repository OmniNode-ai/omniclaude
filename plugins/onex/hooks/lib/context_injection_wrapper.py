#!/usr/bin/env python3
"""CLI wrapper for context injection - backward compatible JSON interface.

This wrapper provides a CLI interface for shell scripts to invoke the
context injection handler. It reads JSON from stdin and writes JSON to stdout.

IMPORTANT: Always exits with code 0 for hook compatibility.
Any errors result in empty patterns_context, not failures.

Usage:
    echo '{"project": "/path/to/project", "domain": "general"}' | python context_injection_wrapper.py

Input JSON:
    {
        "agent_name": "polymorphic-agent",
        "domain": "general",
        "session_id": "abc-123",
        "project": "/path/to/project",
        "correlation_id": "xyz-456",
        "max_patterns": 5,
        "min_confidence": 0.7
    }

Output JSON:
    {
        "success": true,
        "patterns_context": "## Learned Patterns...",
        "pattern_count": 3,
        "source": "/home/user/.claude/learned_patterns.json",
        "retrieval_ms": 42
    }
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import TypedDict, cast

# Configure logging to stderr (stdout reserved for JSON output)
logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


class InjectorInput(TypedDict, total=False):
    """Input schema from shell scripts."""

    agent_name: str
    domain: str
    session_id: str
    project: str
    correlation_id: str
    max_patterns: int
    min_confidence: float


class InjectorOutput(TypedDict):
    """Output schema for shell scripts."""

    success: bool
    patterns_context: str
    pattern_count: int
    source: str
    retrieval_ms: int


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
    CLI entry point for context injection.

    Reads JSON input from stdin, invokes the handler, and writes JSON output to stdout.

    IMPORTANT: Always exits with code 0 for hook compatibility.
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
        session_id = input_json.get("session_id", "")
        correlation_id = input_json.get("correlation_id", "")
        max_patterns = int(input_json.get("max_patterns", 5))
        min_confidence = float(input_json.get("min_confidence", 0.7))

        # Import handler here to avoid import errors if dependencies missing
        try:
            from omniclaude.hooks.context_config import ContextInjectionConfig
            from omniclaude.hooks.handler_context_injection import inject_patterns_sync
        except ImportError as e:
            logger.warning(f"Failed to import handler: {e}")
            # Fall back to legacy injector if new handler not available
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            output = _create_error_output(retrieval_ms=elapsed_ms)
            print(json.dumps(output))
            sys.exit(0)

        # Create config with overrides
        config = ContextInjectionConfig(
            max_patterns=max_patterns,
            min_confidence=min_confidence,
        )

        # Call the handler
        result = inject_patterns_sync(
            project_root=project_path if project_path else None,
            agent_domain=domain,
            session_id=session_id,
            correlation_id=correlation_id,
            config=config,
            emit_event=True,  # Emit Kafka events
        )

        # Calculate elapsed time
        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Build output (use handler timing if available)
        output = InjectorOutput(
            success=result.success,
            patterns_context=result.context_markdown,
            pattern_count=result.pattern_count,
            source=result.source,
            retrieval_ms=result.retrieval_ms or elapsed_ms,
        )

        print(json.dumps(output))
        sys.exit(0)

    except Exception as e:
        # Catch-all for any unexpected errors
        # CRITICAL: Always exit 0 for hook compatibility
        logger.error(f"Unexpected error in context injection wrapper: {e}")
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        output = _create_error_output(retrieval_ms=elapsed_ms)
        print(json.dumps(output))
        sys.exit(0)


if __name__ == "__main__":
    main()
