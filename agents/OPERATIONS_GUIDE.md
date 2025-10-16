# Phase 7 Operations Guide

**Version**: 1.0
**Status**: Production Ready
**Date**: 2025-10-15

---

## Table of Contents

1. [Deployment](#deployment)
2. [Configuration](#configuration)
3. [Monitoring](#monitoring)
4. [Troubleshooting](#troubleshooting)
5. [Maintenance](#maintenance)
6. [Performance Tuning](#performance-tuning)
7. [Backup and Recovery](#backup-and-recovery)
8. [Security](#security)

---

## Deployment

### Prerequisites

#### System Requirements
- **Python**: 3.11 or higher
- **PostgreSQL**: 12 or higher (14+ recommended)
- **Memory**: 4GB minimum, 8GB recommended
- **CPU**: 4 cores minimum for parallel execution
- **Disk**: 10GB for databases, logs, and cache

#### Dependencies
```bash
# Core dependencies
pip install asyncpg>=0.29.0
pip install pydantic>=2.0.0
pip install pyyaml>=6.0.0

# Optional monitoring dependencies
pip install prometheus-client>=0.19.0  # For Prometheus export
```

### Initial Setup

#### 1. Database Setup

```bash
# Set database password
export PGPASSWORD="your-secure-password"

# Create database (if not exists)
psql -h localhost -p 5432 -U postgres -c "CREATE DATABASE omninode_bridge;"

# Apply Phase 7 migration
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/006_phase7_schema_enhancements.sql

# Verify migration
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -c "SELECT version, description FROM schema_migrations WHERE version = 6;"

# Expected output:
# version |                                description
#---------+---------------------------------------------------------------------------
#       6 | Phase 7: Add mixin learning, pattern feedback, performance metrics...
```

#### 2. Configuration Files

**Create `agents/configs/deployment.yaml`**:
```yaml
# Deployment configuration
environment: production  # or development, staging

database:
  host: localhost
  port: 5432
  database: omninode_bridge
  user: postgres
  password_env: POSTGRES_PASSWORD  # Read from environment
  pool_size: 20
  pool_max: 50

template_cache:
  enabled: true
  max_templates: 100
  max_size_mb: 50
  ttl_seconds: 3600
  enable_persistence: true

parallel_generation:
  enabled: true
  max_workers: 4  # Adjust based on CPU cores
  worker_timeout_seconds: 300

monitoring:
  enabled: true
  metric_retention_points: 1000
  health_check_interval_seconds: 60

logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: json  # json or text
  rotation:
    max_bytes: 104857600  # 100MB
    backup_count: 30
```

#### 3. Environment Variables

**Create `.env` file**:
```bash
# Database
POSTGRES_PASSWORD=your-secure-password
DATABASE_URL=postgresql://postgres:${POSTGRES_PASSWORD}@localhost:5432/omninode_bridge

# Monitoring
MONITORING_ENABLED=true
ALERT_WEBHOOK_URL=https://your-webhook-url.com/alerts

# Logging
LOG_LEVEL=INFO
LOG_DIR=/var/log/omniclaude/agents
```

**Load environment**:
```bash
# Option 1: Export manually
export $(cat .env | xargs)

# Option 2: Use python-dotenv
pip install python-dotenv
# Add to your code:
# from dotenv import load_dotenv
# load_dotenv()
```

### Deployment Steps

#### Production Deployment

```bash
# 1. Clone repository
git clone https://github.com/your-org/omniclaude.git
cd omniclaude/agents

# 2. Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up database
export PGPASSWORD="your-secure-password"
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -f parallel_execution/migrations/006_phase7_schema_enhancements.sql

# 5. Run database tests
python -m pytest tests/test_phase7_schema.py -v
# Expected: 26 passed

# 6. Run all Phase 7 tests
python -m pytest tests/test_template_cache.py -v  # 22 passed
python -m pytest tests/test_monitoring.py -v      # 30 passed
python -m pytest tests/test_structured_logging.py -v  # 27 passed

# 7. Start monitoring dashboard (optional)
python scripts/monitoring_dashboard.py --format json > /var/log/dashboard.json

# 8. Configure log rotation
# Create /etc/logrotate.d/omniclaude-agents
# (See Maintenance section)

# 9. Verify deployment
python -c "from lib.monitoring import check_system_health; import asyncio; asyncio.run(check_system_health())"
```

#### Docker Deployment (Recommended)

**Create `Dockerfile`**:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY agents/ /app/agents/

# Set environment
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "from agents.lib.health_checker import check_database_health; import asyncio; asyncio.run(check_database_health())"

# Run application
CMD ["python", "-m", "agents.lib.codegen_workflow"]
```

**Create `docker-compose.yml`**:
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:14
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: omninode_bridge
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./agents/parallel_execution/migrations:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  agents:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/omninode_bridge
      LOG_LEVEL: INFO
      MONITORING_ENABLED: true
    volumes:
      - ./logs:/var/log/omniclaude
      - ./output:/app/output
    ports:
      - "8080:8080"  # Monitoring dashboard

volumes:
  postgres_data:
```

**Deploy with Docker Compose**:
```bash
# Set environment variables
export POSTGRES_PASSWORD="your-secure-password"

# Build and start services
docker-compose up -d

# Check logs
docker-compose logs -f agents

# Run tests inside container
docker-compose exec agents python -m pytest tests/ -v

# Check health
docker-compose exec agents python -c "from agents.lib.health_checker import check_system_health; import asyncio; print(asyncio.run(check_system_health()))"
```

---

## Configuration

### Template Cache Configuration

**File**: `agents/lib/template_cache.py`

```python
from agents.lib.template_cache import TemplateCache

# Development settings (fast invalidation)
cache = TemplateCache(
    max_templates=50,
    max_size_mb=25,
    ttl_seconds=600,  # 10 minutes
    enable_persistence=False  # No DB writes
)

# Production settings (optimized)
cache = TemplateCache(
    max_templates=100,
    max_size_mb=50,
    ttl_seconds=3600,  # 1 hour
    enable_persistence=True  # DB analytics enabled
)

# High-traffic settings (more cache)
cache = TemplateCache(
    max_templates=200,
    max_size_mb=100,
    ttl_seconds=7200,  # 2 hours
    enable_persistence=True
)
```

### Parallel Generation Configuration

```python
from agents.parallel_execution.dispatch_runner import ParallelCodeGenerator

# Conservative settings (low resource)
generator = ParallelCodeGenerator(
    max_workers=2,
    worker_timeout_seconds=600
)

# Balanced settings (recommended)
generator = ParallelCodeGenerator(
    max_workers=4,
    worker_timeout_seconds=300
)

# Aggressive settings (high performance)
generator = ParallelCodeGenerator(
    max_workers=8,
    worker_timeout_seconds=120
)
```

### Monitoring Configuration

**File**: `agents/configs/alert_config.yaml`

```yaml
# Adjust thresholds based on your environment
rules:
  - name: cache_hit_rate_low
    threshold: 0.70  # Warning at 70%
    severity: warning

  - name: generation_time_slow
    threshold: 3000.0  # Warning at 3s
    severity: warning

  - name: event_latency_high
    threshold: 200.0  # Warning at 200ms
    severity: warning

# Configure notification channels
channels:
  - name: slack_alerts
    type: webhook
    enabled: true
    config:
      url: ${SLACK_WEBHOOK_URL}

  - name: email_alerts
    type: email
    enabled: true
    config:
      recipients:
        - ops-team@example.com
      smtp_host: smtp.example.com
      smtp_port: 587
```

### Logging Configuration

```python
from agents.lib.log_rotation import configure_global_rotation

# Development
configure_global_rotation(
    environment="development",
    max_bytes=10485760,  # 10MB
    backup_count=5
)

# Production
configure_global_rotation(
    environment="production",
    max_bytes=104857600,  # 100MB
    backup_count=30,
    compression=True
)
```

---

## Monitoring

### Real-Time Monitoring

#### Dashboard Generation

```bash
# Generate JSON dashboard (for automation)
python agents/scripts/monitoring_dashboard.py --format json > dashboard.json

# Generate HTML dashboard (for viewing)
python agents/scripts/monitoring_dashboard.py --format html --output dashboard.html

# Export Prometheus metrics
python agents/scripts/monitoring_dashboard.py --prometheus > metrics.txt

# Custom time window (last 2 hours)
python agents/scripts/monitoring_dashboard.py --time-window 120 --format json
```

#### Health Checks

```bash
# Check all components
python -c "
from agents.lib.health_checker import check_system_health
import asyncio
import json

async def check():
    results = await check_system_health()
    for component, result in results.items():
        print(f'{component}: {result.status.value} - {result.message}')

asyncio.run(check())
"

# Check specific component
python -c "
from agents.lib.health_checker import check_database_health
import asyncio

async def check():
    result = await check_database_health()
    print(f'Database: {result.status.value} - {result.message}')

asyncio.run(check())
"
```

### Database Queries

#### Performance Metrics

```sql
-- Template cache efficiency
SELECT * FROM template_cache_efficiency
ORDER BY overall_hit_rate DESC;

-- Performance summary (last hour)
SELECT
    node_type,
    phase,
    AVG(duration_ms) as avg_duration,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_duration,
    COUNT(*) as total_operations
FROM generation_performance_metrics
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY node_type, phase
ORDER BY avg_duration DESC;

-- Mixin compatibility summary
SELECT * FROM mixin_compatibility_summary
WHERE compatibility_score < 0.80  -- Low compatibility
ORDER BY failure_count DESC;

-- Pattern feedback analysis
SELECT * FROM pattern_feedback_analysis
WHERE precision < 0.85  -- Low precision patterns
ORDER BY false_positive_count DESC;

-- Event processing health
SELECT * FROM event_processing_health
ORDER BY p95_latency_ms DESC;
```

#### Cache Analysis

```sql
-- Cache hit rate by template type
SELECT
    template_type,
    SUM(cache_hits) as total_hits,
    SUM(cache_misses) as total_misses,
    ROUND(SUM(cache_hits)::numeric / NULLIF(SUM(cache_hits) + SUM(cache_misses), 0), 4) as hit_rate
FROM template_cache_metadata
GROUP BY template_type
ORDER BY hit_rate DESC;

-- Most accessed templates
SELECT
    template_name,
    template_type,
    access_count,
    cache_hits,
    cache_misses,
    last_accessed_at
FROM template_cache_metadata
ORDER BY access_count DESC
LIMIT 10;

-- Templates with low hit rates
SELECT
    template_name,
    template_type,
    cache_hits,
    cache_misses,
    ROUND(cache_hits::numeric / NULLIF(cache_hits + cache_misses, 0), 4) as hit_rate
FROM template_cache_metadata
WHERE cache_hits + cache_misses > 10  -- Minimum sample size
  AND cache_hits::numeric / NULLIF(cache_hits + cache_misses, 0) < 0.80
ORDER BY hit_rate ASC;
```

### Alerts

#### Active Alerts

```bash
# Get active alerts
python -c "
from agents.lib.alert_manager import get_alert_manager

manager = get_alert_manager()
active_alerts = manager.get_active_alerts()

for alert in active_alerts:
    print(f'[{alert.severity.value}] {alert.rule_name}: {alert.message}')
    print(f'  Triggered: {alert.triggered_at}')
    print(f'  Status: {alert.status.value}')
    print()
"

# Get alert statistics
python -c "
from agents.lib.alert_manager import get_alert_manager

manager = get_alert_manager()
stats = manager.get_alert_statistics(hours=24)

print(f'Total alerts (24h): {stats[\"total_alerts\"]}')
print(f'By severity:')
for severity, count in stats['by_severity'].items():
    print(f'  {severity}: {count}')
"
```

#### Alert Management

```bash
# Acknowledge alert
python -c "
from agents.lib.alert_manager import get_alert_manager

manager = get_alert_manager()
manager.acknowledge_alert('alert-uuid-here', 'john.doe')
print('Alert acknowledged')
"

# Resolve alert
python -c "
from agents.lib.alert_manager import get_alert_manager

manager = get_alert_manager()
manager.resolve_alert('alert-uuid-here')
print('Alert resolved')
"
```

### Performance Monitoring

#### System Metrics

```bash
# CPU and memory usage
top -b -n 1 | grep python

# Database connections
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -c "SELECT count(*) as connections FROM pg_stat_activity WHERE datname = 'omninode_bridge';"

# Database size
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -c "SELECT pg_size_pretty(pg_database_size('omninode_bridge'));"

# Table sizes
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -c "SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
      FROM pg_tables
      WHERE tablename IN ('mixin_compatibility_matrix', 'pattern_feedback_log', 'generation_performance_metrics', 'template_cache_metadata', 'event_processing_metrics')
      ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;"
```

---

## Troubleshooting

### Common Issues

#### Issue: Low Cache Hit Rate

**Symptoms**: Cache hit rate below 80%

**Diagnosis**:
```bash
# Check cache statistics
python -c "
from agents.lib.omninode_template_engine import OmniNodeTemplateEngine

engine = OmniNodeTemplateEngine()
stats = engine.get_cache_stats()
print(f'Hit rate: {stats[\"hit_rate\"]:.1%}')
print(f'Hits: {stats[\"hits\"]}, Misses: {stats[\"misses\"]}')
print(f'Cached templates: {stats[\"cached_templates\"]}')
"

# Check template modification times
ls -lt agents/templates/omninode/
```

**Solutions**:
1. **TTL too short**: Increase `ttl_seconds` in cache config
2. **Templates changing frequently**: Check CI/CD for template updates
3. **Cache size too small**: Increase `max_templates` or `max_size_mb`
4. **No warmup**: Ensure cache warmup runs on startup

```python
# Fix: Increase TTL
cache = TemplateCache(ttl_seconds=7200)  # 2 hours

# Fix: Increase size
cache = TemplateCache(max_templates=200, max_size_mb=100)

# Fix: Ensure warmup
engine = OmniNodeTemplateEngine(enable_cache=True)
engine._warmup_cache()  # Explicitly warm up
```

#### Issue: Slow Parallel Generation

**Symptoms**: Parallel generation not achieving 2.5x+ speedup

**Diagnosis**:
```sql
-- Check generation performance
SELECT
    node_type,
    parallel_execution,
    AVG(duration_ms) as avg_duration,
    COUNT(*) as operations
FROM generation_performance_metrics
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY node_type, parallel_execution
ORDER BY parallel_execution DESC, avg_duration DESC;
```

**Solutions**:
1. **Worker count too low**: Increase `max_workers`
2. **Worker timeout**: Increase `worker_timeout_seconds`
3. **Cache not helping**: Check cache hit rate
4. **Database contention**: Check connection pool size

```python
# Fix: Increase workers (adjust for CPU cores)
generator = ParallelCodeGenerator(max_workers=8)

# Fix: Increase timeout
generator = ParallelCodeGenerator(worker_timeout_seconds=600)

# Fix: Check database pool
# In persistence.py, increase pool size:
await asyncpg.create_pool(dsn, min_size=20, max_size=50)
```

#### Issue: High Event Processing Latency

**Symptoms**: p95 latency > 200ms

**Diagnosis**:
```sql
-- Check event latency
SELECT * FROM event_processing_health
WHERE p95_latency_ms > 200
ORDER BY p95_latency_ms DESC;

-- Check queue wait times
SELECT
    event_type,
    AVG(queue_wait_time_ms) as avg_wait,
    MAX(queue_wait_time_ms) as max_wait,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY queue_wait_time_ms) as p95_wait
FROM event_processing_metrics
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY event_type
ORDER BY p95_wait DESC;
```

**Solutions**:
1. **Batch size too small**: Increase batch size
2. **Database writes slow**: Use async writes, increase pool size
3. **Too many retries**: Check error rates

```python
# Fix: Increase batch size
event_processor.set_batch_size(100)  # Default: 10

# Fix: Async database writes
await asyncio.create_task(persistence.insert_event_metric(metric))

# Fix: Reduce retries for non-critical events
event_processor.set_max_retries(2)  # Default: 3
```

#### Issue: Database Connection Errors

**Symptoms**: "connection refused" or "too many connections"

**Diagnosis**:
```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Check connection count
psql -h localhost -p 5432 -U postgres \
  -c "SELECT count(*) FROM pg_stat_activity;"

# Check max connections
psql -h localhost -p 5432 -U postgres \
  -c "SHOW max_connections;"
```

**Solutions**:
1. **PostgreSQL not running**: Start PostgreSQL
2. **Too many connections**: Increase `max_connections` in PostgreSQL config
3. **Connection leaks**: Check connection pool cleanup

```bash
# Fix: Start PostgreSQL
sudo systemctl start postgresql

# Fix: Increase max connections
# Edit /etc/postgresql/14/main/postgresql.conf
max_connections = 200  # Default: 100
# Restart PostgreSQL
sudo systemctl restart postgresql

# Fix: Check for connection leaks
# In code, ensure connections are properly released:
async with get_db_pool().acquire() as conn:
    # Use connection
    pass  # Connection auto-released
```

#### Issue: Monitoring Alerts Not Firing

**Symptoms**: Expected alerts not appearing

**Diagnosis**:
```bash
# Check alert rules
python -c "
from agents.lib.alert_manager import get_alert_manager

manager = get_alert_manager()
config = manager.export_config()
print('Alert rules:', len(config['rules']))
for rule in config['rules']:
    print(f'  {rule.name}: {rule.severity.value}, enabled={rule.enabled}')
"

# Check metrics
python -c "
from agents.lib.monitoring import get_monitoring_system

system = get_monitoring_system()
summary = system.get_summary()
print('Metrics collected:', len(summary['metrics']))
"
```

**Solutions**:
1. **Alert rules not loaded**: Load `alert_config.yaml`
2. **Thresholds too lenient**: Adjust thresholds
3. **Metrics not collected**: Verify metrics are being recorded

```python
# Fix: Load alert configuration
from agents.lib.alert_manager import load_alert_config
load_alert_config('agents/configs/alert_config.yaml')

# Fix: Verify metrics collection
from agents.lib.monitoring import record_metric, MetricType
await record_metric('test_metric', 100.0, MetricType.GAUGE)

# Fix: Lower thresholds for testing
# In alert_config.yaml:
rules:
  - name: test_alert
    threshold: 50.0  # Lower threshold
    severity: warning
```

### Debug Mode

Enable debug logging for troubleshooting:

```bash
# Set environment variable
export LOG_LEVEL=DEBUG

# Or in code
from agents.lib.structured_logger import get_logger
logger = get_logger(__name__, component="troubleshooting")
logger.setLevel("DEBUG")

# Run with debug logging
python -m agents.lib.codegen_workflow

# Check logs
tail -f /var/log/omniclaude/agents/debug.log
```

---

## Maintenance

### Log Rotation

#### Automatic Log Rotation (Linux)

**Create `/etc/logrotate.d/omniclaude-agents`**:
```
/var/log/omniclaude/agents/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 omniclaude omniclaude
    sharedscripts
    postrotate
        # Reload application if needed
        systemctl reload omniclaude-agents || true
    endscript
}
```

**Test logrotate**:
```bash
sudo logrotate -f /etc/logrotate.d/omniclaude-agents
```

#### Application-Level Log Rotation

```python
# Already configured in Stream 8
from agents.lib.log_rotation import configure_global_rotation

configure_global_rotation(
    environment="production",
    max_bytes=104857600,  # 100MB
    backup_count=30,
    compression=True
)
```

### Database Maintenance

#### Vacuum and Analyze

```bash
# Vacuum all Phase 7 tables
psql -h localhost -p 5432 -U postgres -d omninode_bridge << EOF
VACUUM ANALYZE mixin_compatibility_matrix;
VACUUM ANALYZE pattern_feedback_log;
VACUUM ANALYZE generation_performance_metrics;
VACUUM ANALYZE template_cache_metadata;
VACUUM ANALYZE event_processing_metrics;
EOF
```

#### Index Maintenance

```sql
-- Check index usage
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
  AND tablename IN ('mixin_compatibility_matrix', 'pattern_feedback_log',
                     'generation_performance_metrics', 'template_cache_metadata',
                     'event_processing_metrics')
ORDER BY idx_scan ASC;

-- Reindex if needed
REINDEX TABLE mixin_compatibility_matrix;
REINDEX TABLE pattern_feedback_log;
REINDEX TABLE generation_performance_metrics;
REINDEX TABLE template_cache_metadata;
REINDEX TABLE event_processing_metrics;
```

#### Cleanup Old Data

```sql
-- Delete metrics older than 90 days
DELETE FROM generation_performance_metrics
WHERE created_at < NOW() - INTERVAL '90 days';

DELETE FROM event_processing_metrics
WHERE created_at < NOW() - INTERVAL '90 days';

DELETE FROM pattern_feedback_log
WHERE created_at < NOW() - INTERVAL '90 days';

-- Keep mixin compatibility data indefinitely (ML training)
-- Only clean up very old low-confidence data
DELETE FROM mixin_compatibility_matrix
WHERE created_at < NOW() - INTERVAL '1 year'
  AND success_count + failure_count < 5;
```

### Cache Maintenance

```python
# Invalidate stale cache entries
from agents.lib.omninode_template_engine import OmniNodeTemplateEngine

engine = OmniNodeTemplateEngine()

# Invalidate all cache (use sparingly)
engine.invalidate_cache()

# Invalidate specific template
engine.invalidate_cache("EFFECT_template")

# Get cache statistics
stats = engine.get_cache_stats()
print(f"Cache size: {stats['total_size_mb']:.2f}MB / {stats['max_size_mb']}MB")
print(f"Templates: {stats['cached_templates']} / {stats['max_templates']}")
```

---

## Performance Tuning

### Database Tuning

#### PostgreSQL Configuration

**Edit `/etc/postgresql/14/main/postgresql.conf`**:
```
# Memory settings (adjust based on available RAM)
shared_buffers = 2GB
effective_cache_size = 6GB
maintenance_work_mem = 512MB
work_mem = 16MB

# Checkpoint settings
checkpoint_completion_target = 0.9
wal_buffers = 16MB
min_wal_size = 1GB
max_wal_size = 4GB

# Connection settings
max_connections = 200
max_prepared_transactions = 200

# Query planner
random_page_cost = 1.1  # For SSD storage
effective_io_concurrency = 200  # For SSD storage

# Logging
log_min_duration_statement = 1000  # Log slow queries (>1s)
```

**Apply changes**:
```bash
sudo systemctl restart postgresql
```

### Application Tuning

#### Connection Pool Sizing

```python
# In persistence.py
import asyncpg

# Calculate based on: (cores * 2) + effective_spindle_count
# For 4 cores + SSD: (4 * 2) + 1 = 9, round up to 10-20
pool = await asyncpg.create_pool(
    dsn=DATABASE_URL,
    min_size=10,
    max_size=20,
    command_timeout=60
)
```

#### Worker Pool Sizing

```python
# Calculate based on CPU cores
import os

cpu_count = os.cpu_count() or 4

# Conservative: Use half of cores
generator = ParallelCodeGenerator(max_workers=cpu_count // 2)

# Aggressive: Use all cores
generator = ParallelCodeGenerator(max_workers=cpu_count)

# I/O-bound workloads: Use 2x cores
generator = ParallelCodeGenerator(max_workers=cpu_count * 2)
```

#### Cache Tuning

```python
# High-memory system: Larger cache
cache = TemplateCache(
    max_templates=500,
    max_size_mb=200,
    ttl_seconds=14400  # 4 hours
)

# Low-memory system: Smaller cache
cache = TemplateCache(
    max_templates=50,
    max_size_mb=25,
    ttl_seconds=1800  # 30 minutes
)
```

### Monitoring Performance Tuning

```python
# Reduce metric retention for memory-constrained systems
from agents.lib.monitoring import MonitoringSystem

monitoring = MonitoringSystem(
    metric_retention_points=500  # Default: 1000
)

# Increase for long-term analysis
monitoring = MonitoringSystem(
    metric_retention_points=5000
)
```

---

## Backup and Recovery

### Database Backup

#### Automated Backups

**Create backup script `backup.sh`**:
```bash
#!/bin/bash
BACKUP_DIR="/var/backups/omniclaude"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PGPASSWORD="your-secure-password"

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup database
pg_dump -h localhost -p 5432 -U postgres omninode_bridge \
  -f "$BACKUP_DIR/omninode_bridge_$TIMESTAMP.sql"

# Compress backup
gzip "$BACKUP_DIR/omninode_bridge_$TIMESTAMP.sql"

# Delete backups older than 30 days
find $BACKUP_DIR -name "omninode_bridge_*.sql.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_DIR/omninode_bridge_$TIMESTAMP.sql.gz"
```

**Schedule with cron**:
```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /opt/omniclaude/backup.sh >> /var/log/omniclaude/backup.log 2>&1
```

#### Manual Backup

```bash
# Full database backup
pg_dump -h localhost -p 5432 -U postgres omninode_bridge \
  -f omninode_bridge_backup.sql

# Phase 7 tables only
pg_dump -h localhost -p 5432 -U postgres omninode_bridge \
  -t mixin_compatibility_matrix \
  -t pattern_feedback_log \
  -t generation_performance_metrics \
  -t template_cache_metadata \
  -t event_processing_metrics \
  -f phase7_backup.sql
```

### Database Restore

```bash
# Restore full database
psql -h localhost -p 5432 -U postgres omninode_bridge \
  -f omninode_bridge_backup.sql

# Restore specific tables (will error if tables exist)
# Option 1: Drop tables first
psql -h localhost -p 5432 -U postgres omninode_bridge \
  -c "DROP TABLE IF EXISTS mixin_compatibility_matrix CASCADE;"
# Then restore

# Option 2: Use --clean flag in backup
pg_dump --clean -h localhost -p 5432 -U postgres omninode_bridge \
  -t mixin_compatibility_matrix -f backup.sql
```

### Configuration Backup

```bash
# Backup configuration files
tar -czf config_backup_$(date +%Y%m%d).tar.gz \
  agents/configs/ \
  .env \
  docker-compose.yml

# Restore configuration
tar -xzf config_backup_20251015.tar.gz
```

### Disaster Recovery

#### Recovery Procedure

1. **Assess damage**:
```bash
# Check database connectivity
psql -h localhost -p 5432 -U postgres -c "SELECT version();"

# Check table existence
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -c "\dt mixin_compatibility_matrix"
```

2. **Restore from backup**:
```bash
# Stop application
docker-compose down  # or systemctl stop omniclaude-agents

# Restore database
psql -h localhost -p 5432 -U postgres omninode_bridge \
  -f /var/backups/omniclaude/omninode_bridge_latest.sql

# Verify restoration
psql -h localhost -p 5432 -U postgres -d omninode_bridge \
  -c "SELECT COUNT(*) FROM mixin_compatibility_matrix;"
```

3. **Restart application**:
```bash
# Start application
docker-compose up -d  # or systemctl start omniclaude-agents

# Verify health
docker-compose exec agents python -c "from agents.lib.health_checker import check_system_health; import asyncio; asyncio.run(check_system_health())"
```

---

## Security

### Database Security

#### Password Management

```bash
# Use strong passwords
export POSTGRES_PASSWORD=$(openssl rand -base64 32)

# Store in secrets management system (recommended)
# AWS Secrets Manager, HashiCorp Vault, etc.

# Or use .env file with restricted permissions
chmod 600 .env
```

#### Connection Security

```python
# Use SSL for database connections
import asyncpg

pool = await asyncpg.create_pool(
    dsn=DATABASE_URL,
    ssl='require',  # or 'verify-full' for certificate verification
    command_timeout=60
)
```

#### User Permissions

```sql
-- Create dedicated application user
CREATE USER omniclaude_app WITH PASSWORD 'secure-password';

-- Grant minimal required permissions
GRANT CONNECT ON DATABASE omninode_bridge TO omniclaude_app;
GRANT USAGE ON SCHEMA public TO omniclaude_app;

-- Grant table permissions
GRANT SELECT, INSERT, UPDATE ON TABLE mixin_compatibility_matrix TO omniclaude_app;
GRANT SELECT, INSERT ON TABLE pattern_feedback_log TO omniclaude_app;
GRANT SELECT, INSERT ON TABLE generation_performance_metrics TO omniclaude_app;
GRANT SELECT, INSERT, UPDATE ON TABLE template_cache_metadata TO omniclaude_app;
GRANT SELECT, INSERT ON TABLE event_processing_metrics TO omniclaude_app;

-- Grant view permissions
GRANT SELECT ON ALL TABLES IN SCHEMA public TO omniclaude_app;
```

### Application Security

#### Input Validation

```python
# All inputs validated with Pydantic models
from pydantic import BaseModel, validator

class MixinCompatibilityCreate(BaseModel):
    node_type: str
    mixin_combination: list[str]

    @validator('node_type')
    def validate_node_type(cls, v):
        allowed = ['EFFECT', 'COMPUTE', 'REDUCER', 'ORCHESTRATOR']
        if v not in allowed:
            raise ValueError(f'Invalid node type: {v}')
        return v
```

#### SQL Injection Prevention

```python
# All queries use parameterized statements
async def insert_metric(metric: PerformanceMetric):
    query = """
        INSERT INTO generation_performance_metrics
        (session_id, node_type, phase, duration_ms)
        VALUES ($1, $2, $3, $4)
    """
    # Parameters passed separately (safe)
    await conn.execute(query, metric.session_id, metric.node_type,
                       metric.phase, metric.duration_ms)
```

#### Secrets Management

```python
# Use environment variables for secrets
import os

DATABASE_PASSWORD = os.getenv('POSTGRES_PASSWORD')
WEBHOOK_URL = os.getenv('ALERT_WEBHOOK_URL')

# Never hardcode secrets in code
# ❌ BAD: password = "hardcoded-password"
# ✅ GOOD: password = os.getenv('POSTGRES_PASSWORD')
```

### Monitoring Security

#### Alert Webhook Security

```yaml
# In alert_config.yaml
channels:
  - name: secure_webhook
    type: webhook
    config:
      url: ${WEBHOOK_URL}
      headers:
        Authorization: Bearer ${WEBHOOK_TOKEN}
        X-API-Key: ${API_KEY}
```

#### Log Security

```python
# Redact sensitive data in logs
from agents.lib.structured_logger import get_logger

logger = get_logger(__name__)

# ❌ BAD: Logging sensitive data
logger.info(f"User password: {password}")

# ✅ GOOD: Redact sensitive data
logger.info(f"User authenticated", metadata={"user_id": user_id})
```

---

## See Also

- [API Reference](./API_REFERENCE.md) - Complete API documentation
- [User Guide](./USER_GUIDE.md) - Usage examples and best practices
- [Architecture](./ARCHITECTURE.md) - System architecture and design
- [Integration Guide](./INTEGRATION_GUIDE.md) - Integration patterns
- [Summary](./SUMMARY.md) - Executive summary

---

**Document Version**: 1.0
**Last Updated**: 2025-10-15
**Status**: Production Ready
