#!/usr/bin/env python3
"""
Pattern Tracker - Core infrastructure for Phase 4 Pattern Traceability

This module provides the foundational pattern tracking infrastructure that bridges
Claude Code hooks with Phase 4 Pattern Traceability APIs (port 8053).

Core Responsibilities:
- Pattern ID generation (SHA256-based, deterministic)
- Event tracking methods (creation, execution, modification)
- Session/correlation ID management
- Configuration management (YAML + env var overrides)
- Error handling with graceful degradation

Design Philosophy:
- Non-blocking: All API calls are async to prevent workflow disruption
- Fail gracefully: Continue execution even when Phase 4 unavailable
- Deterministic: Same code always generates same pattern ID
- Observable: Comprehensive logging for debugging and monitoring
"""

import asyncio
import hashlib
import httpx
import json
import os
import sys
import uuid
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

# Add resilience imports (if available via environment variable or in path)
resilience_lib_path = os.getenv("ARCHON_HOOKS_LIB_PATH")
if resilience_lib_path and Path(resilience_lib_path).exists():
    sys.path.insert(0, resilience_lib_path)

try:
    from error_handling import CircuitBreaker, resilient_operation
    from resilience import ResilientAPIClient, PatternCache
    from debug_utils import ServiceMonitor
    RESILIENCE_AVAILABLE = True
except ImportError:
    RESILIENCE_AVAILABLE = False
    # Create fallback CircuitBreaker if import fails
    class CircuitBreaker:
        def __init__(self, *args, **kwargs):
            pass
        def __call__(self, func):
            return func
    def resilient_operation(func):
        return func
    class PatternCache:
        def __init__(self, *args, **kwargs):
            pass
        async def cache_pattern_event(self, event):
            return ""
        async def sync_cached_events(self, api_client):
            return {"synced": 0, "failed": 0}
    class ServiceMonitor:
        def __init__(self, *args, **kwargs):
            pass


class PatternEventType(Enum):
    """Types of pattern events tracked by the system."""
    CREATION = "creation"
    EXECUTION = "execution"
    MODIFICATION = "modification"
    DERIVATION = "derivation"
    FEEDBACK = "feedback"


@dataclass
class PatternCreationEvent:
    """
    Event data for pattern creation tracking.

    Captures when Claude generates new code patterns during tool use.
    """
    pattern_id: str
    code: str
    context: Dict[str, Any]
    session_id: str
    correlation_id: str
    timestamp: str
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for API serialization."""
        return asdict(self)


@dataclass
class PatternExecutionEvent:
    """
    Event data for pattern execution tracking.

    Captures runtime execution metrics and outcomes.
    """
    pattern_id: str
    session_id: str
    correlation_id: str
    timestamp: str
    metrics: Dict[str, Any]
    success: bool
    error_message: Optional[str] = None
    execution_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for API serialization."""
        return asdict(self)


