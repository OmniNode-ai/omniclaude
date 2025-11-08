"""
Pattern Tracker for Claude Code Hooks

Integrates with Phase 4 Pattern Traceability APIs to track pattern lifecycle
with bulletproof resilience. Ensures pattern tracking NEVER disrupts Claude
Code workflows.

Features:
- Fire-and-forget tracking (never blocks)
- Circuit breaker for fault tolerance
- Local caching for offline scenarios
- Health checking with auto-recovery
- Graceful degradation on errors

Usage in Claude Code Hooks:
    from lib.pattern_tracker import PatternTracker

    # Initialize tracker (singleton pattern)
    tracker = PatternTracker.get_instance()

    # Track pattern creation (non-blocking)
    await tracker.track_pattern_creation(
        code=code_content,
        context={
            "file_path": file_path,
            "tool_name": "Write",
            "language": "python"
        }
    )

    # Track pattern application
    await tracker.track_pattern_application(
        pattern_id="auth-jwt-001",
        context={"file_path": file_path}
    )
"""

import asyncio
import hashlib
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import requests

from config import settings
from lib.resilience import ResilientAPIClient, graceful_tracking

logger = logging.getLogger(__name__)


class PatternTracker:
    """
    Resilient pattern tracker for Claude Code hooks.

    Singleton pattern to ensure consistent state across hook executions.
    All tracking operations are fire-and-forget and never block Claude workflows.

    Example:
        tracker = PatternTracker.get_instance()

        # Track pattern creation
        await tracker.track_pattern_creation(
            code="function authenticate(token) { ... }",
            context={
                "file_path": "src/auth.js",
                "tool_name": "Write",
                "language": "javascript"
            }
        )
    """

    _instance: Optional["PatternTracker"] = None
    _lock: Optional[asyncio.Lock] = None

    @classmethod
    async def _get_lock(cls) -> asyncio.Lock:
        """
        Get or create the singleton lock lazily under a running event loop.

        This ensures asyncio.Lock() is never created at module level, which
        would cause RuntimeError in Python 3.12+ when no event loop exists.

        Returns:
            asyncio.Lock: The singleton lock instance
        """
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    def __init__(self, base_url: Optional[str] = None, enable_tracking: bool = True):
        """
        Initialize pattern tracker.

        Args:
            base_url: Base URL for Phase 4 API (defaults to settings.archon_intelligence_url)
            enable_tracking: Enable/disable tracking (useful for testing)
        """
        # Get base URL from settings
        self.base_url = base_url or str(settings.archon_intelligence_url)

        self.enable_tracking = enable_tracking

        # Initialize resilient API client
        self.api_client = ResilientAPIClient(
            base_url=self.base_url, enable_caching=True, enable_circuit_breaker=True
        )

        # Pattern ID cache for deduplication
        self._pattern_cache: Dict[str, str] = {}

        logger.info(
            f"[PatternTracker] Initialized with base_url={self.base_url}, "
            f"tracking_enabled={enable_tracking}"
        )

        # Health check: Verify Phase 4 API is reachable
        self.api_healthy = self._check_api_health()

    def _check_api_health(self) -> bool:
        """
        Check if Phase 4 API is reachable. Prints status to stderr.

        Returns:
            bool: True if API is healthy, False otherwise
        """
        try:
            response = requests.get(f"{self.base_url}/health", timeout=2)
            if response.status_code == 200:
                print(
                    f"✅ [PatternTracker] Phase 4 API reachable at {self.base_url}",
                    file=sys.stderr,
                )
                return True
            else:
                print(
                    f"⚠️ [PatternTracker] Phase 4 API unhealthy: HTTP {response.status_code}",
                    file=sys.stderr,
                )
                return False
        except requests.exceptions.ConnectionError as e:
            print(
                f"❌ [PatternTracker] Cannot connect to Phase 4 API at {self.base_url}: {e}",
                file=sys.stderr,
            )
            return False
        except requests.exceptions.Timeout as e:
            print(f"❌ [PatternTracker] Health check timeout: {e}", file=sys.stderr)
            return False
        except Exception as e:
            print(
                f"⚠️ [PatternTracker] Health check failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return False

    @classmethod
    async def get_instance(cls) -> "PatternTracker":
        """
        Get singleton instance of PatternTracker.

        Returns:
            PatternTracker singleton instance
        """
        if cls._instance is None:
            # Get the lock (created lazily under running event loop)
            lock = await cls._get_lock()
            async with lock:
                if cls._instance is None:
                    cls._instance = cls()

        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset singleton instance (useful for testing)"""
        cls._instance = None
        cls._lock = None  # Also reset the lock for clean slate

    def _generate_pattern_id(self, code: str, context: Dict[str, Any]) -> str:
        """
        Generate unique pattern ID from code and context.

        Args:
            code: Pattern code content
            context: Pattern context

        Returns:
            Unique pattern ID
        """
        # Create hash from code + key context fields
        hash_input = (
            f"{code}:{context.get('language', '')}:{context.get('pattern_type', '')}"
        )
        hash_digest = hashlib.sha256(hash_input.encode()).hexdigest()[:12]

        # Create readable pattern ID
        language = context.get("language", "unknown")
        pattern_type = context.get("pattern_type", "code")

        pattern_id = f"{language}-{pattern_type}-{hash_digest}"

        return pattern_id

    def _extract_pattern_name(self, code: str, context: Dict[str, Any]) -> str:
        """
        Extract human-readable pattern name from code and context.

        Args:
            code: Pattern code content
            context: Pattern context

        Returns:
            Human-readable pattern name
        """
        # Try to get function/class name from code
        file_path = context.get("file_path", "")
        if file_path:
            return Path(file_path).stem

        # Fallback to context-based name
        language = context.get("language", "unknown")
        pattern_type = context.get("pattern_type", "code")

        return f"{language.title()} {pattern_type.title()} Pattern"

    @graceful_tracking(fallback_return={})
    async def track_pattern_creation(
        self,
        code: str,
        context: Dict[str, Any],
        parent_pattern_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Track pattern creation event.

        This is fired when a new code pattern is created via Claude Code.

        Args:
            code: Pattern code content
            context: Pattern context (file_path, language, tool_name, etc.)
            parent_pattern_ids: Optional parent pattern IDs if derived

        Returns:
            Tracking result dict (empty dict on error due to graceful degradation)

        Example:
            await tracker.track_pattern_creation(
                code="function authenticateJWT(token) { ... }",
                context={
                    "file_path": "src/auth/jwt.js",
                    "language": "javascript",
                    "tool_name": "Write",
                    "framework": "express",
                    "pattern_type": "authentication"
                }
            )
        """
        if not self.enable_tracking:
            return {"success": False, "reason": "tracking_disabled"}

        # Generate pattern ID
        pattern_id = self._generate_pattern_id(code, context)
        pattern_name = self._extract_pattern_name(code, context)

        # Check if already tracked (deduplication)
        if pattern_id in self._pattern_cache:
            logger.debug(
                f"[PatternTracker] Pattern {pattern_id} already tracked, skipping"
            )
            return {"success": True, "cached": True, "pattern_id": pattern_id}

        # Prepare pattern data
        pattern_data = {
            "code": code,
            "language": context.get("language", "unknown"),
            "file_path": context.get("file_path", ""),
            "tool_name": context.get("tool_name", "unknown"),
            "framework": context.get("framework", ""),
            "pattern_type": context.get("pattern_type", "code"),
            "created_at": datetime.utcnow().isoformat(),
            "metadata": {
                k: v
                for k, v in context.items()
                if k not in ["code", "language", "file_path", "tool_name"]
            },
        }

        # Track via resilient API client with comprehensive error handling
        try:
            result = await self.api_client.track_pattern_resilient(
                event_type="pattern_created",
                pattern_id=pattern_id,
                pattern_name=pattern_name,
                pattern_type=context.get("pattern_type", "code"),
                pattern_version="1.0.0",
                pattern_data=pattern_data,
                parent_pattern_ids=parent_pattern_ids or [],
                edge_type="created_from" if parent_pattern_ids else None,
                triggered_by="claude-code",
            )

            # Cache pattern ID on success
            if result.get("success"):
                self._pattern_cache[pattern_id] = pattern_name
                print(
                    f"✅ [PatternTracker] Pattern created: {pattern_id}",
                    file=sys.stderr,
                )

            return result

        except httpx.ConnectError as e:
            print(
                f"❌ [PatternTracker.track_pattern_creation] Cannot connect to Phase 4 API at {self.base_url}: {e}",
                file=sys.stderr,
            )
            return None
        except httpx.TimeoutError as e:
            print(
                f"❌ [PatternTracker.track_pattern_creation] Phase 4 API timeout: {e}",
                file=sys.stderr,
            )
            return None
        except KeyError as e:
            print(
                f"❌ [PatternTracker.track_pattern_creation] Missing field in API response: {e}",
                file=sys.stderr,
            )
            return None
        except Exception as e:
            print(
                f"❌ [PatternTracker.track_pattern_creation] Unexpected error: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return None

    @graceful_tracking(fallback_return={})
    async def track_pattern_modification(
        self,
        pattern_id: str,
        new_code: str,
        context: Dict[str, Any],
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Track pattern modification event.

        This is fired when an existing pattern is modified.

        Args:
            pattern_id: Existing pattern ID
            new_code: Modified code
            context: Modification context
            reason: Reason for modification

        Returns:
            Tracking result dict

        Example:
            await tracker.track_pattern_modification(
                pattern_id="javascript-auth-abc123",
                new_code="function authenticateJWT(token, options) { ... }",
                context={
                    "file_path": "src/auth/jwt.js",
                    "tool_name": "Edit"
                },
                reason="Added options parameter for flexibility"
            )
        """
        if not self.enable_tracking:
            return {"success": False, "reason": "tracking_disabled"}

        # Generate new version pattern ID
        new_pattern_id = self._generate_pattern_id(new_code, context)

        # Prepare pattern data
        pattern_data = {
            "code": new_code,
            "language": context.get("language", "unknown"),
            "file_path": context.get("file_path", ""),
            "tool_name": context.get("tool_name", "unknown"),
            "modified_at": datetime.utcnow().isoformat(),
            "reason": reason,
            "metadata": context,
        }

        # Track via resilient API client with comprehensive error handling
        try:
            result = await self.api_client.track_pattern_resilient(
                event_type="pattern_modified",
                pattern_id=new_pattern_id,
                pattern_name=self._extract_pattern_name(new_code, context),
                pattern_type=context.get("pattern_type", "code"),
                pattern_version="1.1.0",  # Increment version
                pattern_data=pattern_data,
                parent_pattern_ids=[pattern_id],
                edge_type="modified_from",
                transformation_type="modification",
                reason=reason,
                triggered_by="claude-code",
            )

            if result.get("success"):
                print(
                    f"✅ [PatternTracker] Pattern modified: {new_pattern_id} (from {pattern_id})",
                    file=sys.stderr,
                )

            return result

        except httpx.ConnectError as e:
            print(
                f"❌ [PatternTracker.track_pattern_modification] Cannot connect to Phase 4 API at {self.base_url}: {e}",
                file=sys.stderr,
            )
            return None
        except httpx.TimeoutError as e:
            print(
                f"❌ [PatternTracker.track_pattern_modification] Phase 4 API timeout: {e}",
                file=sys.stderr,
            )
            return None
        except KeyError as e:
            print(
                f"❌ [PatternTracker.track_pattern_modification] Missing field in API response: {e}",
                file=sys.stderr,
            )
            return None
        except Exception as e:
            print(
                f"❌ [PatternTracker.track_pattern_modification] Unexpected error: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return None

    @graceful_tracking(fallback_return={})
    async def track_pattern_application(
        self, pattern_id: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Track pattern application event.

        This is fired when a pattern is applied/reused in a new location.

        Args:
            pattern_id: Pattern ID being applied
            context: Application context

        Returns:
            Tracking result dict

        Example:
            await tracker.track_pattern_application(
                pattern_id="javascript-auth-abc123",
                context={
                    "file_path": "src/api/endpoints.js",
                    "tool_name": "Write",
                    "reason": "Reusing JWT auth pattern for API routes"
                }
            )
        """
        if not self.enable_tracking:
            return {"success": False, "reason": "tracking_disabled"}

        # Prepare application data
        pattern_data = {
            "applied_at": datetime.utcnow().isoformat(),
            "file_path": context.get("file_path", ""),
            "tool_name": context.get("tool_name", "unknown"),
            "reason": context.get("reason", "Pattern reused"),
            "metadata": context,
        }

        # Track via resilient API client with comprehensive error handling
        try:
            result = await self.api_client.track_pattern_resilient(
                event_type="pattern_applied",
                pattern_id=pattern_id,
                pattern_data=pattern_data,
                triggered_by="claude-code",
            )

            if result.get("success"):
                print(
                    f"✅ [PatternTracker] Pattern applied: {pattern_id}",
                    file=sys.stderr,
                )

            return result

        except httpx.ConnectError as e:
            print(
                f"❌ [PatternTracker.track_pattern_application] Cannot connect to Phase 4 API at {self.base_url}: {e}",
                file=sys.stderr,
            )
            return None
        except httpx.TimeoutError as e:
            print(
                f"❌ [PatternTracker.track_pattern_application] Phase 4 API timeout: {e}",
                file=sys.stderr,
            )
            return None
        except KeyError as e:
            print(
                f"❌ [PatternTracker.track_pattern_application] Missing field in API response: {e}",
                file=sys.stderr,
            )
            return None
        except Exception as e:
            print(
                f"❌ [PatternTracker.track_pattern_application] Unexpected error: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return None

    @graceful_tracking(fallback_return={})
    async def track_pattern_merge(
        self,
        source_pattern_ids: List[str],
        merged_code: str,
        context: Dict[str, Any],
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Track pattern merge event.

        This is fired when multiple patterns are combined into one.

        Args:
            source_pattern_ids: List of pattern IDs being merged
            merged_code: Resulting merged code
            context: Merge context
            reason: Reason for merge

        Returns:
            Tracking result dict

        Example:
            await tracker.track_pattern_merge(
                source_pattern_ids=["auth-001", "auth-002"],
                merged_code="function authenticateWithMultipleProviders() { ... }",
                context={
                    "file_path": "src/auth/unified.js",
                    "tool_name": "Write"
                },
                reason="Unified authentication patterns"
            )
        """
        if not self.enable_tracking:
            return {"success": False, "reason": "tracking_disabled"}

        # Generate merged pattern ID
        merged_pattern_id = self._generate_pattern_id(merged_code, context)

        # Prepare merge data
        pattern_data = {
            "code": merged_code,
            "merged_from": source_pattern_ids,
            "merged_at": datetime.utcnow().isoformat(),
            "reason": reason,
            "metadata": context,
        }

        # Track via resilient API client with comprehensive error handling
        try:
            result = await self.api_client.track_pattern_resilient(
                event_type="pattern_merged",
                pattern_id=merged_pattern_id,
                pattern_name=self._extract_pattern_name(merged_code, context),
                pattern_type=context.get("pattern_type", "code"),
                pattern_version="2.0.0",  # Major version for merge
                pattern_data=pattern_data,
                parent_pattern_ids=source_pattern_ids,
                edge_type="merged_from",
                transformation_type="merge",
                reason=reason,
                triggered_by="claude-code",
            )

            if result.get("success"):
                print(
                    f"✅ [PatternTracker] Pattern merged: {merged_pattern_id} (from {', '.join(source_pattern_ids)})",
                    file=sys.stderr,
                )

            return result

        except httpx.ConnectError as e:
            print(
                f"❌ [PatternTracker.track_pattern_merge] Cannot connect to Phase 4 API at {self.base_url}: {e}",
                file=sys.stderr,
            )
            return None
        except httpx.TimeoutError as e:
            print(
                f"❌ [PatternTracker.track_pattern_merge] Phase 4 API timeout: {e}",
                file=sys.stderr,
            )
            return None
        except KeyError as e:
            print(
                f"❌ [PatternTracker.track_pattern_merge] Missing field in API response: {e}",
                file=sys.stderr,
            )
            return None
        except Exception as e:
            print(
                f"❌ [PatternTracker.track_pattern_merge] Unexpected error: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return None

    async def get_tracker_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive tracker statistics.

        Returns:
            Dict with tracker and resilience stats
        """
        try:
            resilience_stats = await self.api_client.get_stats()

            stats = {
                "tracker": {
                    "enabled": self.enable_tracking,
                    "base_url": self.base_url,
                    "cached_patterns": len(self._pattern_cache),
                },
                "resilience": resilience_stats,
            }

            return stats

        except httpx.ConnectError as e:
            print(
                f"❌ [PatternTracker.get_tracker_stats] Cannot connect to Phase 4 API at {self.base_url}: {e}",
                file=sys.stderr,
            )
            return {
                "tracker": {
                    "enabled": self.enable_tracking,
                    "base_url": self.base_url,
                    "cached_patterns": len(self._pattern_cache),
                },
                "resilience": {"error": "connection_failed"},
            }
        except httpx.TimeoutError as e:
            print(
                f"❌ [PatternTracker.get_tracker_stats] Phase 4 API timeout: {e}",
                file=sys.stderr,
            )
            return {
                "tracker": {
                    "enabled": self.enable_tracking,
                    "base_url": self.base_url,
                    "cached_patterns": len(self._pattern_cache),
                },
                "resilience": {"error": "timeout"},
            }
        except Exception as e:
            print(
                f"❌ [PatternTracker.get_tracker_stats] Unexpected error: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return {
                "tracker": {
                    "enabled": self.enable_tracking,
                    "base_url": self.base_url,
                    "cached_patterns": len(self._pattern_cache),
                },
                "resilience": {"error": str(e)},
            }

    async def sync_offline_events(self) -> Dict[str, Any]:
        """
        Manually trigger sync of offline cached events.

        Returns:
            Sync statistics
        """
        if not self.api_client.cache:
            return {"success": False, "reason": "caching_disabled"}

        try:
            sync_stats = await self.api_client.cache.sync_cached_events(self.api_client)

            logger.info(
                f"[PatternTracker] Synced {sync_stats['synced']} offline events"
            )
            print(
                f"✅ [PatternTracker] Synced {sync_stats.get('synced', 0)} offline events",
                file=sys.stderr,
            )

            return {"success": True, "sync_stats": sync_stats}

        except httpx.ConnectError as e:
            print(
                f"❌ [PatternTracker.sync_offline_events] Cannot connect to Phase 4 API at {self.base_url}: {e}",
                file=sys.stderr,
            )
            return {"success": False, "error": "connection_failed"}
        except httpx.TimeoutError as e:
            print(
                f"❌ [PatternTracker.sync_offline_events] Phase 4 API timeout: {e}",
                file=sys.stderr,
            )
            return {"success": False, "error": "timeout"}
        except KeyError as e:
            print(
                f"❌ [PatternTracker.sync_offline_events] Missing field in sync response: {e}",
                file=sys.stderr,
            )
            return {"success": False, "error": f"missing_field: {e}"}
        except Exception as e:
            print(
                f"❌ [PatternTracker.sync_offline_events] Unexpected error: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return {"success": False, "error": str(e)}

    async def cleanup_cache(self) -> Dict[str, Any]:
        """
        Clean up old cached events.

        Returns:
            Cleanup statistics
        """
        if not self.api_client.cache:
            return {"success": False, "reason": "caching_disabled"}

        try:
            cleaned = await self.api_client.cache.cleanup_old_events()

            logger.info(f"[PatternTracker] Cleaned up {cleaned} old cached events")
            print(
                f"✅ [PatternTracker] Cleaned up {cleaned} old cached events",
                file=sys.stderr,
            )

            return {"success": True, "cleaned_count": cleaned}

        except httpx.ConnectError as e:
            print(
                f"❌ [PatternTracker.cleanup_cache] Cannot connect to Phase 4 API at {self.base_url}: {e}",
                file=sys.stderr,
            )
            return {"success": False, "error": "connection_failed"}
        except httpx.TimeoutError as e:
            print(
                f"❌ [PatternTracker.cleanup_cache] Phase 4 API timeout: {e}",
                file=sys.stderr,
            )
            return {"success": False, "error": "timeout"}
        except Exception as e:
            print(
                f"❌ [PatternTracker.cleanup_cache] Unexpected error: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return {"success": False, "error": str(e)}


# ============================================================================
# Convenience Functions for Hook Integration
# ============================================================================


async def track_write_tool_pattern(
    file_path: str, content: str, language: str = "unknown"
) -> Dict[str, Any]:
    """
    Convenience function for tracking Write tool patterns.

    Args:
        file_path: Path to file being written
        content: File content
        language: Programming language

    Returns:
        Tracking result
    """
    tracker = await PatternTracker.get_instance()

    return await tracker.track_pattern_creation(
        code=content,
        context={
            "file_path": file_path,
            "language": language,
            "tool_name": "Write",
            "pattern_type": "code",
        },
    )


async def track_edit_tool_pattern(
    file_path: str,
    pattern_id: str,
    new_content: str,
    language: str = "unknown",
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convenience function for tracking Edit tool patterns.

    Args:
        file_path: Path to file being edited
        pattern_id: Existing pattern ID
        new_content: New file content
        language: Programming language
        reason: Reason for edit

    Returns:
        Tracking result
    """
    tracker = await PatternTracker.get_instance()

    return await tracker.track_pattern_modification(
        pattern_id=pattern_id,
        new_code=new_content,
        context={
            "file_path": file_path,
            "language": language,
            "tool_name": "Edit",
            "pattern_type": "code",
        },
        reason=reason,
    )


# ============================================================================
# Usage Example
# ============================================================================


async def example_usage():
    """Example of using pattern tracker in Claude Code hooks"""

    # Get tracker instance
    tracker = await PatternTracker.get_instance()

    # Example 1: Track pattern creation from Write tool
    result1 = await tracker.track_pattern_creation(
        code="""
function authenticateJWT(token) {
    const decoded = jwt.verify(token, process.env.JWT_SECRET);
    return decoded;
}
        """,
        context={
            "file_path": "src/auth/jwt.js",
            "language": "javascript",
            "tool_name": "Write",
            "framework": "express",
            "pattern_type": "authentication",
        },
    )
    print(f"Pattern creation: {result1}")

    # Example 2: Track pattern modification from Edit tool
    result2 = await tracker.track_pattern_modification(
        pattern_id="javascript-authentication-abc123",
        new_code="""
function authenticateJWT(token, options = {}) {
    const decoded = jwt.verify(token, options.secret || process.env.JWT_SECRET);
    return decoded;
}
        """,
        context={
            "file_path": "src/auth/jwt.js",
            "language": "javascript",
            "tool_name": "Edit",
        },
        reason="Added options parameter for flexibility",
    )
    print(f"Pattern modification: {result2}")

    # Example 3: Get tracker stats
    stats = await tracker.get_tracker_stats()
    print(f"Tracker stats: {stats}")


if __name__ == "__main__":
    # Run example
    asyncio.run(example_usage())
