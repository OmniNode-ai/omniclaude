# Agent Actions Consumer - Quick Start

**5-minute setup guide for the impatient developer** ⚡

## Prerequisites Check

```bash
# 1. PostgreSQL running?
psql -h localhost -p 5436 -U postgres -d omniclaude -c "SELECT 1"

# 2. Kafka/Redpanda running?
telnet localhost 9092

# 3. Python 3.9+?
python3 --version
```

If any fail, see [DEPLOYMENT.md](DEPLOYMENT.md) for setup instructions.

## Install & Run (3 commands)

```bash
# 1. Install dependencies
cd consumers
pip install -r requirements.txt

# 2. Apply database migration (if not already done)
PGPASSWORD="omninode-bridge-postgres-dev-2024" psql -h localhost -p 5436 -U postgres -d omniclaude -f ../migrations/005_create_agent_actions_table.sql

# 3. Start consumer
python agent_actions_consumer.py
```

**Expected output:**
```
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Consumer started successfully
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Health check server running at http://0.0.0.0:8080/health
2025-10-20 18:45:32 - agent_actions_consumer - INFO - Starting consume loop...
```

## Test (1 command)

In another terminal:

```bash
python test_consumer.py
```

**Expected:**
```
🎉 All critical tests passed!
```

## Monitor (1 command)

```bash
# Watch metrics in real-time
watch -n 1 'curl -s http://localhost:8080/metrics | python -m json.tool'
```

## Stop

Press `Ctrl+C` - consumer will gracefully shutdown.

---

## What's Next?

- **Production deployment**: See [DEPLOYMENT.md](DEPLOYMENT.md#production-deployment-systemd)
- **Performance tuning**: See [README.md](README.md#performance-tuning)
- **Monitoring setup**: See [DEPLOYMENT.md](DEPLOYMENT.md#monitoring--alerting)
- **Troubleshooting**: See [README.md](README.md#troubleshooting)

## Common Issues

### "connection refused" (Kafka)
```bash
# Start Redpanda/Kafka
docker-compose up -d redpanda
```

### "connection refused" (PostgreSQL)
```bash
# Check PostgreSQL is running
pg_isready -h localhost -p 5436
```

### "ModuleNotFoundError: No module named 'kafka'"
```bash
pip install kafka-python psycopg2-binary
```

### "relation 'agent_actions' does not exist"
```bash
# Apply migration
psql -h localhost -p 5436 -U postgres -d omniclaude -f ../migrations/005_create_agent_actions_table.sql
```

---

**Need help?** See the full [README.md](README.md) or [DEPLOYMENT.md](DEPLOYMENT.md)
