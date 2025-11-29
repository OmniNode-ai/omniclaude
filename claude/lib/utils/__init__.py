"""Shared utilities for Claude artifacts.

This package contains utility functions and classes for:
- Error handling infrastructure (logging, retry, circuit breaker)
- Health checks for Phase 4 pattern traceability
- Quality enforcement with naming convention validation
- Manifest loading and parsing
- Debug utilities and diagnostics
- Pattern tracking with performance monitoring
- Naming convention validators (Omninode and PEP 8)

Modules:
    error_handling: Error handling infrastructure with retry and circuit breaker
    health_checks: Service health monitoring and diagnostics
    quality_enforcer: Code quality enforcement with AI-assisted corrections
    manifest_loader: Dynamic manifest loading via event bus
    naming_validator: Naming convention validation for Python/TypeScript
    pattern_tracker: Performance-optimized pattern tracking
    debug_utils: Debug utilities for service diagnostics
"""

# Error Handling
# Debug Utilities
from .debug_utils import (
    check_network_connectivity,
    check_pattern_tracking_files,
    check_python_environment,
    check_running_services,
    print_debug_status,
    test_pattern_tracking_flow,
)
from .error_handling import (
    CircuitBreaker,
    PatternTrackingErrorHandler,
    PatternTrackingLogger,
    get_default_error_handler,
    get_default_logger,
    handle_error,
    log_error,
    log_success,
    safe_execute_operation,
)

# Health Checks
from .health_checks import (
    HealthCheckResult,
    HealthStatus,
    Phase4HealthChecker,
)

# Manifest Loading
from .manifest_loader import (
    load_manifest,
)

# Naming Validation
from .naming_validator import (
    NamingValidator,
    Violation,
)

# Pattern Tracking
from .pattern_tracker import (
    BatchProcessor,
    PatternTracker,
    PatternTrackerConfig,
    PerformanceMetrics,
    PerformanceMonitor,
    ProcessingMode,
    get_tracker,
)

# Quality Enforcement
from .quality_enforcer import (
    QualityEnforcer,
    ViolationsLogger,
)


__all__ = [
    # Error Handling
    "PatternTrackingLogger",
    "PatternTrackingErrorHandler",
    "CircuitBreaker",
    "safe_execute_operation",
    "get_default_logger",
    "get_default_error_handler",
    "log_success",
    "log_error",
    "handle_error",
    # Health Checks
    "HealthStatus",
    "HealthCheckResult",
    "Phase4HealthChecker",
    # Quality Enforcement
    "ViolationsLogger",
    "QualityEnforcer",
    # Manifest Loading
    "load_manifest",
    # Naming Validation
    "Violation",
    "NamingValidator",
    # Pattern Tracking
    "ProcessingMode",
    "PerformanceMetrics",
    "PatternTrackerConfig",
    "PerformanceMonitor",
    "BatchProcessor",
    "PatternTracker",
    "get_tracker",
    # Debug Utilities
    "check_running_services",
    "check_network_connectivity",
    "check_pattern_tracking_files",
    "check_python_environment",
    "print_debug_status",
    "test_pattern_tracking_flow",
]
