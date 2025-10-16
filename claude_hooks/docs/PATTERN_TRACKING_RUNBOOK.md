# Pattern Tracking Runbook

## Emergency Response Procedures

### Critical Alert: Pattern Tracking Service Down

**Severity**: Critical
**Impact**: Pattern tracking not working, Claude Code hooks may fail
**Response Time**: Immediate (within 5 minutes)

#### Symptoms
- `❌ [PatternTracker] API unavailable` messages in logs
- Claude Code hooks failing or timing out
- High error rates in monitoring dashboards
- Circuit breaker in permanent open state

#### Immediate Actions
1. **Check Phase 4 API Status**:
   ```bash
   # Check if intelligence service is running
   docker compose ps intelligence

   # Check service health
   curl -f http://localhost:8053/health || echo "SERVICE DOWN"

   # View recent logs
   docker compose logs --tail=50 intelligence
   ```

2. **Restart Intelligence Service**:
   ```bash
   docker compose restart intelligence

   # Wait for service to start
   sleep 30

   # Verify health
   curl -f http://localhost:8053/health
   ```

3. **Check Pattern Tracker Health**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   health = tracker.get_health_summary()
   print('Status:', health['status'])
   print('API Available:', health['api_available'])
   print('Cache Size:', health['cache_size'])
   "
   ```

4. **If Still Down - Manual Intervention**:
   ```bash
   # Full restart of all services
   docker compose restart

   # Check system resources
   docker compose stats

   # Check for port conflicts
   lsof -i :8053
   ```

#### Escalation Path
- **Level 1**: Service restart (automated)
- **Level 2**: System administrator (15 minutes)
- **Level 3**: Development team (30 minutes)

---

### High Alert: Pattern Tracking Performance Degradation

**Severity**: High
**Impact**: Slow pattern tracking, degraded user experience
**Response Time**: Within 15 minutes

#### Symptoms
- Pattern tracking operations taking > 5 seconds
- Timeout errors in logs
- High retry attempt counts
- Increasing response times in metrics

#### Immediate Actions
1. **Check Performance Metrics**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   metrics = tracker.get_error_metrics()
   print('Total Requests:', metrics['total_requests'])
   print('Success Rate:', metrics['successful_requests']/metrics['total_requests']*100, '%')
   print('Circuit Breaker Trips:', metrics['circuit_breaker_trips'])
   print('Cached Events:', metrics['cached_events'])
   "
   ```

2. **Check Phase 4 API Performance**:
   ```bash
   # Test API response time
   time curl -s http://localhost:8053/health > /dev/null

   # Check service resource usage
   docker compose stats intelligence

   # Check for database issues
   docker compose logs --tail=20 memgraph
   docker compose logs --tail=20 qdrant
   ```

3. **Check Network Latency**:
   ```bash
   # Test network latency
   for i in {1..10}; do
     echo "Attempt $i:"
     time curl -s http://localhost:8053/health > /dev/null
     sleep 1
   done
   ```

4. **Adjust Timeout Settings** (if needed):
   ```python
   # Temporarily increase timeout
   tracker.timeout = 15.0  # Increase from default 5.0
   ```

#### Investigation Steps
1. Review recent changes to Phase 4 API
2. Check database performance and query times
3. Monitor network connectivity and latency
4. Check for resource contention (CPU, memory, disk I/O)

---

### Medium Alert: Circuit Breaker Frequently Tripping

**Severity**: Medium
**Impact**: Intermittent pattern tracking failures
**Response Time**: Within 30 minutes

#### Symptoms
- Circuit breaker tripping multiple times
- Intermittent API failures
- High cache usage
- `❌ [PatternTracker] Circuit breaker tripped` messages

#### Immediate Actions
1. **Check Circuit Breaker Status**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   cb = tracker.circuit_breaker
   print('State:', cb.state)
   print('Failure Count:', cb.failure_count)
   print('Last Failure:', cb.last_failure_time)
   print('Last Success:', cb.last_success_time)
   "
   ```

2. **Manually Reset Circuit Breaker**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   tracker.circuit_breaker.reset()
   print('Circuit breaker reset')
   "
   ```

