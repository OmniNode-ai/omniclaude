# Immediate Fix: Pattern Discovery System

**Status**: 🔴 CRITICAL - System Down
**Date**: 2025-10-29
**ETA to Resolution**: 15 minutes

---

## 🎯 Quick Summary

**Problem**: "(No patterns discovered)" in all manifests
**Root Cause**: Out-of-Memory (OOM) kills
**Primary Issue**: Docker only has 7.6GB but needs 16GB minimum
**System Resources**: 32GB RAM available, Docker using only 24% of it

---

## 🚨 Immediate Action Required (5 minutes)

### Step 1: Increase Docker Memory Allocation

**Current**: 7.653 GiB (24% of 32GB system RAM)
**Required**: 16 GiB minimum (50% of system RAM)
**Recommended**: 20 GiB optimal (62% of system RAM)

**How to Fix**:

1. **Open Docker Desktop Settings**:
   - Click Docker icon in menu bar
   - Settings → Resources → Advanced

2. **Increase Memory**:
   - Move "Memory" slider from **7.65 GB** to **20.00 GB**
   - Keep CPUs at 12 (already optimal)

3. **Apply & Restart**:
   - Click "Apply & Restart"
   - Wait ~60 seconds for Docker to restart

### Step 2: Restart Intelligence Services

After Docker restarts with new memory:

```bash
# Navigate to project
cd /Volumes/PRO-G40/Code/omniclaude

# Restart all intelligence services
docker start archon-intelligence
docker start omninode-bridge-redpanda-dev
docker start archon-kafka-consumer
docker start archon-search

# Wait for healthy status (30-60 seconds)
sleep 60

# Verify services are up
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "archon-intelligence|redpanda|kafka|search"
```

**Expected Output**:
```
NAME                       STATUS
archon-intelligence        Up X seconds (healthy)
archon-kafka-consumer      Up X seconds (healthy)
archon-search              Up X seconds (healthy)
omninode-bridge-redpanda-dev Up X seconds (healthy)
```

### Step 3: Verify Pattern Discovery Working

```bash
# Run health check
./scripts/health_check.sh

# Expected output includes:
# ✅ archon-intelligence (healthy)
# ✅ Qdrant: http://localhost:6333 (connected, 1065 patterns)
# ✅ Manifest Injections: 120 patterns discovered

# Test end-to-end
python3 agents/lib/test_pattern_discovery.py

# Expected output:
# ✅ Client started successfully
# ✅ PATTERN DISCOVERY WORKING!
#    First pattern: Node State Management Pattern
#    Has file_path: True
```

---

## 📊 Current Memory Breakdown

**Before Fix**:
```
Total System RAM:    32.0 GB  (100%)
Docker Allocation:    7.6 GB  ( 24%)  ← TOO LOW
  └─ archon-server:   5.8 GB  ( 76% of Docker)
  └─ Other services:  1.8 GB  ( 24% of Docker)
  └─ Available:       0.0 GB  (  0% - NONE!)

Result: archon-intelligence, redpanda, kafka-consumer OOMKilled
```

**After Fix (20GB Docker)**:
```
Total System RAM:    32.0 GB  (100%)
Docker Allocation:   20.0 GB  ( 62%)  ← HEALTHY
  └─ archon-server:   5.8 GB  ( 29% of Docker)
  └─ Other services:  6.0 GB  ( 30% of Docker)
  └─ Available:       8.2 GB  ( 41% - PLENTY!)

Result: All services healthy with room to grow
```

---

## 🔍 Why This Happened

### OOM Kill Evidence

```bash
# Check exit codes (137 = OOM kill)
$ docker inspect archon-intelligence --format='{{.State.ExitCode}} | OOMKilled: {{.State.OOMKilled}}'
137 | OOMKilled: true

$ docker inspect omninode-bridge-redpanda-dev --format='{{.State.ExitCode}} | OOMKilled: {{.State.OOMKilled}}'
137 | OOMKilled: true
```

### Database Proof

**Manifest Injection Timeline**:
```sql
Hour (UTC) | Total Requests | Success | Failed | Avg Time
-----------|----------------|---------|--------|----------
17:00      | 16             | 16      | 0      | 15s ✅
16:00      | 30             | 0       | 30     | 25s ❌ (timeout)
15:00      | 16             | 0       | 16     | 25s ❌ (timeout)
14:00      | 5              | 0       | 5      | 25s ❌ (timeout)
```

**Pattern**: Services died at ~16:00, temporarily restarted at ~17:00, died again within 1 hour.

### Service Memory Hog

