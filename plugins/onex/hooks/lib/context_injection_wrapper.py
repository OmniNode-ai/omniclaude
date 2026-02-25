#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

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
        "min_confidence": 0.7,
        "emit_event": true,
        "injection_context": "user_prompt_submit",
        "include_footer": false
    }

Output JSON:
    {
        "success": true,
        "patterns_context": "## Learned Patterns...",
        "pattern_count": 3,
        "source": "database:contract:<postgres-host>:5436/omniclaude",
        "retrieval_ms": 42,
        "injection_id": "abc12345-...",
        "cohort": "treatment"
    }
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pattern_types import (
    InjectorInput,
    InjectorOutput,
    create_empty_output,
    create_error_output,
)

if TYPE_CHECKING:
    from omniclaude.hooks.models_injection_tracking import EnumInjectionContext


# ---------------------------------------------------------------------------
# Tier banner helpers (OMN-2782)
# ---------------------------------------------------------------------------

_TIER_LABELS: dict[str, str] = {
    "standalone": "STANDALONE (73 skills)",
    "event_bus": "EVENT_BUS (routing + telemetry)",
    "full_onex": "FULL_ONEX (enrichment + memory)",
}


def _build_tier_banner() -> str:
    """Read capabilities file and return a tier banner string.

    If the capabilities file is missing or stale, spawns a fresh background
    probe and returns an UNKNOWN banner.

    Returns:
        A single-line banner string, e.g.
        "─── OmniClaude: STANDALONE (73 skills) (probe: 42s ago) ───"
    """
    try:
        from capability_probe import read_capabilities  # type: ignore[import-untyped]

        caps = read_capabilities()
    except Exception:
        caps = None

    if caps is None:
        # Stale or missing: spawn a fresh probe asynchronously
        _spawn_probe_background()
        return "─── OmniClaude: UNKNOWN (re-probing...) ───"

    tier = str(caps.get("tier", "unknown"))
    label = _TIER_LABELS.get(tier, tier.upper())
    probed_at_str = caps.get("probed_at")
    if isinstance(probed_at_str, str):
        try:
            probed_at = datetime.fromisoformat(probed_at_str)
            if probed_at.tzinfo is None:
                probed_at = probed_at.replace(tzinfo=UTC)
            age_secs = int((datetime.now(tz=UTC) - probed_at).total_seconds())
            age_str = f"{age_secs}s ago"
        except Exception:
            age_str = "?"
    else:
        age_str = "?"

    return f"─── OmniClaude: {label} (probe: {age_str}) ───"


