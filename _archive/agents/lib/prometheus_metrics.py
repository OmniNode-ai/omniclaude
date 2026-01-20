#!/usr/bin/env python3
"""
Prometheus Metrics Collection for OmniClaude

Comprehensive metrics collection for monitoring agent performance, action logging,
manifest injection, event publishing, database operations, and cache performance.

Usage:
    from agents.lib.prometheus_metrics import (
        action_log_duration,
        manifest_injection_duration,
        event_publish_counter,
        db_operation_duration,
        cache_hit_counter,
        cache_miss_counter,
    )

    # Record action logging timing
    with action_log_duration.labels(agent_name="agent-researcher", action_type="tool_call").time():
        await logger.log_tool_call(...)

    # Record manifest injection timing
    with manifest_injection_duration.labels(query_type="patterns").time():
        patterns = await injector.query_patterns()

    # Record event publish success/failure
    event_publish_counter.labels(topic="agent-actions", status="success").inc()

    # Record database operation timing
    with db_operation_duration.labels(operation="insert", table="agent_actions").time():
        await db.insert(...)

    # Record cache hit/miss
    cache_hit_counter.labels(cache_type="patterns").inc()
    cache_miss_counter.labels(cache_type="patterns").inc()

Features:
- Comprehensive metrics for all key operations
- Label-based filtering and grouping
- Histogram buckets optimized for typical operation timings
- Counter metrics for success/failure tracking
- Gauge metrics for current state
- Info metrics for system metadata
"""

import logging
import os

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
)

logger = logging.getLogger(__name__)

# ============================================================================
# Registry Configuration
# ============================================================================

# Use default registry or custom registry for testing
_metrics_registry = REGISTRY

# Enable multiprocess mode for production (gunicorn/uvicorn workers)
# Set PROMETHEUS_MULTIPROC_DIR environment variable to enable
PROMETHEUS_MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
if PROMETHEUS_MULTIPROC_DIR:
    from prometheus_client import CollectorRegistry, multiprocess

    _metrics_registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(_metrics_registry)
    logger.info(f"Prometheus multiprocess mode enabled: {PROMETHEUS_MULTIPROC_DIR}")


# ============================================================================
# System Information Metrics
# ============================================================================

system_info = Info(
    "omniclaude_system",
    "OmniClaude system information",
    registry=_metrics_registry,
)


# Set system info (call this on startup)
def set_system_info(
    version: str = "0.1.0",
    environment: str = "production",
    agent_registry_path: str | None = None,
):
    """Set system information metrics."""
    system_info.info(
        {
            "version": version,
            "environment": environment,
            "agent_registry_path": agent_registry_path or "~/.claude/agents/onex",
        }
    )


# ============================================================================
# Action Logging Metrics
# ============================================================================

action_log_duration = Histogram(
    "omniclaude_action_log_duration_seconds",
    "Time spent logging agent actions",
    labelnames=["agent_name", "action_type"],
    buckets=(
        0.001,  # 1ms
        0.005,  # 5ms
        0.01,  # 10ms
        0.025,  # 25ms
        0.05,  # 50ms
        0.1,  # 100ms
        0.25,  # 250ms
        0.5,  # 500ms
        1.0,  # 1s
        2.5,  # 2.5s
        5.0,  # 5s
    ),
    registry=_metrics_registry,
)

action_log_counter = Counter(
    "omniclaude_action_log_total",
    "Total number of action log events",
    labelnames=["agent_name", "action_type", "status"],
    registry=_metrics_registry,
)

action_log_errors_counter = Counter(
    "omniclaude_action_log_errors_total",
    "Total number of action logging errors",
    labelnames=["agent_name", "error_type"],
    registry=_metrics_registry,
)


# ============================================================================
# Manifest Injection Metrics
# ============================================================================

manifest_injection_duration = Histogram(
    "omniclaude_manifest_injection_duration_seconds",
    "Time spent injecting manifest intelligence",
    labelnames=["query_type", "collection"],
    buckets=(
        0.05,  # 50ms
        0.1,  # 100ms
        0.25,  # 250ms
        0.5,  # 500ms
        1.0,  # 1s
        2.0,  # 2s
        5.0,  # 5s
        10.0,  # 10s
        30.0,  # 30s
    ),
    registry=_metrics_registry,
)

manifest_injection_counter = Counter(
    "omniclaude_manifest_injection_total",
    "Total number of manifest injections",
    labelnames=["agent_name", "status"],
    registry=_metrics_registry,
)