**archon-server** consuming **5.8GB of 7.6GB** (75.88%) leaves:
- Only 1.8GB for ALL other services
- archon-intelligence needs ~1GB → OOMKilled
- redpanda needs ~2GB → OOMKilled
- kafka-consumer needs ~512MB → OOMKilled
- archon-search needs ~512MB → OOMKilled

**Solution**: Give Docker 20GB so archon-server's 5.8GB is only 29% instead of 76%.

---

## ✅ Success Verification Checklist

After applying fix, verify:

- [ ] Docker Desktop shows 20GB memory allocated
- [ ] All 4 intelligence services running (intelligence, redpanda, kafka-consumer, search)
- [ ] `curl http://localhost:8053/health` returns `{"status": "healthy"}`
- [ ] `curl http://localhost:6333/collections/code_patterns` shows 1065 points
- [ ] `./scripts/health_check.sh` shows ✅ for all services
- [ ] Test pattern discovery returns 10+ patterns
- [ ] Recent manifest injections show patterns_count = 120
- [ ] No OOM kills in `docker events` for 1 hour
- [ ] Memory usage stable (<70% of Docker allocation)

---

## 📋 Long-Term Recommendations

### 1. Configure Resource Limits (prevents single service hogging memory)

Add to docker-compose.yml:

```yaml
services:
  archon-server:
    deploy:
      resources:
        limits:
          memory: 4G    # Cap at 4GB instead of 5.8GB
        reservations:
          memory: 2G

  archon-intelligence:
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 1G

  omninode-bridge-redpanda-dev:
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 2G
```

### 2. Monitor for OOM Kills

```bash
# Add to cron or monitoring system
docker events --filter 'event=oom' --format '{{.Time}}: {{.Actor.Attributes.name}} OOMKilled' >> /var/log/docker-oom.log
```

### 3. Implement Circuit Breaker

In `manifest_injector.py`:
- Detect when services down (3+ timeouts)
- Switch to fallback patterns (static ONEX templates)
- Retry every 60s until services recover
- Alert user to degraded intelligence

### 4. Add Health Alerts

```bash
# Add to health_check.sh
if [ "$ARCHON_INTELLIGENCE_HEALTHY" != "true" ]; then
  echo "🚨 ALERT: archon-intelligence unhealthy - pattern discovery unavailable"
  # Send notification (email, Slack, etc.)
fi
```

---

## 🎓 What You Learned

### Q1: Should metadata and tree information be generated automatically?

**A**: Two different systems:
- **File path metadata**: ✅ Auto-generated during Qdrant ingestion (already working)
- **Tree discovery**: ❌ Separate service needed (currently missing/down)

### Q2: Is that different from file_path metadata?

**A**: YES - fundamentally different:
- File path: Simple string (`"src/node_state.py"`)
- Tree discovery: Complex graph (imports, relationships, dependencies)

### Q3: Why no patterns when database shows 120?

**A**: Intelligence services were **OOMKilled**:
- Qdrant has patterns ✅
- archon-intelligence down ❌
- Manifest injector times out ❌
- Fallback manifest with 0 patterns ❌

---

## 📞 If Still Not Working After Fix

1. **Check Docker actually restarted with new memory**:
   ```bash
   docker info | grep "Total Memory"
   # Should show: Total Memory: 20GiB (or higher)
   ```

2. **Verify services aren't crashing for other reasons**:
   ```bash
   docker logs archon-intelligence --tail 100
   # Should NOT show errors/exceptions
   ```

3. **Check Kafka/Redpanda actually started**:
   ```bash
   docker exec archon-kafka-consumer kafka-topics --bootstrap-server omninode-bridge-redpanda:9092 --list
   # Should show topics list
   ```

4. **Test Qdrant directly** (bypass archon-intelligence):
   ```bash
   curl -X POST http://localhost:6333/collections/code_patterns/points/scroll \
     -H "Content-Type: application/json" \
     -d '{"limit": 5, "with_payload": true}' | jq '.result.points[].payload.pattern_name'
   # Should show pattern names
   ```

5. **Check database connectivity**:
   ```bash
   PGPASSWORD="${POSTGRES_PASSWORD}" psql \
     -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
     -c "SELECT COUNT(*) FROM agent_manifest_injections;"
   # Should show count
   ```

---

## 📄 Full Analysis

See `/Volumes/PRO-G40/Code/omniclaude/docs/PATTERN_DISCOVERY_ROOT_CAUSE_ANALYSIS.md` for:
- Complete technical analysis
- OOM kill evidence
- Database query examples
- Service dependency graph
- Circuit breaker implementation
- Graceful degradation patterns

---

**Last Updated**: 2025-10-29 18:45 UTC
**Status After Fix**: 🟡 Pending Docker memory increase
**ETA to Green**: 15 minutes after applying Step 1
