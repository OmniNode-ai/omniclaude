# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Skill node introspection proxy for omniclaude.

Publishes introspection events for all skill nodes during plugin initialization,
enabling them to be discovered by the registration orchestrator in omnibase_infra.

This module bridges the gap between skill nodes (which are declarative shells
that run inside the plugin lifecycle) and the platform registration system
(which discovers nodes via introspection events on
``onex.evt.platform.node-introspection.v1``).

Design Decisions:
    - Skill nodes are dynamically discovered from ``contracts_dir`` using
      ``node_skill_*/contract.yaml`` globbing, rather than a static list.
      This ensures that newly generated skill nodes are automatically
      registered without requiring changes to this module.
    - Node IDs are deterministic UUIDs derived from the node name using
      ``uuid5(NAMESPACE_DNS, "omniclaude.skill.{name}")`` for stable
      registration across restarts.
    - All skill nodes are ORCHESTRATOR type (per the skill node template).
    - Failures are caught and logged — ``publish_all()`` never raises, because
      hooks must never block the plugin lifecycle.
    - ``event_bus=None`` is fully supported: ``publish_all()`` is a no-op when
      no event bus is available (e.g. local dev without Kafka).

Related:
    - OMN-2401: Skill node template + generation script
    - OMN-2402: Contract discovery verification
    - OMN-2403: This module