@dataclass
class PatternModificationEvent:
    """
    Event data for pattern modification tracking.

    Captures when patterns are modified, creating derivation lineage.
    """
    pattern_id: str
    parent_pattern_id: str
    session_id: str
    correlation_id: str
    timestamp: str
    modification_type: str
    changes: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for API serialization."""
        return asdict(self)


class PatternTrackerConfig:
    """
    Configuration management for PatternTracker.

    Supports hierarchical configuration with precedence:
    1. Environment variables (highest priority)
    2. config.yaml values
    3. Default values (fallback)
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize configuration.

        Args:
            config_path: Path to config.yaml (defaults to ~/.claude/hooks/config.yaml)
        """
        self.config_path = config_path or Path.home() / ".claude" / "hooks" / "config.yaml"
        self._config = self._load_config()

    def _load_config(self) -> Dict:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            return {}

        try:
            with open(self.config_path) as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            # Graceful degradation - use defaults
            print(f"Warning: Could not load {self.config_path}: {e}")
            return {}

    def get(self, key: str, yaml_path: List[str], default: Any) -> Any:
        """
        Get configuration value with environment variable override.

        Args:
            key: Environment variable name
            yaml_path: Path through YAML structure (e.g., ['pattern_tracking', 'enabled'])
            default: Default value if not found

        Returns:
            Configuration value with precedence: env var > YAML > default
        """
        # Environment variable takes precedence
        env_value = os.getenv(key)
        if env_value is not None:
            # Handle boolean conversion
            if isinstance(default, bool):
                return env_value.lower() in ('true', '1', 'yes')
            # Handle numeric conversion
            if isinstance(default, (int, float)):
                try:
                    return type(default)(env_value)
                except ValueError:
                    pass
            return env_value

        # Check YAML config
        value = self._config
        for path_key in yaml_path:
            if isinstance(value, dict) and path_key in value:
                value = value[path_key]
            else:
                return default

        return value if value is not None else default

    @property
    def intelligence_url(self) -> str:
        """Get Intelligence Service base URL."""
        return self.get(
            "INTELLIGENCE_SERVICE_URL",
            ["pattern_tracking", "intelligence_url"],
            "http://localhost:8053"
        )

    @property
    def enabled(self) -> bool:
        """Check if pattern tracking is enabled."""
        return self.get(
            "PATTERN_TRACKING_ENABLED",
            ["pattern_tracking", "enabled"],
            True
        )

    @property
    def timeout_seconds(self) -> float:
        """Get API call timeout in seconds."""
        return self.get(
            "PATTERN_TRACKING_TIMEOUT",
            ["pattern_tracking", "timeout_seconds"],
            2.0
        )

    @property
    def max_retries(self) -> int:
        """Get maximum retry attempts for failed API calls."""
        return self.get(
            "PATTERN_TRACKING_MAX_RETRIES",
            ["pattern_tracking", "max_retries"],
            3
        )

    @property
    def log_file(self) -> Path:
        """Get log file path."""
        log_path = self.get(
            "PATTERN_TRACKING_LOG",
            ["pattern_tracking", "log_file"],
            "~/.claude/hooks/logs/pattern-tracker.log"
        )
        return Path(log_path).expanduser()


class PatternTracker:
    """
    Core pattern tracking infrastructure.

    Provides methods for tracking pattern lifecycle events and managing
    correlation with Phase 4 Pattern Traceability APIs.

    Features:
    - Deterministic pattern ID generation (SHA256-based)
    - Session and correlation tracking
    - Async API communication (non-blocking)
    - Graceful degradation when services unavailable
    - Comprehensive logging and error handling

    Usage:
        tracker = PatternTracker()
        pattern_id = await tracker.track_pattern_creation(
            code="def example(): pass",
            context={"tool": "Write", "file": "example.py"}
        )
    """

    # Phase 4 API endpoints
    ENDPOINTS = {
        "track_lineage": "/api/pattern-traceability/lineage/track",
        "compute_analytics": "/api/pattern-traceability/analytics/compute",
        "record_feedback": "/api/pattern-traceability/feedback/record",
        "query_lineage": "/api/pattern-traceability/lineage/query",
        "get_analytics": "/api/pattern-traceability/analytics/get",
    }

    def __init__(self, config: Optional[PatternTrackerConfig] = None):
        """
        Initialize PatternTracker.

        Args:
            config: Configuration object (creates default if None)
        """
        self.config = config or PatternTrackerConfig()
        self.session_id = self._generate_session_id()
        self._setup_logging()

        # Initialize circuit breaker for API resilience
        if RESILIENCE_AVAILABLE:
            self.circuit_breaker = CircuitBreaker(
                failure_threshold=5,  # Open after 5 failures
                recovery_timeout=60,  # Try recovery after 60 seconds
                expected_exception=(httpx.RequestError, httpx.HTTPStatusError, Exception)
            )
            self._log("INFO", "Circuit breaker initialized for API resilience")

            # Initialize offline cache
            self.pattern_cache = PatternCache()
            self._log("INFO", "Offline cache initialized for pattern events")

            # Initialize service monitor for error tracking
            self.service_monitor = ServiceMonitor(base_url=self.config.intelligence_url)
            self.error_metrics = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "cached_events": 0,
                "circuit_breaker_trips": 0,
                "retry_attempts": 0
            }
            self._log("INFO", "Service monitor initialized for error tracking")
        else:
            self.circuit_breaker = None
            self.pattern_cache = None
            self.service_monitor = None
            self.error_metrics = {}
            self._log("WARNING", "Resilience features unavailable - using basic error handling")

    def _generate_session_id(self) -> str:
        """
        Generate unique session identifier.

        Returns:
            UUID v4 string for this tracking session
        """
        return str(uuid.uuid4())

    def _setup_logging(self):
        """Setup logging infrastructure."""
        # Ensure log directory exists
        log_file = self.config.log_file
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Note: Actual logging implementation can be added by integration agents
        # For now, we provide the infrastructure
        self.log_file = log_file

    def _log(self, level: str, message: str, **kwargs):
        """
        Internal logging method.

        Args:
            level: Log level (INFO, WARNING, ERROR, DEBUG)
            message: Log message
            **kwargs: Additional context to include in log
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "session_id": self.session_id,
            "message": message,
            **kwargs
        }

        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            # Fail silently - don't disrupt workflow
            print(f"Warning: Could not write to log file: {e}")

    def generate_pattern_id(self, code: str, context: Optional[Dict] = None) -> str:
        """
        Generate deterministic pattern ID from code content.

        Uses SHA256 hash of code to ensure:
        - Same code always produces same pattern ID
        - Different code produces different pattern IDs
        - Pattern IDs are globally unique

        Args:
            code: Source code to generate ID for
            context: Optional context for additional uniqueness (not currently used)

        Returns:
            16-character hexadecimal pattern ID

        Example:
            >>> tracker = PatternTracker()
            >>> pattern_id = tracker.generate_pattern_id("def example(): pass")
            >>> len(pattern_id)
            16
        """
        # Normalize code (strip whitespace for consistency)
        normalized_code = code.strip()

        # Generate SHA256 hash
        code_hash = hashlib.sha256(normalized_code.encode('utf-8')).hexdigest()

        # Use first 16 characters for pattern ID
        pattern_id = code_hash[:16]

        self._log("DEBUG", "Generated pattern ID", pattern_id=pattern_id, code_length=len(code))

        return pattern_id

    def generate_correlation_id(self) -> str:
        """
        Generate correlation ID for tracking related events.

        Returns:
            UUID v4 string for event correlation
        """
        return str(uuid.uuid4())

    async def track_pattern_creation(
        self,
        code: str,
        context: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None
    ) -> str:
        """
        Track pattern creation event.

        Called when Claude generates new code through tool use (Write, Edit, etc.).
        Sends event to Phase 4 lineage tracking API.

        Args:
            code: Generated code content
            context: Execution context (tool name, file path, etc.)
            metadata: Additional metadata to attach
            correlation_id: Optional correlation ID (generates if None)

        Returns:
            Pattern ID for the created pattern

        Example:
            pattern_id = await tracker.track_pattern_creation(
                code='def hello(): print("world")',
                context={"tool": "Write", "file": "hello.py"},
                metadata={"author": "claude-code"}
            )
        """
        if not self.config.enabled:
            self._log("DEBUG", "Pattern tracking disabled, skipping creation event")
            return self.generate_pattern_id(code)

        # Generate identifiers
        pattern_id = self.generate_pattern_id(code, context)
        correlation_id = correlation_id or self.generate_correlation_id()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Create event
        event = PatternCreationEvent(
            pattern_id=pattern_id,
            code=code,
            context=context,
            session_id=self.session_id,
            correlation_id=correlation_id,
            timestamp=timestamp,
            metadata=metadata
        )

        self._log(
            "INFO",
            "Tracking pattern creation",
            pattern_id=pattern_id,
            correlation_id=correlation_id,
            context=context
        )

        # Transform to LineageTrackRequest format for Phase 4 API
        payload = {
            "event_type": "pattern_created",
            "pattern_id": pattern_id,
            "pattern_type": "code",
            "pattern_version": "1.0.0",
            "tool_name": context.get("tool", "Write"),
            "file_path": context.get("file_path"),
            "language": context.get("language", "python"),
            "pattern_data": {
                "code": code,
                "session_id": self.session_id,
                "correlation_id": correlation_id,
                "timestamp": timestamp,
                "context": context,
                "metadata": metadata or {}
            },
            "triggered_by": "claude-code",
            "reason": context.get("reason", f"Code generated by {context.get('tool', 'Write')} tool")
        }

        # Send to Phase 4 API
        await self._send_to_api("track_lineage", payload)

        return pattern_id

    def track_pattern_creation_sync(
        self,
        code: str,
        context: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None
    ) -> str:
        """
        Synchronous wrapper for track_pattern_creation.

        Used by PostToolUse hooks which need sync methods.

        Args:
            code: Generated code content
            context: Execution context (tool name, file path, etc.)
            metadata: Additional metadata to attach
            correlation_id: Optional correlation ID (generates if None)

        Returns:
            Pattern ID for the created pattern
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self.track_pattern_creation(code=code, context=context,
                                      metadata=metadata, correlation_id=correlation_id)
        )

    async def track_pattern_execution(
        self,
        pattern_id: str,
        metrics: Dict[str, Any],
        success: bool = True,
        error_message: Optional[str] = None,
        execution_context: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None
    ) -> None:
        """
        Track pattern execution event.

        Called after pattern execution to record metrics and outcomes.
        Sends event to Phase 4 analytics computation API.

        Args:
            pattern_id: ID of executed pattern
            metrics: Execution metrics (response_time, memory_usage, etc.)
            success: Whether execution succeeded
            error_message: Error message if execution failed
            execution_context: Additional execution context
            correlation_id: Optional correlation ID

        Example:
            await tracker.track_pattern_execution(
                pattern_id="a1b2c3d4e5f6g7h8",
                metrics={"duration_ms": 42, "memory_mb": 1.5},
                success=True
            )
        """
        if not self.config.enabled:
            self._log("DEBUG", "Pattern tracking disabled, skipping execution event")
            return

        correlation_id = correlation_id or self.generate_correlation_id()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Create event
        event = PatternExecutionEvent(
            pattern_id=pattern_id,
            session_id=self.session_id,
            correlation_id=correlation_id,
            timestamp=timestamp,
            metrics=metrics,
            success=success,
            error_message=error_message,
            execution_context=execution_context
        )

        self._log(
            "INFO",
            "Tracking pattern execution",
            pattern_id=pattern_id,
            correlation_id=correlation_id,
            success=success,
            metrics=metrics
        )

        # Send to Phase 4 API
        await self._send_to_api("compute_analytics", event.to_dict())

    async def track_pattern_modification(
        self,
        pattern_id: str,
        parent_pattern_id: str,
        modification_type: str,
        changes: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None
    ) -> str:
        """
        Track pattern modification event.

        Called when patterns are modified, creating derivation lineage.
        Tracks parent-child relationships for pattern evolution.

        Args:
            pattern_id: ID of modified (child) pattern
            parent_pattern_id: ID of original (parent) pattern
            modification_type: Type of modification (refactor, optimize, fix, etc.)
            changes: Description of changes made
            metadata: Additional metadata
            correlation_id: Optional correlation ID

        Returns:
            Pattern ID of the modified pattern

        Example:
            new_pattern_id = await tracker.track_pattern_modification(
                pattern_id="new_pattern_id",
                parent_pattern_id="original_pattern_id",
                modification_type="optimization",
                changes={"optimized": "replaced loop with list comprehension"}
            )
        """
        if not self.config.enabled:
            self._log("DEBUG", "Pattern tracking disabled, skipping modification event")
            return pattern_id

        correlation_id = correlation_id or self.generate_correlation_id()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Create event
        event = PatternModificationEvent(
            pattern_id=pattern_id,
            parent_pattern_id=parent_pattern_id,
            session_id=self.session_id,
            correlation_id=correlation_id,
            timestamp=timestamp,
            modification_type=modification_type,
            changes=changes,
            metadata=metadata
        )

        self._log(
            "INFO",
            "Tracking pattern modification",
            pattern_id=pattern_id,
            parent_pattern_id=parent_pattern_id,
            correlation_id=correlation_id,
            modification_type=modification_type
        )

        # Send to Phase 4 API
        await self._send_to_api("track_lineage", event.to_dict())

        return pattern_id

    async def _make_http_request(self, endpoint_key: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make HTTP request to Phase 4 API - protected by circuit breaker.

        Args:
            endpoint_key: Key in ENDPOINTS dict
            data: Data to send

        Returns:
            API response dict

        Raises:
            httpx.RequestError: For network/connection errors
            httpx.HTTPStatusError: For HTTP error responses
        """
        url = f"{self.config.intelligence_url}{self.ENDPOINTS[endpoint_key]}"

        self._log(
            "INFO",
            "Making HTTP request with circuit breaker protection",
            endpoint=endpoint_key,
            url=url
        )

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post(url, json=data)

            # Log the response
            self._log(
                "INFO",
                "HTTP request completed",
                endpoint=endpoint_key,
                status_code=response.status_code
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code in [404, 400]:
                # Don't retry for client errors
                self._log(
                    "ERROR",
                    "API call failed with client error (no retry)",
                    endpoint=endpoint_key,
                    status_code=response.status_code,
                    response_text=response.text[:200]
                )
                raise httpx.HTTPStatusError(
                    f"Client error {response.status_code}",
                    request=response.request,
                    response=response
                )
            else:
                # Retry for server errors
                response.raise_for_status()

    @resilient_operation
    async def _send_to_api(
        self,
        endpoint_key: str,
        data: Dict[str, Any],
        retry_count: int = 0
    ) -> Optional[Dict]:
        """
        Send data to Phase 4 API with enhanced resilience.

        Features:
        - Circuit breaker pattern for fault tolerance
        - Exponential backoff with jitter for retries
        - Comprehensive error classification
        - Graceful degradation when API unavailable
        - Error tracking and metrics collection

        Args:
            endpoint_key: Key in ENDPOINTS dict
            data: Data to send
            retry_count: Current retry attempt

        Returns:
            API response dict or None on failure
        """
        # Track request metrics
        if RESILIENCE_AVAILABLE:
            self.error_metrics["total_requests"] += 1

        if retry_count >= self.config.max_retries:
            self._log(
                "ERROR",
                "Max retries exceeded - giving up",
                endpoint=endpoint_key,
                retry_count=retry_count
            )
            if RESILIENCE_AVAILABLE:
                self.error_metrics["failed_requests"] += 1
            return None

        try:
            if self.circuit_breaker and RESILIENCE_AVAILABLE:
                # Use circuit breaker for protection
                result = await self.circuit_breaker(self._make_http_request)(endpoint_key, data)
                self._log(
                    "INFO",
                    "API call successful with circuit breaker protection",
                    endpoint=endpoint_key
                )
                if RESILIENCE_AVAILABLE:
                    self.error_metrics["successful_requests"] += 1
                return result
            else:
                # Fallback to direct HTTP request
                result = await self._make_http_request(endpoint_key, data)
                self._log(
                    "INFO",
                    "API call successful (fallback mode)",
                    endpoint=endpoint_key
                )
                if RESILIENCE_AVAILABLE:
                    self.error_metrics["successful_requests"] += 1
                return result

        except httpx.TimeoutException as e:
            self._log(
                "WARNING",
                "API call timed out",
                endpoint=endpoint_key,
                error=str(e),
                retry_count=retry_count
            )
            if RESILIENCE_AVAILABLE:
                self.error_metrics["retry_attempts"] += 1
        except httpx.NetworkError as e:
            self._log(
                "WARNING",
                "API call failed with network error",
                endpoint=endpoint_key,
                error=str(e),
                retry_count=retry_count
            )
            if RESILIENCE_AVAILABLE:
                self.error_metrics["retry_attempts"] += 1
        except httpx.HTTPStatusError as e:
            self._log(
                "WARNING",
                "API call failed with HTTP error",
                endpoint=endpoint_key,
                error=str(e),
                retry_count=retry_count
            )
            if RESILIENCE_AVAILABLE:
                self.error_metrics["retry_attempts"] += 1
        except Exception as e:
            self._log(
                "ERROR",
                "API call failed with unexpected error",
                endpoint=endpoint_key,
                error=str(e),
                retry_count=retry_count
            )
            if RESILIENCE_AVAILABLE:
                self.error_metrics["retry_attempts"] += 1

        # Exponential backoff with jitter before retry
        if retry_count < self.config.max_retries:
            import random
            base_delay = 2 ** retry_count
            jitter = random.uniform(0.1, 0.5)  # Add jitter to avoid thundering herd
            delay = base_delay + jitter
            self._log(
                "INFO",
                f"Retrying after {delay:.2f}s delay",
                endpoint=endpoint_key,
                retry_count=retry_count + 1
            )
            if RESILIENCE_AVAILABLE:
                self.error_metrics["retry_attempts"] += 1
            await asyncio.sleep(delay)
            return await self._send_to_api(endpoint_key, data, retry_count + 1)

        # All retries exhausted - try offline caching if available
        if self.pattern_cache and RESILIENCE_AVAILABLE and endpoint_key == "track_lineage":
            try:
                event_id = await self.pattern_cache.cache_pattern_event(data)
                if event_id:
                    self._log(
                        "INFO",
                        "Event cached locally due to API unavailability",
                        endpoint=endpoint_key,
                        cached_event_id=event_id
                    )
                    self.error_metrics["cached_events"] += 1
                    return {"cached": True, "event_id": event_id}
                else:
                    self._log(
                        "WARNING",
                        "Failed to cache event locally",
                        endpoint=endpoint_key
                    )
            except Exception as e:
                self._log(
                    "ERROR",
                    "Offline caching failed",
                    endpoint=endpoint_key,
                    error=str(e)
                )

        if RESILIENCE_AVAILABLE:
            self.error_metrics["failed_requests"] += 1
        return None

    async def sync_cached_events(self) -> Dict[str, Any]:
        """
        Sync cached pattern events when API becomes available.

        Returns:
            Dict with sync statistics
        """
        if not self.pattern_cache or not RESILIENCE_AVAILABLE:
            self._log("WARNING", "Offline cache unavailable - cannot sync")
            return {"synced": 0, "failed": 0}

        try:
            self._log("INFO", "Starting sync of cached pattern events")
            stats = await self.pattern_cache.sync_cached_events(self)

            self._log(
                "INFO",
                "Completed sync of cached events",
                synced=stats.get("synced", 0),
                failed=stats.get("failed", 0),
                remaining=stats.get("remaining", 0)
            )

            return stats

        except Exception as e:
            self._log(
                "ERROR",
                "Failed to sync cached events",
                error=str(e)
            )
            return {"synced": 0, "failed": 0}

    async def get_cache_status(self) -> Dict[str, Any]:
        """
        Get status of offline cache.

        Returns:
            Dict with cache status information
        """
        if not self.pattern_cache or not RESILIENCE_AVAILABLE:
            return {"available": False, "cached_count": 0}

        try:
            # Count cached events
            cached_files = list(self.pattern_cache.cache_dir.glob("pending_*.json"))
            cached_count = len(cached_files)

            return {
                "available": True,
                "cached_count": cached_count,
                "cache_dir": str(self.pattern_cache.cache_dir),
                "metadata": getattr(self.pattern_cache, '_metadata', {})
            }

        except Exception as e:
            self._log(
                "ERROR",
                "Failed to get cache status",
                error=str(e)
            )
            return {"available": False, "cached_count": 0}

    def get_error_metrics(self) -> Dict[str, Any]:
        """
        Get comprehensive error metrics and monitoring data.

        Returns:
            Dict with error metrics, performance data, and health status
        """
        if not RESILIENCE_AVAILABLE:
            return {"available": False, "message": "Error monitoring not available"}

        # Calculate derived metrics
        total_requests = self.error_metrics.get("total_requests", 0)
        successful_requests = self.error_metrics.get("successful_requests", 0)
        failed_requests = self.error_metrics.get("failed_requests", 0)
        retry_attempts = self.error_metrics.get("retry_attempts", 0)
        cached_events = self.error_metrics.get("cached_events", 0)

        success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
        failure_rate = (failed_requests / total_requests * 100) if total_requests > 0 else 0
        retry_rate = (retry_attempts / total_requests * 100) if total_requests > 0 else 0

        # Determine health status
        health_status = "healthy"
        alerts = []

        if failure_rate > 20:  # More than 20% failure rate
            health_status = "critical"
            alerts.append({
                "type": "high_failure_rate",
                "message": f"High failure rate: {failure_rate:.1f}%",
                "severity": "critical"
            })
        elif failure_rate > 10:  # More than 10% failure rate
            health_status = "warning"
            alerts.append({
                "type": "elevated_failure_rate",
                "message": f"Elevated failure rate: {failure_rate:.1f}%",
                "severity": "warning"
            })

        if retry_rate > 30:  # More than 30% of requests are retries
            health_status = "warning" if health_status == "healthy" else "critical"
            alerts.append({
                "type": "high_retry_rate",
                "message": f"High retry rate: {retry_rate:.1f}%",
                "severity": "warning"
            })

        if cached_events > 10:  # Many cached events might indicate API issues
            alerts.append({
                "type": "cached_events_accumulating",
                "message": f"{cached_events} events cached (API may be unavailable)",
                "severity": "info"
            })

        # Get service status if monitor available
        service_status = {}
        if self.service_monitor:
            try:
                service_status = {
                    "api_reachable": getattr(self.service_monitor, 'api_reachable', False),
                    "last_check": getattr(self.service_monitor, 'last_check_time', None),
                    "uptime_percent": getattr(self.service_monitor, 'uptime_percent', 0)
                }
            except Exception:
                service_status = {"error": "Service monitor status unavailable"}

        return {
            "available": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "health_status": health_status,
            "raw_metrics": self.error_metrics.copy(),
            "calculated_metrics": {
                "success_rate": round(success_rate, 2),
                "failure_rate": round(failure_rate, 2),
                "retry_rate": round(retry_rate, 2),
                "total_requests": total_requests
            },
            "service_status": service_status,
            "alerts": alerts,
            "recommendations": self._generate_recommendations(failure_rate, retry_rate, cached_events)
        }

    def _generate_recommendations(self, failure_rate: float, retry_rate: float, cached_events: int) -> List[str]:
        """Generate operational recommendations based on metrics."""
        recommendations = []

        if failure_rate > 20:
            recommendations.append("Critical: Check Phase 4 API service availability and connectivity")
            recommendations.append("Consider enabling graceful degradation mode")
        elif failure_rate > 10:
            recommendations.append("Warning: Monitor API performance and consider scaling")

        if retry_rate > 30:
            recommendations.append("High retry rate detected - check network stability and API response times")

        if cached_events > 10:
            recommendations.append("Multiple events cached - API may be unavailable")
            recommendations.append("Consider manually syncing cached events when API is available")

        if not recommendations:
            recommendations.append("System operating normally")

        return recommendations

    async def start_monitoring(self, interval_seconds: int = 30) -> bool:
        """
        Start real-time monitoring and alerting.

        Args:
            interval_seconds: Monitoring check interval

        Returns:
            True if monitoring started successfully
        """
        if not self.service_monitor or not RESILIENCE_AVAILABLE:
            self._log("WARNING", "Service monitor unavailable - cannot start monitoring")
            return False

        try:
            await self.service_monitor.start_monitoring()
            self._log("INFO", f"Started real-time monitoring with {interval_seconds}s interval")
            return True
        except Exception as e:
            self._log("ERROR", f"Failed to start monitoring: {e}")
            return False

    async def stop_monitoring(self) -> bool:
        """
        Stop real-time monitoring.

        Returns:
            True if monitoring stopped successfully
        """
        if not self.service_monitor or not RESILIENCE_AVAILABLE:
            return False

        try:
            await self.service_monitor.stop_monitoring()
            self._log("INFO", "Stopped real-time monitoring")
            return True
        except Exception as e:
            self._log("ERROR", f"Failed to stop monitoring: {e}")
            return False

    def get_health_summary(self) -> Dict[str, Any]:
        """
        Get a comprehensive health summary for operational dashboards.

        Returns:
            Health summary with status, metrics, and actionable insights
        """
        error_metrics = self.get_error_metrics()
        cache_status = self.get_cache_status()

        # Overall system health assessment
        if error_metrics.get("health_status") == "critical":
            overall_health = "critical"
            health_message = "System experiencing critical issues - immediate attention required"
        elif error_metrics.get("health_status") == "warning":
            overall_health = "degraded"
            health_message = "System performance degraded - monitoring recommended"
        else:
            overall_health = "healthy"
            health_message = "System operating normally"

        return {
            "overall_health": overall_health,
            "health_message": health_message,
            "components": {
                "pattern_tracker": "operational",
                "circuit_breaker": "operational" if self.circuit_breaker else "unavailable",
                "offline_cache": "operational" if self.pattern_cache else "unavailable",
                "service_monitor": "operational" if self.service_monitor else "unavailable"
            },
            "metrics": error_metrics,
            "cache": cache_status,
            "session_info": {
                "session_id": self.session_id,
                "uptime_minutes": self._get_session_uptime_minutes()
            },
            "resilience_features": {
                "circuit_breaker": bool(self.circuit_breaker),
                "offline_caching": bool(self.pattern_cache),
                "error_monitoring": bool(self.service_monitor),
                "exponential_backoff": True
            }
        }

    def _get_session_uptime_minutes(self) -> int:
        """Get session uptime in minutes (simplified)."""
        # This is a simplified implementation - in production, track actual start time
        return 0


# Singleton instance for easy access
_tracker_instance: Optional[PatternTracker] = None


def get_tracker() -> PatternTracker:
    """
    Get singleton PatternTracker instance.

    Returns:
        Global PatternTracker instance
    """
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = PatternTracker()
    return _tracker_instance


def track_pattern_creation_sync(
    code: str,
    context: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None
) -> str:
    """
    Synchronous wrapper for track_pattern_creation.

    This provides a sync interface for non-async contexts like hooks.

    Args:
        code: Generated code content
        context: Execution context (tool name, file path, etc.)
        metadata: Additional metadata to attach
        correlation_id: Optional correlation ID (generates if None)

    Returns:
        Pattern ID for the created pattern
    """
    tracker = get_tracker()

    # Run the async method in a new event loop
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        tracker.track_pattern_creation(
            code=code,
            context=context,
            metadata=metadata,
            correlation_id=correlation_id
        )
    )


