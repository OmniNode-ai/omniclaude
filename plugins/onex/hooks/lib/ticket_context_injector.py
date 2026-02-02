#!/usr/bin/env python3
"""Ticket context injector - Inject active ticket context into Claude sessions.

This module enables SessionStart hooks to inject active ticket context from
the /ticket-work workflow. It follows the same patterns as context_injection_wrapper.py
and learned_pattern_injector.py.

Part of OMN-1830: Ticket context injection for session enrichment.

Usage:
    # Python API
    from ticket_context_injector import find_active_ticket, build_ticket_context

    ticket_id = find_active_ticket()
    if ticket_id:
        context = build_ticket_context(ticket_id)

    # CLI (JSON stdin -> JSON stdout)
    echo '{}' | python ticket_context_injector.py

IMPORTANT: Always exits with code 0 for hook compatibility.
Any errors result in empty context, not failures.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import TypedDict

# Optional YAML dependency - handled gracefully if not installed
try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    yaml = None  # type: ignore[assignment]
    YAML_AVAILABLE = False

# Configure logging to stderr (stdout reserved for JSON output)
logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# Default tickets directory
DEFAULT_TICKETS_DIR = Path.home() / ".claude" / "tickets"


# =============================================================================
# TypedDicts for JSON Interface
# =============================================================================


class TicketInjectorInput(TypedDict, total=False):
    """Input schema for the ticket context injector.

    All fields are optional with defaults applied at runtime via .get().

    Attributes:
        tickets_dir: Override the default tickets directory.
        ticket_id: Specific ticket ID to load (if not provided, finds active ticket).
    """

    tickets_dir: str
    ticket_id: str


class TicketInjectorOutput(TypedDict):
    """Output schema for the ticket context injector.

    Attributes:
        success: Whether ticket loading succeeded.
        ticket_context: Formatted markdown context for injection.
        ticket_id: The ticket ID that was loaded (or None if no ticket found).
        retrieval_ms: Time taken to retrieve and format context.
    """

    success: bool
    ticket_context: str
    ticket_id: str | None
    retrieval_ms: int


class ContractData(TypedDict, total=False):
    """Partial schema for contract.yaml files.

    Only includes fields needed for context injection.
    """

    ticket_id: str
    title: str
    repo: str
    branch: str
    phase: str
    questions: list[dict[str, str | None]]
    gates: list[dict[str, str]]


# =============================================================================
# Core Functions
# =============================================================================


def find_active_ticket(tickets_dir: Path | None = None) -> str | None:
    """Find the active ticket by searching for the most recently modified contract.

    Searches `~/.claude/tickets/` directory for all `contract.yaml` files in
    subdirectories and returns the ticket_id from the most recently modified one.

    Args:
        tickets_dir: Override the default tickets directory. If None, uses
            ~/.claude/tickets/

    Returns:
        The ticket_id of the most recently modified contract, or None if no
        tickets found or directory doesn't exist.

    Note:
        This function handles all errors gracefully and will never raise.
        On any error, it returns None.
    """
    try:
        search_dir = tickets_dir or DEFAULT_TICKETS_DIR

        if not search_dir.exists():
            logger.debug(f"Tickets directory does not exist: {search_dir}")
            return None

        if not search_dir.is_dir():
            logger.debug(f"Tickets path is not a directory: {search_dir}")
            return None

        # Find all contract.yaml files in subdirectories
        contract_files: list[tuple[Path, float]] = []
        for ticket_dir in search_dir.iterdir():
            if not ticket_dir.is_dir():
                continue

            contract_path = ticket_dir / "contract.yaml"
            if contract_path.exists() and contract_path.is_file():
                try:
                    mtime = contract_path.stat().st_mtime
                    contract_files.append((contract_path, mtime))
                except OSError as e:
                    logger.debug(f"Failed to stat {contract_path}: {e}")
                    continue

        if not contract_files:
            logger.debug("No contract.yaml files found")
            return None

        # Sort by mtime descending, then by path ascending for deterministic tie-breaking
        contract_files.sort(key=lambda x: (-x[1], str(x[0])))
        most_recent_path = contract_files[0][0]

        # Extract ticket_id from directory name
        ticket_id = most_recent_path.parent.name
        logger.debug(f"Found active ticket: {ticket_id}")
        return ticket_id

    except Exception as e:
        logger.warning(f"Error finding active ticket: {e}")
        return None


def build_ticket_context(
    ticket_id: str,
    tickets_dir: Path | None = None,
) -> str:
    """Build markdown context for an active ticket.

    Loads the contract from `~/.claude/tickets/{ticket_id}/contract.yaml`,
    parses YAML to extract ticket metadata, and formats it as a markdown summary.

    Args:
        ticket_id: The ticket ID to load.
        tickets_dir: Override the default tickets directory. If None, uses
            ~/.claude/tickets/

    Returns:
        Formatted markdown context string, or empty string if contract not found
        or parse error occurs.

    Note:
        This function is read-only and will NEVER mutate contract files.
        It handles all errors gracefully and will never raise.
    """
    try:
        search_dir = tickets_dir or DEFAULT_TICKETS_DIR
        contract_path = search_dir / ticket_id / "contract.yaml"

        if not contract_path.exists():
            logger.debug(f"Contract not found: {contract_path}")
            return ""

        # Parse YAML
        if not YAML_AVAILABLE:
            logger.warning("PyYAML not installed, cannot parse contract")
            return ""

        with contract_path.open("r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        if not raw_data or not isinstance(raw_data, dict):
            logger.debug(f"Invalid contract format in {contract_path}")
            return ""

        data: ContractData = raw_data

        # Extract fields with defaults
        title = data.get("title", "Untitled")
        repo = data.get("repo", "unknown")
        branch = data.get("branch") or "not created"
        phase = data.get("phase", "unknown")

        # Count pending questions (where answer is null/empty)
        questions = data.get("questions", [])
        pending_questions = 0
        if isinstance(questions, list):
            for q in questions:
                if isinstance(q, dict):
                    answer = q.get("answer")
                    if answer is None or answer == "":
                        pending_questions += 1

        # Count pending gates (where status != "approved")
        gates = data.get("gates", [])
        pending_gates = 0
        if isinstance(gates, list):
            for g in gates:
                if isinstance(g, dict):
                    status = g.get("status", "")
                    if status != "approved":
                        pending_gates += 1

        # Format markdown
        lines = [
            f"## Active Ticket: {ticket_id}",
            "",
            f"**{title}**",
            f"- Repository: {repo}",
            f"- Branch: {branch}",
            f"- Phase: {phase}",
            f"- Pending Questions: {pending_questions}",
            f"- Pending Gates: {pending_gates}",
            "",
            f"Run `/ticket-work {ticket_id}` to continue.",
        ]

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"Error building ticket context for {ticket_id}: {e}")
        return ""


# =============================================================================
# Output Helpers
# =============================================================================


def _create_error_output(retrieval_ms: int = 0) -> TicketInjectorOutput:
    """Create an output for error cases (still returns success for hook compatibility)."""
    return TicketInjectorOutput(
        success=True,  # Always success for hook compatibility
        ticket_context="",
        ticket_id=None,
        retrieval_ms=retrieval_ms,
    )


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> None:
    """CLI entry point for ticket context injection.

    Reads JSON input from stdin, loads ticket context, and writes JSON output
    to stdout.

    IMPORTANT: Always exits with code 0 for hook compatibility.
    Any errors result in empty context, not failures.
    """
    start_time = time.monotonic()

    try:
        # Read input from stdin
        input_data = sys.stdin.read().strip()

        # Parse input JSON (empty input is valid)
        input_json: TicketInjectorInput = {}
        if input_data:
            try:
                input_json = json.loads(input_data)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON input: {e}")
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                output = _create_error_output(retrieval_ms=elapsed_ms)
                print(json.dumps(output))
                sys.exit(0)

        # Extract input parameters
        tickets_dir_str = input_json.get("tickets_dir", "")
        tickets_dir: Path | None = None
        if tickets_dir_str:
            tickets_dir = Path(tickets_dir_str)

        explicit_ticket_id = input_json.get("ticket_id", "")

        # Find active ticket or use explicit one
        ticket_id: str | None
        if explicit_ticket_id:
            ticket_id = explicit_ticket_id
        else:
            ticket_id = find_active_ticket(tickets_dir)

        # Build context if ticket found
        ticket_context = ""
        if ticket_id:
            ticket_context = build_ticket_context(ticket_id, tickets_dir)

        # Calculate elapsed time
        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Build output
        output = TicketInjectorOutput(
            success=True,
            ticket_context=ticket_context,
            ticket_id=ticket_id,
            retrieval_ms=elapsed_ms,
        )

        print(json.dumps(output))
        sys.exit(0)

    except Exception as e:
        # Catch-all for any unexpected errors
        # CRITICAL: Always exit 0 for hook compatibility
        logger.error(f"Unexpected error in ticket context injector: {e}")
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        output = _create_error_output(retrieval_ms=elapsed_ms)
        print(json.dumps(output))
        sys.exit(0)


if __name__ == "__main__":
    main()
