# Agent Actions Kafka Consumer

Production-ready Kafka consumer that reads agent action events from the `agent-actions` topic and persists them to PostgreSQL with comprehensive error handling and monitoring.

## Features

### Core Capabilities
- **Batch Processing**: Configurable batch size (default: 100 events) and timeout (default: 1 second)
- **Dead Letter Queue**: Failed messages automatically routed to `agent-actions-dlq` topic
- **Graceful Shutdown**: Processes remaining messages on SIGTERM/SIGINT before exit
- **Health Check Endpoint**: HTTP endpoint for monitoring consumer health and metrics
- **Idempotency**: Duplicate detection prevents double-processing of events
- **Consumer Lag Tracking**: Real-time metrics for monitoring backlog

### Production Features
- Connection pooling with automatic retry
- Structured logging with configurable levels
- Resource limits and security hardening (systemd)
- Automatic offset management with manual commits
- Performance metrics tracking (messages/sec, batch timing)

## Architecture

```
┌─────────────┐    ┌──────────────────┐    ┌──────────────┐
│   Kafka     │───▶│  Agent Actions   │───▶│  PostgreSQL  │
│   Topic     │    │    Consumer      │    │  Database    │
│agent-actions│    │                  │    │agent_actions │
└─────────────┘    │  ┌────────────┐  │    └──────────────┘
                   │  │ Batch      │  │
                   │  │ Processor  │  │
                   │  └────────────┘  │
                   │         │        │
                   │         ▼        │
                   │  ┌────────────┐  │
                   │  │ Dead Letter│  │───▶ agent-actions-dlq
                   │  │   Queue    │  │
                   │  └────────────┘  │
                   └──────────────────┘
                            │
                            ▼
                   HTTP Health Check
                   :8080/health
                   :8080/metrics
```

## Installation

### Prerequisites
- Python 3.9+
- Kafka/Redpanda running (localhost:9092)
- PostgreSQL (localhost:5436)
- Database migration applied (`005_create_agent_actions_table.sql`)

### Dependencies

Install Python dependencies:

```bash
pip install kafka-python psycopg2-binary
```

Or using the project's requirements:

```bash
cd /opt/omniclaude
pip install -r requirements.txt
```

### Database Setup

Apply the database migration:

```bash
psql -h localhost -p 5436 -U postgres -d omniclaude \
  -f migrations/005_create_agent_actions_table.sql
```

## Configuration

### Environment Variables

```bash
# Kafka Configuration
export KAFKA_BROKERS="localhost:9092"
export KAFKA_GROUP_ID="agent-actions-postgres"

# PostgreSQL Configuration
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5436"
export POSTGRES_DATABASE="omniclaude"
export POSTGRES_USER="postgres"
export POSTGRES_PASSWORD="<your-postgres-password>"

# Consumer Tuning
export BATCH_SIZE="100"
export BATCH_TIMEOUT_MS="1000"

# Monitoring
export HEALTH_CHECK_PORT="8080"
export LOG_LEVEL="INFO"
```

### Configuration File (Optional)

Create `config.json`:

```json
{
  "kafka_brokers": "localhost:9092",
  "group_id": "agent-actions-postgres",
  "batch_size": 100,
  "batch_timeout_ms": 1000,
  "postgres_host": "localhost",
  "postgres_port": 5436,
  "health_check_port": 8080
}
```

Run with config file:

```bash
python agent_actions_consumer.py --config config.json
```

## Usage

### Development Mode

Run consumer directly:

```bash
cd /opt/omniclaude/consumers
python agent_actions_consumer.py
```

### Production Deployment (Systemd)

1. **Copy service file**:

```bash
sudo cp agent_actions_consumer.service /etc/systemd/system/
```

2. **Edit service file** with your paths:

```bash
sudo nano /etc/systemd/system/agent_actions_consumer.service
```

3. **Reload systemd**:

```bash
sudo systemctl daemon-reload
```

4. **Start service**:

```bash
sudo systemctl start agent_actions_consumer
```

5. **Enable auto-start**:

```bash
sudo systemctl enable agent_actions_consumer
```

### Systemd Commands

```bash
# Check status
sudo systemctl status agent_actions_consumer

# View logs
sudo journalctl -u agent_actions_consumer -f

# Restart service
sudo systemctl restart agent_actions_consumer

# Stop service
sudo systemctl stop agent_actions_consumer
```

## Monitoring

### Health Check

The consumer exposes HTTP endpoints for monitoring:

```bash
# Health check
curl http://localhost:8080/health

# Response (healthy):
{
  "status": "healthy",
  "consumer": "running"
}

# Metrics endpoint
curl http://localhost:8080/metrics

# Response:
{
  "uptime_seconds": 3600.5,
  "messages_consumed": 15432,
  "messages_inserted": 15420,
  "messages_failed": 12,
  "batches_processed": 155,
  "avg_batch_processing_ms": 45.2,
  "messages_per_second": 4.28,
  "last_commit_time": "2025-10-20T18:45:32.123Z"
}
```

### Prometheus Integration (Optional)

Add to Prometheus configuration:

```yaml
scrape_configs:
  - job_name: 'agent-actions-consumer'
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: '/metrics'
```

### Consumer Lag Monitoring

Monitor Kafka consumer lag:

```bash
# Using Kafka tools
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --group agent-actions-postgres

# Using rpk (Redpanda)
rpk group describe agent-actions-postgres
```

