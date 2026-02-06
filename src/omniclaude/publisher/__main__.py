"""Entry point for running the publisher as a background process.

Usage from shell scripts:
    python -m omniclaude.publisher start --kafka-servers $KAFKA_BOOTSTRAP_SERVERS
    python -m omniclaude.publisher start --kafka-servers $KAFKA_BOOTSTRAP_SERVERS --socket-path /tmp/my.sock

This replaces the old: python -m omnibase_infra.runtime.emit_daemon.cli start
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OmniClaude Embedded Event Publisher",
        prog="python -m omniclaude.publisher",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start_parser = sub.add_parser("start", help="Start the publisher")
    start_parser.add_argument(
        "--kafka-servers",
        required=True,
        help="Kafka bootstrap servers (host:port, comma-separated)",
    )
    _default_sock = str(Path(tempfile.gettempdir()) / "omniclaude-emit.sock")
    start_parser.add_argument(
        "--socket-path",
        default=_default_sock,
        help=f"Unix socket path (default: {_default_sock})",
    )
    start_parser.add_argument(
        "--daemonize",
        action="store_true",
        help="Run as daemon (detach from terminal)",
    )

    sub.add_parser("stop", help="Stop the publisher")

    return parser.parse_args(argv)


def _do_start(args: argparse.Namespace) -> int:
    from omniclaude.publisher.embedded_publisher import EmbeddedEventPublisher
    from omniclaude.publisher.publisher_config import PublisherConfig

    # Build config from args + env vars (pydantic-settings handles env automatically)
    config = PublisherConfig(
        kafka_bootstrap_servers=args.kafka_servers,
        socket_path=Path(args.socket_path),
    )

    publisher = EmbeddedEventPublisher(config)

    async def _run() -> None:
        await publisher.start()
        await publisher.run_until_shutdown()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass

    return 0


def _do_stop(args: argparse.Namespace) -> int:  # noqa: ARG001
    """Stop publisher by sending SIGTERM to PID file."""
    import signal

    pid_path = Path(tempfile.gettempdir()) / "omniclaude-emit.pid"
    if not pid_path.exists():
        print("Publisher is not running (no PID file)")
        return 0

    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to publisher (PID {pid})")
        return 0
    except ProcessLookupError:
        print("Publisher process not found, cleaning up stale PID file")
        pid_path.unlink(missing_ok=True)
        return 0
    except Exception as e:
        print(f"Error stopping publisher: {e}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    args = _parse_args(argv)

    if args.command == "start":
        return _do_start(args)
    elif args.command == "stop":
        return _do_stop(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
