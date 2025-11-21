"""
Resilience Layer for Pattern Tracking System

Provides bulletproof error handling, graceful degradation, and resilience patterns
to ensure pattern tracking NEVER disrupts Claude Code workflows.

Key Features:
- Fire-and-forget execution that never blocks
- Circuit breaker to prevent repeated failures
- Local caching for offline scenarios
- Health checking with auto-recovery
- Graceful degradation decorators

Usage:
    from lib.resilience import (
        ResilientExecutor,
        CircuitBreaker,
        PatternCache,
        Phase4HealthChecker,
        graceful_tracking
    )

    # Initialize resilience components
    executor = ResilientExecutor()
    circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=60)
    cache = PatternCache()
    health_checker = Phase4HealthChecker()  # Uses settings.archon_intelligence_url by default

    # Fire-and-forget pattern tracking
    executor.fire_and_forget(
        track_pattern_creation(code, context)
    )

    # Use circuit breaker for API calls
    result = await circuit_breaker.call(
        lambda: api_client.track_lineage(...)
    )

    # Cache events when API is down
    if result is None:
        await cache.cache_pattern_event(event_data)
"""

import asyncio
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import settings


logger = logging.getLogger(__name__)


# ============================================================================
# Fire-and-Forget Executor
# ============================================================================


