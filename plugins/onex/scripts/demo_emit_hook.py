#!/usr/bin/env python3
"""Demo script: Emit test hook event to Kafka.

Part of VERTICAL-001 (OMN-1802): Validates the emit phase of the pattern pipeline.

This script emits a test Claude Code hook event using the existing
emit_claude_hook_event() function. The event is published to:
    onex.cmd.omniintelligence.claude-hook-event.v1

Usage:
    # Ensure environment is configured (REQUIRED)
    source .env

    # Run with defaults
    python plugins/onex/scripts/demo_emit_hook.py

    # Custom prompt
    python plugins/onex/scripts/demo_emit_hook.py --prompt "My test prompt"

Environment Variables (REQUIRED - no defaults):
    KAFKA_BOOTSTRAP_SERVERS: Kafka brokers (e.g., 192.168.86.200:29092)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# Add src to path for imports
SRC_DIR = Path(__file__).parent.parent.parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from omnibase_core.enums.hooks.claude_code import EnumClaudeCodeHookEventType

from omniclaude.hooks.handler_event_emitter import (
    ModelClaudeHookEventConfig,
    emit_claude_hook_event,
)
from omniclaude.hooks.topics import TopicBase, build_topic


def validate_config() -> None:
    """Validate required environment variables.

    Per CLAUDE.md, the .env file is the SINGLE SOURCE OF TRUTH for configuration.
    No hardcoded defaults are allowed.
    """
    missing = []
    if not os.environ.get("KAFKA_BOOTSTRAP_SERVERS"):
        missing.append("KAFKA_BOOTSTRAP_SERVERS")
    if missing:
        print("[ERROR] Missing required environment variables:")
        for var in missing:
            print(f"  - {var}")
        print()
        print("Run: source .env")
        sys.exit(1)


def print_banner() -> None:
    """Print demo banner."""
    print("=" * 70)
    print("VERTICAL-001 Demo: Emit Hook Event")
    print("=" * 70)
    print()


def print_config() -> None:
    """Print current configuration.

    Note: validate_config() must be called before this function.
    """
    kafka_servers = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
    # Topics are realm-agnostic (OMN-1972): no environment prefix
    topic = build_topic("", TopicBase.CLAUDE_HOOK_EVENT)

    print("Configuration:")
    print(f"  Kafka Brokers: {kafka_servers}")
    print(f"  Topic:         {topic}")
    print()


async def emit_demo_event(prompt: str, session_id: str | None = None) -> bool:
    """Emit a demo hook event.

    Args:
        prompt: The test prompt to emit.
        session_id: Optional session ID (generated if not provided).

    Returns:
        True if emission succeeded, False otherwise.
    """
    session = session_id or str(uuid4())
    correlation_id = uuid4()

    print("Emitting event:")
    print(f"  Session ID:     {session}")
    print(f"  Correlation ID: {correlation_id}")
    print(
        f"  Prompt:         {prompt[:50]}..."
        if len(prompt) > 50
        else f"  Prompt:         {prompt}"
    )
    print()

    config = ModelClaudeHookEventConfig(
        event_type=EnumClaudeCodeHookEventType.USER_PROMPT_SUBMIT,
        session_id=session,
        prompt=prompt,
        correlation_id=correlation_id,
        timestamp_utc=datetime.now(UTC),
    )

    result = await emit_claude_hook_event(config)

    if result.success:
        print("[OK] Event emitted successfully")
        print(f"  Topic: {result.topic}")
        return True
    else:
        print("[FAIL] Event emission failed")
        print(f"  Error: {result.error_message}")
        return False


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Emit test hook event to Kafka (VERTICAL-001 demo)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--prompt",
        default="Demo pattern: Always validate input before processing",
        help="Prompt text to emit (default: demo pattern text)",
    )
    parser.add_argument(
        "--session-id",
        help="Session ID (generated if not provided)",
    )

    args = parser.parse_args()

    print_banner()
    validate_config()
    print_config()

    # Run async emission
    success = asyncio.run(emit_demo_event(args.prompt, args.session_id))

    print()
    print("=" * 70)
    if success:
        print("Demo step 1/3 complete: Event emitted to Kafka")
        print()
        print("Next steps:")
        print("  1. Run consumer: python plugins/onex/scripts/demo_consume_store.py")
        print("  2. Query patterns: python plugins/onex/scripts/demo_query_patterns.py")
    else:
        print("Demo failed at step 1/3: Event emission")
        print()
        print("Troubleshooting:")
        print("  1. Run: source .env")
        print("  2. Check KAFKA_BOOTSTRAP_SERVERS is set correctly")
        print("  3. Verify Kafka/Redpanda is running at the configured address")
        print("  4. Check network connectivity")
    print("=" * 70)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
