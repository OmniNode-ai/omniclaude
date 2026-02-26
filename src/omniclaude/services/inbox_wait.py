# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Inbox-wait pattern for ci-watch and pr-watch skills.

Provides a unified interface for waiting on PR status notifications.
Supports two modes:
- EVENT_BUS: Register watch via Valkey -> wait for Kafka inbox message
- STANDALONE: Spawn ``gh run watch`` background -> wait for inbox file

Skills call ``wait_for_pr_status()`` without caring about the underlying
transport mechanism.

See OMN-2826 Phase 2e for specification.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _is_event_bus_available() -> bool:
    """Check if the ONEX event bus is available.

    Returns True if Kafka and Valkey are configured and reachable.
    Falls back to STANDALONE mode if not.
    """
    kafka_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")
    enable_events = os.environ.get("ENABLE_REAL_TIME_EVENTS", "false").lower()
    return bool(kafka_servers) and enable_events == "true"


async def register_watch(
    agent_id: str,
    repo: str,
    pr_number: int,
) -> bool:
    """Register an agent's interest in PR status events.

    In EVENT_BUS mode, registers with the Valkey watch registry.
    In STANDALONE mode, this is a no-op (watching starts when
    ``wait_for_pr_status`` is called).

    Args:
        agent_id: Agent identifier.
        repo: Full repo slug.
        pr_number: PR number.

    Returns:
        True if registration succeeded or not needed.
    """
    if _is_event_bus_available():
        try:
            from omniclaude.nodes.node_github_pr_watcher_effect.handlers import (
                WatchRegistry,
            )
            from omniclaude.nodes.node_github_pr_watcher_effect.handlers.watch_registry import (
                InMemoryValkeyClient,
            )

            # In production, the Valkey client would be injected via ServiceRegistry.
            # For now, fall back to in-memory for development.
            valkey_host = os.environ.get("VALKEY_HOST", "localhost")
            valkey_port = int(os.environ.get("VALKEY_PORT", "16379"))

            try:
                import valkey.asyncio as avalkey

                client = avalkey.Valkey(host=valkey_host, port=valkey_port)
            except ImportError:
                logger.warning("valkey package not installed, using in-memory client")
                client = InMemoryValkeyClient()  # type: ignore[assignment]

            registry = WatchRegistry(client)  # type: ignore[arg-type]
            return await registry.register_watch(agent_id, repo, pr_number)
        except Exception as exc:
            logger.warning(
                "Event bus watch registration failed, will use STANDALONE: %s",
                exc,
            )
    return True  # STANDALONE mode: no registration needed


async def unregister_watch(
    agent_id: str,
    repo: str,
    pr_number: int,
) -> bool:
    """Unregister an agent's interest in PR status events.

    Args:
        agent_id: Agent identifier.
        repo: Full repo slug.
        pr_number: PR number.

    Returns:
        True if unregistration succeeded or not needed.
    """
    if _is_event_bus_available():
        try:
            from omniclaude.nodes.node_github_pr_watcher_effect.handlers import (
                WatchRegistry,
            )
            from omniclaude.nodes.node_github_pr_watcher_effect.handlers.watch_registry import (
                InMemoryValkeyClient,
            )

            valkey_host = os.environ.get("VALKEY_HOST", "localhost")
            valkey_port = int(os.environ.get("VALKEY_PORT", "16379"))

            try:
                import valkey.asyncio as avalkey

                client = avalkey.Valkey(host=valkey_host, port=valkey_port)
            except ImportError:
                client = InMemoryValkeyClient()  # type: ignore[assignment]

            registry = WatchRegistry(client)  # type: ignore[arg-type]
            return await registry.unregister_watch(agent_id, repo, pr_number)
        except Exception as exc:
            logger.warning("Event bus watch unregistration failed: %s", exc)
    return True


def wait_for_pr_status(
    *,
    repo: str,
    pr_number: int,
    run_id: int | None = None,
    agent_id: str = "default",
    timeout_seconds: int = 3600,
) -> dict[str, Any] | None:
    """Wait for a PR status notification.

    Unified interface for both EVENT_BUS and STANDALONE modes.

    In STANDALONE mode:
    1. Spawns ``gh run watch`` background process (if run_id provided)
    2. Polls the file-based inbox for results

    In EVENT_BUS mode:
    1. Assumes watch is already registered via ``register_watch()``
    2. Waits for Kafka inbox message (TODO: implement consumer)

    Args:
        repo: Full repo slug.
        pr_number: PR number.
        run_id: GH Actions run ID (required for STANDALONE mode).
        agent_id: Agent identifier (used for EVENT_BUS mode).
        timeout_seconds: Max seconds to wait.

    Returns:
        Notification payload dict, or None on timeout.
    """
    if _is_event_bus_available():
        # EVENT_BUS mode: wait for Kafka inbox message
        # TODO(OMN-2826): Implement Kafka consumer wait
        # For now, fall through to STANDALONE mode
        logger.info(
            "EVENT_BUS mode not yet fully implemented for inbox consumer. "
            "Falling back to STANDALONE."
        )

    # STANDALONE mode
    from omniclaude.services.standalone_inbox import BackgroundWatcher, StandaloneInbox

    watcher = BackgroundWatcher()
    inbox = StandaloneInbox()

    # Run GC on stale files first
    watcher.gc_stale_files()

    # Start background watcher if run_id is provided
    if run_id is not None:
        watcher.start_watcher(repo, pr_number, run_id)

    # Wait for notification
    return inbox.wait_for_notification(
        repo=repo,
        pr_number=pr_number,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=10,
    )
