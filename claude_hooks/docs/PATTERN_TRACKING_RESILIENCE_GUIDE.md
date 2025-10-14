# Pattern Tracking Resilience Guide

## Overview

This guide documents the comprehensive resilience enhancements implemented in the Claude Code Pattern Tracking system. The system now includes advanced error handling, circuit breaker patterns, exponential backoff with jitter, offline caching, and comprehensive monitoring capabilities.

## Architecture

### Enhanced Pattern Tracker Components

```
┌─────────────────────────────────────────────────────────────────┐
│                    Enhanced Pattern Tracker                     │
├─────────────────────────┬─────────────────────────────────────┤
│      Resilience Layer   │         Monitoring Layer             │
├─────────────────────────┼─────────────────────────────────────┤
│ • Circuit Breaker       │ • Error Metrics Collection         │
│ • Exponential Backoff   │ • Health Status Monitoring         │
│ • Offline Cache         │ • Service Monitoring               │
│ • Graceful Degradation  │ • Alerting System                  │
│ • Retry Policies        │ • Performance Tracking             │
├─────────────────────────┼─────────────────────────────────────┤
│      Integration Layer  │         Data Layer                   │
├─────────────────────────┼─────────────────────────────────────┤
│ • Phase 4 API Client    │ • Pattern Cache                    │
│ • Hook System           │ • Error Log Storage                │
│ • Claude Code Integration│ • Metrics Database                 │
│ • Async/Sync Support    │ • Health Check Results             │
└─────────────────────────┴─────────────────────────────────────┘
```

## Key Features

### 1. Circuit Breaker Pattern

**Purpose**: Prevent cascading failures when the Phase 4 API is unavailable

**Configuration**:
- Failure threshold: 5 consecutive failures
- Recovery timeout: 60 seconds
- Expected exceptions: HTTP errors, request errors, general exceptions

**Behavior**:
- **Closed**: Normal operation, all requests pass through
- **Open**: Circuit breaker tripped, requests fail fast
- **Half-Open**: Testing recovery, limited requests allowed

### 2. Exponential Backoff with Jitter

**Purpose**: Prevent thundering herd problems during API recovery

**Algorithm**:
```python
base_delay = 1.0  # Base delay in seconds
max_delay = 30.0  # Maximum delay
jitter_factor = 0.1  # 10% jitter

delay = min(base_delay * (2 ** attempt) + random_jitter, max_delay)
```

### 3. Offline Caching

**Purpose**: Ensure pattern tracking continues during API unavailability

**Features**:
- Automatic cache for failed API calls
- Batch replay when service recovers
- Configurable cache size and TTL
- Persistent storage across restarts

### 4. Comprehensive Monitoring

**Metrics Collected**:
- Total requests and success/failure rates
- Circuit breaker status and trip count
- Cache hit/miss ratios
- Retry attempt statistics
- Response time percentiles
- Error classification and trends

## Configuration

### Environment Variables

```bash
# Pattern Tracking Configuration
PATTERN_TRACKING_ENABLED=true
PATTERN_TRACKING_CACHE_SIZE=1000
PATTERN_TRACKING_CACHE_TTL=3600

# Resilience Configuration
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60
EXPONENTIAL_BACKOFF_BASE_DELAY=1.0
EXPONENTIAL_BACKOFF_MAX_DELAY=30.0

# Monitoring Configuration
MONITORING_ENABLED=true
MONITORING_INTERVAL=60
ALERTING_ENABLED=true
ALERTING_THRESHOLD=0.8
```

### Configuration File

The system uses YAML configuration for advanced settings:

```yaml
pattern_tracking:
  enabled: true
  cache_size: 1000
  cache_ttl: 3600
  batch_size: 50

resilience:
  circuit_breaker:
    failure_threshold: 5
    recovery_timeout: 60
    half_open_attempts: 3
  retry:
    max_attempts: 3
    base_delay: 1.0
    max_delay: 30.0
    jitter_factor: 0.1

monitoring:
  enabled: true
  interval: 60
  metrics_retention: 86400
  alerting:
    enabled: true
    threshold: 0.8
    channels: ["log", "console"]
```

## Operational Procedures

### Startup Verification

1. **Check Service Health**:
   ```bash
   curl -f http://localhost:8053/health || echo "Phase 4 API unavailable"
   ```