3. **Check API Stability**:
   ```bash
   # Monitor API stability
   for i in {1..20}; do
     if curl -s http://localhost:8053/health > /dev/null; then
       echo "✅ Attempt $i: SUCCESS"
     else
       echo "❌ Attempt $i: FAILED"
     fi
     sleep 2
   done
   ```

4. **Adjust Circuit Breaker Thresholds** (if needed):
   ```yaml
   # In config.yaml
   resilience:
     circuit_breaker:
       failure_threshold: 10  # Increase from 5
       recovery_timeout: 30   # Decrease from 60
       half_open_attempts: 5 # Increase from 3
   ```

#### Investigation Steps
1. Check for intermittent network issues
2. Review Phase 4 API error logs
3. Monitor system resource usage
4. Check for database connection issues

---

### Low Alert: High Cache Usage

**Severity**: Low
**Impact**: Normal operation with caching fallback
**Response Time**: Within 1 hour

#### Symptoms
- High number of cached events
- Low cache hit rate
- Memory usage increasing
- `⚠️ [PatternTracker] High cache usage` messages

#### Immediate Actions
1. **Check Cache Status**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   cache = tracker.pattern_cache
   print('Cache Size:', len(cache.cache))
   print('Cache Hit Rate:', cache.hit_rate)
   print('Cache Size:', cache.size)
   print('Cache TTL:', cache.ttl)
   "
   ```

2. **Clear Cache** (if needed):
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   tracker.pattern_cache.clear()
   print('Cache cleared')
   "
   ```

3. **Adjust Cache Configuration**:
   ```yaml
   # In config.yaml
   pattern_tracking:
     cache_size: 500  # Reduce from 1000
     cache_ttl: 1800  # Reduce from 3600
   ```

#### Investigation Steps
1. Check Phase 4 API availability
2. Monitor cache growth patterns
3. Review cache hit rates
4. Consider increasing cache size if needed

---

## Standard Operating Procedures

### Daily Health Checks

#### Morning Checklist (9:00 AM)
1. **Service Health Check**:
   ```bash
   # Check all services are running
   docker compose ps

   # Check Phase 4 API health
   curl -f http://localhost:8053/health

   # Check pattern tracker health
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   health = tracker.get_health_summary()
   assert health['status'] == 'healthy'
   print('✅ All systems healthy')
   "
   ```

2. **Metrics Review**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   metrics = tracker.get_error_metrics()

   # Check key metrics
   success_rate = metrics['successful_requests'] / metrics['total_requests']
   print(f'Success Rate: {success_rate:.2%}')
   print(f'Circuit Breaker Trips: {metrics[\"circuit_breaker_trips\"]}')
   print(f'Cached Events: {metrics[\"cached_events\"]}')

   # Alert if metrics are out of bounds
   if success_rate < 0.95:
       print('⚠️ Low success rate detected')
   if metrics['circuit_breaker_trips'] > 0:
       print('⚠️ Circuit breaker trips detected')
   "
   ```

3. **Log Review**:
   ```bash
   # Check for error patterns
   docker compose logs --since=24h intelligence | grep -i error | tail -10

   # Check pattern tracker logs
   docker compose logs --since=24h archon-mcp | grep -i pattern | tail -10
   ```

#### Evening Checklist (5:00 PM)
1. **Performance Summary**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   metrics = tracker.get_error_metrics()

   print('=== Daily Performance Summary ===')
   print(f'Total Requests: {metrics[\"total_requests\"]}')
   print(f'Success Rate: {metrics[\"successful_requests\"]/metrics[\"total_requests\"]:.2%}')
   print(f'Average Response Time: {metrics[\"avg_response_time_ms\"]:.1f}ms')
   print(f'Circuit Breaker Trips: {metrics[\"circuit_breaker_trips\"]}')
   print(f'Cache Hit Rate: {metrics[\"cache_hit_rate\"]:.2%}')
   "
   ```

2. **Resource Usage Check**:
   ```bash
   docker compose stats --no-stream
   ```

3. **Backup Configuration**:
   ```bash
   # Backup current configuration
   cp config.yaml config.yaml.backup.$(date +%Y%m%d)
   ```

### Weekly Maintenance

#### Sunday Maintenance Window (2:00 AM - 4:00 AM)

1. **Service Restart**:
   ```bash
   # Graceful restart of all services
   docker compose restart

   # Wait for services to stabilize
   sleep 60

   # Verify all services are healthy
   curl -f http://localhost:8053/health
   ```

