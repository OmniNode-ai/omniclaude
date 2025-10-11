# Pattern Tracking Troubleshooting Guide

## Quick Reference

### Common Error Messages

#### API Connection Issues
```
❌ [PatternTracker] API unavailable: ConnectionError
❌ [PatternTracker] Connection failed: Connection refused
❌ [PatternTracker] API unreachable: HTTPConnectionPool
```

**Immediate Actions**:
1. Check if intelligence service is running: `docker compose ps intelligence`
2. Verify API health: `curl http://localhost:8053/health`
3. Restart service: `docker compose restart intelligence`

#### Timeout Issues
```
❌ [PatternTracker] Timeout after 5s: timeout error
❌ [PatternTracker] Request timed out
```

**Immediate Actions**:
1. Check API response time: `time curl http://localhost:8053/health`
2. Increase timeout: `tracker.timeout = 10.0`
3. Check system resources: `htop`

#### Circuit Breaker Issues
```
❌ [PatternTracker] Circuit breaker tripped
❌ [PatternTracker] Circuit breaker is open
```

**Immediate Actions**:
1. Check circuit breaker status: `tracker.circuit_breaker.state`
2. Manually reset: `tracker.circuit_breaker.reset()`
3. Check API stability: Monitor for intermittent failures

#### Cache Issues
```
⚠️ [PatternTracker] High cache usage
⚠️ [PatternTracker] Cache hit rate low
```

**Immediate Actions**:
1. Check cache status: `len(tracker.pattern_cache.cache)`
2. Clear cache: `tracker.pattern_cache.clear()`
3. Adjust cache size in config

### Performance Issues

#### Slow Pattern Tracking
**Symptoms**: Operations taking > 1 second

**Diagnostic Commands**:
```bash
# Check API response time
time curl http://localhost:8053/health

# Check system resources
docker compose stats intelligence

# Check database performance
docker compose logs --tail=20 memgraph
```

**Solutions**:
1. Increase timeout: `tracker.timeout = 15.0`
2. Restart intelligence service: `docker compose restart intelligence`
3. Check network connectivity: `ping -c 4 localhost`

#### High Memory Usage
**Symptoms**: Memory usage > 1GB, system slowdown

**Diagnostic Commands**:
```bash
# Check memory usage
htop
docker compose stats intelligence

# Check cache size
python -c "from pattern_tracker import PatternTracker; print(len(PatternTracker().pattern_cache.cache))"
```

**Solutions**:
1. Clear cache: `tracker.pattern_cache.clear()`
2. Reduce cache size in config
3. Restart service: `docker compose restart intelligence`

#### High CPU Usage
**Symptoms**: CPU usage > 80%, slow response times

**Diagnostic Commands**:
```bash
# Check CPU usage
htop
docker compose stats intelligence

# Check process activity
top -p $(pgrep -f intelligence)
```

**Solutions**:
1. Restart service: `docker compose restart intelligence`
2. Check for infinite loops or resource leaks
3. Scale service if needed

## Diagnostic Commands

### Health Checks

#### Basic Health Check
```bash
# Check if all services are running
docker compose ps

# Check Phase 4 API health
curl -f http://localhost:8053/health

# Check pattern tracker health
python -c "
from pattern_tracker import PatternTracker
tracker = PatternTracker()
health = tracker.get_health_summary()
print('Status:', health['status'])
print('API Available:', health['api_available'])
print('Cache Size:', health['cache_size'])
"
```

#### Detailed Health Check
```bash
python -c "
from pattern_tracker import PatternTracker
tracker = PatternTracker()

print('=== Circuit Breaker ===')
print('State:', tracker.circuit_breaker.state)
print('Failure Count:', tracker.circuit_breaker.failure_count)

print('\n=== Cache ===')
print('Size:', len(tracker.pattern_cache.cache))
print('Hit Rate:', tracker.pattern_cache.hit_rate)

print('\n=== Service Monitor ===')
print('Status:', tracker.service_monitor.get_service_status())

print('\n=== Error Metrics ===')
metrics = tracker.get_error_metrics()
for key, value in metrics.items():
    print(f'{key}: {value}')
"
```

### Performance Testing

