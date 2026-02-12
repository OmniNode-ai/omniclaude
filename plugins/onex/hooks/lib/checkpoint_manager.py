#!/usr/bin/env python3
"""Checkpoint Manager - CLI wrapper for pipeline checkpoint operations.

Provides a command-line interface for writing, reading, validating, and listing
pipeline checkpoints.  Delegates to ``omnibase_infra`` checkpoint handlers and
models when available, falling back to a JSON error response when the package
is not installed.

Design Decisions:
    - **CLI-first**: Designed for invocation from shell scripts and skill prompts.
    - **JSON output**: All output is JSON to stdout for machine parsing.
    - **Non-blocking**: Checkpoint write failures in the pipeline context are
      non-blocking (the caller decides; this CLI reports success/failure).
    - **Graceful degradation**: If ``omnibase_infra`` is not installed, the CLI
      prints an error JSON and exits with code 1.

Storage Layout::

    ~/.claude/checkpoints/{ticket_id}/{run_id}/phase_{N}_{name}_a{attempt}.yaml

CLI Usage::

    # Write a checkpoint
    python checkpoint_manager.py write \\
      --ticket-id OMN-2144 --run-id abcd1234 --phase implement --attempt 1 \\
      --repo-commit-map '{"omniclaude": "a1b2c3d"}' \\
      --artifact-paths '["src/foo.py"]' \\
      --payload '{"branch_name": "feat/x", "commit_sha": "a1b2c3d", ...}'

    # Read latest checkpoint for a phase
    python checkpoint_manager.py read \\
      --ticket-id OMN-2144 --run-id abcd1234 --phase implement

    # Validate a checkpoint
    python checkpoint_manager.py validate \\
      --ticket-id OMN-2144 --run-id abcd1234 --phase implement

    # List all checkpoints
    python checkpoint_manager.py list --ticket-id OMN-2144 [--run-id abcd1234]

Related Tickets:
    - OMN-2143: Checkpoint infrastructure in omnibase_infra
    - OMN-2144: Checkpoint skill and pipeline resume integration

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

logger = logging.getLogger(__name__)

# =============================================================================
# Lazy import gate — omnibase_infra may not be installed
# =============================================================================

_INFRA_AVAILABLE = False
_IMPORT_ERROR: str | None = None

try:
    from omnibase_infra.enums.enum_checkpoint_phase import EnumCheckpointPhase
    from omnibase_infra.models.checkpoint.model_checkpoint import (
        CHECKPOINT_SCHEMA_VERSION,
        ModelCheckpoint,
    )
    from omnibase_infra.nodes.node_checkpoint_effect.handlers.handler_checkpoint_list import (
        HandlerCheckpointList,
    )
    from omnibase_infra.nodes.node_checkpoint_effect.handlers.handler_checkpoint_read import (
        HandlerCheckpointRead,
    )
    from omnibase_infra.nodes.node_checkpoint_effect.handlers.handler_checkpoint_write import (
        HandlerCheckpointWrite,
    )
    from omnibase_infra.nodes.node_checkpoint_validate_compute.handlers.handler_checkpoint_validate import (
        HandlerCheckpointValidate,
    )

    _INFRA_AVAILABLE = True
except ImportError as exc:
    _IMPORT_ERROR = str(exc)


# =============================================================================
# Container Stub
# =============================================================================


class _ContainerStub:
    # TODO(OMN-2144): Replace with proper DI container when checkpoint_manager runs within service context
    """Minimal stub satisfying the ``ModelONEXContainer`` TYPE_CHECKING guard.

    The checkpoint handlers store the container but never call methods on it
    during normal operation.  This stub allows CLI instantiation without the
    full DI container stack.

    Defensive ``__getattr__``: If a handler *does* access a container attribute
    (e.g. during future refactoring or in an error path), this returns a no-op
    callable rather than raising ``AttributeError``.  The no-op returns ``None``
    so callers that inspect the result see a falsy sentinel instead of crashing.
    """

    def __getattr__(self, name: str) -> Any:
        """Return a no-op callable for any missing attribute access."""

        def _noop(*args: Any, **kwargs: Any) -> None:  # noqa: ANN401
            sys.stderr.write(
                f"WARNING: _ContainerStub.__getattr__ called for '{name}' "
                f"with args={args}, kwargs={kwargs}. "
                f"This may indicate a handler is using container features "
                f"not available in CLI mode.\n"
            )

        return _noop


# =============================================================================
# Helpers
# =============================================================================

# Phase name -> EnumCheckpointPhase mapping (populated after import gate)
_PHASE_MAP: dict[str, Any] = {}
if _INFRA_AVAILABLE:
    _PHASE_MAP = {phase.value: phase for phase in EnumCheckpointPhase}

# Canonical list of valid phase names for argparse choices.
# Derived from _PHASE_MAP when omnibase_infra is available; hardcoded fallback otherwise
# so that ``--help`` always displays the valid options.
_PHASE_CHOICES: list[str] = (
    list(_PHASE_MAP.keys())
    if _PHASE_MAP
    else [
        "implement",
        "local_review",
        "create_pr",
        "pr_release_ready",
        "ready_for_merge",
    ]
)

# Project-specific UUID namespace for deterministic ID generation.
# Derived via ``uuid5(NAMESPACE_DNS, "onex.omninode.io")`` so it is stable
# and does NOT collide with the well-known RFC 4122 namespaces (DNS, URL, etc.).
_ONEX_NAMESPACE = UUID("e176b05f-f761-5a9d-9a51-ac6d5a3566ee")


def _error_json(message: str) -> str:
    """Return a JSON error string."""
    return json.dumps({"success": False, "error": message})


def _result_json(data: dict[str, Any]) -> str:
    """Return a JSON result string with pretty printing."""
    return json.dumps(data, indent=2, default=str)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _normalize_run_id(run_id: str) -> str:
    """Convert a short run ID to a deterministic full UUID.

    The ticket-pipeline uses ``str(uuid4())[:8]`` as short run IDs (e.g. "a1b2c3d4"),
    but the checkpoint model requires a full UUID.  This function pads short IDs into
    a valid UUID v5 (deterministic, namespace-based) so the same short ID always maps
    to the same UUID.

    If the input is already a valid UUID, it is returned unchanged.
    """
    try:
        UUID(run_id)
        return run_id  # Already valid
    except ValueError:
        # Deterministic UUID5 from ONEX namespace + short run_id
        return str(uuid5(_ONEX_NAMESPACE, run_id))


def _build_checkpoint_dict(
    *,
    ticket_id: str,
    run_id: str,
    phase: str,
    attempt: int,
    repo_commit_map: dict[str, str],
    artifact_paths: list[str],
    payload: dict[str, Any],
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Build a checkpoint dict suitable for ModelCheckpoint.model_validate().

    Args:
        timestamp: ISO-8601 timestamp string.  If ``None`` (the default),
            ``datetime.now(UTC).isoformat()`` is used.  Accepting an explicit
            value enables deterministic testing per the repo invariant that
            timestamps must be explicitly injectable.
    """
    # Ensure the payload has the phase discriminator
    payload_with_phase = {**payload, "phase": phase}

    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "run_id": _normalize_run_id(run_id),
        "ticket_id": ticket_id,
        "phase": phase,
        "timestamp_utc": timestamp
        if timestamp is not None
        else datetime.now(UTC).isoformat(),
        "repo_commit_map": repo_commit_map,
        "artifact_paths": tuple(artifact_paths),
        "attempt_number": attempt,
        "phase_payload": payload_with_phase,
    }


