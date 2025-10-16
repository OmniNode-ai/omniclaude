# Pattern Tracking Resilience Quick Reference

## Overview

This quick reference guide provides immediate access to the most commonly used commands and procedures for the enhanced pattern tracking resilience system.

## Essential Commands

### Health Checks

#### Quick Health Check
```bash
# Check if services are running
docker compose ps

# Check API health
curl -f http://localhost:8053/health

# Check pattern tracker health
python -c "from pattern_tracker import PatternTracker; print(PatternTracker().get_health_summary())"
```

#### Detailed Health Check
```bash
python -c "
from pattern_tracker import PatternTracker
tracker = PatternTracker()
health = tracker.get_health_summary()
metrics = tracker.get_error_metrics()

print('=== Health Summary ===')
for k, v in health.items():
    print(f'{k}: {v}')

print('\n=== Error Metrics ===')
for k, v in metrics.items():
    print(f'{k}: {v}')
"
```

### Performance Testing

#### Quick Performance Test
```bash
python -c "
from pattern_tracker import PatternTracker
import time

tracker = PatternTracker()
start = time.time()
pattern_id = tracker.track_pattern_creation(
    code='def test(): pass',
    context={'file_path': '/test/test.py'}
)
duration = time.time() - start

print(f'Time: {duration*1000:.1f}ms')
print(f'Success: {bool(pattern_id)}')
"
```

#### Load Test
```bash
python -c "
from pattern_tracker import PatternTracker
import time

tracker = PatternTracker()
print('Running load test (50 operations)...')
start = time.time()
success_count = 0

for i in range(50):
    try:
        pattern_id = tracker.track_pattern_creation(
            code=f'def test_{i}(): pass',
            context={'file_path': f'/test/test_{i}.py'}
        )
        if pattern_id:
            success_count += 1
    except Exception as e:
        print(f'Error on {i}: {e}')

duration = time.time() - start
print(f'Time: {duration:.2f}s')
print(f'Success: {success_count}/50 ({success_count/50:.1%})')
print(f'Avg: {duration/50*1000:.1f}ms/op')
"
```

### Troubleshooting

#### Quick Diagnostics
```bash
# Check recent errors
docker compose logs --tail=20 intelligence | grep -i error

# Check service status
docker compose stats intelligence

# Test API connectivity
time curl -s http://localhost:8053/health > /dev/null

# Check port availability
lsof -i :8053
```

#### Common Issues
```bash
# Service down
docker compose restart intelligence

# Circuit breaker tripped
python -c "from pattern_tracker import PatternTracker; PatternTracker().circuit_breaker.reset()"

# Clear cache
python -c "from pattern_tracker import PatternTracker; PatternTracker().pattern_cache.clear()"

# High memory usage
docker compose restart intelligence
```

## Configuration

### Environment Variables
```bash
# Enable/disable features
PATTERN_TRACKING_ENABLED=true
MONITORING_ENABLED=true
ALERTING_ENABLED=true

# Performance settings
PATTERN_TRACKING_TIMEOUT=5.0
PATTERN_TRACKING_CACHE_SIZE=1000
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60
```

### Key Configuration Files
- **Main Config**: `${HOME}/.claude/hooks/config.yaml`
- **Resilience Config**: `${HOME}/.claude/hooks/resilience.yaml`
- **Pattern Tracker**: `${HOME}/.claude/hooks/pattern_tracker.py`
- **Sync Version**: `${HOME}/.claude/hooks/lib/pattern_tracker_sync.py`

### Configuration Template
```yaml
pattern_tracking:
  enabled: true
  cache_size: 1000
  cache_ttl: 3600
  timeout: 5.0

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
  alerting_threshold: 0.8
```

## Monitoring

### Key Metrics to Monitor
- **Success Rate**: Should be > 95%
- **Response Time**: Should be < 1000ms
- **Circuit Breaker Trips**: Should be 0
- **Cache Hit Rate**: Should be > 80%
- **Memory Usage**: Should be < 1GB
- **CPU Usage**: Should be < 80%

### Monitoring Commands
```bash
# Check error metrics
python -c "
from pattern_tracker import PatternTracker
metrics = PatternTracker().get_error_metrics()
success_rate = metrics['successful_requests'] / metrics['total_requests']
print(f'Success Rate: {success_rate:.2%}')
print(f'Response Time: {metrics.get(\"avg_response_time_ms\", 0):.1f}ms')
"

# Check circuit breaker status
python -c "
from pattern_tracker import PatternTracker
cb = PatternTracker().circuit_breaker
print(f'State: {cb.state}')
print(f'Failures: {cb.failure_count}')
"

# Check cache status
python -c "
from pattern_tracker import PatternTracker
cache = PatternTracker().pattern_cache
print(f'Size: {len(cache.cache)}')
print(f'Hit Rate: {cache.hit_rate:.2%}')
"
```

## Emergency Procedures

### Service Recovery
```bash
# Quick restart
docker compose restart intelligence

# Full restart
docker compose down && docker compose up -d

# Reset circuit breaker
python -c "from pattern_tracker import PatternTracker; PatternTracker().circuit_breaker.reset()"

# Clear cache
python -c "from pattern_tracker import PatternTracker; PatternTracker().pattern_cache.clear()"
```

### Configuration Recovery
```bash
# Backup current config
cp config.yaml config.yaml.backup

# Restore from backup
cp config.yaml.backup config.yaml

# Restart with new config
docker compose restart
```

## Code Integration