2. **Log Rotation**:
   ```bash
   # Rotate and compress old logs
   find /var/log/docker -name "*.log" -mtime +7 -exec gzip {} \;

   # Clean up old logs
   find /var/log/docker -name "*.log.gz" -mtime +30 -delete
   ```

3. **Cache Maintenance**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()

   # Clear old cache entries
   tracker.pattern_cache.cleanup()

   # Reset error metrics
   tracker.error_metrics = {
       'total_requests': 0,
       'successful_requests': 0,
       'failed_requests': 0,
       'cached_events': 0,
       'circuit_breaker_trips': 0,
       'retry_attempts': 0
   }
   print('Cache cleaned and metrics reset')
   "
   ```

4. **Performance Test**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   import time

   tracker = PatternTracker()

   # Run performance test
   start_time = time.time()
   for i in range(50):
       tracker.track_pattern_creation(
           code='def test(): pass',
           context={'file_path': f'/test/test_{i}.py'}
       )
   duration = time.time() - start_time

   print(f'50 operations in {duration:.2f}s')
   print(f'Average: {duration/50*1000:.1f}ms per operation')

   # Assert performance is acceptable
   assert duration/50 < 1.0, 'Performance degradation detected'
   "
   ```

5. **Configuration Review**:
   ```bash
   # Review configuration files
   echo "=== Configuration Review ==="
   cat config.yaml | grep -E "(timeout|cache|circuit_breaker|retry)"

   # Check for configuration drift
   diff config.yaml config.yaml.backup.$(date +%Y%m%d --date='last sunday')
   ```

### Monthly Maintenance

#### First Sunday of Month (2:00 AM - 6:00 AM)

1. **System Updates**:
   ```bash
   # Update Docker images
   docker compose pull

   # Restart with updated images
   docker compose up -d --force-recreate
   ```

2. **Database Maintenance**:
   ```bash
   # Database backup
   docker compose exec memgraph neo4j-admin backup --to=/tmp/backup

   # Database optimization
   docker compose exec memgraph neo4j-admin optimize
   ```