class ResilientExecutor:
    """
    Execute async tasks without blocking or raising errors.

    Ensures that pattern tracking operations never interfere with
    Claude Code's main workflow, even if they fail.

    Example:
        executor = ResilientExecutor()
        executor.fire_and_forget(track_pattern_creation(code, context))
        # Execution continues immediately, tracking happens in background
    """

    def __init__(self):
        self._active_tasks: List[asyncio.Task] = []
        self._task_count = 0
        self._success_count = 0
        self._error_count = 0

    def fire_and_forget(self, coro) -> asyncio.Task:
        """
        Execute async task without blocking or raising errors.

        Args:
            coro: Coroutine to execute in background

        Returns:
            asyncio.Task object for optional monitoring

        Note:
            Errors are logged but never propagated to caller
        """
        task = asyncio.create_task(coro)
        task.add_done_callback(self._handle_task_completion)
        self._active_tasks.append(task)
        self._task_count += 1
        return task

    def _handle_task_completion(self, task: asyncio.Task) -> None:
        """Handle task completion (success or error)"""
        try:
            # Remove from active tasks
            if task in self._active_tasks:
                self._active_tasks.remove(task)

            # Check for exceptions
            try:
                task.result()
                self._success_count += 1
                logger.debug("[PatternTracker] Background task completed successfully")
            except Exception as e:
                self._error_count += 1
                # Log but don't raise - fire-and-forget pattern
                logger.warning(
                    f"[PatternTracker] Background task failed: {e}", exc_info=True
                )
        except Exception as e:
            # Even the error handler shouldn't fail
            print(
                f"[PatternTracker] Error in task completion handler: {e}",
                file=sys.stderr,
            )

    def get_stats(self) -> Dict[str, int]:
        """Get executor statistics"""
        return {
            "total_tasks": self._task_count,
            "active_tasks": len(self._active_tasks),
            "success_count": self._success_count,
            "error_count": self._error_count,
            "success_rate": (
                self._success_count / self._task_count if self._task_count > 0 else 0.0
            ),
        }

    async def wait_for_completion(self, timeout: float = 5.0) -> bool:
        """
        Wait for all active tasks to complete (useful for testing/cleanup)

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if all tasks completed, False if timeout
        """
        try:
            if not self._active_tasks:
                return True

            await asyncio.wait_for(
                asyncio.gather(*self._active_tasks, return_exceptions=True),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(
                f"[PatternTracker] {len(self._active_tasks)} tasks did not "
                f"complete within {timeout}s"
            )
            return False


# ============================================================================
# Circuit Breaker Pattern
# ============================================================================


@dataclass
class CircuitBreakerState:
    """Circuit breaker state tracking"""

    state: str  # "closed", "open", "half_open"
    failure_count: int
    last_failure_time: Optional[float]
    last_success_time: Optional[float]
    consecutive_successes: int


class CircuitBreaker:
    """
    Circuit breaker pattern to prevent repeated failures.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests are blocked
    - HALF_OPEN: Testing if service recovered, limited requests pass

    Example:
        breaker = CircuitBreaker(failure_threshold=3, timeout=60)

        result = await breaker.call(
            lambda: api_client.track_lineage(...)
        )

        if result is None:
            # Circuit is open, API is down
            await cache.cache_pattern_event(event)
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        timeout: int = 60,
        half_open_max_calls: int = 1,
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Seconds to wait before attempting half-open
            half_open_max_calls: Max concurrent calls in half-open state
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitBreakerState(
            state="closed",
            failure_count=0,
            last_failure_time=None,
            last_success_time=None,
            consecutive_successes=0,
        )
        self._half_open_calls = 0

    async def call(self, func: Callable) -> Optional[Any]:
        """
        Call function through circuit breaker.

        Args:
            func: Async callable to execute

        Returns:
            Function result if successful, None if circuit is open or call failed

        Note:
            Never raises exceptions - returns None on any error
        """
        # Check if circuit should transition from open to half-open
        if self._state.state == "open":
            if self._should_attempt_reset():
                logger.info(
                    "[PatternTracker] Circuit breaker transitioning to half-open"
                )
                self._state.state = "half_open"
                self._half_open_calls = 0
            else:
                logger.debug("[PatternTracker] Circuit breaker is open, skipping call")
                return None

        # Check half-open call limit
        if self._state.state == "half_open":
            if self._half_open_calls >= self.half_open_max_calls:
                logger.debug(
                    "[PatternTracker] Circuit breaker half-open limit reached, "
                    "skipping call"
                )
                return None
            self._half_open_calls += 1

        # Execute the call
        try:
            result = await func()
            self._record_success()
            return result
        except Exception as e:
            self._record_failure(e)
            return None

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        if self._state.last_failure_time is None:
            return True

        elapsed = time.time() - self._state.last_failure_time
        return elapsed >= self.timeout

    def _record_success(self) -> None:
        """Record successful call"""
        self._state.last_success_time = time.time()
        self._state.consecutive_successes += 1
        self._state.failure_count = 0

        # Transition from half-open to closed after success
        if self._state.state == "half_open":
            logger.info(
                "[PatternTracker] Circuit breaker closing after successful call"
            )
            self._state.state = "closed"
            self._half_open_calls = 0

    def _record_failure(self, error: Exception) -> None:
        """Record failed call"""
        self._state.last_failure_time = time.time()
        self._state.failure_count += 1
        self._state.consecutive_successes = 0

        logger.warning(
            f"[PatternTracker] Circuit breaker recorded failure "
            f"({self._state.failure_count}/{self.failure_threshold}): {error}"
        )

        # Open circuit if threshold reached
        if self._state.failure_count >= self.failure_threshold:
            if self._state.state != "open":
                logger.warning(
                    f"[PatternTracker] Circuit breaker opening after "
                    f"{self._state.failure_count} failures"
                )
                self._state.state = "open"

    def get_state(self) -> Dict[str, Any]:
        """Get current circuit breaker state"""
        return {
            "state": self._state.state,
            "failure_count": self._state.failure_count,
            "consecutive_successes": self._state.consecutive_successes,
            "last_failure_time": (
                datetime.fromtimestamp(self._state.last_failure_time).isoformat()
                if self._state.last_failure_time
                else None
            ),
            "last_success_time": (
                datetime.fromtimestamp(self._state.last_success_time).isoformat()
                if self._state.last_success_time
                else None
            ),
            "is_available": self._state.state in ["closed", "half_open"],
        }

    def reset(self) -> None:
        """Manually reset circuit breaker to closed state"""
        logger.info("[PatternTracker] Circuit breaker manually reset")
        self._state = CircuitBreakerState(
            state="closed",
            failure_count=0,
            last_failure_time=None,
            last_success_time=None,
            consecutive_successes=0,
        )
        self._half_open_calls = 0


# ============================================================================
# Local Cache for Offline Scenarios
# ============================================================================


@dataclass
class CachedPatternEvent:
    """Cached pattern event for offline storage"""

    event_id: str
    timestamp: str
    event_type: str
    pattern_id: str
    event_data: Dict[str, Any]
    retry_count: int = 0
    last_retry: Optional[str] = None


class PatternCache:
    """
    Local cache for pattern events when API is unavailable.

    Features:
    - Stores events locally when API is down
    - Auto-syncs when API becomes available
    - Retry logic with exponential backoff
    - Automatic cleanup of old events

    Example:
        cache = PatternCache()

        # Cache event when API is down
        await cache.cache_pattern_event({
            "event_type": "pattern_created",
            "pattern_id": "auth-001",
            "pattern_data": {...}
        })

        # Sync when API is back
        synced = await cache.sync_cached_events(api_client)
        print(f"Synced {synced} events")
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_age_days: int = 7,
        max_cache_size_mb: int = 50,
    ):
        """
        Initialize pattern cache.

        Args:
            cache_dir: Cache directory path (default: ~/.claude/hooks/.cache/patterns)
            max_age_days: Maximum age for cached events before cleanup
            max_cache_size_mb: Maximum cache size in megabytes
        """
        self._cache_dir = cache_dir or (
            Path.home() / ".claude" / "hooks" / ".cache" / "patterns"
        )
        self.max_age_days = max_age_days
        self.max_cache_size_mb = max_cache_size_mb

        # Create cache directory
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Metadata file
        self.metadata_file = self._cache_dir / "cache_metadata.json"
        self._load_metadata()

    @property
    def cache_dir(self) -> Path:
        """Get cache directory (property to ensure it exists)"""
        return self._cache_dir

    @cache_dir.setter
    def cache_dir(self, value: Path):
        """Set cache directory and ensure it exists"""
        self._cache_dir = value
        # Ensure directory exists when set
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # Update metadata file path
        self.metadata_file = self._cache_dir / "cache_metadata.json"
        self._load_metadata()

    def _load_metadata(self) -> None:
        """Load cache metadata"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file) as f:
                    self._metadata = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cache metadata: {e}")
                self._metadata = {"total_cached": 0, "total_synced": 0}
        else:
            self._metadata = {"total_cached": 0, "total_synced": 0}

    def _save_metadata(self) -> None:
        """Save cache metadata"""
        try:
            with open(self.metadata_file, "w") as f:
                json.dump(self._metadata, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache metadata: {e}")

    async def cache_pattern_event(self, event: Dict[str, Any]) -> str:
        """
        Cache pattern event locally when API is unavailable.

        Args:
            event: Event data to cache

        Returns:
            Event ID for the cached event
        """
        try:
            # Generate event ID
            event_id = f"{int(time.time() * 1000)}_{event.get('pattern_id', 'unknown')}"

            # Create cached event
            cached_event = CachedPatternEvent(
                event_id=event_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type=event.get("event_type", "unknown"),
                pattern_id=event.get("pattern_id", "unknown"),
                event_data=event,
            )

            # Save to file
            cache_file = self.cache_dir / f"pending_{event_id}.json"
            with open(cache_file, "w") as f:
                json.dump(asdict(cached_event), f, indent=2)

            # Update metadata
            self._metadata["total_cached"] = self._metadata.get("total_cached", 0) + 1
            self._save_metadata()

            logger.info(
                f"[PatternTracker] Cached event {event_id} locally "
                f"(type: {cached_event.event_type})"
            )

            return event_id

        except Exception as e:
            logger.error(f"[PatternTracker] Failed to cache event: {e}", exc_info=True)
            # Don't raise - caching failure shouldn't break workflow
            return ""

    async def sync_cached_events(
        self, api_client, max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Sync cached events when API becomes available.

        Args:
            api_client: API client with track_lineage method
            max_retries: Maximum retries per event

        Returns:
            Dict with sync statistics
        """
        stats = {"total_found": 0, "synced": 0, "failed": 0, "skipped": 0}

        try:
            # Find all pending cache files
            cache_files = list(self.cache_dir.glob("pending_*.json"))
            stats["total_found"] = len(cache_files)

            if not cache_files:
                logger.debug("[PatternTracker] No cached events to sync")
                return stats

            logger.info(f"[PatternTracker] Syncing {len(cache_files)} cached events...")

            for cache_file in cache_files:
                try:
                    # Load cached event
                    with open(cache_file) as f:
                        cached_event_data = json.load(f)
                        cached_event = CachedPatternEvent(**cached_event_data)

                    # Check retry limit
                    if cached_event.retry_count >= max_retries:
                        logger.warning(
                            f"[PatternTracker] Skipping event {cached_event.event_id} "
                            f"(max retries reached)"
                        )
                        stats["skipped"] += 1
                        continue

                    # Try to sync
                    await api_client.track_lineage(**cached_event.event_data)

                    # Success - delete cache file
                    cache_file.unlink()
                    stats["synced"] += 1

                    logger.info(
                        f"[PatternTracker] Synced cached event {cached_event.event_id}"
                    )

                except Exception as e:
                    # Update retry count
                    cached_event.retry_count += 1
                    cached_event.last_retry = datetime.now(timezone.utc).isoformat()

                    # Save updated event
                    with open(cache_file, "w") as f:
                        json.dump(asdict(cached_event), f, indent=2)

                    stats["failed"] += 1
                    logger.warning(
                        f"[PatternTracker] Failed to sync event "
                        f"{cached_event.event_id}: {e}"
                    )

            # Update metadata
            self._metadata["total_synced"] = (
                self._metadata.get("total_synced", 0) + stats["synced"]
            )
            self._save_metadata()

            logger.info(
                f"[PatternTracker] Sync complete: {stats['synced']} synced, "
                f"{stats['failed']} failed, {stats['skipped']} skipped"
            )

        except Exception as e:
            logger.error(f"[PatternTracker] Error during sync: {e}", exc_info=True)

        return stats

    async def cleanup_old_events(self) -> int:
        """
        Clean up old cached events.

        Returns:
            Number of events cleaned up
        """
        cleaned = 0

        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=self.max_age_days)

            for cache_file in self.cache_dir.glob("pending_*.json"):
                try:
                    with open(cache_file) as f:
                        event_data = json.load(f)
                        timestamp = datetime.fromisoformat(event_data["timestamp"])

                    if timestamp < cutoff_time:
                        cache_file.unlink()
                        cleaned += 1
                        logger.info(
                            f"[PatternTracker] Cleaned up old cached event: "
                            f"{event_data['event_id']}"
                        )

                except Exception as e:
                    logger.warning(f"Failed to clean up {cache_file}: {e}")

            if cleaned > 0:
                logger.info(f"[PatternTracker] Cleaned up {cleaned} old cached events")

        except Exception as e:
            logger.error(f"[PatternTracker] Error during cleanup: {e}", exc_info=True)

        return cleaned

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        pending_files = list(self.cache_dir.glob("pending_*.json"))

        return {
            "pending_events": len(pending_files),
            "total_cached": self._metadata.get("total_cached", 0),
            "total_synced": self._metadata.get("total_synced", 0),
            "cache_dir": str(self.cache_dir),
            "max_age_days": self.max_age_days,
        }


