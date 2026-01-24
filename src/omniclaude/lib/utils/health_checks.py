#!/usr/bin/env python3
"""
Enhanced Health Check Infrastructure for Phase 4 Pattern Traceability

Provides comprehensive health checking capabilities with async support:
- Phase 4 API reachability and endpoint testing
- Database connectivity validation
- Service status monitoring with caching
- Graceful degradation when services unavailable
- Comprehensive error handling and logging

Design Philosophy:
- Non-blocking: All health checks are async and timeout-aware
- Fail gracefully: System continues operation even during health check failures
- Observable: Detailed logging for debugging and monitoring
- Configurable: Flexible timeout and retry policies
"""

import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Always import requests for sync methods
import requests

# Use httpx for async requests if available
# This pattern provides graceful degradation when httpx is not installed:
# - When available: exception aliases point to real httpx exception types
# - When unavailable: placeholder exception classes are created that will never
#   be raised by any code, making the except blocks effectively unreachable
#   (which is the desired behavior for graceful degradation)
HAS_HTTPX = False
httpx: Any = None  # Module placeholder for when httpx is unavailable


class _HttpxPlaceholderException(Exception):
    """
    Base class for placeholder exceptions when httpx is not installed.

    These placeholders exist so that except clauses referencing httpx exception
    types don't cause NameError when httpx is unavailable. Since nothing raises
    these placeholder types, the except blocks become unreachable - providing
    graceful degradation without runtime errors.
    """

    pass


# Default to placeholder types - overwritten if httpx import succeeds
HttpxTimeoutException: type[Exception] = type(
    "HttpxTimeoutException", (_HttpxPlaceholderException,), {}
)
HttpxConnectError: type[Exception] = type(
    "HttpxConnectError", (_HttpxPlaceholderException,), {}
)
HttpxRequestError: type[Exception] = type(
    "HttpxRequestError", (_HttpxPlaceholderException,), {}
)

try:
    import httpx as _httpx_module

    # Import succeeded - update module reference and exception aliases
    httpx = _httpx_module
    HAS_HTTPX = True
    # Point to actual httpx exception types for proper exception handling
    HttpxTimeoutException = _httpx_module.TimeoutException
    HttpxConnectError = _httpx_module.ConnectError
    HttpxRequestError = _httpx_module.RequestError
except ImportError:
    # httpx not available - placeholders already set above
    pass  # nosec B110 - Optional dependency, graceful degradation

# Import pattern tracker for configuration
HAS_PATTERN_TRACKER = False
get_tracker: Any = None
try:
    from .pattern_tracker import PatternTrackerConfig, get_tracker

    HAS_PATTERN_TRACKER = True
except ImportError:
    pass  # nosec B110 - Optional dependency, graceful degradation

# Import for type checking only
if TYPE_CHECKING:
    from .pattern_tracker import PatternTrackerConfig

# Import settings for configuration
from omniclaude.config import settings


