#!/usr/bin/env python3
"""
Metrics collection and aggregation framework.

Provides performance tracking, threshold validation, and metrics aggregation
following ONEX patterns from omninode_bridge.
"""

from .metrics_collector import MetricsCollector, ThresholdBreach


__all__ = ["MetricsCollector", "ThresholdBreach"]