### Basic Usage
```python
from pattern_tracker import PatternTracker

# Initialize tracker
tracker = PatternTracker()

# Track pattern
pattern_id = tracker.track_pattern_creation(
    code="def example(): pass",
    context={
        "file_path": "/path/to/file.py",
        "language": "python",
        "event_type": "pattern_created"
    }
)

print(f"Pattern tracked: {pattern_id}")
```

### Advanced Usage
```python
from pattern_tracker import PatternTracker

# Initialize with custom config
tracker = PatternTracker(config_path="custom_config.yaml")

# Track pattern with quality metadata
pattern_id = tracker.track_pattern_creation(
    code="def example(): pass",
    context={
        "file_path": "/path/to/file.py",
        "language": "python",
        "event_type": "pattern_created",
        "quality_score": 0.95,
        "violations_found": 0
    }
)

# Get health status
health = tracker.get_health_summary()

# Get error metrics
metrics = tracker.get_error_metrics()
```

### Sync Version Usage
```python
from pattern_tracker_sync import PatternTrackerSync

# Initialize sync tracker
tracker = PatternTrackerSync()

# Track pattern synchronously
pattern_id = tracker.track_pattern_creation(
    code="def example(): pass",
    context={
        "file_path": "/path/to/file.py",
        "language": "python"
    }
)

# Get performance metrics
metrics = tracker.get_performance_metrics()
```

## Hook Integration

### PostToolUse Hook
The pattern tracker integrates with Claude Code through the PostToolUse hook:

```bash
# Test hook integration
echo "print('test')" > /tmp/test.py
python post_tool_use_enforcer.py /tmp/test.py
```

### Hook Configuration
```yaml
# config.yaml
enforcement:
  post_tool_use_enabled: true

pattern_tracking:
  enabled: true
  track_on_write: true
  track_on_edit: true

quality:
  enabled: true
  auto_fix: true
```

## Error Handling

### Common Error Patterns

#### API Unavailable
```python
try:
    pattern_id = tracker.track_pattern_creation(
        code="def test(): pass",
        context={"file_path": "/test/test.py"}
    )
except Exception as e:
    print(f"Pattern tracking failed: {e}")
    # Check circuit breaker status
    print(f"Circuit breaker state: {tracker.circuit_breaker.state}")
```

#### Timeout Handling
```python
# Increase timeout for slow operations
tracker.timeout = 10.0

try:
    pattern_id = tracker.track_pattern_creation(
        code="def test(): pass",
        context={"file_path": "/test/test.py"}
    )
except Exception as e:
    if "timeout" in str(e).lower():
        print("Timeout occurred, retrying...")
    else:
        print(f"Other error: {e}")
```

#### Circuit Breaker Handling
```python
# Check circuit breaker state
cb = tracker.circuit_breaker
print(f"State: {cb.state}")
print(f"Failure count: {cb.failure_count}")

# Reset circuit breaker if needed
if cb.state == "open":
    cb.reset()
    print("Circuit breaker reset")
```

## Performance Optimization

### Caching Strategies
```python
# Check cache effectiveness
cache = tracker.pattern_cache
print(f"Cache size: {len(cache.cache)}")
print(f"Hit rate: {cache.hit_rate:.2%}")

# Clear cache if needed
cache.clear()

# Adjust cache size
cache.size = 2000  # Increase from default 1000
```

### Retry Strategies
```python
# Configure retry parameters
tracker.max_retries = 5
tracker.base_delay = 2.0  # Increase from default 1.0
tracker.max_delay = 60.0  # Increase from default 30.0

# Manually retry failed operations
for attempt in range(3):
    try:
        pattern_id = tracker.track_pattern_creation(
            code="def test(): pass",
            context={"file_path": "/test/test.py"}
        )
        break
    except Exception as e:
        print(f"Attempt {attempt + 1} failed: {e}")
        if attempt == 2:
            raise
        time.sleep(2 ** attempt)
```

## Logging and Debugging

### Enable Debug Logging
```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Create tracker with debug mode
tracker = PatternTracker(debug=True)

# Test operation
pattern_id = tracker.track_pattern_creation(
    code="def test(): pass",
    context={"file_path": "/test/test.py"}
)
```

### Log Analysis
```bash
# View recent logs
docker compose logs --tail=50 intelligence

# Filter for errors
docker compose logs --tail=100 intelligence | grep -i error

# Monitor in real-time
docker compose logs -f intelligence
```

## Best Practices

### Development
- Always test with small code samples first
- Use appropriate timeout values
- Monitor circuit breaker status
- Check cache effectiveness regularly
- Test both sync and async versions

### Operations
- Monitor key metrics continuously
- Set up automated alerts
- Test recovery procedures regularly
- Keep configuration backed up
- Document all changes

### Performance
- Use caching for frequently accessed patterns
- Monitor response times and success rates
- Adjust retry parameters based on network conditions
- Scale services based on demand
- Optimize database queries

## Contact and Support

### Documentation
- **Full Guide**: `PATTERN_TRACKING_RESILIENCE_GUIDE.md`
- **Runbook**: `PATTERN_TRACKING_RUNBOOK.md`
- **Troubleshooting**: `PATTERN_TRACKING_TROUBLESHOOTING.md`

### Quick Help
```bash
# Get help
python -c "from pattern_tracker import PatternTracker; help(PatternTracker())"

# Check version
python -c "from pattern_tracker import PatternTracker; print(PatternTracker().version)"

# Test basic functionality
python -c "
from pattern_tracker import PatternTracker
tracker = PatternTracker()
print('✅ Pattern tracker working correctly')
"
```

### Emergency Contacts
- **System Administrator**: admin@example.com
- **Development Team**: dev@example.com
- **Operations Team**: ops@example.com

---

This quick reference guide provides immediate access to the most commonly used commands and procedures. For detailed information, please refer to the full documentation.