# ============================================================================
# Health Check and Auto-Recovery
# ============================================================================


class Phase4HealthChecker:
    """
    Health checker for Phase 4 Pattern Traceability APIs.

    Features:
    - Periodic health checks with caching
    - Auto-recovery detection
    - Component-level health tracking
    - Minimal overhead (<30s check interval)

    Example:
        health_checker = Phase4HealthChecker()  # Uses settings.archon_intelligence_url

        is_healthy = await health_checker.check_health()
        if is_healthy:
            result = await api_client.track_lineage(...)
    """

    def __init__(
        self,
        base_url: str = None,
        check_interval: int = 30,
        timeout: float = 1.0,
    ):
        """
        Initialize health checker.

        Args:
            base_url: Base URL for Phase 4 API (defaults to settings.archon_intelligence_url)
            check_interval: Seconds between health checks
            timeout: Health check timeout in seconds
        """
        self.base_url = (base_url or str(settings.archon_intelligence_url)).rstrip("/")
        self.check_interval = check_interval
        self.timeout = timeout

        self.is_healthy = False
        self.last_check = 0
        self.last_health_data: Optional[Dict] = None
        self.consecutive_failures = 0
        self.consecutive_successes = 0

    async def check_health(self, force: bool = False) -> bool:
        """
        Check if Phase 4 APIs are responsive.

        Args:
            force: Force health check even if recently checked

        Returns:
            True if healthy, False otherwise
        """
        # Use cached result if recent
        if not force and (time.time() - self.last_check) < self.check_interval:
            return self.is_healthy

        try:
            import httpx

            # Check health endpoint
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/pattern-traceability/health"
                )

                if response.status_code == 200:
                    self.last_health_data = response.json()
                    self.is_healthy = True
                    self.consecutive_successes += 1
                    self.consecutive_failures = 0

                    # Log recovery
                    if self.consecutive_successes == 1:
                        logger.info(
                            "[PatternTracker] Phase 4 API recovered and is now healthy"
                        )
                else:
                    self.is_healthy = False
                    self.consecutive_failures += 1
                    self.consecutive_successes = 0

        except Exception as e:
            self.is_healthy = False
            self.consecutive_failures += 1
            self.consecutive_successes = 0

            # Only log first failure to avoid spam
            if self.consecutive_failures == 1:
                logger.warning(f"[PatternTracker] Phase 4 API health check failed: {e}")

        self.last_check = time.time()
        return self.is_healthy

    def get_health_status(self) -> Dict[str, Any]:
        """Get detailed health status"""
        return {
            "is_healthy": self.is_healthy,
            "last_check": (
                datetime.fromtimestamp(self.last_check).isoformat()
                if self.last_check > 0
                else None
            ),
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "last_health_data": self.last_health_data,
            "base_url": self.base_url,
        }