def _checkpoint_to_dict(checkpoint: Any) -> dict[str, Any]:
    """Serialize a ModelCheckpoint to a JSON-safe dict."""
    return cast("dict[str, Any]", checkpoint.model_dump(mode="json"))


# =============================================================================
# CLI Command Handlers
# =============================================================================


def _cli_write(args: argparse.Namespace) -> int:
    """Write a checkpoint to disk."""
    if not _INFRA_AVAILABLE:
        print(_error_json(f"omnibase_infra not available: {_IMPORT_ERROR}"))
        return 1

    try:
        repo_commit_map = (
            json.loads(args.repo_commit_map) if args.repo_commit_map else {}
        )
        artifact_paths = json.loads(args.artifact_paths) if args.artifact_paths else []
        payload = json.loads(args.payload) if args.payload else {}
    except json.JSONDecodeError as exc:
        print(_error_json(f"Invalid JSON argument: {exc}"))
        return 1

    if not isinstance(repo_commit_map, dict):
        print(_error_json("--repo-commit-map must be a JSON object"))
        return 1
    if not isinstance(artifact_paths, list):
        print(_error_json("--artifact-paths must be a JSON array"))
        return 1
    if not isinstance(payload, dict):
        print(_error_json("--payload must be a JSON object"))
        return 1

    # Validate phase name
    if args.phase not in _PHASE_MAP:
        print(
            _error_json(
                f"Invalid phase: {args.phase}. Valid: {list(_PHASE_MAP.keys())}"
            )
        )
        return 1

    try:
        checkpoint_dict = _build_checkpoint_dict(
            ticket_id=args.ticket_id,
            run_id=args.run_id,
            phase=args.phase,
            attempt=args.attempt,
            repo_commit_map=repo_commit_map,
            artifact_paths=artifact_paths,
            payload=payload,
            timestamp=args.timestamp,
        )

        # Validate the checkpoint data via Pydantic before writing
        checkpoint = ModelCheckpoint.model_validate(checkpoint_dict)

        # Create handler with stub container
        handler = HandlerCheckpointWrite(container=_ContainerStub())  # type: ignore[arg-type]

        correlation_id = uuid4()
        envelope: dict[str, object] = {
            "checkpoint": checkpoint,
            "correlation_id": correlation_id,
        }

        result = _run_async(handler.execute(envelope))
        output_model = result.result

        print(
            _result_json(
                {
                    "success": output_model.success,
                    "checkpoint_path": output_model.checkpoint_path,
                    "correlation_id": str(correlation_id),
                }
            )
        )
        return 0 if output_model.success else 1

    except Exception as exc:
        print(_error_json(f"Write failed: {exc}"))
        return 1


