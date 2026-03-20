# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Hook runtime daemon async Unix socket server. [OMN-5306, OMN-5312]

Lightweight asyncio Unix socket server that services all omniclaude hook
nodes. Follows the EmbeddedEventPublisher lifecycle pattern:
- PID file management
- Stale socket detection and cleanup
- asyncio.start_unix_server binding
- Signal handlers (SIGTERM, SIGINT)
- Graceful shutdown via asyncio.Event
- Newline-delimited JSON protocol
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
from dataclasses import dataclass, field
from pathlib import Path

from omnibase_infra.event_bus.event_bus_inmemory import EventBusInmemory

from omniclaude.hook_runtime.delegation_state import DelegationConfig, DelegationState
from omniclaude.hook_runtime.protocol import (
    HookRuntimeRequest,
    HookRuntimeResponse,
    parse_hook_runtime_request,
)

logger = logging.getLogger(__name__)

_DEFAULT_SOCKET_PATH = "/tmp/omniclaude-hook-runtime.sock"  # noqa: S108  # nosec B108
_DEFAULT_PID_PATH = "/tmp/omniclaude-hook-runtime.pid"  # noqa: S108  # nosec B108


@dataclass
class HookRuntimeConfig:
    """Configuration for the hook runtime daemon server."""

    socket_path: str = _DEFAULT_SOCKET_PATH
    pid_path: str = _DEFAULT_PID_PATH
    delegation: DelegationConfig = field(default_factory=DelegationConfig)

    @classmethod
    def from_yaml(cls, path: str) -> HookRuntimeConfig:
        """Load config from a YAML file.

        Reads the `delegation_enforcement` section and maps it to
        DelegationConfig. Missing keys use dataclass defaults.
        """
        import yaml

        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        de = raw.get("delegation_enforcement", {})

        _defaults = DelegationConfig()
        delegation = DelegationConfig(
            write_warn_threshold=de.get(
                "write_warn_threshold", _defaults.write_warn_threshold
            ),
            write_block_threshold=de.get(
                "write_block_threshold", _defaults.write_block_threshold
            ),
            read_warn_threshold=de.get(
                "read_warn_threshold", _defaults.read_warn_threshold
            ),
            read_block_threshold=de.get(
                "read_block_threshold", _defaults.read_block_threshold
            ),
            total_block_threshold=de.get(
                "total_block_threshold", _defaults.total_block_threshold
            ),
            skill_loaded_write_block=de.get(
                "skill_loaded_write_block", _defaults.skill_loaded_write_block
            ),
            skill_loaded_read_block=de.get(
                "skill_loaded_read_block", _defaults.skill_loaded_read_block
            ),
            skill_loaded_total_block=de.get(
                "skill_loaded_total_block", _defaults.skill_loaded_total_block
            ),
            delegation_rule_tool_threshold=de.get(
                "delegation_rule_tool_threshold",
                _defaults.delegation_rule_tool_threshold,
            ),
            bash_readonly_patterns=de.get("bash_readonly_patterns", []),
            bash_compound_deny_patterns=de.get("bash_compound_deny_patterns", []),
        )
        return cls(delegation=delegation)