# Export public API
__all__ = [
    'PatternTracker',
    'PatternTrackerConfig',
    'PatternEventType',
    'PatternCreationEvent',
    'PatternExecutionEvent',
    'PatternModificationEvent',
    'get_tracker',
    'track_pattern_creation_sync',
]


if __name__ == "__main__":
    # Self-test and validation
    print("Pattern Tracker - Self Test")
    print("=" * 60)

    # Test configuration
    config = PatternTrackerConfig()
    print(f"✓ Configuration loaded")
    print(f"  - Intelligence URL: {config.intelligence_url}")
    print(f"  - Enabled: {config.enabled}")
    print(f"  - Timeout: {config.timeout_seconds}s")
    print(f"  - Max Retries: {config.max_retries}")
    print(f"  - Log File: {config.log_file}")

    # Test tracker initialization
    tracker = PatternTracker(config)
    print(f"\n✓ Tracker initialized")
    print(f"  - Session ID: {tracker.session_id}")

    # Test pattern ID generation
    test_code = 'def hello():\n    print("world")'
    pattern_id_1 = tracker.generate_pattern_id(test_code)
    pattern_id_2 = tracker.generate_pattern_id(test_code)
    print(f"\n✓ Pattern ID generation")
    print(f"  - Pattern ID: {pattern_id_1}")
    print(f"  - Deterministic: {pattern_id_1 == pattern_id_2}")
    print(f"  - Length: {len(pattern_id_1)} chars")

    # Test correlation ID generation
    correlation_id = tracker.generate_correlation_id()
    print(f"\n✓ Correlation ID generation")
    print(f"  - Correlation ID: {correlation_id}")

    # Test singleton access
    tracker2 = get_tracker()
    print(f"\n✓ Singleton pattern")
    print(f"  - Same instance: {tracker2.session_id == tracker.session_id}")

    print("\n" + "=" * 60)
    print("Self-test complete! Core infrastructure ready for integration.")
    print("\nNext steps:")
    print("  - Agent 2: Implement HTTP client integration (_send_to_api)")
    print("  - Agent 3: Integrate with pre-tool-use hook")
    print("  - Agent 4: Integrate with post-tool-use hook")
    print("  - Agent 5: Add async execution context management")