#### Basic Performance Test
```bash
python -c "
from pattern_tracker import PatternTracker
import time

tracker = PatternTracker()

# Test single operation
start = time.time()
pattern_id = tracker.track_pattern_creation(
    code='def test(): pass',
    context={'file_path': '/test/test.py'}
)
duration = time.time() - start

print(f'Single operation: {duration*1000:.1f}ms')
print(f'Pattern ID: {pattern_id}')
"
```

#### Load Test
```bash
python -c "
from pattern_tracker import PatternTracker
import time

tracker = PatternTracker()

print('Load test: 100 operations')
start = time.time()
success_count = 0

for i in range(100):
    try:
        pattern_id = tracker.track_pattern_creation(
            code=f'def test_{i}(): pass',
            context={'file_path': f'/test/test_{i}.py'}
        )
        if pattern_id:
            success_count += 1
    except Exception as e:
        print(f'Operation {i} failed: {e}')

duration = time.time() - start
success_rate = success_count / 100

print(f'Total time: {duration:.2f}s')
print(f'Average per operation: {duration/100*1000:.1f}ms')
print(f'Success rate: {success_rate:.2%}')
print(f'Operations per second: {100/duration:.1f}')
"
```

### Error Diagnosis

#### Check Recent Errors
```bash
# Check service logs for errors
docker compose logs --tail=50 intelligence | grep -i error

# Check pattern tracker errors
docker compose logs --tail=50 archon-mcp | grep -i pattern

# Check system logs
journalctl -u docker --since "1 hour ago" | grep -i error
```

#### Test API Endpoints
```bash
# Test health endpoint
curl -v http://localhost:8053/health

# Test pattern tracking endpoint
curl -v -X POST http://localhost:8053/api/pattern-traceability/lineage/track \
  -H "Content-Type: application/json" \
  -d '{"event_type": "test", "pattern_id": "test", "pattern_name": "test"}'

# Test pattern query endpoint
curl -v "http://localhost:8053/api/pattern-traceability/lineage/query?limit=10"
```

## Configuration Issues

### Common Configuration Problems

#### Incorrect API URL
**Symptoms**: Connection refused, host not found errors

**Solution**:
```bash
# Check current API URL
python -c "
from pattern_tracker import PatternTracker
print('API URL:', PatternTracker().base_url)
"

# Update in config.yaml
echo "intelligence_url: http://localhost:8053" >> config.yaml
```

#### Incorrect Timeout Settings
**Symptoms**: Frequent timeout errors

**Solution**:
```bash
# Check current timeout
python -c "
from pattern_tracker import PatternTracker
print('Timeout:', PatternTracker().timeout)
"

# Update timeout in pattern_tracker.py
# Edit line: self.timeout = 10.0  # Increase from 5.0
```

#### Incorrect Cache Settings
**Symptoms**: Memory issues, cache misses

**Solution**:
```yaml
# In config.yaml
pattern_tracking:
  cache_size: 500  # Reduce if memory issues
  cache_ttl: 1800  # Reduce if stale data
```

### Configuration Validation

#### Validate Configuration
```bash
python -c "
from pattern_tracker import PatternTracker
try:
    tracker = PatternTracker()
    health = tracker.get_health_summary()
    print('✅ Configuration valid')
    print('Health status:', health['status'])
except Exception as e:
    print('❌ Configuration error:', e)
"
```

#### Test Configuration Changes
```bash
# Test new configuration before deploying
python -c "
import tempfile
import yaml

# Load current config
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Modify config
config['resilience']['circuit_breaker']['failure_threshold'] = 10

# Test config
with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml') as f:
    yaml.dump(config, f)
    f.flush()

    try:
        tracker = PatternTracker(config_path=f.name)
        print('✅ Configuration test successful')
    except Exception as e:
        print('❌ Configuration test failed:', e)
"
```

## Network Issues

### Common Network Problems

#### Port Conflicts
**Symptoms**: Address already in use, connection refused

**Diagnostic**:
```bash
# Check if port is available
lsof -i :8053
netstat -an | grep 8053
```

**Solution**:
```bash
# Kill process using port
kill -9 $(lsof -ti:8053)

# Or change port in config.yaml
echo "intelligence_port: 8054" >> config.yaml
```

#### Firewall Issues
**Symptoms**: Connection timeout, network unreachable

**Diagnostic**:
```bash
# Check firewall status
sudo ufw status

# Test connectivity
telnet localhost 8053
nc -z localhost 8053
```

