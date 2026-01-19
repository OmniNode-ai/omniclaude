# Kafka Advertised Listeners Configuration Fix

## Issue Summary

Tests are correctly loading the remote Kafka broker address (`192.168.86.200:29102`) from `.env`, but when the Kafka client connects, the broker returns metadata indicating clients should connect to `localhost:29092` instead. This causes subsequent connections to fail.

## Root Cause

The Redpanda/Kafka broker at `192.168.86.200` is configured with advertised listeners pointing to `localhost:29092`. When clients connect:

1. Client connects to `192.168.86.200:29102` ✅
2. Broker returns metadata: "I'm at `localhost:29092`"
3. Client tries to reconnect to `localhost:29092` ❌
4. Connection fails (localhost is not the broker)

## Evidence

```
WARNING kafka.coordinator:base.py:810 Marking the coordinator dead (node coordinator-0)
  for group agent-action-consumer: Node Disconnected.
ERROR kafka.coordinator:base.py:569 Error sending FindCoordinatorRequest_v2 to node 0
  [Cancelled: <BrokerConnection node_id=0 host=localhost:29092 <connected> ...>]
```

## Solution

Update the Redpanda/Kafka broker configuration on `192.168.86.200` to advertise its external IP address instead of localhost.

### For Redpanda (Recommended)

Edit the Redpanda configuration or docker-compose.yml:

```yaml
# In docker-compose.yml for Redpanda service
environment:
  - REDPANDA_ADVERTISED_KAFKA_API=192.168.86.200:29102
  - REDPANDA_KAFKA_ADDRESS=0.0.0.0:29092
```

Or in `redpanda.yaml`:

```yaml
redpanda:
  kafka_api:
    - address: 0.0.0.0
      port: 29092
      name: external
  advertised_kafka_api:
    - address: 192.168.86.200
      port: 29102
      name: external
```

### For Apache Kafka

Edit `server.properties`:

```properties
# Listeners that Kafka binds to
listeners=PLAINTEXT://0.0.0.0:29092

# Advertised listeners that clients use
advertised.listeners=PLAINTEXT://192.168.86.200:29102
```

## Current Test Status

### ✅ Working
- `.env` configuration loading via `conftest.py`
- PostgreSQL connection to remote database at `192.168.86.200:5436`
- Test fixtures using correct environment variables
- Database schema migrations applied successfully
- Consumer start/stop lifecycle tests

### ⏸️ Blocked by Advertised Listeners
- Full Kafka integration tests (message publishing/consuming)
- Tests requiring actual message flow through Kafka
- Consumer offset commit verification

## Workaround for Local Testing

If you cannot modify the remote broker configuration, you can:

1. **SSH tunnel** (not recommended for automated tests):
   ```bash
   ssh -L 29092:localhost:29092 jonah@192.168.86.200
   # Then in .env:
   KAFKA_BROKERS=localhost:29092
   ```

2. **Local Redpanda container** with correct advertised listeners:
   ```bash
   docker run -d \
     --name redpanda-local \
     -p 29102:29092 \
     -e REDPANDA_ADVERTISED_KAFKA_API=localhost:29102 \
     redpandadata/redpanda:latest
   ```

3. **Update /etc/hosts** (fragile, not recommended):
   ```bash
   # Add to /etc/hosts
   192.168.86.200 localhost
   ```

## Verification After Fix

Once the broker configuration is updated, run:

```bash
# Verify advertised listeners are correct
poetry run pytest tests/test_kafka_consumer.py::TestKafkaConsumerIntegration::test_consume_single_event -v

# Should see successful connection to 192.168.86.200:29102 without localhost errors
```

## Related Files

- `tests/conftest.py` - Loads .env configuration
- `tests/test_kafka_consumer.py` - Integration tests (updated to use remote config)
- `tests/test_env_loading.py` - Verifies .env loading
- `.env` - Contains remote broker configuration
- `migrations/005_create_agent_actions_table.sql` - Database schema (applied successfully)

## Contact

If you have access to the Redpanda broker at `192.168.86.200`, please update the advertised listeners configuration as described above. This is a one-time configuration change that will enable all distributed testing scenarios.
