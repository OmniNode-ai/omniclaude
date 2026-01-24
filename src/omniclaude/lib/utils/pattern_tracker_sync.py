"""Synchronous Pattern Tracker for Claude Code Hooks.

This is a simplified synchronous version for use in hook scripts
where async execution causes premature exit.
Enhanced with performance optimizations from the enhanced tracker.
"""

import hashlib
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import requests

from omniclaude.config import settings


class PatternTrackerSync:
    """Synchronous pattern tracker using blocking HTTP calls with performance optimizations."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.base_url = str(settings.intelligence_service_url)
        self.timeout = 5  # seconds

        # Performance optimizations
        self._session = requests.Session()
        self._pattern_id_cache: dict[str, tuple[float, str]] = {}
        self._cache_ttl = 300  # 5 minutes
        self._metrics: dict[str, float] = {
            "total_requests": 0.0,
            "cache_hits": 0.0,
            "cache_misses": 0.0,
            "total_time_ms": 0.0,
        }

        # Configure session with connection pooling
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=3)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        # Health check
        self._check_api_health()

    def _check_api_health(self) -> bool:
        """Check if Phase 4 API is reachable."""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            if response.status_code == 200:
                print("✅ [PatternTrackerSync] Phase 4 API reachable", file=sys.stderr)
                self._api_healthy = True
                return True
            else:
                print(
                    f"⚠️ [PatternTrackerSync] Phase 4 API unhealthy: {response.status_code}",
                    file=sys.stderr,
                )
                self._api_healthy = False
                return False
        except Exception as e:
            print(f"❌ [PatternTrackerSync] API unreachable: {e}", file=sys.stderr)
            self._api_healthy = False
            return False

    def is_api_available(self) -> bool:
        """Check if API is available for tracking."""
        return hasattr(self, "_api_healthy") and self._api_healthy

    def track_pattern_creation_sync(
        self,
        code: str,
        context: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str | None:
        """Synchronous wrapper for track_pattern_creation - matches expected interface.

        Args:
            code: The code content to track
            context: Context dictionary with metadata:
                - event_type: Type of event (default: "pattern_created")
                - file_path: Path to the file
                - language: Programming language
                - reason: Reason for tracking
                - quality_score: Quality score (0.0-1.0)
                - violations_found: Number of violations
            metadata: Additional metadata (unused, for interface compatibility)
            correlation_id: Correlation ID (unused, for interface compatibility)

        Returns:
            Pattern ID if successful, None otherwise
        """
        return self.track_pattern_creation(code, context)

    def track_pattern_creation(self, code: str, context: dict[str, Any]) -> str | None:
        """Track pattern creation synchronously.

        Args:
            code: The code content to track
            context: Context dictionary with metadata:
                - event_type: Type of event (default: "pattern_created")
                - file_path: Path to the file
                - language: Programming language
                - reason: Reason for tracking
                - quality_score: Quality score (0.0-1.0)
                - violations_found: Number of violations

        Returns:
            Pattern ID if successful, None otherwise
        """
        # Check if API is available before attempting to track
        if not self.is_api_available():
            print(
                "⚠️ [PatternTrackerSync] Skipping pattern tracking - API not available",
                file=sys.stderr,
            )
            return None

        try:
            # Generate pattern ID
            pattern_id = self._generate_pattern_id(code, context)

            # Prepare payload
            payload = {
                "event_type": context.get("event_type", "pattern_created"),
                "pattern_id": pattern_id,
                "pattern_name": context.get("file_path", "unknown").split("/")[-1],
                "pattern_type": "code",
                "pattern_version": "1.0.0",
                "pattern_data": {
                    "code": code,
                    "language": context.get("language", "python"),
                    "file_path": context.get("file_path", ""),
                },
                "triggered_by": "claude_code_hook",
                "reason": context.get("reason", "Code generation via Claude Code"),
                "metadata": {
                    "session_id": self.session_id,
                    "quality_score": context.get("quality_score", 1.0),
                    "violations_found": context.get("violations_found", 0),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            }

            # Make synchronous API call with connection pooling
            start_time = time.time()
            print(
                "📤 [PatternTrackerSync] Sending pattern to Phase 4 API...",
                file=sys.stderr,
            )
            response = self._session.post(
                f"{self.base_url}/api/pattern-traceability/lineage/track",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()

            response_time_ms = (time.time() - start_time) * 1000
            self._metrics["total_requests"] += 1
            self._metrics["total_time_ms"] += response_time_ms

            result = response.json()
            print(
                f"✅ [PatternTrackerSync] Pattern tracked: {pattern_id}",
                file=sys.stderr,
            )
            print(f"   Status: {result.get('status', 'unknown')}", file=sys.stderr)
            print(f"   Response time: {response_time_ms:.1f}ms", file=sys.stderr)
            return pattern_id

        except requests.exceptions.ConnectionError as e:
            print(f"❌ [PatternTrackerSync] Connection failed: {e}", file=sys.stderr)
            print(
                f"   Make sure Intelligence service is running on {self.base_url}",
                file=sys.stderr,
            )
            return None
        except requests.exceptions.Timeout as e:
            print(
                f"❌ [PatternTrackerSync] Timeout after {self.timeout}s: {e}",
                file=sys.stderr,
            )
            return None
        except requests.exceptions.HTTPError as e:
            print(f"❌ [PatternTrackerSync] HTTP error: {e}", file=sys.stderr)
            print(
                f"   Response: {e.response.text if hasattr(e, 'response') else 'N/A'}",
                file=sys.stderr,
            )
            return None
        except Exception as e:
            print(
                f"❌ [PatternTrackerSync] Unexpected error: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            import traceback

            traceback.print_exc(file=sys.stderr)
            return None

    def _generate_pattern_id(self, code: str, context: dict[str, Any]) -> str:
        """Generate deterministic pattern ID with caching.

        Pattern ID is based on file path and first 200 chars of code
        to ensure the same code generates the same ID.
        """
        # Create cache key
        file_path = context.get("file_path", "")
        cache_key = f"{file_path}:{code[:200]}"

        # Check cache
        current_time = time.time()
        if cache_key in self._pattern_id_cache:
            cached_time, pattern_id = self._pattern_id_cache[cache_key]
            if current_time - cached_time < self._cache_ttl:
                self._metrics["cache_hits"] += 1
                return pattern_id

        # Generate new pattern ID
        hash_obj = hashlib.sha256(cache_key.encode())
        pattern_id = hash_obj.hexdigest()[:16]

        # Cache the result
        self._pattern_id_cache[cache_key] = (current_time, pattern_id)
        self._metrics["cache_misses"] += 1

        return pattern_id

    def get_performance_metrics(self) -> dict[str, Any]:
        """Get performance metrics for the sync tracker.

        Returns:
            Dictionary with performance metrics
        """
        total_requests = self._metrics["total_requests"]
        cache_hits = self._metrics["cache_hits"]
        cache_misses = self._metrics["cache_misses"]

        avg_response_time: float = 0.0
        if total_requests > 0:
            avg_response_time = self._metrics["total_time_ms"] / total_requests

        cache_hit_rate: float = 0.0
        total_cache_ops = cache_hits + cache_misses
        if total_cache_ops > 0:
            cache_hit_rate = (cache_hits / total_cache_ops) * 100

        return {
            "total_requests": total_requests,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_hit_rate": cache_hit_rate,
            "average_response_time_ms": avg_response_time,
            "total_time_ms": self._metrics["total_time_ms"],
            "session_id": self.session_id,
            "base_url": self.base_url,
        }

    def print_performance_summary(self) -> None:
        """Print performance summary to stderr."""
        metrics = self.get_performance_metrics()
        print("\n📊 [PatternTrackerSync] Performance Summary:", file=sys.stderr)
        print(f"   Total Requests: {metrics['total_requests']}", file=sys.stderr)
        print(f"   Cache Hit Rate: {metrics['cache_hit_rate']:.1f}%", file=sys.stderr)
        print(
            f"   Avg Response Time: {metrics['average_response_time_ms']:.1f}ms",
            file=sys.stderr,
        )
        print(f"   Cache Size: {len(self._pattern_id_cache)} entries", file=sys.stderr)

    def clear_cache(self) -> None:
        """Clear the pattern ID cache."""
        self._pattern_id_cache.clear()
        print("🧹 [PatternTrackerSync] Cache cleared", file=sys.stderr)

    def calculate_quality_score(self, violations: list[Any]) -> float:
        """Calculate quality score based on violations.

        Args:
            violations: List of violations found

        Returns:
            Quality score from 0.0 to 1.0
        """
        if not violations:
            return 1.0
        # Simple scoring: 1.0 - (violations * 0.1), minimum 0.0
        score = max(0.0, 1.0 - (len(violations) * 0.1))
        return score


def main() -> None:
    """Test the synchronous pattern tracker with performance metrics."""
    print("🧪 Testing PatternTrackerSync...\n", file=sys.stderr)

    # Create tracker
    tracker = PatternTrackerSync()

    # Test code
    test_code = """