def _cli_read(args: argparse.Namespace) -> int:
    """Read the latest checkpoint for a given phase."""
    if not _INFRA_AVAILABLE:
        print(_error_json(f"omnibase_infra not available: {_IMPORT_ERROR}"))
        return 1

    if args.phase not in _PHASE_MAP:
        print(
            _error_json(
                f"Invalid phase: {args.phase}. Valid: {list(_PHASE_MAP.keys())}"
            )
        )
        return 1

    try:
        handler = HandlerCheckpointRead(container=_ContainerStub())  # type: ignore[arg-type]

        correlation_id = uuid4()
        normalized_run_id = UUID(_normalize_run_id(args.run_id))
        envelope: dict[str, object] = {
            "ticket_id": args.ticket_id,
            "run_id": normalized_run_id,
            "phase": _PHASE_MAP[args.phase],
            "correlation_id": correlation_id,
        }

        result = _run_async(handler.execute(envelope))
        output_model = result.result

        response: dict[str, Any] = {
            "success": output_model.success,
            "correlation_id": str(correlation_id),
        }

        if output_model.success and output_model.checkpoint is not None:
            response["checkpoint"] = _checkpoint_to_dict(output_model.checkpoint)
        elif output_model.error:
            response["error"] = output_model.error

        print(_result_json(response))
        return 0 if output_model.success else 1

    except Exception as exc:
        print(_error_json(f"Read failed: {exc}"))
        return 1


def _cli_validate(args: argparse.Namespace) -> int:
    """Validate a checkpoint by reading it first, then running structural validation."""
    if not _INFRA_AVAILABLE:
        print(_error_json(f"omnibase_infra not available: {_IMPORT_ERROR}"))
        return 1

    if args.phase not in _PHASE_MAP:
        print(
            _error_json(
                f"Invalid phase: {args.phase}. Valid: {list(_PHASE_MAP.keys())}"
            )
        )
        return 1

    try:
        # Step 1: Read the checkpoint
        read_handler = HandlerCheckpointRead(container=_ContainerStub())  # type: ignore[arg-type]

        correlation_id = uuid4()
        normalized_run_id = UUID(_normalize_run_id(args.run_id))
        read_envelope: dict[str, object] = {
            "ticket_id": args.ticket_id,
            "run_id": normalized_run_id,
            "phase": _PHASE_MAP[args.phase],
            "correlation_id": correlation_id,
        }

        read_result = _run_async(read_handler.execute(read_envelope))
        read_output = read_result.result

        if not read_output.success or read_output.checkpoint is None:
            print(
                _result_json(
                    {
                        "is_valid": False,
                        "success": False,
                        "errors": [read_output.error or "Checkpoint not found"],
                        "warnings": [],
                        "correlation_id": str(correlation_id),
                    }
                )
            )
            return 1

        # Step 2: Validate the checkpoint
        validate_handler = HandlerCheckpointValidate(container=_ContainerStub())  # type: ignore[arg-type]

        validate_envelope: dict[str, object] = {
            "checkpoint": read_output.checkpoint,
            "correlation_id": correlation_id,
        }

        validate_result = _run_async(validate_handler.execute(validate_envelope))
        validate_output = validate_result.result

        print(
            _result_json(
                {
                    "is_valid": validate_output.is_valid,
                    "success": True,
                    "errors": list(validate_output.errors),
                    "warnings": list(validate_output.warnings),
                    "correlation_id": str(correlation_id),
                    "checkpoint": _checkpoint_to_dict(read_output.checkpoint),
                }
            )
        )
        return 0 if validate_output.is_valid else 1

    except Exception as exc:
        print(_error_json(f"Validate failed: {exc}"))
        return 1


