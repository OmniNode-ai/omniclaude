#!/usr/bin/env python3
"""
Provider Selection Event Publisher - CLI Integration

Command-line tool for publishing provider selection events to Kafka.
Designed to be called from toggle-claude-provider.sh script after provider changes.

Usage:
    python3 scripts/publish_provider_selection.py \
        --provider gemini-flash \
        --model gemini-1.5-flash-002 \
        --reason "Cost-effective for high-volume pattern matching" \
        --criteria '{"cost_per_token": 0.000001, "latency_ms": 50}'

    # Or with simpler arguments:
    python3 scripts/publish_provider_selection.py \
        --provider claude \
        --model claude-3-5-sonnet-20241022 \
        --reason "User requested switch to Claude"

Exit Codes:
    0 - Event published successfully
    1 - Failed to publish event (Kafka unavailable or error)
    2 - Invalid arguments

Integration Example (in toggle-claude-provider.sh):
    # After switching to provider:
    python3 scripts/publish_provider_selection.py \
        --provider "$provider_name" \
        --model "$model_name" \
        --reason "$selection_reason" || true  # Don't fail script if event publish fails

Created: 2025-11-13
Reference: OMN-32
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path as PathLib
from uuid import uuid4


# Add project root to path
_project_root = PathLib(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from agents.lib.provider_selection_publisher import publish_provider_selection_sync


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Publish provider selection event to Kafka",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage:
  %(prog)s --provider gemini-flash --model gemini-1.5-flash-002 --reason "Speed"

  # With selection criteria:
  %(prog)s --provider claude --model claude-3-5-sonnet-20241022 \\
    --reason "High quality" \\
    --criteria '{"quality_score": 0.95, "cost_per_token": 0.003}'

  # With correlation ID (for request tracking):
  %(prog)s --provider openai --model gpt-4 \\
    --reason "Testing" \\
    --correlation-id abc-123-def-456
        """,
    )

    parser.add_argument(
        "--provider",
        required=True,
        help="Provider name (e.g., gemini-flash, claude, openai, zai, together)",
    )

    parser.add_argument(
        "--model",
        required=True,
        help="Model name (e.g., gemini-1.5-flash-002, claude-3-5-sonnet-20241022)",
    )

    parser.add_argument(
        "--reason",
        required=True,
        help="Human-readable selection reason (e.g., 'Cost-effective for pattern matching')",
    )

    parser.add_argument(
        "--criteria",
        type=str,
        default=None,
        help='JSON string with selection criteria (e.g., \'{"cost": 0.000001, "latency_ms": 50}\')',
    )

    parser.add_argument(
        "--correlation-id",
        type=str,
        default=None,
        help="Correlation ID for request tracking (auto-generated if not provided)",
    )

    parser.add_argument(
        "--causation-id",
        type=str,
        default=None,
        help="Causation ID for event chains (optional)",
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output (only errors shown)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output (debug logging)",
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # Parse selection criteria JSON if provided
    selection_criteria = None
    if args.criteria:
        try:
            selection_criteria = json.loads(args.criteria)
            if not isinstance(selection_criteria, dict):
                logger.error("--criteria must be a JSON object (dictionary)")
                return 2
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in --criteria: {e}")
            return 2

    # Generate correlation ID if not provided
    correlation_id = args.correlation_id or str(uuid4())

    # Publish provider selection event
    try:
        logger.info(
            f"Publishing provider selection event: provider={args.provider}, "
            f"model={args.model}, correlation_id={correlation_id}"
        )

        success = publish_provider_selection_sync(
            provider_name=args.provider,
            model_name=args.model,
            correlation_id=correlation_id,
            selection_reason=args.reason,
            selection_criteria=selection_criteria,
            causation_id=args.causation_id,
        )

        if success:
            if not args.quiet:
                logger.info(
                    f"✓ Successfully published provider selection event "
                    f"(correlation_id={correlation_id})"
                )
            return 0
        else:
            logger.error("Failed to publish provider selection event")
            return 1

    except Exception as e:
        logger.error(f"Error publishing provider selection event: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