def _spawn_probe_background() -> None:
    """Spawn capability_probe.py in the background without blocking."""
    try:
        probe_script = Path(__file__).parent / "capability_probe.py"
        if probe_script.is_file():
            subprocess.Popen(  # noqa: S603
                [
                    sys.executable,
                    str(probe_script),
                    "--kafka",
                    os.getenv("KAFKA_BOOTSTRAP_SERVERS", ""),
                    "--intelligence",
                    os.getenv("INTELLIGENCE_SERVICE_URL", "http://localhost:8053"),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
    except Exception:
        pass  # Never block the hook on probe failures


# Module-level cache for context mapping (lazily initialized)
_CONTEXT_MAPPING: dict[str, EnumInjectionContext] | None = None


def _get_context_mapping(
    EnumInjectionContext: type,  # noqa: N803 - matches class name
) -> dict[str, EnumInjectionContext]:
    """
    Get or create the context mapping dictionary.

    Uses module-level caching to avoid recreating the dictionary on every call.
    The EnumInjectionContext type is passed in to handle the lazy import pattern.

    Args:
        EnumInjectionContext: The enum class (imported in main after try/except)

    Returns:
        Dictionary mapping string keys to EnumInjectionContext values
    """
    global _CONTEXT_MAPPING
    if _CONTEXT_MAPPING is None:
        # Map injection_context string to enum
        # Valid values: "session_start", "user_prompt_submit", "pre_tool_use", "subagent_start"
        # Also accept PascalCase for backwards compatibility with enum values
        _CONTEXT_MAPPING = {
            "session_start": EnumInjectionContext.SESSION_START,
            "sessionstart": EnumInjectionContext.SESSION_START,
            "SessionStart": EnumInjectionContext.SESSION_START,
            "user_prompt_submit": EnumInjectionContext.USER_PROMPT_SUBMIT,
            "userpromptsubmit": EnumInjectionContext.USER_PROMPT_SUBMIT,
            "UserPromptSubmit": EnumInjectionContext.USER_PROMPT_SUBMIT,
            "pre_tool_use": EnumInjectionContext.PRE_TOOL_USE,
            "pretooluse": EnumInjectionContext.PRE_TOOL_USE,
            "PreToolUse": EnumInjectionContext.PRE_TOOL_USE,
            "subagent_start": EnumInjectionContext.SUBAGENT_START,
            "subagentstart": EnumInjectionContext.SUBAGENT_START,
            "SubagentStart": EnumInjectionContext.SUBAGENT_START,
        }
    return _CONTEXT_MAPPING


def _reset_context_mapping() -> None:
    """Reset the context mapping cache.

    Used for testing to ensure clean state between test runs.
    Should not be called in production code.
    """
    global _CONTEXT_MAPPING
    _CONTEXT_MAPPING = None


# Configure logging to stderr (stdout reserved for JSON output)
logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


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
            output = create_empty_output()
            print(json.dumps(output))
            sys.exit(0)

        # Parse input JSON
        try:
            input_json = cast("InjectorInput", json.loads(input_data))
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON input: {e}")
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            output = create_error_output(retrieval_ms=elapsed_ms)
            print(json.dumps(output))
            sys.exit(0)

        # Extract input parameters with defaults
        project_path = input_json.get("project", "")
        domain = input_json.get("domain", "")
        session_id = input_json.get("session_id", "")
        correlation_id = input_json.get("correlation_id", "")
        max_patterns = int(input_json.get("max_patterns", 5))
        min_confidence = float(input_json.get("min_confidence", 0.7))
        emit_event = bool(input_json.get("emit_event", True))
        injection_context_str = input_json.get(
            "injection_context", "user_prompt_submit"
        )
        include_footer = bool(input_json.get("include_footer", False))

        # Import handler here to avoid import errors if dependencies missing
        try:
            from omniclaude.hooks.context_config import ContextInjectionConfig
            from omniclaude.hooks.handler_context_injection import inject_patterns_sync
            from omniclaude.hooks.models_injection_tracking import EnumInjectionContext
        except ImportError as e:
            logger.warning(f"Failed to import handler: {e}")
            # Handler import failed - return empty output for graceful degradation
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            output = create_error_output(retrieval_ms=elapsed_ms)
            print(json.dumps(output))
            sys.exit(0)

        # Get cached context mapping (created once at module level)
        context_mapping = _get_context_mapping(EnumInjectionContext)
        injection_context = context_mapping.get(
            injection_context_str, EnumInjectionContext.USER_PROMPT_SUBMIT
        )

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
            emit_event=emit_event,
            injection_context=injection_context,
        )

        # Calculate elapsed time
        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Prepend tier banner (OMN-2782)
        tier_banner = _build_tier_banner()

        # Prepare patterns_context with optional footer
        patterns_context = result.context_markdown
        if include_footer and result.injection_id and patterns_context:
            patterns_context += f"\n\n<!-- injection_id: {result.injection_id} -->"

        # Prepend tier banner to context
        if patterns_context:
            patterns_context = f"{tier_banner}\n\n{patterns_context}"
        else:
            patterns_context = tier_banner

        # Build output (use handler timing if available)
        output = InjectorOutput(
            success=result.success,
            patterns_context=patterns_context,
            pattern_count=result.pattern_count,
            source=result.source,
            retrieval_ms=result.retrieval_ms or elapsed_ms,
            injection_id=result.injection_id,
            cohort=result.cohort,
        )

        print(json.dumps(output))
        sys.exit(0)

    except Exception as e:
        # Catch-all for any unexpected errors
        # CRITICAL: Always exit 0 for hook compatibility
        logger.error(f"Unexpected error in context injection wrapper: {e}")
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        output = create_error_output(retrieval_ms=elapsed_ms)
        print(json.dumps(output))
        sys.exit(0)


if __name__ == "__main__":
    main()
