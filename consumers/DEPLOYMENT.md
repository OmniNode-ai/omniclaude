# Agent Actions Consumer - Deployment Guide

Quick deployment guide for the production Kafka consumer.

## Prerequisites Checklist

- [ ] Kafka/Redpanda running on localhost:9092
- [ ] PostgreSQL running on localhost:5436
- [ ] Database migration 005 applied
- [ ] Python 3.9+ installed
- [ ] Dependencies installed (`pip install -r requirements.txt`)

## Quick Start (Development)

### 1. Verify Prerequisites

```bash
# Check PostgreSQL
psql -h localhost -p 5436 -U postgres -d omniclaude -c "SELECT COUNT(*) FROM agent_actions"

# Check Kafka (if using rpk)
rpk topic list

# Or using kafka-console tools
kafka-topics.sh --bootstrap-server localhost:9092 --list
```

### 2. Install Dependencies

```bash
cd consumers
pip install -r requirements.txt
```

### 3. Configure Environment

Create `.env` file:

```bash
cat > .env << 'EOF'
KAFKA_BROKERS=localhost:9092
KAFKA_GROUP_ID=agent-actions-postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5436
POSTGRES_DATABASE=omniclaude
POSTGRES_USER=postgres
POSTGRES_PASSWORD=omninode-bridge-postgres-dev-2024
BATCH_SIZE=100
BATCH_TIMEOUT_MS=1000
HEALTH_CHECK_PORT=8080
LOG_LEVEL=INFO
EOF
```

Load environment:

```bash
export $(grep -v '^#' .env | xargs)
```

### 4. Start Consumer

```bash
python agent_actions_consumer.py
```

Expected output:

```
2025-10-20 18:45:32 - agent_actions_consumer - INFO - AgentActionsConsumer initialized with config: {...}
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Setting up Kafka consumer...
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Kafka consumer connected to brokers: ['localhost:9092'], group: agent-actions-postgres, topic: agent-actions
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Setting up DLQ producer...
2025-10-20 18:45:32 - agent_actions_consumer - INFO - DLQ producer initialized
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Setting up database connection...
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Database connection established: localhost:5436/omniclaude
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Starting health check server on port 8080...
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Health check server running at http://0.0.0.0:8080/health
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Consumer started successfully
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Starting consume loop...
```

### 5. Test Consumer

In another terminal:

```bash
python test_consumer.py
```

Expected output:

```
======================================================================
Agent Actions Kafka Consumer - Test Suite
======================================================================

Step 1: Pre-flight checks
----------------------------------------------------------------------
🏥 Checking health endpoint...
✅ Health check passed: {'status': 'healthy', 'consumer': 'running'}

Step 2: Publish test events
----------------------------------------------------------------------
📤 Publishing 15 test events to Kafka...
  ✓ Event 1/15: 7415f61f-ab2f-4961-97f5-a5f5c6499a4d
  ...
✅ Published 15 events successfully

Step 3: Verify database persistence
----------------------------------------------------------------------
🔍 Verifying 15 records in database...
✅ All 15 records found in database!

🎉 All critical tests passed!
```

## Production Deployment (Systemd)

### 1. Create Service User

```bash
sudo useradd -r -s /bin/false omniclaude
```

### 2. Setup Directories

```bash
sudo mkdir -p /opt/omniclaude/consumers
sudo mkdir -p /var/log/omniclaude
sudo chown -R omniclaude:omniclaude /opt/omniclaude
sudo chown -R omniclaude:omniclaude /var/log/omniclaude
```

### 3. Copy Files

```bash
# Copy consumer script
sudo cp agent_actions_consumer.py /opt/omniclaude/consumers/
sudo cp requirements.txt /opt/omniclaude/consumers/

# Install dependencies in virtualenv
sudo -u omniclaude python3 -m venv /opt/omniclaude/venv
sudo -u omniclaude /opt/omniclaude/venv/bin/pip install -r /opt/omniclaude/consumers/requirements.txt
```

### 4. Configure Service

```bash
# Copy service file
sudo cp agent_actions_consumer.service /etc/systemd/system/

# Edit environment variables
sudo nano /etc/systemd/system/agent_actions_consumer.service

# Reload systemd
sudo systemctl daemon-reload
```

### 5. Start Service

```bash
# Start service
sudo systemctl start agent_actions_consumer

# Check status
sudo systemctl status agent_actions_consumer

# Enable auto-start
sudo systemctl enable agent_actions_consumer
```

### 6. Verify Deployment

```bash
# Check health
curl http://localhost:8080/health

# Check metrics
curl http://localhost:8080/metrics

# View logs
sudo journalctl -u agent_actions_consumer -f
```

## Docker Deployment (Recommended)

The agent observability consumer is now integrated into the main docker-compose stack.