**Solution**:
```bash
# Allow port through firewall
sudo ufw allow 8053

# Or disable firewall (temporary)
sudo ufw disable
```

#### DNS Issues
**Symptoms**: Host not found, name resolution failed

**Diagnostic**:
```bash
# Test DNS resolution
nslookup localhost
dig localhost

# Check hosts file
cat /etc/hosts | grep localhost
```

**Solution**:
```bash
# Add entry to hosts file
echo "127.0.0.1 localhost" | sudo tee -a /etc/hosts
```

## Database Issues

### Common Database Problems

#### Database Connection Issues
**Symptoms**: Connection refused, authentication failed

**Diagnostic**:
```bash
# Check database service
docker compose ps memgraph

# Check database logs
docker compose logs --tail=20 memgraph

# Test database connection
docker compose exec memgraph neo4j-client "MATCH (n) RETURN count(n) LIMIT 1"
```

**Solution**:
```bash
# Restart database
docker compose restart memgraph

# Check database configuration
docker compose exec memgraph cat /etc/neo4j/neo4j.conf
```

#### Database Performance Issues
**Symptoms**: Slow queries, high response times

**Diagnostic**:
```bash
# Check database performance
docker compose stats memgraph

# Check slow queries
docker compose logs --tail=50 memgraph | grep -i slow

# Monitor database connections
docker compose exec memgraph neo4j-client "SHOW DATABASES"
```

**Solution**:
```bash
# Optimize database
docker compose exec memgraph neo4j-admin optimize

# Clear cache
docker compose exec memgraph neo4j-admin cache clear

# Increase database resources
# Update docker-compose.yml with higher memory limits
```

## Resource Issues

### Memory Issues

#### Memory Leaks
**Symptoms**: Memory usage grows continuously, system slowdown

**Diagnostic**:
```bash
# Monitor memory usage
htop

# Check memory growth over time
watch -n 5 'docker compose stats intelligence'

# Check for memory leaks
valgrind --leak-check=full python -c "
from pattern_tracker import PatternTracker
tracker = PatternTracker()
tracker.track_pattern_creation(
    code=\"def test(): pass\",
    context={\"file_path\": \"/test/test.py\"}
)
"
```

**Solution**:
```bash
# Restart service
docker compose restart intelligence

# Clear cache
python -c "
from pattern_tracker import PatternTracker
tracker = PatternTracker()
tracker.pattern_cache.clear()
"

# Increase memory limits
# Update docker-compose.yml
```

#### High Memory Usage
**Symptoms**: Memory usage > 80%, system unresponsive

**Diagnostic**:
```bash
# Check memory usage
free -m
docker compose stats

# Find memory-intensive processes
ps aux --sort=-%mem | head -10
```

**Solution**:
```bash
# Clear caches
sync && echo 1 > /proc/sys/vm/drop_caches

# Restart services
docker compose restart

# Increase system memory
# Add more RAM to system
```

### CPU Issues

#### High CPU Usage
**Symptoms**: CPU usage > 80%, slow response times

**Diagnostic**:
```bash
# Check CPU usage
htop
docker compose stats

# Find CPU-intensive processes
ps aux --sort=-%cpu | head -10

# Check process threads
top -H -p $(pgrep -f intelligence)
```

**Solution**:
```bash
# Restart service
docker compose restart intelligence

# Check for infinite loops
# Review code for loops without exit conditions

# Scale service
# Add more CPU cores or instances
```

#### CPU Spikes
**Symptoms**: Intermittent high CPU usage

**Diagnostic**:
```bash
# Monitor CPU usage over time
sar -u 1 10

# Check for scheduled tasks
crontab -l

# Check for background processes
ps aux | grep -i intelligence
```

**Solution**:
```bash
# Identify and optimize resource-intensive operations
# Review code for inefficient algorithms
# Add caching for expensive operations
```

## Debugging Techniques

### Enable Debug Logging

#### Pattern Tracker Debug
```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Create tracker with debug mode
tracker = PatternTracker(debug=True)

# Test with debug output
tracker.track_pattern_creation(
    code="def test(): pass",
    context={"file_path": "/test/debug.py"}
)
```

#### Service Debug
```bash
# Enable debug logging for services
docker compose logs -f intelligence --tail=100

# Check service configuration
docker compose exec intelligence env

# Monitor service activity
docker compose top intelligence
```