manifest_pattern_count = Histogram(
    "omniclaude_manifest_patterns_count",
    "Number of patterns discovered per manifest injection",
    labelnames=["collection"],
    buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500, 1000),
    registry=_metrics_registry,
)

manifest_query_time = Histogram(
    "omniclaude_manifest_query_time_seconds",
    "Individual query time within manifest injection",
    labelnames=["query_type"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
    registry=_metrics_registry,
)


# ============================================================================
# Event Publishing Metrics (Kafka)
# ============================================================================

event_publish_counter = Counter(
    "omniclaude_event_publish_total",
    "Total number of events published to Kafka",
    labelnames=["topic", "status"],
    registry=_metrics_registry,
)

event_publish_duration = Histogram(
    "omniclaude_event_publish_duration_seconds",
    "Time spent publishing events to Kafka",
    labelnames=["topic"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    registry=_metrics_registry,
)

event_publish_errors_counter = Counter(
    "omniclaude_event_publish_errors_total",
    "Total number of event publishing errors",
    labelnames=["topic", "error_type"],
    registry=_metrics_registry,
)

event_publish_bytes = Histogram(
    "omniclaude_event_publish_bytes",
    "Size of events published to Kafka in bytes",
    labelnames=["topic"],
    buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000),
    registry=_metrics_registry,
)


# ============================================================================
# Database Operation Metrics
# ============================================================================

db_operation_duration = Histogram(
    "omniclaude_db_operation_duration_seconds",
    "Time spent on database operations",
    labelnames=["operation", "table"],
    buckets=(
        0.001,  # 1ms
        0.005,  # 5ms
        0.01,  # 10ms
        0.025,  # 25ms
        0.05,  # 50ms
        0.1,  # 100ms
        0.25,  # 250ms
        0.5,  # 500ms
        1.0,  # 1s
        2.5,  # 2.5s
    ),
    registry=_metrics_registry,
)

db_operation_counter = Counter(
    "omniclaude_db_operation_total",
    "Total number of database operations",
    labelnames=["operation", "table", "status"],
    registry=_metrics_registry,
)

db_connection_pool_size = Gauge(
    "omniclaude_db_connection_pool_size",
    "Current size of database connection pool",
    labelnames=["pool_name"],
    registry=_metrics_registry,
)

db_connection_pool_available = Gauge(
    "omniclaude_db_connection_pool_available",
    "Number of available connections in pool",
    labelnames=["pool_name"],
    registry=_metrics_registry,
)


# ============================================================================
# Cache Metrics
# ============================================================================

cache_hit_counter = Counter(
    "omniclaude_cache_hit_total",
    "Total number of cache hits",
    labelnames=["cache_type"],
    registry=_metrics_registry,
)

cache_miss_counter = Counter(
    "omniclaude_cache_miss_total",
    "Total number of cache misses",
    labelnames=["cache_type"],
    registry=_metrics_registry,
)

cache_operation_duration = Histogram(
    "omniclaude_cache_operation_duration_seconds",
    "Time spent on cache operations",
    labelnames=["cache_type", "operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
    registry=_metrics_registry,
)

cache_size_bytes = Gauge(
    "omniclaude_cache_size_bytes",
    "Current size of cache in bytes",
    labelnames=["cache_type"],
    registry=_metrics_registry,
)

cache_entries_count = Gauge(
    "omniclaude_cache_entries_count",
    "Current number of entries in cache",
    labelnames=["cache_type"],
    registry=_metrics_registry,
)


# ============================================================================
# Agent Routing Metrics
# ============================================================================

agent_routing_duration = Histogram(
    "omniclaude_agent_routing_duration_seconds",
    "Time spent on agent routing decisions",
    labelnames=["routing_method"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    registry=_metrics_registry,
)

agent_routing_counter = Counter(
    "omniclaude_agent_routing_total",
    "Total number of agent routing decisions",
    labelnames=["selected_agent", "status"],
    registry=_metrics_registry,
)

agent_routing_confidence = Histogram(
    "omniclaude_agent_routing_confidence",
    "Confidence score of agent routing decisions",
    labelnames=["selected_agent"],
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
    registry=_metrics_registry,
)


# ============================================================================
# Kafka Consumer Metrics
# ============================================================================

kafka_consumer_lag = Gauge(
    "omniclaude_kafka_consumer_lag",
    "Kafka consumer lag (messages behind)",
    labelnames=["consumer_group", "topic", "partition"],
    registry=_metrics_registry,
)

kafka_consumer_messages_consumed = Counter(
    "omniclaude_kafka_consumer_messages_consumed_total",
    "Total number of messages consumed",
    labelnames=["consumer_group", "topic"],
    registry=_metrics_registry,
)

kafka_consumer_processing_duration = Histogram(
    "omniclaude_kafka_consumer_processing_duration_seconds",
    "Time spent processing consumed messages",
    labelnames=["consumer_group", "topic"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=_metrics_registry,
)

kafka_consumer_errors_counter = Counter(
    "omniclaude_kafka_consumer_errors_total",
    "Total number of consumer processing errors",
    labelnames=["consumer_group", "topic", "error_type"],
    registry=_metrics_registry,
)


# ============================================================================
# Intelligence Collection Metrics
# ============================================================================

intelligence_collection_duration = Histogram(
    "omniclaude_intelligence_collection_duration_seconds",
    "Time spent collecting intelligence data",
    labelnames=["intelligence_type"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
    registry=_metrics_registry,
)

intelligence_collection_counter = Counter(
    "omniclaude_intelligence_collection_total",
    "Total number of intelligence collection operations",
    labelnames=["intelligence_type", "status"],
    registry=_metrics_registry,
)

intelligence_data_points = Histogram(
    "omniclaude_intelligence_data_points",
    "Number of data points collected per intelligence operation",
    labelnames=["intelligence_type"],
    buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500, 1000),
    registry=_metrics_registry,
)


# ============================================================================
# HTTP Request Metrics (FastAPI)
# ============================================================================

http_request_duration = Histogram(
    "omniclaude_http_request_duration_seconds",
    "HTTP request duration",
    labelnames=["method", "endpoint", "status_code"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=_metrics_registry,
)

http_request_counter = Counter(
    "omniclaude_http_request_total",
    "Total number of HTTP requests",
    labelnames=["method", "endpoint", "status_code"],
    registry=_metrics_registry,
)

http_request_size_bytes = Histogram(
    "omniclaude_http_request_size_bytes",
    "HTTP request size in bytes",
    labelnames=["method", "endpoint"],
    buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000),
    registry=_metrics_registry,
)

http_response_size_bytes = Histogram(
    "omniclaude_http_response_size_bytes",
    "HTTP response size in bytes",
    labelnames=["method", "endpoint"],
    buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000),
    registry=_metrics_registry,
)


# ============================================================================
# System Health Metrics
# ============================================================================

service_health_status = Gauge(
    "omniclaude_service_health_status",
    "Health status of services (1 = healthy, 0 = unhealthy)",
    labelnames=["service_name"],
    registry=_metrics_registry,
)

service_startup_time = Gauge(
    "omniclaude_service_startup_timestamp_seconds",
    "Service startup timestamp in seconds since epoch",
    labelnames=["service_name"],
    registry=_metrics_registry,
)


# ============================================================================
# Helper Functions
# ============================================================================


def get_metrics_registry() -> CollectorRegistry:
    """
    Get the metrics registry.

    Returns:
        CollectorRegistry: The Prometheus metrics registry
    """
    return _metrics_registry


def get_metrics_text() -> bytes:
    """
    Get metrics in Prometheus text format.

    Returns:
        bytes: Metrics in Prometheus exposition format
    """
    return generate_latest(_metrics_registry)


def reset_metrics():
    """
    Reset all metrics (useful for testing).

    Note: This only works with the default registry, not multiprocess mode.
    """
    if PROMETHEUS_MULTIPROC_DIR:
        logger.warning(
            "Cannot reset metrics in multiprocess mode. "
            "Restart all workers to reset metrics."
        )
        return

    # Clear all collectors and re-register
    logger.info("Resetting all Prometheus metrics")

    # Get list of collectors before modifying registry
    collectors = list(_metrics_registry._collector_to_names.keys())

    # Clear each collector or unregister if no clear method
    for collector in collectors:
        clear_method = getattr(collector, "clear", None)
        if callable(clear_method):
            clear_method()
        else:
            # If no clear method, unregister the collector
            try:
                _metrics_registry.unregister(collector)
            except Exception as e:
                logger.debug(f"Could not unregister collector {collector}: {e}")


# ============================================================================
# Metric Recording Helper Functions
# ============================================================================


def record_action_log(
    agent_name: str, action_type: str, duration: float, status: str = "success"
):
    """
    Record action log metrics.

    Args:
        agent_name: Agent name
        action_type: Type of action (tool_call, decision, error, success)
        duration: Duration in seconds
        status: Status (success, failure)
    """
    action_log_duration.labels(agent_name=agent_name, action_type=action_type).observe(
        duration
    )
    action_log_counter.labels(
        agent_name=agent_name, action_type=action_type, status=status
    ).inc()


def record_manifest_injection(
    agent_name: str,
    total_duration: float,
    pattern_count: int,
    status: str = "success",
):
    """
    Record manifest injection metrics.

    Args:
        agent_name: Agent name
        total_duration: Total duration in seconds
        pattern_count: Number of patterns discovered
        status: Status (success, failure)
    """
    manifest_injection_counter.labels(agent_name=agent_name, status=status).inc()
    manifest_injection_duration.labels(agent_name=agent_name).observe(total_duration)
    manifest_pattern_count.labels(collection="execution_patterns").observe(
        pattern_count
    )


def record_event_publish(topic: str, duration: float, size_bytes: int, status: str):
    """
    Record event publishing metrics.

    Args:
        topic: Kafka topic
        duration: Duration in seconds
        size_bytes: Event size in bytes
        status: Status (success, failure)
    """
    event_publish_counter.labels(topic=topic, status=status).inc()
    event_publish_duration.labels(topic=topic).observe(duration)
    event_publish_bytes.labels(topic=topic).observe(size_bytes)


def record_db_operation(
    operation: str, table: str, duration: float, status: str = "success"
):
    """
    Record database operation metrics.

    Args:
        operation: Operation type (insert, update, delete, select)
        table: Table name
        duration: Duration in seconds
        status: Status (success, failure)
    """
    db_operation_duration.labels(operation=operation, table=table).observe(duration)
    db_operation_counter.labels(operation=operation, table=table, status=status).inc()


def record_cache_operation(cache_type: str, operation: str, duration: float, hit: bool):
    """
    Record cache operation metrics.

    Args:
        cache_type: Cache type (patterns, manifest, routing, etc.)
        operation: Operation type (get, set, delete)
        duration: Duration in seconds
        hit: Whether it was a cache hit (for get operations)
    """
    cache_operation_duration.labels(cache_type=cache_type, operation=operation).observe(
        duration
    )

    if operation == "get":
        if hit:
            cache_hit_counter.labels(cache_type=cache_type).inc()
        else:
            cache_miss_counter.labels(cache_type=cache_type).inc()


def record_agent_routing(
    selected_agent: str,
    confidence: float,
    duration: float,
    routing_method: str = "event_based",
    status: str = "success",
):
    """
    Record agent routing metrics.

    Args:
        selected_agent: Selected agent name
        confidence: Confidence score (0.0-1.0)
        duration: Duration in seconds
        routing_method: Routing method (event_based, fuzzy, etc.)
        status: Status (success, failure)
    """
    agent_routing_duration.labels(routing_method=routing_method).observe(duration)
    agent_routing_counter.labels(selected_agent=selected_agent, status=status).inc()
    agent_routing_confidence.labels(selected_agent=selected_agent).observe(confidence)


# ============================================================================
# Initialization
# ============================================================================


def initialize_metrics(
    version: str = "0.1.0",
    environment: str = "production",
    agent_registry_path: str | None = None,
):
    """
    Initialize metrics system.

    Call this on application startup to set system information.

    Args:
        version: Application version
        environment: Environment (production, development, test)
        agent_registry_path: Path to agent registry
    """
    set_system_info(version, environment, agent_registry_path)
    logger.info(
        f"Prometheus metrics initialized: version={version}, environment={environment}"
    )


if __name__ == "__main__":
    # Test metrics collection

    # Initialize
    initialize_metrics(version="0.1.0", environment="development")

    # Record some test metrics
    record_action_log("agent-researcher", "tool_call", 0.045)
    record_manifest_injection("agent-researcher", 1.5, 120)
    record_event_publish("agent-actions", 0.005, 1024, "success")
    record_db_operation("insert", "agent_actions", 0.025)
    record_cache_operation("patterns", "get", 0.002, hit=True)
    record_agent_routing("agent-researcher", 0.92, 0.008)

    # Print metrics
    print(get_metrics_text().decode("utf-8"))