3. **Comprehensive Performance Test**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   import time
   import random

   tracker = PatternTracker()

   # Load test
   print('=== Load Test ===')
   start_time = time.time()
   for i in range(1000):
       tracker.track_pattern_creation(
           code=f'def test_{i}(): pass',
           context={'file_path': f'/test/test_{i}.py'}
       )
       if i % 100 == 0:
           print(f'Completed {i} operations')
   duration = time.time() - start_time

   print(f'1000 operations in {duration:.2f}s')
   print(f'Average: {duration/1000*1000:.1f}ms per operation')
   print(f'Operations per second: {1000/duration:.1f}')
   "
   ```

4. **Security Audit**:
   ```bash
   # Check for security vulnerabilities
   docker compose exec intelligence pip-audit

   # Check file permissions
   ls -la ${HOME}/.claude/hooks/

   # Check for exposed credentials
   grep -r "password\|secret\|key" ${HOME}/.claude/hooks/ --exclude-dir=.git
   ```

5. **Documentation Update**:
   ```bash
   # Update documentation with current configuration
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()

   # Generate current configuration
   config = {
       'timeout': tracker.timeout,
       'base_url': tracker.base_url,
       'cache_size': tracker.pattern_cache.size,
       'circuit_breaker': {
           'failure_threshold': tracker.circuit_breaker.failure_threshold,
           'recovery_timeout': tracker.circuit_breaker.recovery_timeout
       }
   }

   print('Current Configuration:')
   import json
   print(json.dumps(config, indent=2))
   "
   ```

---

## Disaster Recovery Procedures

### Scenario 1: Complete System Failure

#### Recovery Steps
1. **Assess Damage**:
   ```bash
   # Check which services are down
   docker compose ps

   # Check system resources
   htop
   df -h

   # Check network connectivity
   ping -c 4 localhost
   ```

2. **Restore from Backup**:
   ```bash
   # Stop all services
   docker compose down

   # Restore configuration
   cp config.yaml.backup config.yaml

   # Restart services
   docker compose up -d

   # Wait for services to start
   sleep 60

   # Verify health
   curl -f http://localhost:8053/health
   ```

3. **Test Pattern Tracking**:
   ```bash
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()

   # Test basic functionality
   pattern_id = tracker.track_pattern_creation(
       code='def test(): pass',
       context={'file_path': '/test/recovery_test.py'}
   )

   if pattern_id:
       print('✅ Pattern tracking recovered successfully')
   else:
       print('❌ Pattern tracking still failing')
   "
   ```

4. **Notify Stakeholders**:
   ```bash
   # Send notification
   echo "Pattern tracking system recovered at $(date)" | mail -s "System Recovery Complete" admin@example.com
   ```

### Scenario 2: Database Corruption

#### Recovery Steps
1. **Identify Corrupted Database**:
   ```bash
   # Check database logs
   docker compose logs --tail=50 memgraph

   # Try database connection
   docker compose exec memgraph neo4j-client "MATCH (n) RETURN count(n) LIMIT 1"
   ```

2. **Restore Database Backup**:
   ```bash
   # Stop database service
   docker compose stop memgraph

   # Restore from backup
   docker compose exec memgraph neo4j-admin restore --from=/tmp/backup

   # Start database service
   docker compose start memgraph
   ```

3. **Verify Data Integrity**:
   ```bash
   # Check pattern data
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()

   # Test pattern query
   patterns = tracker.query_patterns(limit=10)
   print(f'Found {len(patterns)} patterns')
   "
   ```

### Scenario 3: Network Partition

#### Recovery Steps
1. **Diagnose Network Issue**:
   ```bash
   # Test network connectivity
   ping -c 4 localhost
   ping -c 4 google.com

   # Check port availability
   lsof -i :8053
   netstat -an | grep 8053
   ```

2. **Restore Network Connectivity**:
   ```bash
   # Restart network services
   sudo systemctl restart networking

   # Restart Docker services
   sudo systemctl restart docker

   # Restart our services
   docker compose restart
   ```

3. **Test Service Communication**:
   ```bash
   # Test API connectivity
   curl -f http://localhost:8053/health

   # Test pattern tracking
   python -c "
   from pattern_tracker import PatternTracker
   tracker = PatternTracker()
   health = tracker.get_health_summary()
   print('Status:', health['status'])
   "
   ```

---

## Contact Information

### Emergency Contacts
- **System Administrator**: admin@example.com
- **Development Team**: dev@example.com
- **Operations Team**: ops@example.com

### Documentation
- **Resilience Guide**: `${HOME}/.claude/hooks/docs/PATTERN_TRACKING_RESILIENCE_GUIDE.md`
- **API Documentation**: `${HOME}/.claude/hooks/docs/API_REFERENCE.md`
- **Troubleshooting Guide**: `${HOME}/.claude/hooks/docs/TROUBLESHOOTING.md`

### Monitoring Dashboards
- **System Health**: http://localhost:3000/d/pattern-tracking
- **Performance Metrics**: http://localhost:3000/d/pattern-performance
- **Error Rates**: http://localhost:3000/d/pattern-errors

---

## Appendix

### Useful Commands
```bash
# Check service status
docker compose ps

# View service logs
docker compose logs -f [service-name]

# Restart specific service
docker compose restart [service-name]

# Check system resources
htop
df -h
free -m

# Test API connectivity
curl -f http://localhost:8053/health

# Check pattern tracker health
python -c "from pattern_tracker import PatternTracker; print(PatternTracker().get_health_summary())"
```

### Configuration Files
- **Main Config**: `${HOME}/.claude/hooks/config.yaml`
- **Resilience Config**: `${HOME}/.claude/hooks/resilience.yaml`
- **Logging Config**: `${HOME}/.claude/hooks/logging.yaml`

### Log Files
- **Pattern Tracker**: `/var/log/pattern-tracker.log`
- **Service Logs**: `docker compose logs [service-name]`
- **System Logs**: `/var/log/syslog`

### Performance Benchmarks
- **Normal Operation**: < 100ms per pattern tracking operation
- **Acceptable Degradation**: < 500ms per operation
- **Critical Threshold**: > 1000ms per operation
- **Success Rate**: > 95% under normal conditions
- **Cache Hit Rate**: > 80% when API is available

---

This runbook provides comprehensive procedures for operating and maintaining the pattern tracking resilience system. All procedures should be followed in order, and all incidents should be documented for future analysis and improvement.