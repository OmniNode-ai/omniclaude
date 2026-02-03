#!/usr/bin/env python3
"""Architecture handshake injector - Inject repo-specific architecture constraints.

This module enables SessionStart hooks to inject architecture handshake content
from `.claude/architecture-handshake.md` files installed by omnibase_core.

Part of OMN-1860: Architecture handshake injection for session enrichment.

Usage:
    # Python API
    from architecture_handshake_injector import find_handshake, read_handshake

    handshake_path = find_handshake("/path/to/project")
    if handshake_path:
        content = read_handshake(handshake_path)

    # CLI (JSON stdin -> JSON stdout)
    echo '{"project_path": "/path/to/project"}' | python architecture_handshake_injector.py

IMPORTANT: Always exits with code 0 for hook compatibility.
Any errors result in empty context, not failures.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import TypedDict

# Configure logging to stderr (stdout reserved for JSON output)
# Also log to LOG_FILE if set (per CLAUDE.md: "Failures must be logged to
# ~/.claude/hooks.log when LOG_FILE environment variable is set")
_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
_log_file = os.environ.get("LOG_FILE")
if _log_file:
    try:
        _handlers.append(logging.FileHandler(_log_file))
    except OSError:
        # Fail open: keep stderr logging only
        pass

logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_handlers,
)
logger = logging.getLogger(__name__)

# Handshake filename (standard location per OMN-1832)
HANDSHAKE_FILENAME = "architecture-handshake.md"
CLAUDE_DIR = ".claude"


# =============================================================================
# TypedDicts for JSON Interface
# =============================================================================


class HandshakeInjectorInput(TypedDict, total=False):
    """Input schema for the architecture handshake injector.

    All fields are optional with defaults applied at runtime via .get().

    Attributes:
        project_path: Path to the project directory. If not provided, uses CWD.
        cwd: Alternative to project_path (for compatibility with hook input).
    """

    project_path: str
    cwd: str


class HandshakeInjectorOutput(TypedDict):
    """Output schema for the architecture handshake injector.

    Attributes:
        success: Whether handshake loading succeeded.
        handshake_context: Markdown content from the handshake file.
        handshake_path: Path to the handshake file that was loaded (or None).
        retrieval_ms: Time taken to retrieve the handshake.
    """

    success: bool
    handshake_context: str
    handshake_path: str | None
    retrieval_ms: int


# =============================================================================
# Core Functions
# =============================================================================


def find_handshake(project_path: str | Path | None = None) -> Path | None:
    """Find the architecture handshake file for a project.

    Searches for `.claude/architecture-handshake.md` in the given project path.
    If project_path is None, uses current working directory.

    Args:
        project_path: Path to the project directory. If None, uses CWD.

    Returns:
        Path to the handshake file if found, None otherwise.

    Note:
        This function handles all errors gracefully and will never raise.
        On any error, it returns None.
    """
    try:
        if project_path is None:
            search_path = Path.cwd()
        else:
            search_path = Path(project_path)

        if not search_path.exists():
            logger.debug(f"Project path does not exist: {search_path}")
            return None

        if not search_path.is_dir():
            logger.debug(f"Project path is not a directory: {search_path}")
            return None

        handshake_path = search_path / CLAUDE_DIR / HANDSHAKE_FILENAME

        if handshake_path.exists() and handshake_path.is_file():
            logger.debug(f"Found handshake: {handshake_path}")
            return handshake_path

        logger.debug(f"Handshake not found: {handshake_path}")
        return None

    except Exception as e:
        logger.warning(f"Error finding handshake: {e}")
        return None


def read_handshake(handshake_path: Path) -> str:
    """Read the content of an architecture handshake file.

    Args:
        handshake_path: Path to the handshake file.

    Returns:
        Content of the handshake file, or empty string on error.

    Note:
        This function handles all errors gracefully and will never raise.
        On any error, it returns an empty string.
    """
    try:
        if not handshake_path.exists():
            logger.debug(f"Handshake file does not exist: {handshake_path}")
            return ""

        if not handshake_path.is_file():
            logger.debug(f"Handshake path is not a file: {handshake_path}")
            return ""

        content = handshake_path.read_text(encoding="utf-8")
        logger.debug(f"Read handshake ({len(content)} chars): {handshake_path}")
        return content

    except Exception as e:
        logger.warning(f"Error reading handshake: {e}")
        return ""


# =============================================================================
# Output Helpers
# =============================================================================


def _create_empty_output(retrieval_ms: int = 0) -> HandshakeInjectorOutput:
    """Create an output for cases where no handshake is found."""
    return HandshakeInjectorOutput(
        success=True,  # Always success for hook compatibility
        handshake_context="",
        handshake_path=None,
        retrieval_ms=retrieval_ms,
    )


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> None:
    """CLI entry point for architecture handshake injection.

    Reads JSON input from stdin, loads handshake content, and writes JSON
    output to stdout.

    IMPORTANT: Always exits with code 0 for hook compatibility.
    Any errors result in empty context, not failures.
    """
    start_time = time.monotonic()

    try:
        # Read input from stdin
        input_data = sys.stdin.read().strip()

        # Parse input JSON (empty input is valid)
        input_json: HandshakeInjectorInput = {}
        if input_data:
            try:
                input_json = json.loads(input_data)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON input: {e}")
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                output = _create_empty_output(retrieval_ms=elapsed_ms)
                print(json.dumps(output))
                sys.exit(0)

        # Extract project path (support both project_path and cwd)
        project_path_str = input_json.get("project_path") or input_json.get("cwd") or ""
        project_path: Path | None = None
        if project_path_str:
            project_path = Path(project_path_str)

        # Find and read handshake
        handshake_path = find_handshake(project_path)
        handshake_context = ""
        handshake_path_str: str | None = None

        if handshake_path:
            handshake_context = read_handshake(handshake_path)
            handshake_path_str = str(handshake_path)

        # Calculate elapsed time
        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Build output
        output = HandshakeInjectorOutput(
            success=True,
            handshake_context=handshake_context,
            handshake_path=handshake_path_str,
            retrieval_ms=elapsed_ms,
        )

        print(json.dumps(output))
        sys.exit(0)

    except Exception as e:
        # Catch-all for any unexpected errors
        # CRITICAL: Always exit 0 for hook compatibility
        logger.error(f"Unexpected error in architecture handshake injector: {e}")
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        output = _create_empty_output(retrieval_ms=elapsed_ms)
        print(json.dumps(output))
        sys.exit(0)


if __name__ == "__main__":
    main()
