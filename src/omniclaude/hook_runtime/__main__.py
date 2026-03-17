"""Hook Runtime Daemon entry point. [OMN-5307]

Usage:
    python -m omniclaude.hook_runtime start [--socket-path PATH] [--config PATH]
    python -m omniclaude.hook_runtime stop [--socket-path PATH]
    python -m omniclaude.hook_runtime status [--socket-path PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
from pathlib import Path

_DEFAULT_SOCKET_PATH = "/tmp/omniclaude-hook-runtime.sock"  # noqa: S108  # nosec B108
_DEFAULT_PID_PATH = "/tmp/omniclaude-hook-runtime.pid"  # noqa: S108  # nosec B108


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Hook Runtime Daemon — lightweight Unix socket server for hook enforcement",
        prog="python -m omniclaude.hook_runtime",
    )
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="Start the hook runtime daemon")
    start_p.add_argument(
        "--socket-path",
        default=_DEFAULT_SOCKET_PATH,
        help="Unix socket path (default: %(default)s)",
    )
    start_p.add_argument(
        "--pid-path",
        default=_DEFAULT_PID_PATH,
        help="PID file path (default: %(default)s)",
    )
    start_p.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to config.yaml (uses defaults if not provided)",
    )

    stop_p = sub.add_parser("stop", help="Stop a running hook runtime daemon")
    stop_p.add_argument(
        "--socket-path",
        default=_DEFAULT_SOCKET_PATH,
        help="Unix socket path (default: %(default)s)",
    )
    stop_p.add_argument(
        "--pid-path",
        default=_DEFAULT_PID_PATH,
        help="PID file path (default: %(default)s)",
    )

    status_p = sub.add_parser("status", help="Check hook runtime daemon status")
    status_p.add_argument(
        "--socket-path",
        default=_DEFAULT_SOCKET_PATH,
        help="Unix socket path (default: %(default)s)",
    )

    return parser


def _ping_daemon(socket_path: str) -> bool:
    """Ping the daemon via socket. Returns True if alive."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(socket_path)
            s.sendall(b'{"action":"ping","session_id":"cli"}\n')
            raw = s.makefile().readline().strip()
            resp = json.loads(raw)
            return bool(resp.get("decision") == "ack")
    except (OSError, json.JSONDecodeError):
        return False


def _stop_daemon(socket_path: str, pid_path: str) -> int:
    """Stop the daemon via PID file SIGTERM."""
    import os
    import signal as _signal

    pid_file = Path(pid_path)
    if not pid_file.exists():
        print(f"PID file not found: {pid_path}", file=sys.stderr)  # noqa: T201
        return 1
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, _signal.SIGTERM)
        print(f"Sent SIGTERM to PID {pid}")  # noqa: T201
        return 0
    except (ProcessLookupError, ValueError) as e:
        print(f"Failed to stop daemon: {e}", file=sys.stderr)  # noqa: T201
        return 1


def main() -> None:
    """CLI entry point for the hook runtime daemon."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "start":
        from omniclaude.hook_runtime.server import HookRuntimeConfig, HookRuntimeServer

        if args.config:
            config = HookRuntimeConfig.from_yaml(args.config)
            config.socket_path = args.socket_path
            config.pid_path = args.pid_path
        else:
            config = HookRuntimeConfig(
                socket_path=args.socket_path,
                pid_path=args.pid_path,
            )
        server = HookRuntimeServer(config=config)
        asyncio.run(server.start_and_run())

    elif args.command == "stop":
        sys.exit(_stop_daemon(args.socket_path, args.pid_path))

    elif args.command == "status":
        if _ping_daemon(args.socket_path):
            print(f"Hook runtime daemon is running at {args.socket_path}")  # noqa: T201
            sys.exit(0)
        else:
            print(f"Hook runtime daemon is NOT running (socket: {args.socket_path})")  # noqa: T201
            sys.exit(1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
