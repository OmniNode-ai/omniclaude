"""CLI wrapper for emitting agent status events from the ticket-work skill.

Thin CLI around emit_agent_status() that enables markdown-based skills
(which instruct Claude to run bash commands) to emit status events at
key workflow points.

INVARIANT: This script MUST fail open and ALWAYS exit 0.
If emission fails, print a warning to stderr and continue.

Related Tickets:
    - OMN-1850: Integrate status reporting with /ticket-work phases
    - OMN-1848: Agent Status Kafka Emitter (dependency)

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

try:
    from omniclaude.hooks.schemas import EnumAgentState as _EnumAgentState

    _VALID_STATES = [s.value for s in _EnumAgentState]
except (ImportError, ModuleNotFoundError):
    # Fallback: must match EnumAgentState values in schemas.py
    _VALID_STATES = [
        "idle",
        "working",
        "blocked",
        "awaiting_input",
        "finished",
        "error",
    ]


def _progress_in_range(raw: str) -> float:
    """Argparse *type* callback: parse a float and enforce [0.0, 1.0]."""
    value = float(raw)
    if value < 0.0 or value > 1.0:
        raise argparse.ArgumentTypeError(
            f"progress must be between 0.0 and 1.0, got {value}"
        )
    return value


def _message_within_limit(raw: str) -> str:
    """Argparse *type* callback: enforce max 500 character message length."""
    if len(raw) > 500:
        raise argparse.ArgumentTypeError(
            f"message must be at most 500 characters, got {len(raw)}"
        )
    return raw


def main(argv: list[str] | None = None) -> None:
    """Parse CLI args and delegate to emit_agent_status().

    Args:
        argv: CLI arguments (defaults to sys.argv[1:] when None).
              Exposed for testability.
    """
    try:
        parser = argparse.ArgumentParser(
            description="Emit agent status event for ticket-work phases.",
            prog="emit_ticket_status",
        )
        parser.add_argument(
            "--state",
            required=True,
            choices=_VALID_STATES,
            help="Agent state (idle, working, blocked, awaiting_input, finished, error)",
        )
        parser.add_argument(
            "--message",
            required=True,
            type=_message_within_limit,
            help="Human-readable status message (max 500 chars)",
        )
        parser.add_argument(
            "--phase",
            default=None,
            help="Current workflow phase (e.g., intake, research, spec)",
        )
        parser.add_argument(
            "--task",
            default=None,
            help="Current task description",
        )
        parser.add_argument(
            "--progress",
            type=_progress_in_range,
            default=None,
            help="Progress 0.0-1.0",
        )
        parser.add_argument(
            "--blocking-reason",
            default=None,
            help="Why the agent is blocked (for notifications)",
        )
        parser.add_argument(
            "--ticket-id",
            default=None,
            help="Linear ticket ID (e.g., OMN-1850), injected into metadata",
        )
        parser.add_argument(
            "--metadata",
            default=None,
            help="Additional metadata as a JSON string",
        )

        args = parser.parse_args(argv)

        # Build metadata dict: parse JSON string, then inject ticket_id.
        # json.loads can return dict[str, Any]; Pydantic coerces values at
        # the model layer so we keep the annotation honest here.
        metadata: dict[str, Any] | None = None
        if args.metadata is not None:
            try:
                parsed = json.loads(args.metadata)
            except (json.JSONDecodeError, TypeError):
                print(
                    f"Warning: --metadata is not valid JSON: {args.metadata!r}, ignoring",
                    file=sys.stderr,
                )
                metadata = {}
            else:
                if isinstance(parsed, dict):
                    metadata = parsed
                else:
                    print(
                        f"Warning: --metadata must be a JSON object, got {type(parsed).__name__}, ignoring",
                        file=sys.stderr,
                    )
                    metadata = {}

        if args.ticket_id is not None:
            if metadata is None:
                metadata = {}
            if "ticket_id" in metadata and metadata["ticket_id"] != args.ticket_id:
                print(
                    f"Warning: --ticket-id '{args.ticket_id}' overwrites "
                    f"metadata ticket_id '{metadata['ticket_id']}'",
                    file=sys.stderr,
                )
            metadata["ticket_id"] = args.ticket_id

        # Delegate to the real emitter.
        # Uses __package__ check for proper import resolution: when run
        # as ``python3 emit_ticket_status.py`` there is no parent package,
        # so the relative import would fail.  This matches the pattern
        # established in route_via_events_wrapper.py.
        if __package__:
            from .agent_status_emitter import emit_agent_status
        else:
            from agent_status_emitter import emit_agent_status  # type: ignore[no-redef]

        result = emit_agent_status(
            state=args.state,
            message=args.message,
            current_phase=args.phase,
            current_task=args.task,
            progress=args.progress,
            blocking_reason=args.blocking_reason,
            metadata=metadata,
        )

        if not result:
            print(
                "Warning: status emission returned False (non-fatal)",
                file=sys.stderr,
            )

    except SystemExit as e:
        # argparse calls sys.exit(2) on missing required args;
        # re-raise only exit(0), swallow everything else to stay fail-open
        if e.code == 0:
            raise
        print(
            f"Warning: argument parsing failed (exit code {e.code}), continuing",
            file=sys.stderr,
        )
    except Exception as e:
        print(
            f"Warning: emit_ticket_status failed: {type(e).__name__}: {e}",
            file=sys.stderr,
        )


# CLI-only module -- nothing to export
__all__: list[str] = []


if __name__ == "__main__":
    main()
