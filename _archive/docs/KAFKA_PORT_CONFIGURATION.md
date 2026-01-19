# Kafka/Redpanda Port Configuration

**Critical Reference**: Port configuration for Redpanda/Kafka connections in omniclaude

## Port Mapping Overview

### Redpanda Container Ports

From `docker ps` output:
```
omninode-bridge-redpanda:
  0.0.0.0:29102->29092/tcp  ← Main Kafka API (CORRECT PORT)
  0.0.0.0:29092->9092/tcp   ← Internal Kafka API
  0.0.0.0:28092->8082/tcp   ← Admin/HTTP API
  0.0.0.0:29654->9644/tcp   ← Schema Registry
```

### Critical Rule

**ALWAYS use port 29102 for external host connections to Kafka**

## Correct Configuration

### Environment Variables (.env file)

**Primary configuration is in `.env` file at project root**

```bash
# CORRECT - Use this everywhere in omniclaude
KAFKA_BROKERS=localhost:29102

# Also set (for compatibility)
KAFKA_BOOTSTRAP_SERVERS=localhost:29102

# INCORRECT - Do not use
KAFKA_BROKERS=localhost:29092            # Wrong port!
KAFKA_BOOTSTRAP_SERVERS=localhost:29092  # Wrong port!
```

**Template available**: See `.env.example.kafka` for complete configuration

### Python Code

```python
# CORRECT
from intelligence_event_client import IntelligenceEventClient

client = IntelligenceEventClient(
    bootstrap_servers="localhost:29102",  # ✅ Correct
)

# INCORRECT
client = IntelligenceEventClient(
    bootstrap_servers="localhost:29092",  # ❌ Wrong port
)
```

### Hook Scripts

All hook logging scripts use **port 29102**:

```python
# From log-routing-decision/execute_kafka.py
brokers = os.environ.get("KAFKA_BROKERS", "localhost:29102").split(",")  # ✅
```

## Port Usage by Context

| Context | Port | Why |
|---------|------|-----|
| **omniclaude external** | 29102 | Mapped to container's 29092 |
| **omniclaude Docker internal** | 9092 | Direct container network |
| **omniarchon external** | 29092 | Different port mapping |
| **omniarchon Docker internal** | 9092 | Direct container network |

## Files That Use Kafka

### Already Correct (Use 29102)

✅ `/Users/jonah/.claude/skills/agent-tracking/log-routing-decision/execute_kafka.py`
✅ `/Users/jonah/.claude/skills/agent-tracking/log-agent-action/execute_kafka.py`
✅ `/Users/jonah/.claude/skills/agent-tracking/log-performance-metrics/execute_kafka.py`
✅ `/Users/jonah/.claude/skills/agent-tracking/log-transformation/execute_kafka.py`
✅ `/Users/jonah/.claude/hooks/lib/hook_event_adapter.py` (default: 29102)
✅ `/Users/jonah/.claude/skills/intelligence/request-intelligence/execute.py` (FIXED)
✅ `/Volumes/PRO-G40/Code/omniclaude/agents/lib/intelligence_event_client.py` (FIXED)

### Tests and Validation Scripts

✅ `tests/test_kafka_consumer.py` - Uses 29092 but has env var override
✅ `tests/test_kafka_minimal.py` - Uses 29092 for testing
✅ `tests/validate_event_integration.py` - Uses 29092
✅ `tests/test_logging_performance.py` - Uses 29092

**Note**: Test files may use different ports for local testing. Production code should use **29102**.

## Common Errors

### Error: `UnrecognizedBrokerVersion`

```
aiokafka.errors.UnrecognizedBrokerVersion: UnrecognizedBrokerVersion
```

**Cause**: Using wrong port (usually 29092 instead of 29102)
**Fix**: Change to `localhost:29102`

### Error: Connection refused

```
kafka.errors.NoBrokersAvailable
```

**Cause**: Either wrong port or Redpanda not running
**Fix**:
1. Check Redpanda: `docker ps | grep redpanda`
2. Verify port: Use 29102
3. Test connection: `nc -zv localhost 29102`

### Error: Timeout connecting