def _cli_list(args: argparse.Namespace) -> int:
    """List all checkpoints for a ticket, optionally scoped to a run."""
    if not _INFRA_AVAILABLE:
        print(_error_json(f"omnibase_infra not available: {_IMPORT_ERROR}"))
        return 1

    try:
        handler = HandlerCheckpointList(container=_ContainerStub())  # type: ignore[arg-type]

        correlation_id = uuid4()
        envelope: dict[str, object] = {
            "ticket_id": args.ticket_id,
            "correlation_id": correlation_id,
        }

        if args.run_id:
            envelope["run_id"] = UUID(_normalize_run_id(args.run_id))

        result = _run_async(handler.execute(envelope))
        output_model = result.result

        checkpoints_list = [_checkpoint_to_dict(cp) for cp in output_model.checkpoints]

        print(
            _result_json(
                {
                    "success": output_model.success,
                    "count": len(checkpoints_list),
                    "checkpoints": checkpoints_list,
                    "correlation_id": str(correlation_id),
                }
            )
        )
        return 0

    except Exception as exc:
        print(_error_json(f"List failed: {exc}"))
        return 1


# =============================================================================
# CLI Entry Point
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for checkpoint_manager.

    Args:
        argv: Command line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    parser = argparse.ArgumentParser(
        description="Pipeline checkpoint manager — write, read, validate, and list checkpoints",
        prog="checkpoint_manager",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── write command ─────────────────────────────────────────────────
    write_parser = subparsers.add_parser(
        "write",
        help="Write a checkpoint after a phase completes",
    )
    write_parser.add_argument(
        "--ticket-id", required=True, help="Ticket ID (e.g. OMN-2144)"
    )
    write_parser.add_argument(
        "--run-id", required=True, help="Pipeline run ID (UUID or short ID)"
    )
    write_parser.add_argument(
        "--phase",
        required=True,
        choices=_PHASE_CHOICES,
        help="Pipeline phase that completed",
    )
    write_parser.add_argument(
        "--attempt", type=int, default=1, help="Attempt number (default: 1)"
    )
    write_parser.add_argument(
        "--repo-commit-map",
        default="{}",
        help='JSON object mapping repo names to commit SHAs (e.g. \'{"omniclaude": "a1b2c3d"}\')',
    )
    write_parser.add_argument(
        "--artifact-paths",
        default="[]",
        help="JSON array of relative artifact paths (e.g. '[\"src/foo.py\"]')",
    )
    write_parser.add_argument(
        "--payload",
        default="{}",
        help="JSON object with phase-specific payload fields",
    )
    write_parser.add_argument(
        "--timestamp",
        default=None,
        help="ISO-8601 UTC timestamp for the checkpoint (default: now). "
        "Accepts an explicit value for deterministic testing.",
    )
    write_parser.set_defaults(func=_cli_write)

    # ── read command ──────────────────────────────────────────────────
    read_parser = subparsers.add_parser(
        "read",
        help="Read the latest checkpoint for a phase",
    )
    read_parser.add_argument("--ticket-id", required=True, help="Ticket ID")
    read_parser.add_argument("--run-id", required=True, help="Pipeline run ID")
    read_parser.add_argument(
        "--phase",
        required=True,
        choices=_PHASE_CHOICES,
        help="Phase to read",
    )
    read_parser.set_defaults(func=_cli_read)

    # ── validate command ──────────────────────────────────────────────
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a checkpoint (reads then validates structurally)",
    )
    validate_parser.add_argument("--ticket-id", required=True, help="Ticket ID")
    validate_parser.add_argument("--run-id", required=True, help="Pipeline run ID")
    validate_parser.add_argument(
        "--phase",
        required=True,
        choices=_PHASE_CHOICES,
        help="Phase to validate",
    )
    validate_parser.set_defaults(func=_cli_validate)

    # ── list command ──────────────────────────────────────────────────
    list_parser = subparsers.add_parser(
        "list",
        help="List all checkpoints for a ticket",
    )
    list_parser.add_argument("--ticket-id", required=True, help="Ticket ID")
    list_parser.add_argument(
        "--run-id", default=None, help="Optional: scope to a specific run ID"
    )
    list_parser.set_defaults(func=_cli_list)

    args = parser.parse_args(argv)

    # Configure logging
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
    else:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(levelname)s: %(message)s",
        )

    return cast("int", args.func(args))


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "main",
]