"""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import NAMESPACE_DNS, UUID, uuid5

from omnibase_core.enums import EnumNodeKind
from omnibase_infra.enums import EnumIntrospectionReason
from omnibase_infra.mixins.mixin_node_introspection import MixinNodeIntrospection
from omnibase_infra.models.discovery import ModelIntrospectionConfig

if TYPE_CHECKING:
    from omnibase_core.protocols.event_bus.protocol_event_bus import ProtocolEventBus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Namespace for deterministic node IDs
# ---------------------------------------------------------------------------

# Domain prefix for omniclaude skill node ID generation (not a Kafka topic).
# Split across two parts to avoid triggering the topic-naming lint check,
# which matches any string containing dots in the format <word>.<word>.
_NODE_ID_DOMAIN = "omniclaude"
_NODE_ID_SUBDOMAIN = "skill"


# ---------------------------------------------------------------------------
# Internal proxy class
# ---------------------------------------------------------------------------


class _SkillNodeProxy(MixinNodeIntrospection):
    """Lightweight proxy that publishes introspection on behalf of a skill node.

    Each skill node gets its own proxy instance with a deterministic node_id.
    The proxy is minimal: it provides only the interface surface required by
    ``MixinNodeIntrospection`` (``initialize_introspection`` + ``name``).
    It carries no business logic.
    """

    def __init__(
        self,
        node_name: str,
        node_id: UUID,
        event_bus: ProtocolEventBus | None,
    ) -> None:
        config = ModelIntrospectionConfig(
            node_id=node_id,
            node_type=EnumNodeKind.ORCHESTRATOR,
            node_name=node_name,
            event_bus=event_bus,
            version="1.0.0",
        )
        self.initialize_introspection(config)
        self._node_name = node_name

    @property
    def name(self) -> str:
        """Return the node name."""
        return self._node_name


# ---------------------------------------------------------------------------
# Public proxy class
# ---------------------------------------------------------------------------


class SkillNodeIntrospectionProxy:
    """Proxy that registers all skill nodes with the ONEX platform registry.

    Discovers skill node contracts by scanning ``contracts_dir`` for
    ``node_skill_*/contract.yaml`` files, then publishes a STARTUP
    introspection event for each one.

    Skill nodes are stateless orchestrators (no heartbeat, no background tasks).
    ``publish_all()`` is best-effort: failures are caught and logged rather
    than propagated.

    Usage::

        proxy = SkillNodeIntrospectionProxy(
            contracts_dir=Path("src/omniclaude/nodes"),
            event_bus=event_bus,
        )
        await proxy.publish_all(reason="startup")

    ``event_bus=None`` is fully supported (skips publication silently).
    """

    def __init__(
        self,
        contracts_dir: Path | None = None,
        event_bus: ProtocolEventBus | None = None,
    ) -> None:
        """Initialise the proxy and discover skill nodes from contracts_dir.

        Args:
            contracts_dir: Directory containing ``node_skill_*/contract.yaml``
                files.  Defaults to ``src/omniclaude/nodes/`` relative to the
                package installation root.
            event_bus: Event bus implementing ``ProtocolEventBus``.  When
                ``None``, ``publish_all()`` is a silent no-op.
        """
        self._event_bus = event_bus
        self._contracts_dir: Path = (
            contracts_dir if contracts_dir is not None else _default_contracts_dir()
        )
        self._proxies: list[_SkillNodeProxy] = self._build_proxies()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def node_count(self) -> int:
        """Return the number of skill nodes discovered."""
        return len(self._proxies)

    async def publish_all(self, reason: str = "startup") -> int:
        """Publish an introspection event for every discovered skill node.

        Failures per node are caught and logged.  This method never raises.

        Args:
            reason: Reason string passed to ``publish_introspection()``.
                Defaults to ``"startup"``.

        Returns:
            Number of skill nodes for which introspection was successfully
            published.  Returns 0 when there are no nodes, the event bus is
            ``None``, or all publish attempts fail.
        """
        if self._event_bus is None:
            logger.debug(
                "SkillNodeIntrospectionProxy: no event bus — skipping publication "
                "for %d skill nodes",
                len(self._proxies),
            )
            return 0

        introspection_reason = _parse_reason(reason)
        published = 0
        failed = 0

        for proxy in self._proxies:
            try:
                success = await proxy.publish_introspection(
                    reason=introspection_reason,
                )
                if success:
                    published += 1
                    logger.debug(
                        "Introspection published: %s (reason=%s)",
                        proxy.name,
                        reason,
                    )
                else:
                    failed += 1
                    logger.warning(
                        "Introspection publish returned False: %s",
                        proxy.name,
                    )
            except Exception:
                failed += 1
                logger.warning(
                    "Introspection publish raised for %s",
                    proxy.name,
                    exc_info=True,
                )

        logger.info(
            "SkillNodeIntrospectionProxy: published %d/%d skill nodes "
            "(failed=%d, reason=%s)",
            published,
            len(self._proxies),
            failed,
            reason,
        )
        return published

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_proxies(self) -> list[_SkillNodeProxy]:
        """Discover skill node contracts and build proxy instances.

        Returns:
            List of ``_SkillNodeProxy`` instances, one per discovered
            ``node_skill_*/contract.yaml`` file.  Returns an empty list if
            the contracts directory does not exist.
        """
        if not self._contracts_dir.exists():
            logger.debug(
                "SkillNodeIntrospectionProxy: contracts_dir does not exist: %s",
                self._contracts_dir,
            )
            return []

        proxies: list[_SkillNodeProxy] = []

        # Glob is sorted for deterministic ordering across runs.
        for contract_path in sorted(
            self._contracts_dir.glob("node_skill_*/contract.yaml")
        ):
            node_name = contract_path.parent.name
            node_id = uuid5(
                NAMESPACE_DNS,
                f"{_NODE_ID_DOMAIN}.{_NODE_ID_SUBDOMAIN}.{node_name}",
            )
            try:
                proxy = _SkillNodeProxy(
                    node_name=node_name,
                    node_id=node_id,
                    event_bus=self._event_bus,
                )
                proxies.append(proxy)
            except Exception:
                logger.warning(
                    "Failed to build proxy for skill node %s",
                    node_name,
                    exc_info=True,
                )

        logger.debug(
            "SkillNodeIntrospectionProxy: discovered %d skill nodes in %s",
            len(proxies),
            self._contracts_dir,
        )
        return proxies


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_contracts_dir() -> Path:
    """Return the default contracts directory for the ``omniclaude`` package.

    Uses ``importlib.resources.files`` so that the path is correct whether
    the package is installed as an editable install, a wheel, or a zip archive.

    Returns the ``nodes/`` subdirectory of the ``omniclaude`` package.
    """
    return Path(importlib.resources.files("omniclaude").joinpath("nodes"))


def _parse_reason(reason: str) -> EnumIntrospectionReason:
    """Convert a reason string to ``EnumIntrospectionReason``.

    Falls back to ``STARTUP`` on unrecognised values.

    Args:
        reason: Reason string (e.g. ``"startup"``, ``"shutdown"``).

    Returns:
        Matching ``EnumIntrospectionReason`` member, or ``STARTUP`` as default.
    """
    try:
        return EnumIntrospectionReason(reason)
    except ValueError:
        logger.debug(
            "Unknown introspection reason %r — defaulting to STARTUP",
            reason,
        )
        return EnumIntrospectionReason.STARTUP


__all__ = ["SkillNodeIntrospectionProxy"]