**Cause**: Firewall or port mapping issue
**Fix**:
```bash
# Check port is accessible
nc -zv localhost 29102

# Check Redpanda is healthy
docker ps --filter "name=redpanda"

# Check Redpanda logs
docker logs omninode-bridge-redpanda --tail 50
```

## Verification Checklist

Before committing Kafka code:

- [ ] Port is **29102** for external connections
- [ ] Environment variable is **KAFKA_BROKERS** (not KAFKA_BOOTSTRAP_SERVERS)
- [ ] Default value is `"localhost:29102"`
- [ ] Docker internal uses `"omninode-bridge-redpanda:9092"`
- [ ] Connection tested with `nc -zv localhost 29102`

## Quick Reference

```bash
# Test Kafka connection
nc -zv localhost 29102

# Check Redpanda status
docker ps | grep redpanda

# List Kafka topics
kafka-topics --bootstrap-server localhost:29102 --list

# Consume test events
kafka-console-consumer \
  --bootstrap-server localhost:29102 \
  --topic agent-routing-decisions \
  --from-beginning

# Check health
curl http://localhost:8053/health | jq .
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│ omniclaude (Host Process)                       │
│                                                  │
│  - IntelligenceEventClient                      │
│  - HookEventAdapter                             │
│  - Logging Scripts                              │
│                                                  │
│  bootstrap_servers = "localhost:29102" ← ✅      │
└───────────────────────┬─────────────────────────┘
                        │
                        ▼
                  Port 29102 (Host)
                        │
                        │ Docker Port Mapping
                        │ 29102 → 29092
                        ▼
              ┌─────────────────────┐
              │ Redpanda Container  │
              │                     │
              │ Port 29092 (internal│
              │ Kafka API)          │
              └─────────────────────┘
```

## Why Two Ports?

### Port 29102 (External)
- **Who uses it**: Host processes (omniclaude scripts, Python clients)
- **Why**: Docker port mapping exposes container's 29092 as host's 29102
- **When**: Always for external connections

### Port 29092 (Legacy/Internal)
- **Who uses it**: Some Docker internal services
- **Why**: Historical reasons, being phased out
- **When**: Avoid using for new code

## Environment Variable Standards

### Use KAFKA_BROKERS (Recommended)

```bash
# ✅ Correct - Matches hook scripts
export KAFKA_BROKERS=localhost:29102

# ✅ Also works (for compatibility)
export KAFKA_BROKERS="localhost:29102,localhost:29102"  # Comma-separated
```

### Don't Use KAFKA_BOOTSTRAP_SERVERS

```bash
# ❌ Deprecated - causes confusion
export KAFKA_BOOTSTRAP_SERVERS=localhost:29092
```

## Migration Guide

If you find code using the wrong port:

### Before
```python
client = IntelligenceEventClient(
    bootstrap_servers="localhost:29092",  # Wrong
)
```

### After
```python
client = IntelligenceEventClient(
    bootstrap_servers="localhost:29102",  # Correct
)
```

### Environment Variable Migration

**Before**:
```python
default=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
```

**After**:
```python
default=os.environ.get("KAFKA_BROKERS", "localhost:29102")
```

## Testing Configuration

```bash
# Set environment
export KAFKA_BROKERS=localhost:29102

# Test connection
python3 -c "
from kafka import KafkaProducer
producer = KafkaProducer(bootstrap_servers='localhost:29102')
print('✅ Connection successful')
producer.close()
"

# Test with aiokafka (async)
python3 -c "
import asyncio
from aiokafka import AIOKafkaProducer

async def test():
    producer = AIOKafkaProducer(bootstrap_servers='localhost:29102')
    await producer.start()
    print('✅ Async connection successful')
    await producer.stop()

asyncio.run(test())
"
```

## Summary

**Golden Rule**: Use `localhost:29102` for all omniclaude external Kafka connections.

**Quick Fix**: If you get connection errors, change:
- Port: `29092` → `29102`
- Env var: `KAFKA_BOOTSTRAP_SERVERS` → `KAFKA_BROKERS`

---

**Document Status**: Production Reference
**Last Updated**: 2025-10-24
**Version**: 1.0.0