### Step-by-Step Debugging

#### Pattern Creation Debug
```python
from pattern_tracker import PatternTracker
import traceback

tracker = PatternTracker(debug=True)

try:
    print("Step 1: Creating pattern...")
    pattern_id = tracker.track_pattern_creation(
        code="def test(): pass",
        context={"file_path": "/test/debug.py"}
    )
    print(f"Step 1 Complete: Pattern ID = {pattern_id}")

except Exception as e:
    print(f"Error occurred: {e}")
    print("Stack trace:")
    traceback.print_exc()
```

#### API Debug
```python
import httpx
import json

# Test API directly
try:
    response = httpx.post(
        "http://localhost:8053/api/pattern-traceability/lineage/track",
        json={
            "event_type": "test",
            "pattern_id": "test-debug",
            "pattern_name": "test",
            "pattern_type": "code",
            "pattern_data": {
                "code": "def test(): pass",
                "language": "python",
                "file_path": "/test/debug.py"
            }
        },
        timeout=10.0
    )
    print(f"API Response: {response.status_code}")
    print(f"Response body: {response.text}")
except Exception as e:
    print(f"API Error: {e}")
    traceback.print_exc()
```

### Performance Profiling

#### Profile Pattern Tracking
```python
import cProfile
import pstats
from pattern_tracker import PatternTracker

# Create profiler
profiler = cProfile.Profile()
profiler.enable()

# Run performance test
tracker = PatternTracker()
for i in range(100):
    tracker.track_pattern_creation(
        code=f"def test_{i}(): pass",
        context={"file_path": f"/test/test_{i}.py"}
    )

# Stop profiler and show results
profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)
```

#### Memory Profiling
```python
import tracemalloc
from pattern_tracker import PatternTracker

# Start memory tracing
tracemalloc.start()

# Run operations
tracker = PatternTracker()
for i in range(100):
    tracker.track_pattern_creation(
        code=f"def test_{i}(): pass",
        context={"file_path": f"/test/test_{i}.py"}
    )

# Get memory statistics
snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')

print("Top memory allocations:")
for stat in top_stats[:10]:
    print(stat)
```

## Recovery Procedures

### Emergency Recovery

#### Quick Recovery
```bash
# 1. Restart all services
docker compose restart

# 2. Wait for services to start
sleep 30

# 3. Verify health
curl -f http://localhost:8053/health

# 4. Test pattern tracking
python -c "
from pattern_tracker import PatternTracker
tracker = PatternTracker()
pattern_id = tracker.track_pattern_creation(
    code='def test(): pass',
    context={'file_path': '/test/recovery.py'}
)
print('Recovery test:', 'SUCCESS' if pattern_id else 'FAILED')
"
```

#### Full Recovery
```bash
# 1. Stop all services
docker compose down

# 2. Clear caches and temporary files
docker system prune -f
docker volume prune -f

# 3. Restore configuration
cp config.yaml.backup config.yaml

# 4. Start services
docker compose up -d

# 5. Wait for services to stabilize
sleep 60

# 6. Verify all services
curl -f http://localhost:8053/health

# 7. Test functionality
python -c "
from pattern_tracker import PatternTracker
tracker = PatternTracker()
health = tracker.get_health_summary()
assert health['status'] == 'healthy'
print('✅ Full recovery complete')
"
```

### Configuration Recovery

#### Restore Default Configuration
```bash
# Backup current config
cp config.yaml config.yaml.broken

# Restore default config
cp config.yaml.example config.yaml

# Edit configuration as needed
nano config.yaml

# Test configuration
python -c "
from pattern_tracker import PatternTracker
try:
    tracker = PatternTracker()
    print('✅ Configuration valid')
except Exception as e:
    print('❌ Configuration error:', e)
"
```

#### Reset Circuit Breaker
```python
from pattern_tracker import PatternTracker

tracker = PatternTracker()

# Reset circuit breaker
tracker.circuit_breaker.reset()

# Clear error metrics
tracker.error_metrics = {
    'total_requests': 0,
    'successful_requests': 0,
    'failed_requests': 0,
    'cached_events': 0,
    'circuit_breaker_trips': 0,
    'retry_attempts': 0
}

print('✅ Circuit breaker reset complete')
```