### 1. Using Docker Compose

The consumer is defined in `deployment/Dockerfile.consumer` and integrated in `deployment/docker-compose.yml`:

```bash
# Start all services including the agent consumer
docker-compose -f deployment/docker-compose.yml up -d agent-observability-consumer

# View logs
docker logs -f omniclaude_agent_consumer

# Check health
curl http://localhost:8080/health
```

### 2. Manual Docker Build (Alternative)

```bash
# Build consumer image
docker build -f deployment/Dockerfile.consumer -t agent-actions-consumer:latest .
```

### 3. Run Container

```bash
docker run -d \
  --name agent-actions-consumer \
  --network host \
  -e KAFKA_BROKERS=localhost:9092 \
  -e POSTGRES_HOST=localhost \
  -e POSTGRES_PORT=5436 \
  -e POSTGRES_DATABASE=omniclaude \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=omninode-bridge-postgres-dev-2024 \
  --restart unless-stopped \
  agent-actions-consumer:latest
```

### 4. Monitor Container

```bash
# Check logs
docker logs -f agent-actions-consumer

# Check health
docker inspect --format='{{json .State.Health}}' agent-actions-consumer | jq

# Restart
docker restart agent-actions-consumer
```

## Kubernetes Deployment (Advanced)

### 1. Create ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: agent-actions-consumer-config
data:
  KAFKA_BROKERS: "kafka.default.svc.cluster.local:9092"
  KAFKA_GROUP_ID: "agent-actions-postgres"
  POSTGRES_HOST: "postgres.default.svc.cluster.local"
  POSTGRES_PORT: "5432"
  POSTGRES_DATABASE: "omniclaude"
  BATCH_SIZE: "100"
  BATCH_TIMEOUT_MS: "1000"
  HEALTH_CHECK_PORT: "8080"
  LOG_LEVEL: "INFO"
```

### 2. Create Secret

```bash
kubectl create secret generic agent-actions-consumer-secret \
  --from-literal=postgres-password='your-secure-password'
```

### 3. Create Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-actions-consumer
spec:
  replicas: 2
  selector:
    matchLabels:
      app: agent-actions-consumer
  template:
    metadata:
      labels:
        app: agent-actions-consumer
    spec:
      containers:
      - name: consumer
        image: agent-actions-consumer:latest
        envFrom:
        - configMapRef:
            name: agent-actions-consumer-config
        env:
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: agent-actions-consumer-secret
              key: postgres-password
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
```

### 4. Deploy to Kubernetes

```bash
kubectl apply -f configmap.yaml
kubectl apply -f deployment.yaml

# Check status
kubectl get pods -l app=agent-actions-consumer
kubectl logs -f deployment/agent-actions-consumer
```

## Monitoring & Alerting

### Prometheus Metrics (Future Enhancement)

Add Prometheus exporter to consumer for detailed metrics:

```python
from prometheus_client import Counter, Histogram, Gauge

messages_consumed = Counter('agent_actions_messages_consumed_total', 'Total messages consumed')
messages_inserted = Counter('agent_actions_messages_inserted_total', 'Total messages inserted')
batch_processing_time = Histogram('agent_actions_batch_processing_seconds', 'Batch processing time')
consumer_lag = Gauge('agent_actions_consumer_lag', 'Consumer lag')
```

### Grafana Dashboard

Create dashboard with panels:

- Messages consumed/sec (rate)
- Messages inserted/sec (rate)
- Consumer lag (gauge)
- Batch processing time (histogram)
- Error rate (rate)
- DLQ message count (counter)

### Alerting Rules

Example Prometheus alerts:

```yaml
groups:
  - name: agent_actions_consumer
    rules:
      - alert: HighConsumerLag
        expr: agent_actions_consumer_lag > 1000
        for: 5m
        annotations:
          summary: "Consumer lag is high ({{ $value }} messages)"

      - alert: HighErrorRate
        expr: rate(agent_actions_messages_failed_total[5m]) > 0.01
        for: 2m
        annotations:
          summary: "Error rate is above 1%"

      - alert: ConsumerDown
        expr: up{job="agent-actions-consumer"} == 0
        for: 1m
        annotations:
          summary: "Consumer is down"
```

## Troubleshooting

### Consumer Not Starting

1. Check dependencies:
   ```bash
   pip list | grep -E "(kafka|psycopg2)"
   ```

2. Verify Kafka connectivity:
   ```bash
   telnet localhost 9092
   ```

3. Check PostgreSQL:
   ```bash
   psql -h localhost -p 5436 -U postgres -c "SELECT 1"
   ```

### High Memory Usage

Reduce batch size:

```bash
export BATCH_SIZE=50
```

### Consumer Lag Increasing

Scale horizontally:

