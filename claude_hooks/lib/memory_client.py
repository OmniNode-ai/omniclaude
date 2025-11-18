"""
Memory Client for Anthropic's Context Management API Beta

This module provides a client for managing Claude's memory using Anthropic's
Memory Tool API (beta). It supports:
- Store/retrieve/update/delete operations
- Multiple storage backends (filesystem, PostgreSQL)
- Category-based organization
- Graceful degradation with fallback to correlation manager

Beta Header Required: anthropic-beta: context-management-2025-06-27

Usage:
    from claude_hooks.lib.memory_client import get_memory_client

    memory = get_memory_client()
    await memory.store_memory("workspace_state", {"branch": "main"}, "workspace")
    state = await memory.get_memory("workspace_state", "workspace")
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import aiofiles
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class MemoryItem:
    """Represents a single memory item"""
    key: str
    value: Any
    category: str
    timestamp: str
    version: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)


class MemoryBackend:
    """Abstract base class for memory storage backends"""

    async def store(self, category: str, key: str, value: Any, metadata: Optional[Dict] = None) -> None:
        """Store a memory item"""
        raise NotImplementedError

    async def retrieve(self, category: str, key: str) -> Optional[Any]:
        """Retrieve a memory item"""
        raise NotImplementedError

    async def update(self, category: str, key: str, delta: Any) -> None:
        """Update a memory item with delta"""
        raise NotImplementedError

    async def delete(self, category: str, key: str) -> None:
        """Delete a memory item"""
        raise NotImplementedError

    async def list_keys(self, category: str) -> List[str]:
        """List all keys in a category"""
        raise NotImplementedError

    async def list_categories(self) -> List[str]:
        """List all categories"""
        raise NotImplementedError


class FilesystemMemoryBackend(MemoryBackend):
    """Filesystem-based storage backend for memory tool

    Stores memory as Markdown (.md) files per Claude Code specification.
    """

    def __init__(self, base_path: str = None):
        """Initialize filesystem backend

        Args:
            base_path: Base directory for memory storage
                      Defaults to ~/.claude/memory
        """
        if base_path is None:
            base_path = str(Path.home() / ".claude" / "memory")

        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized filesystem memory backend at {self.base_path}")

    def _format_as_markdown(self, key: str, value: Any, category: str, metadata: Optional[Dict] = None) -> str:
        """Format memory item as markdown

        Per Claude Code docs: Simple markdown with headings and bullet points.
        No frontmatter required.
        """
        lines = [f"# {key.replace('_', ' ').title()}", ""]

        # Add metadata as bullet points if present
        if metadata:
            lines.append("## Metadata")
            for k, v in metadata.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")

        # Format value based on type
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, (list, tuple)):
                    lines.append(f"## {k.replace('_', ' ').title()}")
                    for item in v:
                        lines.append(f"- {item}")
                else:
                    lines.append(f"- **{k}**: {v}")
        elif isinstance(value, (list, tuple)):
            for item in value:
                lines.append(f"- {item}")
        else:
            lines.append(str(value))

        lines.append("")  # Trailing newline
        return "\n".join(lines)

    def _parse_markdown(self, content: str) -> Any:
        """Parse markdown content back to structured data

        Simple parser for our markdown format.
        """
        # For now, return the raw content
        # Can be enhanced to parse back to dict/list if needed
        return content.strip()

    def _get_file_path(self, category: str, key: str, extension: str = "md") -> Path:
        """Get file path for a memory item

        Args:
            category: Memory category
            key: Memory key
            extension: File extension (md for markdown, json for structured data)
        """
        category_path = self.base_path / category
        category_path.mkdir(exist_ok=True)
        # Use safe filename (replace problematic characters)
        safe_key = key.replace("/", "_").replace("\\", "_").replace(":", "_")
        return category_path / f"{safe_key}.{extension}"

    async def store(self, category: str, key: str, value: Any, metadata: Optional[Dict] = None) -> None:
        """Store memory item to filesystem (dual storage: markdown + JSON)

        Stores both markdown (for Claude Code memory tool) and JSON (for programmatic access).
        This allows human-readable memory for Claude while preserving structure for code.
        """
        md_path = self._get_file_path(category, key, "md")
        json_path = self._get_file_path(category, key, "json")

        # Add timestamp to metadata
        full_metadata = metadata or {}
        full_metadata["timestamp"] = datetime.utcnow().isoformat()
        full_metadata["category"] = category

        try:
            # Store as markdown (for Claude Code memory tool)
            content = self._format_as_markdown(key, value, category, full_metadata)
            async with aiofiles.open(md_path, 'w') as f:
                await f.write(content)

            # Store as JSON (for programmatic access)
            json_data = {
                "key": key,
                "value": value,
                "category": category,
                "metadata": full_metadata,
                "version": 1
            }
            async with aiofiles.open(json_path, 'w') as f:
                await f.write(json.dumps(json_data, indent=2))

            logger.debug(f"Stored memory: {category}/{key} (markdown + JSON)")
        except Exception as e:
            logger.error(f"Failed to store memory {category}/{key}: {e}")
            raise

    async def retrieve(self, category: str, key: str) -> Optional[Any]:
        """Retrieve memory item from filesystem

        Prioritizes JSON (structured data) over markdown (human-readable).
        Falls back to markdown if JSON doesn't exist (backward compatibility).
        """
        json_path = self._get_file_path(category, key, "json")
        md_path = self._get_file_path(category, key, "md")

        # Try JSON first (structured data for programmatic access)
        if json_path.exists():
            try:
                async with aiofiles.open(json_path, 'r') as f:
                    content = await f.read()
                    data = json.loads(content)
                    # Return just the value (not the wrapper)
                    return data.get("value")
            except Exception as e:
                logger.warning(f"Failed to load JSON for {category}/{key}: {e}")
                # Fall through to markdown

        # Fall back to markdown (backward compatibility)
        if md_path.exists():
            try:
                async with aiofiles.open(md_path, 'r') as f:
                    content = await f.read()
                    # Return markdown content directly
                    return self._parse_markdown(content)
            except Exception as e:
                logger.error(f"Failed to retrieve memory {category}/{key}: {e}")
                return None

        logger.debug(f"Memory not found: {category}/{key}")
        return None

    async def update(self, category: str, key: str, delta: Any) -> None:
        """Update memory item with delta (merge for dicts, replace otherwise)"""
        current = await self.retrieve(category, key)

        if current is None:
            # No existing value, store delta as new value
            await self.store(category, key, delta)
            return

        # Merge strategy depends on type
        if isinstance(current, dict) and isinstance(delta, dict):
            # Deep merge for dictionaries
            updated = self._deep_merge(current, delta)
        elif isinstance(current, list) and isinstance(delta, list):
            # Concatenate lists
            updated = current + delta
        else:
            # Replace for other types
            updated = delta

        await self.store(category, key, updated)
        logger.debug(f"Updated memory: {category}/{key}")

    def _deep_merge(self, base: Dict, delta: Dict) -> Dict:
        """Deep merge two dictionaries"""
        result = base.copy()
        for key, value in delta.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    async def delete(self, category: str, key: str) -> None:
        """Delete memory item from filesystem (both markdown and JSON)"""
        md_path = self._get_file_path(category, key, "md")
        json_path = self._get_file_path(category, key, "json")

        deleted = False
        try:
            if md_path.exists():
                md_path.unlink()
                deleted = True
            if json_path.exists():
                json_path.unlink()
                deleted = True

            if deleted:
                logger.debug(f"Deleted memory: {category}/{key}")
        except Exception as e:
            logger.error(f"Failed to delete memory {category}/{key}: {e}")
            raise

    async def list_keys(self, category: str) -> List[str]:
        """List all keys in a category"""
        category_path = self.base_path / category

        if not category_path.exists():
            return []

        try:
            keys = []
            for file_path in category_path.glob("*.md"):
                # Extract key from filename (remove .md extension)
                key = file_path.stem
                # Reverse the safe filename transformation
                original_key = key.replace("_", "_")  # Keep as is for now
                keys.append(original_key)
            return keys
        except Exception as e:
            logger.error(f"Failed to list keys in category {category}: {e}")
            return []

    async def list_categories(self) -> List[str]:
        """List all categories"""
        try:
            categories = []
            for category_path in self.base_path.iterdir():
                if category_path.is_dir():
                    categories.append(category_path.name)
            return categories
        except Exception as e:
            logger.error(f"Failed to list categories: {e}")
            return []


class MemoryClient:
    """
    Client for Anthropic's Memory Tool API

    Provides high-level interface for managing Claude's memory with:
    - Store/retrieve/update/delete operations
    - Category-based organization
    - Multiple storage backends
    - Graceful fallback to correlation manager

    Usage:
        memory = MemoryClient(backend="filesystem")
        await memory.store_memory("key", {"data": "value"}, "category")
        value = await memory.get_memory("key", "category")
    """

    def __init__(
        self,
        backend: Optional[MemoryBackend] = None,
        enable_fallback: bool = True
    ):
        """Initialize memory client

        Args:
            backend: Storage backend instance (defaults to FilesystemMemoryBackend)
            enable_fallback: Enable fallback to correlation manager on errors
        """
        self.backend = backend or FilesystemMemoryBackend()
        self.enable_fallback = enable_fallback
        logger.info(f"Initialized memory client with backend: {type(self.backend).__name__}")

    async def store_memory(
        self,
        key: str,
        value: Any,
        category: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Store a memory item

        Args:
            key: Unique identifier for the memory
            category: Category for organization (e.g., "workspace", "patterns")
            value: The value to store (any JSON-serializable type)
            metadata: Optional metadata about the memory

        Returns:
            True if successful, False otherwise
        """
        try:
            await self.backend.store(category, key, value, metadata)
            return True
        except Exception as e:
            logger.error(f"Failed to store memory {category}/{key}: {e}")
            if self.enable_fallback:
                return await self._fallback_store(key, value, category)
            return False

    async def get_memory(
        self,
        key: str,
        category: str,
        default: Any = None
    ) -> Optional[Any]:
        """
        Retrieve a memory item

        Args:
            key: Unique identifier for the memory
            category: Category the memory is stored in
            default: Default value if memory not found

        Returns:
            The stored value, or default if not found
        """
        try:
            value = await self.backend.retrieve(category, key)
            return value if value is not None else default
        except Exception as e:
            logger.error(f"Failed to retrieve memory {category}/{key}: {e}")
            if self.enable_fallback:
                return await self._fallback_retrieve(key, category, default)
            return default

    async def update_memory(
        self,
        key: str,
        delta: Any,
        category: str
    ) -> bool:
        """
        Update a memory item with a delta

        For dictionaries, performs deep merge.
        For lists, concatenates.
        For other types, replaces.

        Args:
            key: Unique identifier for the memory
            delta: The change to apply
            category: Category the memory is stored in

        Returns:
            True if successful, False otherwise
        """
        try:
            await self.backend.update(category, key, delta)
            return True
        except Exception as e:
            logger.error(f"Failed to update memory {category}/{key}: {e}")
            return False

    async def delete_memory(
        self,
        key: str,
        category: str
    ) -> bool:
        """
        Delete a memory item

        Args:
            key: Unique identifier for the memory
            category: Category the memory is stored in

        Returns:
            True if successful, False otherwise
        """
        try:
            await self.backend.delete(category, key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete memory {category}/{key}: {e}")
            return False

    async def list_memory(
        self,
        category: str
    ) -> List[str]:
        """
        List all keys in a category

        Args:
            category: Category to list

        Returns:
            List of keys in the category
        """
        try:
            return await self.backend.list_keys(category)
        except Exception as e:
            logger.error(f"Failed to list memory in category {category}: {e}")
            return []

    async def list_categories(self) -> List[str]:
        """
        List all memory categories

        Returns:
            List of category names
        """
        try:
            return await self.backend.list_categories()
        except Exception as e:
            logger.error(f"Failed to list categories: {e}")
            return []

    async def _fallback_store(self, key: str, value: Any, category: str) -> bool:
        """Fallback to correlation manager for storage"""
        try:
            from claude_hooks.lib.correlation_manager import set_correlation_id
            # Store as correlation context (legacy compatibility)
            set_correlation_id(
                correlation_id=key,
                agent_name=category,
                prompt_preview=json.dumps(value)[:100]
            )
            logger.warning(f"Used fallback storage for {category}/{key}")
            return True
        except Exception as e:
            logger.error(f"Fallback storage failed for {category}/{key}: {e}")
            return False

    async def _fallback_retrieve(self, key: str, category: str, default: Any) -> Any:
        """Fallback to correlation manager for retrieval"""
        try:
            from claude_hooks.lib.correlation_manager import get_correlation_context
            context = get_correlation_context()
            if context and context.get("correlation_id") == key:
                # Try to parse prompt_preview as JSON
                try:
                    return json.loads(context.get("prompt_preview", "{}"))
                except:
                    return context.get("prompt_preview", default)
            return default
        except Exception as e:
            logger.error(f"Fallback retrieval failed for {category}/{key}: {e}")
            return default


# Global singleton instance
_memory_client: Optional[MemoryClient] = None


def get_memory_client(
    backend: Optional[MemoryBackend] = None,
    enable_fallback: bool = True
) -> MemoryClient:
    """
    Get the global memory client instance (singleton pattern)

    Args:
        backend: Storage backend (only used on first call)
        enable_fallback: Enable fallback to correlation manager

    Returns:
        The global MemoryClient instance
    """
    global _memory_client

    if _memory_client is None:
        _memory_client = MemoryClient(backend=backend, enable_fallback=enable_fallback)

    return _memory_client


def reset_memory_client():
    """Reset the global memory client (useful for testing)"""
    global _memory_client
    _memory_client = None