## Preventive Measures

### Monitoring Setup

#### Health Check Script
```bash
#!/bin/bash
# health_check.sh

# Check service health
if ! curl -f http://localhost:8053/health > /dev/null 2>&1; then
    echo "❌ Phase 4 API is down"
    docker compose restart intelligence
    sleep 30
fi

# Check pattern tracker
python -c "
from pattern_tracker import PatternTracker
try:
    tracker = PatternTracker()
    health = tracker.get_health_summary()
    if health['status'] != 'healthy':
        raise Exception(f'Unhealthy status: {health[\"status\"]}')
    print('✅ Pattern tracker healthy')
except Exception as e:
    print(f'❌ Pattern tracker error: {e}')
    exit(1)
"

# Check resources
if docker compose stats --no-stream intelligence | grep -q '100%'; then
    echo "⚠️ High resource usage detected"
fi

echo "✅ Health check complete"
```

#### Performance Monitoring
```python
#!/usr/bin/env python3
# monitor_performance.py

import time
import json
from datetime import datetime
from pattern_tracker import PatternTracker

def monitor_performance():
    tracker = PatternTracker()

    while True:
        try:
            metrics = tracker.get_error_metrics()
            health = tracker.get_health_summary()

            # Calculate key metrics
            success_rate = metrics['successful_requests'] / max(metrics['total_requests'], 1)
            avg_response_time = metrics.get('avg_response_time_ms', 0)

            # Log metrics
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'success_rate': success_rate,
                'avg_response_time': avg_response_time,
                'cache_size': health['cache_size'],
                'api_available': health['api_available'],
                'status': health['status']
            }

            print(json.dumps(log_entry))

            # Alert if metrics are concerning
            if success_rate < 0.9:
                print(f"⚠️ Low success rate: {success_rate:.2%}")
            if avg_response_time > 1000:
                print(f"⚠️ High response time: {avg_response_time:.1f}ms")
            if not health['api_available']:
                print("⚠️ API unavailable")

            time.sleep(60)  # Check every minute

        except Exception as e:
            print(f"❌ Monitoring error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    monitor_performance()
```

### Regular Maintenance

#### Automated Cleanup Script
```bash
#!/bin/bash
# cleanup.sh

# Clear old logs
find /var/log -name "*.log" -mtime +7 -delete

# Clean up Docker resources
docker system prune -f
docker volume prune -f

# Restart services if needed
if docker compose stats --no-stream | grep -q '100%'; then
    echo "Restarting services due to high resource usage"
    docker compose restart
fi

# Backup configuration
cp config.yaml config.yaml.backup.$(date +%Y%m%d)

echo "✅ Cleanup complete"
```

#### Configuration Validation Script
```python
#!/usr/bin/env python3
# validate_config.py

import yaml
from pattern_tracker import PatternTracker

def validate_config():
    try:
        # Load configuration
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)

        # Validate required fields
        required_fields = ['intelligence_url', 'pattern_tracking', 'resilience']
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Missing required field: {field}")

        # Test pattern tracker with config
        tracker = PatternTracker()
        health = tracker.get_health_summary()

        if health['status'] != 'healthy':
            raise ValueError(f"Unhealthy status: {health['status']}")

        print("✅ Configuration validation successful")
        return True

    except Exception as e:
        print(f"❌ Configuration validation failed: {e}")
        return False

if __name__ == "__main__":
    validate_config()
```

## Best Practices

### Development
- Always test configuration changes in development first
- Use version control for all configuration changes
- Implement proper error handling in all custom code
- Log all significant operations for debugging
- Use appropriate timeout values for all API calls

### Operations
- Monitor system metrics continuously
- Set up automated alerts for critical issues
- Document all operational procedures
- Test disaster recovery procedures regularly
- Keep systems and dependencies up to date

### Performance
- Monitor response times and success rates
- Use caching appropriately to reduce API load
- Implement proper resource limits
- Scale services based on demand
- Optimize database queries and indexes

### Security
- Use secure authentication for all API calls
- Implement proper access controls
- Monitor for suspicious activity
- Keep software dependencies updated
- Use encrypted connections for all network communication

---

This troubleshooting guide provides comprehensive procedures for diagnosing and resolving issues with the pattern tracking resilience system. For additional support, consult the runbook or contact the development team.