def example_function():
    '''Example function for testing.'''
    return "Hello, World!"
"""

    # Test context
    test_context = {
        "event_type": "pattern_created",
        "file_path": "/test/example.py",
        "language": "python",
        "reason": "Test pattern tracking",
        "quality_score": 0.95,
        "violations_found": 1,
    }

    # Performance test - multiple tracking operations
    print("\n📝 Running performance test (10 operations)...", file=sys.stderr)
    start_time = time.time()

    pattern_ids = []
    for i in range(10):
        test_context["file_path"] = f"/test/example_{i}.py"
        pattern_id = tracker.track_pattern_creation(test_code, test_context)
        pattern_ids.append(pattern_id)

    total_time = time.time() - start_time

    # Test cache effectiveness - track same code again
    print("\n📝 Testing cache effectiveness...", file=sys.stderr)
    cache_start = time.time()
    for i in range(5):
        tracker.track_pattern_creation(test_code, test_context)
    cache_time = time.time() - cache_start

    # Print performance summary
    tracker.print_performance_summary()
    print("\n⏱️  Performance Test Results:", file=sys.stderr)
    print(
        f"   10 operations in {total_time:.3f}s ({10 / total_time:.1f} ops/sec)",
        file=sys.stderr,
    )
    print(
        f"   5 cached operations in {cache_time:.3f}s ({5 / cache_time:.1f} ops/sec)",
        file=sys.stderr,
    )

    # Basic functionality test
    print("\n📝 Basic functionality test...", file=sys.stderr)
    pattern_id = tracker.track_pattern_creation(test_code, test_context)

    if pattern_id:
        print(f"\n✅ Test passed! Pattern ID: {pattern_id}", file=sys.stderr)
        print("✅ Performance optimizations working correctly!", file=sys.stderr)
    else:
        print("\n❌ Test failed! Pattern was not tracked", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
