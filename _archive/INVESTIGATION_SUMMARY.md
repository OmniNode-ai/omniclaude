# Router Consumer Investigation - Executive Summary
## 2025-11-06

## 🎯 Root Cause Identified

**The consumer service is working correctly**, but messages never reach it due to a **Kafka advertised listener misconfiguration** in the Redpanda container.

## 📊 Evidence

### ✅ Consumer Service (HEALTHY)
- Running and connected to Kafka
- Successfully assigned to partition 0
- PostgreSQL connection working
- Async loop running correctly
- **Issue**: Processes 0 messages (because none arrive)

### ✅ Kafka Topic (EMPTY)
- Topic `agent.routing.requested.v1` exists
- Current offset: 0
- Log end offset: 0
- **Issue**: No messages in topic

### ❌ Configuration Mismatch (ROOT CAUSE)

**Port Mapping**:
```
omninode-bridge-redpanda: 0.0.0.0:29102->29092/tcp
```
- External port: **29102**
- Internal port: 29092

**Advertised Listener**:
```
--advertise-kafka-addr=...external://localhost:29092,...
```
- Redpanda tells clients: "Connect to **localhost:29092**"
- **Problem**: Port 29092 is NOT accessible from host!

## 🔄 Message Flow (Why It Fails)

1. Test script connects to `192.168.86.200:29102` ✅
2. Redpanda responds: "Connect to `localhost:29092`" ❌
3. Test script tries `localhost:29092` (wrong port!) ❌
4. Connection fails ❌
5. Messages never published ❌
6. Consumer never receives messages ❌
7. Timeout after 10 seconds ❌

## 🛠️ Solution

### Fix Redpanda Configuration (REQUIRED)

In the `omninode_bridge` repository's docker-compose.yml:

**Change this**:
```
--advertise-kafka-addr=internal://omninode-bridge-redpanda:9092,external://localhost:29092,external://omninode-bridge-redpanda:29092
```

**To this**:
```
--advertise-kafka-addr=internal://omninode-bridge-redpanda:9092,external://localhost:29102,external://omninode-bridge-redpanda:29102
```

**What changed**: `29092` → `29102` in the external advertised addresses

## ✅ Validation Steps

After fixing the configuration:

```bash
# 1. Restart Redpanda
docker restart omninode-bridge-redpanda

# 2. Verify connection
nc -zv 192.168.86.200 29102

# 3. Run test
python3 agents/services/test_router_consumer.py

# 4. Check consumer logs (should show "Routing completed")
docker logs --tail 50 omniclaude_archon_router_consumer | grep "Routing completed"

# 5. Verify database
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT COUNT(*) FROM agent_routing_decisions WHERE created_at >= NOW() - INTERVAL '5 minutes';"
```

**Expected**: 4 messages processed successfully within seconds

## 📁 Changes Made

1. **test_router_consumer.py**: Added port conversion workaround
2. **KAFKA_CONSUMER_DEBUG_REPORT.md**: Complete investigation details
3. **This summary**: Quick reference

## 🚨 Impact

- **Severity**: CRITICAL
- **Scope**: All event-based routing is non-functional
- **Services Affected**:
  - Agent routing requests (test scripts)
  - Any host-based Kafka publishers
  - Integration tests
- **Services Unaffected**:
  - Docker-based consumers (they use internal port 9092)
  - Consumer service itself (healthy and ready)

## 📝 Remaining Concerns

None. The issue is well-understood and has a clear fix.

## 🎯 Next Actions

1. **IMMEDIATE**: Fix Redpanda advertised listener in `omninode_bridge` repository
2. **UPDATE**: Documentation to reflect correct port configuration
3. **TEST**: Validate with test script after fix applied

---

**Status**: Investigation complete ✅
**Assigned**: Infrastructure team (omninode_bridge configuration)
**Timeline**: Fix can be applied immediately
