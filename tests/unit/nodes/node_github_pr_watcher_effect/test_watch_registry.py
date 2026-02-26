# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for the Valkey watch registry."""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_github_pr_watcher_effect.handlers.watch_registry import (
    InMemoryValkeyClient,
    WatchRegistry,
)


@pytest.fixture
def registry() -> WatchRegistry:
    """Create a WatchRegistry with in-memory Valkey client."""
    client = InMemoryValkeyClient()
    return WatchRegistry(client, ttl_seconds=7200)


@pytest.mark.unit
class TestWatchRegistration:
    """Tests for watch registration and unregistration."""

    @pytest.mark.asyncio
    async def test_register_new_watch(self, registry: WatchRegistry) -> None:
        """Test registering a new watch returns True."""
        result = await registry.register_watch(
            agent_id="agent-001",
            repo="OmniNode-ai/omniclaude",
            pr_number=42,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_register_duplicate_watch(self, registry: WatchRegistry) -> None:
        """Test registering the same watch twice (idempotent via SADD)."""
        await registry.register_watch("agent-001", "OmniNode-ai/omniclaude", 42)
        result = await registry.register_watch(
            "agent-001", "OmniNode-ai/omniclaude", 42
        )
        assert result is False  # Already registered

    @pytest.mark.asyncio
    async def test_unregister_existing_watch(self, registry: WatchRegistry) -> None:
        """Test unregistering an existing watch returns True."""
        await registry.register_watch("agent-001", "OmniNode-ai/omniclaude", 42)
        result = await registry.unregister_watch(
            "agent-001", "OmniNode-ai/omniclaude", 42
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_watch(self, registry: WatchRegistry) -> None:
        """Test unregistering a non-existent watch returns False."""
        result = await registry.unregister_watch(
            "agent-001", "OmniNode-ai/omniclaude", 42
        )
        assert result is False


@pytest.mark.unit
class TestWatcherLookup:
    """Tests for watcher lookup operations."""

    @pytest.mark.asyncio
    async def test_get_watchers_empty(self, registry: WatchRegistry) -> None:
        """Test getting watchers for a PR with no registrations."""
        watchers = await registry.get_watchers("OmniNode-ai/omniclaude", 42)
        assert watchers == set()

    @pytest.mark.asyncio
    async def test_get_watchers_single(self, registry: WatchRegistry) -> None:
        """Test getting watchers with one registration."""
        await registry.register_watch("agent-001", "OmniNode-ai/omniclaude", 42)
        watchers = await registry.get_watchers("OmniNode-ai/omniclaude", 42)
        assert watchers == {"agent-001"}

    @pytest.mark.asyncio
    async def test_get_watchers_multiple(self, registry: WatchRegistry) -> None:
        """Test getting watchers with multiple registrations."""
        await registry.register_watch("agent-001", "OmniNode-ai/omniclaude", 42)
        await registry.register_watch("agent-002", "OmniNode-ai/omniclaude", 42)
        await registry.register_watch("agent-003", "OmniNode-ai/omniclaude", 42)
        watchers = await registry.get_watchers("OmniNode-ai/omniclaude", 42)
        assert watchers == {"agent-001", "agent-002", "agent-003"}

    @pytest.mark.asyncio
    async def test_get_agent_watches(self, registry: WatchRegistry) -> None:
        """Test getting all watches for an agent (reverse index)."""
        await registry.register_watch("agent-001", "OmniNode-ai/omniclaude", 42)
        await registry.register_watch("agent-001", "OmniNode-ai/omnibase_core", 10)
        watches = await registry.get_agent_watches("agent-001")
        assert watches == {
            "OmniNode-ai/omniclaude:42",
            "OmniNode-ai/omnibase_core:10",
        }

    @pytest.mark.asyncio
    async def test_watchers_independent_per_pr(self, registry: WatchRegistry) -> None:
        """Test that watchers are independent per PR number."""
        await registry.register_watch("agent-001", "OmniNode-ai/omniclaude", 42)
        await registry.register_watch("agent-002", "OmniNode-ai/omniclaude", 99)

        watchers_42 = await registry.get_watchers("OmniNode-ai/omniclaude", 42)
        watchers_99 = await registry.get_watchers("OmniNode-ai/omniclaude", 99)

        assert watchers_42 == {"agent-001"}
        assert watchers_99 == {"agent-002"}


@pytest.mark.unit
class TestUnregisterAll:
    """Tests for bulk unregistration."""

    @pytest.mark.asyncio
    async def test_unregister_all_for_agent(self, registry: WatchRegistry) -> None:
        """Test removing all watches for an agent."""
        await registry.register_watch("agent-001", "OmniNode-ai/omniclaude", 42)
        await registry.register_watch("agent-001", "OmniNode-ai/omnibase_core", 10)
        await registry.register_watch("agent-002", "OmniNode-ai/omniclaude", 42)

        removed = await registry.unregister_all_for_agent("agent-001")
        assert removed == 2

        # Agent-001 should have no watches
        watches = await registry.get_agent_watches("agent-001")
        assert watches == set()

        # Agent-002 should still be watching PR 42
        watchers = await registry.get_watchers("OmniNode-ai/omniclaude", 42)
        assert watchers == {"agent-002"}

    @pytest.mark.asyncio
    async def test_unregister_all_empty(self, registry: WatchRegistry) -> None:
        """Test bulk unregister for an agent with no watches."""
        removed = await registry.unregister_all_for_agent("agent-nonexistent")
        assert removed == 0


@pytest.mark.unit
class TestInMemoryValkeyClient:
    """Tests for the in-memory Valkey client."""

    @pytest.mark.asyncio
    async def test_sadd_and_smembers(self) -> None:
        """Test SADD and SMEMBERS operations."""
        client = InMemoryValkeyClient()
        added = await client.sadd("key1", "a", "b", "c")
        assert added == 3
        members = await client.smembers("key1")
        assert members == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_sadd_duplicate(self) -> None:
        """Test that SADD returns 0 for duplicate members."""
        client = InMemoryValkeyClient()
        await client.sadd("key1", "a")
        added = await client.sadd("key1", "a")
        assert added == 0

    @pytest.mark.asyncio
    async def test_srem(self) -> None:
        """Test SREM operation."""
        client = InMemoryValkeyClient()
        await client.sadd("key1", "a", "b")
        removed = await client.srem("key1", "a")
        assert removed == 1
        members = await client.smembers("key1")
        assert members == {"b"}

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        """Test DELETE operation."""
        client = InMemoryValkeyClient()
        await client.sadd("key1", "a")
        deleted = await client.delete("key1")
        assert deleted == 1
        members = await client.smembers("key1")
        assert members == set()
