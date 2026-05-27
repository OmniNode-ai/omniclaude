# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Shared utilities for Claude artifacts -- lazy loading (PEP 562).

This package contains utility functions and classes for:
- Error handling infrastructure (logging, retry, circuit breaker)
- Health checks for Phase 4 pattern traceability
- Quality enforcement with naming convention validation
- Manifest loading and parsing
- Debug utilities and diagnostics
- Pattern tracking with performance monitoring
- Naming convention validators (Omninode and PEP 8)

All re-exported names are resolved lazily on first access to prevent
the circular import chain that occurs when config -> aggregators ->
hooks -> lib.utils -> validator_quality -> config.
"""

from __future__ import annotations

import importlib
from typing import Any

# Maps every re-exported name to its source submodule (relative to this package).
_LAZY_IMPORTS: dict[str, str] = {
    # diagnostics (renamed from debug_utils)
    "check_network_connectivity": ".diagnostics",
    "check_pattern_tracking_files": ".diagnostics",
    "check_python_environment": ".diagnostics",
    "check_running_services": ".diagnostics",
    "print_debug_status": ".diagnostics",
    "test_pattern_tracking_flow": ".diagnostics",
    # error_handling
    "CircuitBreaker": ".error_handling",
    "PatternTrackingErrorPolicy": ".error_handling",
    "PatternTrackingLogger": ".error_handling",
    "get_default_error_handler": ".error_handling",
    "get_default_logger": ".error_handling",
    "handle_error": ".error_handling",
    "log_error": ".error_handling",
    "log_success": ".error_handling",
    "safe_execute_operation": ".error_handling",
    # health_checks
    "HealthCheckResult": ".health_checks",
    "HealthStatus": ".health_checks",
    "Phase4HealthChecker": ".health_checks",
    # manifest_loader
    "load_manifest": ".manifest_loader",
    # validator_naming_conventions (renamed from naming_validator)
    "NamingValidator": ".validator_naming_conventions",
    "Violation": ".validator_naming_conventions",
    # pattern_tracker
    "BatchAggregator": ".pattern_tracker",
    "PatternTracker": ".pattern_tracker",
    "PatternTrackerConfig": ".pattern_tracker",
    "PerformanceMetrics": ".pattern_tracker",
    "PerformanceMonitor": ".pattern_tracker",
    "ProcessingMode": ".pattern_tracker",
    "get_tracker": ".pattern_tracker",
    # validator_quality (renamed from quality_enforcer)
    "QualityEnforcer": ".validator_quality",
    "ViolationsLogger": ".validator_quality",
}

__all__ = sorted(_LAZY_IMPORTS.keys())


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        mod = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        val = getattr(mod, name)
        globals()[name] = val  # cache so __getattr__ is only called once
        return val
    raise AttributeError(f"module 'omniclaude.lib.utils' has no attribute {name!r}")