```bash
# Add more consumer instances (different servers)
# They'll automatically join the same consumer group
```

Or increase batch size:

```bash
export BATCH_SIZE=500
export BATCH_TIMEOUT_MS=2000
```

## Performance Benchmarks

### Expected Performance

| Metric | Development | Production |
|--------|-------------|------------|
| Messages/sec | 100-500 | 500-2000 |
| Batch processing | 50-100ms | 20-50ms |
| Consumer lag | <100 | <500 |
| Memory usage | 100-200MB | 200-512MB |
| CPU usage | <25% | <100% |

### Tuning for High Throughput

```bash
# Increase batch size
export BATCH_SIZE=1000
export BATCH_TIMEOUT_MS=5000

# Increase max poll records
# Edit agent_actions_consumer.py:
max_poll_records=1000

# Use connection pooling
# Consider pgBouncer for PostgreSQL
```

## Backup & Recovery

### Database Backups

```bash
# Backup agent_actions table
pg_dump -h localhost -p 5436 -U postgres -d omniclaude \
  -t agent_actions -f agent_actions_backup.sql

# Restore
psql -h localhost -p 5436 -U postgres -d omniclaude \
  -f agent_actions_backup.sql
```

### Consumer State Recovery

Consumer offsets are managed by Kafka. To reset:

```bash
# Reset to earliest
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --group agent-actions-postgres --reset-offsets --to-earliest \
  --topic agent-actions --execute

# Reset to specific offset
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --group agent-actions-postgres --reset-offsets --to-offset 1000 \
  --topic agent-actions --execute
```

## Security Hardening

### 1. Restrict File Permissions

```bash
chmod 600 /etc/systemd/system/agent_actions_consumer.service
chmod 700 /opt/omniclaude/consumers
```

### 2. Use Secrets Management

Instead of environment variables in service file:

```bash
# Create secrets file
sudo nano /etc/omniclaude/consumer.env
# Add: POSTGRES_PASSWORD=your-secure-password

# Update service file
EnvironmentFile=/etc/omniclaude/consumer.env

# Restrict access
sudo chmod 600 /etc/omniclaude/consumer.env
```

### 3. Network Isolation

Use firewall rules to restrict access:

```bash
# Allow only local PostgreSQL
sudo ufw allow from 127.0.0.1 to any port 5436

# Allow only local Kafka
sudo ufw allow from 127.0.0.1 to any port 9092
```

### 4. TLS Encryption

For production, enable TLS:

```python
# In agent_actions_consumer.py, add to KafkaConsumer config:
security_protocol='SSL',
ssl_cafile='/path/to/ca.pem',
ssl_certfile='/path/to/cert.pem',
ssl_keyfile='/path/to/key.pem'
```

## Maintenance Windows

### Graceful Shutdown

```bash
# Stop consumer gracefully (processes remaining messages)
sudo systemctl stop agent_actions_consumer

# Wait for shutdown (max 30s)
# Check logs to confirm clean shutdown
sudo journalctl -u agent_actions_consumer -n 50
```

### Rolling Updates

```bash
# Update code
sudo cp agent_actions_consumer.py /opt/omniclaude/consumers/

# Restart service
sudo systemctl restart agent_actions_consumer

# Verify
curl http://localhost:8080/health
```

### Database Maintenance

```bash
# Run during low traffic
# Clean old debug logs
psql -h localhost -p 5436 -U postgres -d omniclaude -c "SELECT cleanup_old_debug_logs();"

# Vacuum table
psql -h localhost -p 5436 -U postgres -d omniclaude -c "VACUUM ANALYZE agent_actions;"
```

## Support & Escalation

### Log Analysis

```bash
# View recent errors
sudo journalctl -u agent_actions_consumer -p err -n 100

# Search for specific correlation ID
sudo journalctl -u agent_actions_consumer | grep "7415f61f-ab2f-4961-97f5-a5f5c6499a4d"

# Export logs
sudo journalctl -u agent_actions_consumer --since "1 hour ago" > consumer.log
```

### Health Check Automation

```bash
# Create monitoring script
cat > /usr/local/bin/check-consumer-health.sh << 'EOF'
#!/bin/bash
if ! curl -f -s http://localhost:8080/health > /dev/null; then
    echo "Consumer health check failed!"
    systemctl restart agent_actions_consumer
    # Send alert
fi
EOF

chmod +x /usr/local/bin/check-consumer-health.sh

# Add to cron (every 5 minutes)
*/5 * * * * /usr/local/bin/check-consumer-health.sh
```

## Changelog

- **2025-10-20**: Initial production release
  - Batch processing (100 events/1s)
  - Dead letter queue support
  - Health check endpoint
  - Systemd service configuration
  - Comprehensive monitoring