class HealthStatus(Enum):
    """Health check status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check operation."""

    component: str
    status: HealthStatus
    timestamp: str
    response_time_ms: float | None = None
    error_message: str | None = None
    details: dict[str, Any] | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API serialization."""
        return asdict(self)


class Phase4HealthChecker:
    """
    Enhanced health checker with async support and comprehensive error handling.

    Provides health monitoring for Phase 4 Pattern Traceability system including
    APIs, databases, and supporting services with both sync and async capabilities.
    """

    def __init__(
        self,
        base_url: str | None = None,
        config: "PatternTrackerConfig | None" = None,
    ):
        """
        Initialize Phase 4 health checker.

        Args:
            base_url: Base URL for Phase 4 intelligence service (defaults to settings.intelligence_service_url)
            config: Optional pattern tracker configuration
        """
        self.base_url = base_url or str(settings.intelligence_service_url)
        self.config = config or (get_tracker().config if HAS_PATTERN_TRACKER else None)
        self._health_cache: dict[str, tuple[dict[str, Any], float]] = {}
        self.cache_duration = 30.0  # Cache results for 30 seconds

        # Setup logging
        self.log_file = Path.home() / ".claude" / "hooks" / "logs" / "health-checks.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _log(self, level: str, message: str, **kwargs: Any) -> None:
        """Internal logging method for health check events."""
        timestamp = datetime.now(UTC).isoformat()
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "message": f"[HEALTH] {message}",
            **kwargs,
        }

        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            # Fail silently - don't disrupt health checks
            pass  # nosec B110 - Intentional silent failure for non-critical logging

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached health results are still valid."""
        if cache_key not in self._health_cache:
            return False

        cached_time = self._health_cache[cache_key][1]
        age = time.time() - cached_time
        return age < self.cache_duration

    def _get_cached_result(self, cache_key: str) -> dict[str, Any] | None:
        """Get cached health results if valid."""
        if self._is_cache_valid(cache_key):
            return self._health_cache[cache_key][0]
        return None

    def _cache_result(self, cache_key: str, result: dict[str, Any]) -> None:
        """Cache health results."""
        self._health_cache[cache_key] = (result, time.time())

    async def check_intelligence_service_async(self) -> HealthCheckResult:
        """
        Async version of intelligence service health check.

        Returns:
            HealthCheckResult with detailed status information
        """
        start_time = time.time()
        timestamp = datetime.now(UTC).isoformat()
        cache_key = "intelligence_service"

        # Check cache first
        cached_result = self._get_cached_result(cache_key)
        if cached_result:
            self._log("DEBUG", "Using cached intelligence service health result")
            return HealthCheckResult(**cached_result)

        try:
            if not HAS_HTTPX:
                raise ImportError("httpx not available for async health checks")

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health")
                response_time_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    try:
                        response_data = response.json()
                        details = {
                            "status_code": response.status_code,
                            "response_size": len(response.content),
                            "response_data": response_data,
                        }
                        suggestion = None
                        status = HealthStatus.HEALTHY
                    except json.JSONDecodeError:
                        details = {
                            "status_code": response.status_code,
                            "response_size": len(response.content),
                            "warning": "Non-JSON response",
                        }
                        suggestion = "Endpoint returned non-JSON response"
                        status = HealthStatus.DEGRADED
                else:
                    details = {
                        "status_code": response.status_code,
                        "response_size": len(response.content),
                        "error_type": "http_error",
                    }
                    suggestion = f"HTTP {response.status_code} - check service status"
                    status = HealthStatus.UNHEALTHY

                result = HealthCheckResult(
                    component="intelligence_service",
                    status=status,
                    timestamp=timestamp,
                    response_time_ms=response_time_ms,
                    details=details,
                    suggestion=suggestion,
                )

                self._cache_result(cache_key, result.to_dict())
                return result

        except HttpxTimeoutException:
            response_time_ms = (time.time() - start_time) * 1000
            result = HealthCheckResult(
                component="intelligence_service",
                status=HealthStatus.UNHEALTHY,
                timestamp=timestamp,
                response_time_ms=response_time_ms,
                error_message="Timeout after 5.0s",
                suggestion="Service may be overloaded or unreachable",
            )
            self._cache_result(cache_key, result.to_dict())
            return result

        except HttpxConnectError:
            response_time_ms = (time.time() - start_time) * 1000
            result = HealthCheckResult(
                component="intelligence_service",
                status=HealthStatus.UNHEALTHY,
                timestamp=timestamp,
                response_time_ms=response_time_ms,
                error_message="Connection failed",
                suggestion="Check if Phase 4 service is running",
            )
            self._cache_result(cache_key, result.to_dict())
            return result

        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            result = HealthCheckResult(
                component="intelligence_service",
                status=HealthStatus.UNHEALTHY,
                timestamp=timestamp,
                response_time_ms=response_time_ms,
                error_message=str(e),
                suggestion="Unexpected error during health check",
            )
            self._cache_result(cache_key, result.to_dict())
            return result

    def check_intelligence_service(self) -> dict[str, Any]:
        """Check if Phase 4 intelligence service is reachable"""
        start_time = time.time()
        try:
            response = requests.get(f"{self.base_url}/health", timeout=2)
            response_time_ms = (time.time() - start_time) * 1000

            result = {
                "status": "healthy" if response.status_code == 200 else "unhealthy",
                "response_time_ms": round(response_time_ms, 2),
                "status_code": response.status_code,
            }

            # Parse response if JSON
            try:
                if response.headers.get("content-type", "").startswith("application/json"):
                    result["details"] = response.json()
                else:
                    result["details"] = response.text[:500]  # Limit text length
            except Exception:
                result["details"] = "Could not parse response"

            return result

        except requests.exceptions.Timeout:
            return {
                "status": "timeout",
                "error": "Request timed out after 2 seconds",
                "response_time_ms": 2000,
            }
        except requests.exceptions.ConnectionError:
            return {
                "status": "connection_error",
                "error": f"Cannot connect to {self.base_url}",
                "response_time_ms": (time.time() - start_time) * 1000,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "response_time_ms": (time.time() - start_time) * 1000,
            }

    def check_database_connectivity(self) -> dict[str, Any]:
        """Check if we can reach the database through Phase 4 API"""
        start_time = time.time()
        try:
            response = requests.get(f"{self.base_url}/api/pattern-traceability/health", timeout=5)
            response_time_ms = (time.time() - start_time) * 1000

            if response.status_code == 200:
                try:
                    details = response.json()
                    return {
                        "status": "connected",
                        "response_time_ms": round(response_time_ms, 2),
                        "details": details,
                    }
                except Exception:
                    return {
                        "status": "connected",
                        "response_time_ms": round(response_time_ms, 2),
                        "details": "Connected but response parsing failed",
                    }
            else:
                return {
                    "status": "error",
                    "response_time_ms": round(response_time_ms, 2),
                    "status_code": response.status_code,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}",
                }

        except requests.exceptions.Timeout:
            return {
                "status": "timeout",
                "error": "Database health check timed out after 5 seconds",
                "response_time_ms": 5000,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "response_time_ms": (time.time() - start_time) * 1000,
            }

    def check_lineage_endpoint(self) -> dict[str, Any]:
        """Test pattern lineage tracking endpoint"""
        start_time = time.time()
        try:
            test_payload = {
                "event_type": "test_health_check",
                "pattern_id": "health_test_123",
                "pattern_name": "Health Check Test",
                "pattern_type": "test",
                "pattern_data": {"test": True, "timestamp": time.time()},
                "triggered_by": "health_check",
                "user_id": "health_check_user",
            }

            response = requests.post(
                f"{self.base_url}/api/pattern-traceability/lineage/track",
                json=test_payload,
                timeout=3,
            )

            response_time_ms = (time.time() - start_time) * 1000

            if response.status_code in [200, 201]:
                try:
                    response_data = response.json()
                    return {
                        "status": "working",
                        "response_time_ms": round(response_time_ms, 2),
                        "response_code": response.status_code,
                        "details": response_data,
                    }
                except Exception:
                    return {
                        "status": "working",
                        "response_time_ms": round(response_time_ms, 2),
                        "response_code": response.status_code,
                        "details": "Endpoint responded but response parsing failed",
                    }
            else:
                return {
                    "status": "error",
                    "response_time_ms": round(response_time_ms, 2),
                    "response_code": response.status_code,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}",
                }

        except requests.exceptions.Timeout:
            return {
                "status": "timeout",
                "error": "Lineage endpoint test timed out after 3 seconds",
                "response_time_ms": 3000,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "response_time_ms": (time.time() - start_time) * 1000,
            }

    def check_feedback_endpoint(self) -> dict[str, Any]:
        """Test pattern feedback endpoint"""
        start_time = time.time()
        try:
            test_payload = {
                "pattern_id": "health_test_feedback_123",
                "feedback_type": "test",
                "feedback_data": {"test": True, "rating": 5},
                "user_id": "health_check_user",
                "context": {"test": True},
            }

            response = requests.post(
                f"{self.base_url}/api/pattern-traceability/feedback/submit",
                json=test_payload,
                timeout=3,
            )

            response_time_ms = (time.time() - start_time) * 1000

            if response.status_code in [200, 201]:
                return {
                    "status": "working",
                    "response_time_ms": round(response_time_ms, 2),
                    "response_code": response.status_code,
                }
            else:
                return {
                    "status": "error",
                    "response_time_ms": round(response_time_ms, 2),
                    "response_code": response.status_code,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}",
                }

        except requests.exceptions.Timeout:
            return {
                "status": "timeout",
                "error": "Feedback endpoint test timed out after 3 seconds",
                "response_time_ms": 3000,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "response_time_ms": (time.time() - start_time) * 1000,
            }

    def run_comprehensive_health_check(self) -> dict[str, Any]:
        """Run all health checks and return comprehensive status"""
        print("🔍 Running comprehensive Phase 4 health check...", file=sys.stderr)

        checks: dict[str, dict[str, Any]] = {}

        # Run all checks
        checks["intelligence_service"] = self.check_intelligence_service()
        checks["database_connectivity"] = self.check_database_connectivity()
        checks["lineage_endpoint"] = self.check_lineage_endpoint()
        checks["feedback_endpoint"] = self.check_feedback_endpoint()

        # Calculate overall status
        overall_status = "healthy"
        failed_checks: list[str] = []

        for check_name, check_result in checks.items():
            status = check_result.get("status", "error")
            if status in ["error", "timeout", "connection_error", "unhealthy"]:
                overall_status = "unhealthy"
                failed_checks.append(check_name)
            elif status != "working" and status != "connected" and status != "healthy":
                overall_status = "degraded"
                failed_checks.append(check_name)

        summary = {
            "total_checks": len(checks),
            "passed_checks": len(checks) - len(failed_checks),
            "failed_checks": len(failed_checks),
        }

        results: dict[str, Any] = {
            "timestamp": time.time(),
            "checks": checks,
            "overall_status": overall_status,
            "failed_checks": failed_checks,
            "summary": summary,
        }

        # Print summary
        status_emoji = (
            "✅" if overall_status == "healthy" else ("⚠️" if overall_status == "degraded" else "❌")
        )
        print(
            f"{status_emoji} Overall Phase 4 Status: {overall_status.upper()}",
            file=sys.stderr,
        )
        print(
            f"📊 Passed: {summary['passed_checks']}/{summary['total_checks']} checks",
            file=sys.stderr,
        )

        if failed_checks:
            print(f"❌ Failed checks: {', '.join(failed_checks)}", file=sys.stderr)

        return results


def main() -> None:
    """Run health check when script is executed directly"""
    checker = Phase4HealthChecker()
    results = checker.run_comprehensive_health_check()

    # Output JSON for programmatic use
    print(json.dumps(results, indent=2))

    # Exit with appropriate code
    sys.exit(0 if results["overall_status"] == "healthy" else 1)


if __name__ == "__main__":
    main()
