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

    stop_parser = sub.add_parser("stop", help="Stop the publisher")
    stop_parser.add_argument(
        "--pid-path",
        default=None,
        help="PID file path (default: auto-detect from config or env)",
    )

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


def _do_stop(args: argparse.Namespace) -> int:
    """Stop publisher by sending SIGTERM to PID file.

    PID path resolution priority:
      1. --pid-path CLI argument (explicit override)
      2. PublisherConfig (pydantic-settings, reads OMNICLAUDE_PUBLISHER_PID_PATH)
      3. OMNICLAUDE_PUBLISHER_PID_PATH env var (fallback when config fails)
      4. Default: $TMPDIR/omniclaude-emit.pid
    """
    import signal

    from omniclaude.publisher.publisher_config import PublisherConfig

    if args.pid_path is not None:
        # Explicit CLI override — highest priority
        pid_path = Path(args.pid_path)
    else:
        try:
            config = PublisherConfig()  # type: ignore[call-arg]  # pydantic-settings loads from env
        except Exception:
            # If config validation fails (e.g. missing kafka_bootstrap_servers),
            # fall back to env var / default — stop doesn't need Kafka.
            config = None

        if config is not None:
            pid_path = config.pid_path
        else:
            # Honor the same env var that pydantic-settings would use
            # (prefix OMNICLAUDE_PUBLISHER_ + field PID_PATH).
            env_pid = os.environ.get("OMNICLAUDE_PUBLISHER_PID_PATH")
            pid_path = (
                Path(env_pid)
                if env_pid
                else Path(tempfile.gettempdir()) / "omniclaude-emit.pid"
            )
    if not pid_path.exists():
        print("Publisher is not running (no PID file)")
        return 0

    try:
        pid_str = pid_path.read_text().strip()
        pid = int(pid_str)
    except (OSError, ValueError):
        print("Corrupt or unreadable PID file, cleaning up")
        pid_path.unlink(missing_ok=True)
        return 0

    try:
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