# ============================================================================
# Graceful Degradation Decorator
# ============================================================================


def graceful_tracking(fallback_return=None, log_errors=True):
    """
    Decorator to ensure tracking never fails the main workflow.

    Wraps functions to catch all exceptions and return fallback value.
    Ensures that pattern tracking failures are logged but never propagated.

    Args:
        fallback_return: Value to return on error (default: None)
        log_errors: Whether to log errors (default: True)

    Example:
        @graceful_tracking(fallback_return={})
        async def track_pattern_creation(code: str, context: Dict) -> Dict:
            # This can fail, but will never raise
            return await api_client.track_lineage(...)

        # Usage
        result = await track_pattern_creation(code, context)
        # Returns {} if tracking fails, actual result if successful
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if log_errors:
                    logger.warning(
                        f"[PatternTracker] Error in {func.__name__}: {e}", exc_info=True
                    )
                return fallback_return

        return wrapper

    return decorator


# ============================================================================
# Resilient API Client Wrapper
# ============================================================================


class ResilientAPIClient:
    """
    Resilient wrapper for Phase 4 API client.

    Combines all resilience patterns:
    - Circuit breaker for fault tolerance
    - Health checking for smart routing
    - Local caching for offline scenarios
    - Fire-and-forget execution for non-blocking

    Example:
        client = ResilientAPIClient()  # Uses settings.archon_intelligence_url

        # Track pattern (resilient, non-blocking)
        await client.track_pattern_resilient(
            event_type="pattern_created",
            pattern_id="auth-001",
            pattern_data={...}
        )
    """

    def __init__(
        self,
        base_url: str = None,
        enable_caching: bool = True,
        enable_circuit_breaker: bool = True,
    ):
        """
        Initialize resilient API client.

        Args:
            base_url: Base URL for Phase 4 API (defaults to settings.archon_intelligence_url)
            enable_caching: Enable local caching for offline scenarios
            enable_circuit_breaker: Enable circuit breaker pattern
        """
        self.base_url = (base_url or str(settings.archon_intelligence_url)).rstrip("/")
        self.enable_caching = enable_caching
        self.enable_circuit_breaker = enable_circuit_breaker

        # Initialize resilience components
        self.executor = ResilientExecutor()
        self.health_checker = Phase4HealthChecker(base_url=base_url)

        if enable_circuit_breaker:
            self.circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=60)
        else:
            self.circuit_breaker = None

        if enable_caching:
            self.cache = PatternCache()
        else:
            self.cache = None

    @graceful_tracking(fallback_return=None)
    async def _call_api(
        self,
        endpoint: str,
        method: str = "POST",
        data: Optional[Dict] = None,
        timeout: float = 2.0,
    ) -> Optional[Dict]:
        """
        Internal API call method with resilience.

        Args:
            endpoint: API endpoint path
            method: HTTP method
            data: Request data
            timeout: Request timeout

        Returns:
            Response data or None on error
        """
        import httpx

        url = f"{self.base_url}{endpoint}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "POST":
                response = await client.post(url, json=data)
            elif method == "GET":
                response = await client.get(url)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()

    async def track_pattern_resilient(
        self,
        event_type: str,
        pattern_id: str,
        pattern_name: str = "",
        pattern_data: Optional[Dict] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Track pattern lineage with full resilience.

        Features:
        - Health check before calling
        - Circuit breaker protection
        - Local caching if API unavailable
        - Fire-and-forget execution option

        Args:
            event_type: Event type (pattern_created, pattern_modified, etc.)
            pattern_id: Unique pattern identifier
            pattern_name: Human-readable pattern name
            pattern_data: Pattern content snapshot
            **kwargs: Additional event data

        Returns:
            Dict with tracking result and metadata
        """
        # Check health first
        is_healthy = await self.health_checker.check_health()

        # Prepare event data
        event_data = {
            "event_type": event_type,
            "pattern_id": pattern_id,
            "pattern_name": pattern_name,
            "pattern_data": pattern_data or {},
            **kwargs,
        }

        # If not healthy, cache and return
        if not is_healthy:
            if self.cache:
                event_id = await self.cache.cache_pattern_event(event_data)
                return {
                    "success": False,
                    "cached": True,
                    "event_id": event_id,
                    "message": "API unavailable, event cached locally",
                }
            return {
                "success": False,
                "cached": False,
                "message": "API unavailable, caching disabled",
            }

        # Try to call API through circuit breaker
        async def api_call():
            return await self._call_api(
                endpoint="/api/pattern-traceability/lineage/track",
                method="POST",
                data=event_data,
            )

        if self.circuit_breaker:
            result = await self.circuit_breaker.call(api_call)
        else:
            result = await api_call()

        # If call failed, cache event
        if result is None:
            if self.cache:
                event_id = await self.cache.cache_pattern_event(event_data)
                return {
                    "success": False,
                    "cached": True,
                    "event_id": event_id,
                    "message": "API call failed, event cached locally",
                }
            return {
                "success": False,
                "cached": False,
                "message": "API call failed, caching disabled",
            }

        # Success - try to sync cached events in background
        if self.cache:
            self.executor.fire_and_forget(self.cache.sync_cached_events(self))

        return {
            "success": True,
            "cached": False,
            "data": result,
            "message": "Pattern tracked successfully",
        }

    async def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive resilience statistics"""
        stats = {
            "executor": self.executor.get_stats(),
            "health": self.health_checker.get_health_status(),
        }

        if self.circuit_breaker:
            stats["circuit_breaker"] = self.circuit_breaker.get_state()

        if self.cache:
            stats["cache"] = self.cache.get_stats()

        return stats


# ============================================================================
# Usage Example
# ============================================================================


async def example_usage():
    """Example of using resilient pattern tracking"""

    # Initialize resilient client
    client = ResilientAPIClient()  # Uses settings.archon_intelligence_url

    # Track pattern creation (fully resilient)
    result = await client.track_pattern_resilient(
        event_type="pattern_created",
        pattern_id="auth-jwt-001",
        pattern_name="JWT Authentication Pattern",
        pattern_data={
            "code": "function authenticateUser(token) { ... }",
            "language": "javascript",
            "framework": "express",
        },
        triggered_by="claude-code",
    )

    print(f"Tracking result: {result}")

    # Get resilience stats
    stats = await client.get_stats()
    print(f"Resilience stats: {stats}")


if __name__ == "__main__":
    # Run example
    asyncio.run(example_usage())
