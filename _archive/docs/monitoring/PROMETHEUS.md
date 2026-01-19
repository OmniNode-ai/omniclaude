# Prometheus Metrics for OmniClaude

Comprehensive Prometheus instrumentation for monitoring agent performance, action logging, event publishing, database operations, and cache performance.

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Available Metrics](#available-metrics)
4. [Metric Categories](#metric-categories)
5. [Integration](#integration)
6. [Grafana Dashboard](#grafana-dashboard)
7. [Alerting Rules](#alerting-rules)
8. [Troubleshooting](#troubleshooting)
9. [Best Practices](#best-practices)

---

## Overview

OmniClaude includes comprehensive Prometheus instrumentation for observability across all key operations:

- **Action Logging**: Performance and success/failure tracking
- **Event Publishing**: Kafka publishing metrics with latency and throughput
- **Database Operations**: Query performance and connection pool metrics
- **Cache Performance**: Hit/miss rates and operation timings
- **HTTP Requests**: Request duration, rate, and status codes
- **System Health**: Service health and startup tracking

### Architecture

```
┌─────────────────────────────────────────────────────┐
│  OmniClaude Application                             │
│  ┌───────────────────────────────────────────────┐  │
│  │  FastAPI App (app/main.py)                    │  │
│  │  - /metrics endpoint (Prometheus format)      │  │
│  │  - Request instrumentation middleware         │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │  Instrumented Components                      │  │
│  │  - ActionLogger (agents/lib/action_logger.py) │  │
│  │  - EventPublisher (agents/lib/action_event_*) │  │
│  │  - ManifestInjector (deferred to follow-up)   │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │  Metrics Module                               │  │
│  │  (agents/lib/prometheus_metrics.py)           │  │
│  │  - Metric definitions                         │  │
│  │  - Helper functions                           │  │
│  │  - Registry management                        │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                      │
                      │ HTTP (port 8000/metrics)
                      ↓
┌─────────────────────────────────────────────────────┐
│  Prometheus Server                                   │
│  - Scrapes /metrics endpoint every 15s              │
│  - Stores time-series data (30 day retention)       │
│  - Provides query API (PromQL)                      │
└─────────────────────────────────────────────────────┘
                      │
                      │ PromQL queries
                      ↓
┌─────────────────────────────────────────────────────┐
│  Grafana                                             │
│  - Pre-built dashboard (omniclaude.json)            │
│  - Real-time visualization                          │
│  - Alerting (optional)                              │
└─────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Install Dependencies

Already included in `pyproject.toml`:

```toml
[tool.poetry.dependencies]
prometheus-client = "^0.21.0"
```

Install with:

```bash
poetry install
```

### 2. Start Services

Start the application with Prometheus and Grafana:

```bash
cd deployment
docker-compose --profile monitoring up -d
```

This starts:
- **OmniClaude App** (port 8000)
- **Prometheus** (port 9090)
- **Grafana** (port 3000)

### 3. Access Metrics

**Raw Metrics** (Prometheus text format):
```bash
curl http://localhost:8000/metrics
```

**Prometheus UI**:
```
http://localhost:9090
```

**Grafana Dashboard**:
```
http://localhost:3000
Username: admin
Password: ${GRAFANA_ADMIN_PASSWORD} (from .env)
```

Import dashboard: `grafana/dashboards/omniclaude.json`

---

## Available Metrics

### System Information

| Metric | Type | Description | Labels |
|--------|------|-------------|--------|
| `omniclaude_system_info` | Info | System metadata | `version`, `environment`, `agent_registry_path` |
| `omniclaude_service_health_status` | Gauge | Service health (1=healthy, 0=unhealthy) | `service_name` |
| `omniclaude_service_startup_timestamp_seconds` | Gauge | Service startup time (Unix timestamp) | `service_name` |

### Action Logging

| Metric | Type | Description | Labels |
|--------|------|-------------|--------|
| `omniclaude_action_log_duration_seconds` | Histogram | Time spent logging agent actions | `agent_name`, `action_type` |
| `omniclaude_action_log_total` | Counter | Total action log events | `agent_name`, `action_type`, `status` |
| `omniclaude_action_log_errors_total` | Counter | Total action logging errors | `agent_name`, `error_type` |

**Buckets**: 1ms, 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s

**Example Queries**:

```promql
# p95 action logging latency
histogram_quantile(0.95, rate(omniclaude_action_log_duration_seconds_bucket[5m]))

# Action logging rate by agent
rate(omniclaude_action_log_total[5m])

# Error rate
rate(omniclaude_action_log_errors_total[5m])
```

### Event Publishing (Kafka)

| Metric | Type | Description | Labels |
|--------|------|-------------|--------|
| `omniclaude_event_publish_total` | Counter | Total events published to Kafka | `topic`, `status` |
| `omniclaude_event_publish_duration_seconds` | Histogram | Event publishing latency | `topic` |
| `omniclaude_event_publish_errors_total` | Counter | Event publishing errors | `topic`, `error_type` |
| `omniclaude_event_publish_bytes` | Histogram | Event size in bytes | `topic` |

**Buckets (duration)**: 1ms, 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s

**Buckets (bytes)**: 100, 500, 1K, 5K, 10K, 50K, 100K, 500K

**Example Queries**:

```promql
# Event publishing success rate
sum(rate(omniclaude_event_publish_total{status="success"}[5m]))
/ sum(rate(omniclaude_event_publish_total[5m]))

# p95 publishing latency
histogram_quantile(0.95, rate(omniclaude_event_publish_duration_seconds_bucket[5m]))

# Average event size
rate(omniclaude_event_publish_bytes_sum[5m])
/ rate(omniclaude_event_publish_bytes_count[5m])
```

### Database Operations

| Metric | Type | Description | Labels |
|--------|------|-------------|--------|
| `omniclaude_db_operation_duration_seconds` | Histogram | Database operation latency | `operation`, `table` |
| `omniclaude_db_operation_total` | Counter | Total database operations | `operation`, `table`, `status` |
| `omniclaude_db_connection_pool_size` | Gauge | Current connection pool size | `pool_name` |
| `omniclaude_db_connection_pool_available` | Gauge | Available connections | `pool_name` |

**Buckets**: 1ms, 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s

**Example Queries**:

```promql
# Slow queries (p95 > 100ms)
histogram_quantile(0.95, rate(omniclaude_db_operation_duration_seconds_bucket[5m])) > 0.1

# Top tables by query volume
topk(10, sum(rate(omniclaude_db_operation_total[5m])) by (table))

# Connection pool utilization
(omniclaude_db_connection_pool_size - omniclaude_db_connection_pool_available)
/ omniclaude_db_connection_pool_size
```

### Cache Performance

| Metric | Type | Description | Labels |
|--------|------|-------------|--------|
| `omniclaude_cache_hit_total` | Counter | Cache hits | `cache_type` |
| `omniclaude_cache_miss_total` | Counter | Cache misses | `cache_type` |
| `omniclaude_cache_operation_duration_seconds` | Histogram | Cache operation latency | `cache_type`, `operation` |
| `omniclaude_cache_size_bytes` | Gauge | Current cache size | `cache_type` |
| `omniclaude_cache_entries_count` | Gauge | Current entry count | `cache_type` |

**Buckets**: 1ms, 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms

**Example Queries**:

```promql
# Cache hit rate
sum(rate(omniclaude_cache_hit_total[5m]))
/ (sum(rate(omniclaude_cache_hit_total[5m])) + sum(rate(omniclaude_cache_miss_total[5m])))

# Cache hit rate by type
sum(rate(omniclaude_cache_hit_total[5m])) by (cache_type)
/ (sum(rate(omniclaude_cache_hit_total[5m])) by (cache_type)
   + sum(rate(omniclaude_cache_miss_total[5m])) by (cache_type))
```

### HTTP Requests (FastAPI)

| Metric | Type | Description | Labels |
|--------|------|-------------|--------|
| `omniclaude_http_request_duration_seconds` | Histogram | HTTP request latency | `method`, `endpoint`, `status_code` |
| `omniclaude_http_request_total` | Counter | Total HTTP requests | `method`, `endpoint`, `status_code` |
| `omniclaude_http_request_size_bytes` | Histogram | Request body size | `method`, `endpoint` |
| `omniclaude_http_response_size_bytes` | Histogram | Response body size | `method`, `endpoint` |

**Buckets (duration)**: 1ms, 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s

**Buckets (bytes)**: 100, 500, 1K, 5K, 10K, 50K, 100K, 500K, 1M

**Example Queries**:

```promql
# Error rate (4xx/5xx)
sum(rate(omniclaude_http_request_total{status_code=~"[45].."}[5m]))
/ sum(rate(omniclaude_http_request_total[5m]))

# p95 latency by endpoint
histogram_quantile(0.95,
  rate(omniclaude_http_request_duration_seconds_bucket[5m])) by (endpoint)

# Requests per second
sum(rate(omniclaude_http_request_total[5m]))
```

### Agent Routing (Future)

| Metric | Type | Description | Labels |
|--------|------|-------------|--------|
| `omniclaude_agent_routing_duration_seconds` | Histogram | Routing decision latency | `routing_method` |
| `omniclaude_agent_routing_total` | Counter | Total routing decisions | `selected_agent`, `status` |
| `omniclaude_agent_routing_confidence` | Histogram | Confidence scores | `selected_agent` |

---

## Metric Categories

### Histogram Metrics

Histograms track distributions of values (latency, size, etc.) with predefined buckets.

**Use cases**:
- Request latency (p50, p95, p99)
- Event size distributions
- Query performance percentiles

**Example**:
```python
from agents.lib.prometheus_metrics import action_log_duration

# Automatic timing
with action_log_duration.labels(agent_name="agent-researcher", action_type="tool_call").time():
    await log_tool_call(...)

# Manual timing
action_log_duration.labels(agent_name="agent-researcher", action_type="tool_call").observe(0.045)
```

**Query percentiles**:
```promql
# p50 (median)
histogram_quantile(0.50, rate(omniclaude_action_log_duration_seconds_bucket[5m]))

# p95
histogram_quantile(0.95, rate(omniclaude_action_log_duration_seconds_bucket[5m]))

# p99
histogram_quantile(0.99, rate(omniclaude_action_log_duration_seconds_bucket[5m]))
```

### Counter Metrics

Counters track cumulative totals (requests, errors, events).

**Use cases**:
- Total requests
- Error counts
- Event counts

**Example**:
```python
from agents.lib.prometheus_metrics import action_log_counter

action_log_counter.labels(
    agent_name="agent-researcher",
    action_type="tool_call",
    status="success"
).inc()
```

**Query rates**:
```promql
# Requests per second
rate(omniclaude_action_log_total[5m])

# Error rate
rate(omniclaude_action_log_errors_total[5m])
```

### Gauge Metrics

Gauges track current state (active connections, cache size).

**Use cases**:
- Current values
- Service health
- Resource utilization

**Example**:
```python
from agents.lib.prometheus_metrics import service_health_status

# Set health status (1 = healthy, 0 = unhealthy)
service_health_status.labels(service_name="omniclaude").set(1)

# Update cache size
cache_size_bytes.labels(cache_type="patterns").set(1024 * 1024)  # 1MB
```

**Query current values**:
```promql
# Current health status
omniclaude_service_health_status

# Cache size
omniclaude_cache_size_bytes
```

### Info Metrics

Info metrics provide static metadata.

**Example**:
```python
from agents.lib.prometheus_metrics import initialize_metrics

initialize_metrics(
    version="0.1.0",
    environment="production",
    agent_registry_path="~/.claude/agent-definitions"
)
```

---

## Integration

### Using Metrics in Your Code

#### Option 1: Helper Functions (Recommended)

```python
from agents.lib.prometheus_metrics import (
    record_action_log,
    record_event_publish,
    record_db_operation,
    record_cache_operation,
)

# Record action log
record_action_log(
    agent_name="agent-researcher",
    action_type="tool_call",
    duration=0.045,  # seconds
    status="success"
)

# Record event publish
record_event_publish(
    topic="agent-actions",
    duration=0.005,
    size_bytes=1024,
    status="success"
)

# Record database operation
record_db_operation(
    operation="insert",
    table="agent_actions",
    duration=0.025,
    status="success"
)

# Record cache operation
record_cache_operation(
    cache_type="patterns",
    operation="get",
    duration=0.002,
    hit=True
)
```

#### Option 2: Direct Metric Usage

```python
from agents.lib.prometheus_metrics import (
    action_log_duration,
    action_log_counter,
)

# Automatic timing with context manager
with action_log_duration.labels(agent_name="agent-researcher", action_type="tool_call").time():
    # Your code here
    await execute_tool_call()

# Manual recording
action_log_counter.labels(
    agent_name="agent-researcher",
    action_type="tool_call",
    status="success"
).inc()
```

### ActionLogger Integration

The `ActionLogger` class automatically records metrics:

```python
from agents.lib.action_logger import ActionLogger

logger = ActionLogger(
    agent_name="agent-researcher",
    correlation_id="abc-123"
)

# Metrics recorded automatically
await logger.log_tool_call(
    tool_name="Read",
    tool_parameters={"file_path": "/path/to/file.py"},
    tool_result={"line_count": 100},
    duration_ms=45  # Automatically recorded in Prometheus
)

# Error metrics recorded automatically
await logger.log_error(
    error_type="DatabaseConnectionError",
    error_message="Failed to connect",
    severity="critical"
)
```

### Event Publisher Integration

Event publishing metrics are automatic:

```python
from agents.lib.action_event_publisher import publish_action_event

# Metrics recorded automatically (timing, size, success/failure)
await publish_action_event(
    agent_name="agent-researcher",
    action_type="tool_call",
    action_name="Read",
    action_details={"file_path": "/path/to/file.py"},
    correlation_id="abc-123",
    duration_ms=45
)
```

---

## Grafana Dashboard

### Importing the Dashboard

1. Access Grafana at `http://localhost:3000`
2. Login with admin credentials (from `.env`)
3. Navigate to **Dashboards** → **Import**
4. Upload `grafana/dashboards/omniclaude.json`
5. Select Prometheus data source
6. Click **Import**

### Dashboard Panels

**Included panels**:

1. **Service Health Status** - Bar gauge showing service health
2. **Action Log Rate** - Time series of action logging rate
3. **Action Log Duration (p50, p95)** - Latency percentiles
4. **Event Publishing Rate** - Kafka publishing throughput
5. **Event Publishing Duration (p95)** - Publishing latency
6. **Cache Hit/Miss Rate** - Stacked area chart
7. **Overall Cache Hit Rate** - Gauge showing hit percentage
8. **Database Operation Duration** - Query performance
9. **Database Operation Rate** - Query throughput
10. **HTTP Request Duration** - API latency
11. **HTTP Request Rate** - API throughput

### Customizing the Dashboard

Edit panels to:
- Adjust time ranges
- Add custom queries
- Change visualization types
- Add new panels
- Create alerts

---

## Alerting Rules

### Prometheus Alert Configuration

Create `deployment/monitoring/prometheus/alerts.yml`:

```yaml
groups:
  - name: omniclaude
    interval: 30s
    rules:
      # High action logging latency
      - alert: HighActionLogLatency
        expr: histogram_quantile(0.95, rate(omniclaude_action_log_duration_seconds_bucket[5m])) > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High action logging latency detected"
          description: "p95 action logging latency is {{ $value }}s (threshold: 1s)"

      # High event publish failure rate
      - alert: HighEventPublishFailureRate
        expr: |
          sum(rate(omniclaude_event_publish_total{status="failure"}[5m]))
          / sum(rate(omniclaude_event_publish_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High event publishing failure rate"
          description: "{{ $value | humanizePercentage }} of events failing to publish"

      # Low cache hit rate
      - alert: LowCacheHitRate
        expr: |
          sum(rate(omniclaude_cache_hit_total[5m]))
          / (sum(rate(omniclaude_cache_hit_total[5m])) + sum(rate(omniclaude_cache_miss_total[5m]))) < 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Low cache hit rate"
          description: "Cache hit rate is {{ $value | humanizePercentage }} (threshold: 50%)"

      # Database connection pool exhaustion
      - alert: DatabaseConnectionPoolExhaustion
        expr: |
          (omniclaude_db_connection_pool_size - omniclaude_db_connection_pool_available)
          / omniclaude_db_connection_pool_size > 0.9
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Database connection pool nearly exhausted"
          description: "{{ $value | humanizePercentage }} of connections in use"

      # Service unhealthy
      - alert: ServiceUnhealthy
        expr: omniclaude_service_health_status == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Service {{ $labels.service_name }} is unhealthy"
          description: "Service health status is 0"

      # High HTTP error rate
      - alert: HighHTTPErrorRate
        expr: |
          sum(rate(omniclaude_http_request_total{status_code=~"[45].."}[5m]))
          / sum(rate(omniclaude_http_request_total[5m])) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High HTTP error rate"
          description: "{{ $value | humanizePercentage }} of requests returning 4xx/5xx"
```

### Grafana Alerting

Configure alerts in Grafana:

1. **Navigate to Alerting** → **Alert rules**
2. **Create alert rule**
3. **Select metric query** (e.g., cache hit rate)
4. **Set threshold** (e.g., < 50%)
5. **Configure notification channels** (email, Slack, PagerDuty)
6. **Save alert**

---

## Troubleshooting

### Metrics Not Appearing

**Symptom**: `/metrics` endpoint returns empty or missing metrics

**Diagnosis**:
```bash
# Check if endpoint is accessible
curl http://localhost:8000/metrics

# Check Prometheus targets
# Navigate to: http://localhost:9090/targets
```

**Fixes**:
1. Verify `prometheus_client` is installed: `poetry show prometheus-client`
2. Check application logs for errors
3. Verify Prometheus scrape config in `deployment/monitoring/prometheus/prometheus.yml`

### Prometheus Not Scraping

**Symptom**: Prometheus UI shows targets as "down"

**Diagnosis**:
```bash
# Check Prometheus container logs
docker logs omniclaude_prometheus

# Verify network connectivity
docker exec omniclaude_prometheus wget -O- http://app:8000/metrics
```

**Fixes**:
1. Verify Docker networks are correct
2. Check firewall rules
3. Verify `app` service is running

### Grafana Dashboard Not Loading Data

**Symptom**: Dashboard panels show "No Data"

**Diagnosis**:
1. Check Prometheus data source configuration
2. Verify metrics exist in Prometheus: `http://localhost:9090/graph`
3. Check time range in dashboard

**Fixes**:
1. Re-configure Prometheus data source in Grafana
2. Adjust time range to include data
3. Verify metric names match query

### High Memory Usage

**Symptom**: Application memory grows over time

**Cause**: Prometheus metrics with high cardinality labels

**Diagnosis**:
```promql
# Count unique label combinations
count(omniclaude_http_request_total) by (__name__)
```

**Fixes**:
1. Avoid user-generated label values (e.g., correlation IDs)
2. Use fixed label sets
3. Limit histogram buckets if needed

---

## Best Practices

### Label Design

✅ **Good**:
```python
# Fixed label values
action_log_counter.labels(
    agent_name="agent-researcher",  # Fixed set of agents
    action_type="tool_call",        # Fixed action types
    status="success"                # Fixed: success/failure
).inc()
```

❌ **Bad**:
```python
# Dynamic label values (unbounded cardinality)
action_log_counter.labels(
    correlation_id="abc-123",      # ❌ Every request is unique
    user_input="some text...",     # ❌ Unbounded values
).inc()
```

### Histogram Bucket Selection

Choose buckets based on expected distribution:

```python
# For fast operations (ms range)
buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)

# For slow operations (seconds range)
buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
```

### Metric Naming

Follow Prometheus naming conventions:

- Use `_total` suffix for counters: `omniclaude_action_log_total`
- Use `_seconds` suffix for durations: `omniclaude_action_log_duration_seconds`
- Use `_bytes` suffix for sizes: `omniclaude_event_publish_bytes`
- Use base unit (seconds, not milliseconds; bytes, not KB)

### Performance Considerations

1. **Avoid high-frequency updates**: Batch metrics where possible
2. **Use sampling**: For very high-volume operations
3. **Disable in development**: Set `PROMETHEUS_ENABLED=false` in dev
4. **Monitor cardinality**: Track unique label combinations

### Security

1. **Expose /metrics on internal port only**: Don't expose to public internet
2. **Use authentication**: Add basic auth or OAuth for production
3. **Sanitize labels**: Never include sensitive data in labels

---

## Summary

- **Comprehensive instrumentation** across action logging, event publishing, database, cache, and HTTP
- **/metrics endpoint** at `http://localhost:8000/metrics`
- **Grafana dashboard** with 11 pre-configured panels
- **Helper functions** for easy integration
- **Automatic metrics** in ActionLogger and EventPublisher
- **Alerting rules** for common issues
- **Best practices** for label design, buckets, and performance

For additional help, see:
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [prometheus_client Python Library](https://github.com/prometheus/client_python)