2. **Verify Pattern Tracker**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   health = tracker.get_health_summary()
   print(f'Status: {health[\"status\"]}')
   print(f'API Available: {health[\"api_available\"]}')
   print(f'Cache Size: {health[\"cache_size\"]}')
   "
   ```

3. **Check Hook Integration**:
   ```bash
   # Test pattern tracking with a sample file
   echo "print('test')" > /tmp/test.py
   python post_tool_use_enforcer.py /tmp/test.py
   ```

### Health Monitoring

The system provides comprehensive health monitoring through several endpoints:

1. **Basic Health Check**:
   ```python
   tracker.get_health_summary()
   ```

2. **Detailed Metrics**:
   ```python
   tracker.get_error_metrics()
   ```

3. **Service Status**:
   ```python
   tracker.service_monitor.get_service_status()
   ```

### Performance Monitoring

Monitor key performance indicators:

```python
# Get current performance metrics
metrics = tracker.get_error_metrics()

# Key metrics to watch:
- total_requests: Overall system load
- success_rate: tracker.get_error_metrics()['successful_requests'] / metrics['total_requests']
- circuit_breaker_trips: Should be 0 under normal operation
- cached_events: High values indicate API issues
- avg_response_time: Should be < 1000ms
```

## Troubleshooting

### Common Issues and Solutions

#### 1. Pattern Tracking Fails

**Symptoms**:
- `❌ [PatternTracker] API unavailable` messages
- High cache usage but low success rates
- Circuit breaker frequently tripping

**Solutions**:
1. Check Phase 4 API service:
   ```bash
   docker compose logs intelligence | tail -20
   ```

2. Verify network connectivity:
   ```bash
   curl -v http://localhost:8053/health
   ```

3. Check circuit breaker status:
   ```python
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   print(f"Circuit breaker state: {tracker.circuit_breaker.state}")
   ```

4. Clear cache if corrupted:
   ```python
   tracker.pattern_cache.clear()
   ```

#### 2. High Latency Issues

**Symptoms**:
- Pattern tracking taking > 5 seconds
- Timeout errors in logs
- High retry attempt counts

**Solutions**:
1. Check network latency:
   ```bash
   time curl http://localhost:8053/health
   ```

2. Monitor Phase 4 API performance:
   ```bash
   docker compose stats intelligence
   ```

3. Adjust timeout settings:
   ```python
   # In pattern_tracker.py
   self.timeout = 10.0  # Increase from default
   ```

#### 3. Memory Usage Issues

**Symptoms**:
- High memory consumption by pattern tracker
- Cache growing without bounds
- Memory leak warnings

**Solutions**:
1. Check cache size:
   ```python
   print(f"Cache entries: {len(tracker.pattern_cache.cache)}")
   ```

2. Clear old cache entries:
   ```python
   tracker.pattern_cache.cleanup()
   ```

3. Reduce cache size in configuration:
   ```yaml
   pattern_tracking:
     cache_size: 500  # Reduce from 1000
   ```

#### 4. Circuit Breaker Issues

**Symptoms**:
- Circuit breaker stuck in open state
- Requests failing even when service is healthy
- No automatic recovery

**Solutions**:
1. Manually reset circuit breaker:
   ```python
   tracker.circuit_breaker.reset()
   ```

2. Check for persistent network issues:
   ```bash
   # Monitor network connectivity
   while true; do
     curl -s http://localhost:8053/health > /dev/null
     echo $? $(date)
     sleep 5
   done
   ```

3. Adjust circuit breaker thresholds:
   ```yaml
   resilience:
     circuit_breaker:
       failure_threshold: 10  # Increase from 5
       recovery_timeout: 30   # Decrease from 60
   ```

### Advanced Debugging

#### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Create tracker with debug logging
tracker = PatternTracker(debug=True)
```

#### Monitor Internal State

```python
# Check all internal components
print("=== Circuit Breaker ===")
print(f"State: {tracker.circuit_breaker.state}")
print(f"Failure count: {tracker.circuit_breaker.failure_count}")
print(f"Last failure: {tracker.circuit_breaker.last_failure_time}")

print("\n=== Cache ===")
print(f"Size: {len(tracker.pattern_cache.cache)}")
print(f"Hit rate: {tracker.pattern_cache.hit_rate:.2%}")

print("\n=== Service Monitor ===")
print(f"Status: {tracker.service_monitor.get_service_status()}")
```

#### Performance Analysis

```python
import time

# Run performance test
start_time = time.time()
for i in range(100):
    tracker.track_pattern_creation(
        code="def test(): pass",
        context={"file_path": f"/test/test_{i}.py"}
    )
duration = time.time() - start_time

print(f"100 operations in {duration:.2f}s")
print(f"Average: {duration/100*1000:.1f}ms per operation")
```

## Maintenance