## Performance Tuning

### Batch Size Optimization

- **Small batches (10-50)**: Lower latency, higher overhead
- **Medium batches (100-200)**: Balanced (recommended)
- **Large batches (500-1000)**: Higher throughput, higher latency

Adjust based on message rate:

```bash
export BATCH_SIZE="200"
export BATCH_TIMEOUT_MS="2000"
```

### Database Connection Pooling

The consumer uses a single connection with transactions. For higher throughput, consider:

1. Multiple consumer instances (scale horizontally)
2. Increase PostgreSQL connection limits
3. Use pgBouncer for connection pooling

### Kafka Consumer Tuning

For high-throughput scenarios:

```python
# Add to consumer config in agent_actions_consumer.py
max_poll_records=500,
fetch_min_bytes=10240,
fetch_max_wait_ms=500,
```

## Troubleshooting

### Consumer Not Receiving Messages

1. **Check Kafka connectivity**:

```bash
# List topics
rpk topic list

# Produce test message
echo '{"test": "message"}' | rpk topic produce agent-actions
```

2. **Check consumer group**:

```bash
rpk group describe agent-actions-postgres
```

3. **Verify topic subscription**:

Check consumer logs for "Kafka consumer connected" message.

### Database Connection Failures

1. **Test PostgreSQL connection**:

```bash
psql -h localhost -p 5436 -U postgres -d omniclaude -c "SELECT 1"
```

2. **Check credentials**:

Verify `POSTGRES_PASSWORD` environment variable matches database.

3. **Check connection limits**:

```sql
SELECT * FROM pg_stat_activity;
```

### High Consumer Lag

1. **Increase batch size**:

```bash
export BATCH_SIZE="500"
```

2. **Scale horizontally** - Run multiple consumer instances
3. **Check database performance** - Slow inserts cause backlog

### Dead Letter Queue Issues

Check DLQ for failed messages:

```bash
# Consume from DLQ
rpk topic consume agent-actions-dlq
```

Analyze error patterns and fix upstream issues.

## Security Considerations

### Credentials Management

**Never commit credentials to version control!**

Use environment variables or secrets management:

```bash
# Load from .env file
export $(grep -v '^#' .env | xargs)

# Or use systemd EnvironmentFile
EnvironmentFile=/etc/omniclaude/consumer.env
```

### Network Security

- Use TLS for Kafka connections in production
- Restrict database access with firewall rules
- Use strong passwords for PostgreSQL

### Resource Limits

The systemd service includes resource limits:

```ini
MemoryMax=512M
CPUQuota=100%
LimitNOFILE=65536
```

Adjust based on workload.

## Event Schema

Events consumed from Kafka must match this structure:

```json
{
  "correlation_id": "7415f61f-ab2f-4961-97f5-a5f5c6499a4d",
  "agent_name": "agent-polymorphic-agent",
  "action_type": "tool_call",
  "action_name": "Read",
  "action_details": {
    "file_path": "/path/to/file.py",
    "lines_read": 150
  },
  "debug_mode": true,
  "duration_ms": 42,
  "timestamp": "2025-10-20T18:45:32.123Z"
}
```

### Field Descriptions

- `correlation_id` (UUID): Links related actions
- `agent_name` (string): Agent performing action
- `action_type` (enum): One of: tool_call, decision, error, success
- `action_name` (string): Specific action identifier
- `action_details` (object): Action-specific metadata
- `debug_mode` (boolean): Debug flag for filtering
- `duration_ms` (integer, optional): Action duration
- `timestamp` (ISO 8601): Event timestamp

## Maintenance

### Database Cleanup

Old debug logs are automatically cleaned via function:

```sql
-- Clean logs older than 30 days
SELECT cleanup_old_debug_logs();
```

Schedule with cron:

```cron
# Run cleanup daily at 2 AM
0 2 * * * psql -h localhost -p 5436 -U postgres -d omniclaude -c "SELECT cleanup_old_debug_logs();"
```

### Log Rotation

Configure journald log rotation:

```bash
# /etc/systemd/journald.conf
SystemMaxUse=1G
SystemMaxFileSize=100M
```

### Monitoring Checklist

- [ ] Health check responding (200 OK)
- [ ] Consumer lag < 1000 messages
- [ ] Error rate < 1%
- [ ] Average batch processing < 100ms
- [ ] Database connection healthy
- [ ] DLQ empty or within acceptable threshold

## Development

### Running Tests

```bash
# Unit tests
pytest tests/test_agent_actions_consumer.py

# Integration tests (requires Kafka + PostgreSQL)
pytest tests/integration/test_consumer_e2e.py
```

### Local Development

```bash
# Start dependencies (Docker Compose)
docker-compose up -d kafka postgres

# Run consumer with debug logging
export LOG_LEVEL="DEBUG"
python agent_actions_consumer.py
```

### Publishing Test Events

```bash
# Using the log-agent-action skill
cd skills/agent-tracking/log-agent-action
./execute_kafka.py \
  --agent test-agent \
  --action-type tool_call \
  --action-name TestAction \
  --debug-mode
```

## Support

For issues or questions:

1. Check logs: `sudo journalctl -u agent_actions_consumer -n 100`
2. Verify configuration: `systemctl show agent_actions_consumer`
3. Test connectivity: Health check endpoint and database connection
4. Review metrics: Consumer lag, error rates, throughput

## License

Part of the OmniClaude project.