class HookRuntimeServer:
    """Lightweight async Unix socket server for hook enforcement.

    Follows EmbeddedEventPublisher lifecycle pattern:
    PID file, stale socket detection, signal handlers, graceful shutdown.
    No Kafka, no Postgres — pure in-memory state.
    """

    def __init__(self, config: HookRuntimeConfig) -> None:
        self._config = config
        self._delegation = DelegationState(config=config.delegation)
        self._server: asyncio.Server | None = None
        self._running = False
        self._shutdown_event: asyncio.Event | None = None
        self._event_bus: EventBusInmemory | None = None

    @property
    def socket_path(self) -> str:
        return self._config.socket_path

    @property
    def event_bus(self) -> EventBusInmemory | None:
        """Return the EventBusInmemory instance (available after start())."""
        return self._event_bus

    async def start(self) -> None:
        """Start the server: clean stale socket, bind, write PID file."""
        self._shutdown_event = asyncio.Event()

        # Clean up stale socket if it exists but is not a real socket
        socket_path = Path(self._config.socket_path)
        if socket_path.exists():
            if not self._is_socket_alive(self._config.socket_path):
                logger.debug("Removing stale socket at %s", self._config.socket_path)
                socket_path.unlink(missing_ok=True)
            else:
                logger.debug(
                    "Socket at %s is already alive — skipping start",
                    self._config.socket_path,
                )
                return

        # Ensure parent directory exists
        socket_path.parent.mkdir(parents=True, exist_ok=True)

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self._config.socket_path,
        )
        self._running = True

        # Wire EventBusInmemory for future node registration (OMN-5312)
        # No handlers registered yet — this makes the bus available for
        # future agent routing, LLM delegation, etc.
        self._event_bus = EventBusInmemory(
            environment="hook-runtime",
            group="hook-handlers",
        )

        # Write PID file
        Path(self._config.pid_path).write_text(str(os.getpid()), encoding="utf-8")

        # Install signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._request_shutdown)
            except (RuntimeError, NotImplementedError):
                # Signal handlers may not be available in test environments
                pass

        logger.info(
            "Hook runtime daemon started on %s (PID %d)",
            self._config.socket_path,
            os.getpid(),
        )

    async def stop(self) -> None:
        """Gracefully stop the server and clean up resources."""
        self._running = False
        if self._shutdown_event is not None:
            self._shutdown_event.set()

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Remove socket file
        Path(self._config.socket_path).unlink(missing_ok=True)

        # Remove PID file
        Path(self._config.pid_path).unlink(missing_ok=True)

        logger.info("Hook runtime daemon stopped")

    async def start_and_run(self) -> None:
        """Start server and block until shutdown signal received."""
        await self.start()
        if self._shutdown_event is not None:
            await self._shutdown_event.wait()
        await self.stop()

    def _request_shutdown(self) -> None:
        """Signal handler: request graceful shutdown."""
        if self._shutdown_event is not None:
            self._shutdown_event.set()

    def _is_socket_alive(self, path: str) -> bool:
        """Check if a Unix socket at path is alive (accepts connections)."""
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect(path)
                return True
        except (OSError, ConnectionRefusedError):
            return False

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection (newline-delimited JSON)."""
        try:
            while True:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                except TimeoutError:
                    break
                if not line:
                    break
                try:
                    response_json = await self._process_request(line)
                    writer.write((response_json + "\n").encode())
                    await writer.drain()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error processing request: %s", exc)
                    error_resp = HookRuntimeResponse(
                        decision="pass",
                        message=f"daemon error: {exc}",
                    )
                    writer.write((error_resp.model_dump_json() + "\n").encode())
                    await writer.drain()
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001  # nosec B110
                pass

    async def _process_request(self, line: bytes) -> str:
        """Dispatch a raw request line to the appropriate handler."""
        raw = json.loads(line.decode().strip())
        req: HookRuntimeRequest = parse_hook_runtime_request(raw)

        if req.action == "ping":
            return HookRuntimeResponse(decision="ack").model_dump_json()

        if req.action == "classify_tool":
            tool_name = str(req.payload.get("tool_name", ""))
            tool_input = req.payload.get("tool_input", {})
            if not isinstance(tool_input, dict):
                tool_input = {}
            classification = self._delegation.classify_tool(tool_name, tool_input)
            self._delegation.record_tool(req.session_id, classification)
            decision = self._delegation.check_thresholds(req.session_id)
            counters = self._delegation.get_counters(req.session_id)
            return HookRuntimeResponse(
                decision=decision.decision,
                message=decision.message,
                counters=counters,
            ).model_dump_json()

        if req.action == "reset_session":
            self._delegation.reset_session(req.session_id)
            return HookRuntimeResponse(decision="ack").model_dump_json()

        if req.action == "mark_delegated":
            self._delegation.mark_delegated(req.session_id)
            return HookRuntimeResponse(decision="ack").model_dump_json()

        if req.action == "set_skill_loaded":
            self._delegation.set_skill_loaded(req.session_id)
            return HookRuntimeResponse(decision="ack").model_dump_json()

        if req.action == "check_delegation_rule":
            rule = (
                "All tasks must be dispatched via onex:polymorphic-agent. "
                "Direct tool usage beyond thresholds triggers enforcement."
            )
            return HookRuntimeResponse(
                decision="ack",
                additional_context=rule,
            ).model_dump_json()

        # Unknown action — pass through
        logger.warning("Unknown action: %s", req.action)
        return HookRuntimeResponse(
            decision="pass",
            message=f"unknown action: {req.action}",
        ).model_dump_json()