### Regular Maintenance Tasks

1. **Daily**:
   - Check error metrics and alert thresholds
   - Verify cache size and hit rates
   - Monitor circuit breaker status

2. **Weekly**:
   - Review performance trends
   - Clean up old log files
   - Update configuration if needed

3. **Monthly**:
   - Analyze long-term performance patterns
   - Review and update resilience parameters
   - Test failover procedures

### Configuration Updates

When updating configuration, follow this procedure:

1. **Backup current configuration**:
   ```bash
   cp config.yaml config.yaml.backup
   ```

2. **Apply changes gradually**:
   - Test in staging environment first
   - Monitor metrics after each change
   - Have rollback procedure ready

3. **Validate changes**:
   ```python
   # Test new configuration
   tracker = PatternTracker(config_path="new_config.yaml")
   health = tracker.get_health_summary()
   assert health["status"] == "healthy"
   ```

### Scaling Considerations

The pattern tracking system is designed to scale horizontally. Consider these factors when scaling:

1. **Cache Distribution**: Each instance maintains its own cache
2. **Circuit Breaker Coordination**: Multiple instances need coordinated circuit breaker state
3. **Metrics Aggregation**: Use centralized metrics collection
4. **Load Balancing**: Distribute load across multiple instances

## Integration Points

### With Claude Code Hooks

The system integrates with Claude Code through several hooks:

1. **PostToolUse Hook**: Automatically tracks patterns after file operations
2. **PreCommit Hook**: Validates code quality before commits
3. **User Prompt Hook**: Tracks user interactions and patterns

### With Phase 4 API

The system communicates with the Phase 4 Pattern Traceability API:

```python
# API Endpoints used:
POST /api/pattern-traceability/lineage/track  # Track patterns
GET  /health                                   # Health check
GET  /api/pattern-traceability/lineage/query   # Query patterns
```

### With Monitoring Systems

The system can integrate with external monitoring:

```python
# Example Prometheus integration
from prometheus_client import Counter, Histogram

# Define metrics
pattern_requests = Counter('pattern_requests_total', 'Total pattern requests')
pattern_duration = Histogram('pattern_duration_seconds', 'Pattern request duration')
```

## Security Considerations

### Data Protection

1. **Sensitive Data**: Pattern tracking data may contain code snippets
2. **Access Control**: Ensure proper authentication for API access
3. **Data Retention**: Implement proper data retention policies

### Network Security

1. **API Security**: Use HTTPS in production
2. **Rate Limiting**: Implement rate limiting for API calls
3. **Input Validation**: Validate all inputs to prevent injection attacks

### Operational Security

1. **Logging**: Ensure logs don't contain sensitive information
2. **Monitoring**: Monitor for unusual activity patterns
3. **Incident Response**: Have incident response procedures ready

## Future Enhancements

### Planned Improvements

1. **Multi-Region Support**: Distribute pattern tracking across regions
2. **Advanced Analytics**: Add machine learning for pattern analysis
3. **Real-time Dashboards**: Web-based monitoring dashboard
4. **Automated Tuning**: Self-adjusting resilience parameters
5. **Cross-Service Coordination**: Coordinate with other Claude Code services

### Extension Points

The system is designed to be extensible:

```python
# Custom resilience policies
class CustomResiliencePolicy:
    def should_retry(self, error, attempt):
        # Custom retry logic
        pass

    def get_delay(self, attempt):
        # Custom delay calculation
        pass

# Custom monitoring
class CustomMonitor:
    def record_metric(self, name, value, tags=None):
        # Custom metric recording
        pass
```

## Support

### Getting Help

1. **Documentation**: Check this guide and related documentation
2. **Logs**: Review system logs for error details
3. **Metrics**: Use monitoring dashboards to diagnose issues
4. **Community**: Engage with the Claude Code community

### Reporting Issues

When reporting issues, include:

1. **Environment**: OS, Python version, Claude Code version
2. **Configuration**: Relevant configuration settings
3. **Logs**: Full error logs and stack traces
4. **Steps to Reproduce**: Clear reproduction steps
5. **Expected vs Actual**: What you expected vs what happened

### Contributing

We welcome contributions to improve the pattern tracking resilience system:

1. **Code Style**: Follow existing code style and patterns
2. **Testing**: Include comprehensive tests for new features
3. **Documentation**: Update documentation for any changes
4. **Performance**: Ensure performance improvements are measured

---

This guide provides comprehensive documentation for operating and maintaining the enhanced pattern tracking resilience system. For specific issues not covered here, please consult the codebase or reach out to the development team.