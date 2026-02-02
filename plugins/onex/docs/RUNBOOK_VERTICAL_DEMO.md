# VERTICAL-001 Demo Runbook

**Ticket**: OMN-1802
**Purpose**: End-to-end pattern flow validation with shortcuts
**Last Updated**: 2026-02-02

---

## Overview

This runbook validates the full pattern extraction pipeline:

```
Claude Code Hook -> Kafka -> Consumer -> PostgreSQL -> Query
```

The demo uses shortcuts (direct SQL, hardcoded topics) to prove the architecture works before building proper abstractions.

---

## Prerequisites

### Infrastructure

| Service | Host | Port | Purpose |
|---------|------|------|---------|
| Redpanda/Kafka | `$KAFKA_BOOTSTRAP_SERVERS` | 29092 | Event bus |
| PostgreSQL | `$POSTGRES_HOST` | `$POSTGRES_PORT` | Pattern storage |

### Database

The `learned_patterns` table must exist in the `omninode_bridge` database.

```bash
# Verify table exists and check schema
source .env
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE \
  -c "SELECT COUNT(*) FROM learned_patterns WHERE is_current = true"
```

**Table Schema** (actual columns):

| Column | Type | Description |
|--------|------|-------------|
| `signature_hash` | TEXT | Primary key, SHA-256 hash of pattern signature |
| `pattern_signature` | TEXT | The actual pattern text |
| `domain` | TEXT | Pattern domain (general, testing, etc.) |
| `confidence` | FLOAT | Confidence score (0.0 - 1.0) |
| `status` | TEXT | Pattern status (candidate, validated, etc.) |
| `recurrence_count` | INT | Number of times pattern observed |
| `quality_score` | FLOAT | Quality score (0.0 - 1.0) |
| `days_seen` | INT | Number of distinct days pattern was seen |
| `unique_sessions` | INT | Number of unique sessions |
| `is_current` | BOOLEAN | Whether this is the current version |
| `first_seen_at` | TIMESTAMP | First observation timestamp |
| `last_seen_at` | TIMESTAMP | Most recent observation timestamp |

### Environment

```bash
# Set REPO_ROOT to your omniclaude clone location, e.g.:
# export REPO_ROOT=/path/to/omniclaude
cd $REPO_ROOT

# Load environment variables
source .env

# Verify critical variables
echo "KAFKA_BOOTSTRAP_SERVERS: ${KAFKA_BOOTSTRAP_SERVERS}"
echo "POSTGRES_HOST: ${POSTGRES_HOST}"
echo "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:+(set)}"
```

---

## Demo Execution

### Terminal Setup

Open **three** terminal windows:

| Terminal | Purpose |
|----------|---------|
| T1 | Consumer (runs continuously) |
| T2 | Emit events |
| T3 | Query patterns |

### Step 1: Start Consumer (Terminal T1)

```bash
cd $REPO_ROOT  # Navigate to your omniclaude repository root
source .env

# Start consumer (runs until Ctrl+C)
python plugins/onex/scripts/demo_consume_store.py
```

Expected output:
```
======================================================================
VERTICAL-001 Demo: Consume and Store Patterns
======================================================================

Kafka Configuration:
  Brokers:  ['192.168.86.200:29092']
  Topic:    dev.onex.cmd.omniintelligence.claude-hook-event.v1
  Group:    demo-vertical-001-consumer

PostgreSQL Configuration:
  Host:     192.168.86.200:5436
  Database: omninode_bridge
  User:     postgres

[INFO] Connecting to PostgreSQL...
[OK] PostgreSQL connected

[INFO] Connecting to Kafka...
[OK] Kafka consumer connected, subscribed to dev.onex.cmd.omniintelligence.claude-hook-event.v1

[INFO] Running in continuous mode (Ctrl+C to stop)
```

Leave this running.

### Step 2: Emit Test Event (Terminal T2)

```bash
cd $REPO_ROOT  # Navigate to your omniclaude repository root
source .env

# Emit default test event
python plugins/onex/scripts/demo_emit_hook.py
```

Expected output:
```
======================================================================
VERTICAL-001 Demo: Emit Hook Event
======================================================================

Configuration:
  Kafka Brokers: 192.168.86.200:29092
  Environment:   dev
  Topic:         dev.onex.cmd.omniintelligence.claude-hook-event.v1

Emitting event:
  Session ID:     demo-<uuid>
  Correlation ID: <uuid>
  Prompt:         Demo pattern: Always validate input before...

[OK] Event emitted successfully
  Topic: dev.onex.cmd.omniintelligence.claude-hook-event.v1
```

**Within 5 seconds**, you should see in Terminal T1:
```
[INSERT] Pattern: abc123def456... (domain=general)
```

Note: The consumer shows the first 12 characters of the `signature_hash`.

### Step 3: Query Patterns (Terminal T3)

```bash
cd $REPO_ROOT  # Navigate to your omniclaude repository root
source .env

# Query demo patterns
python plugins/onex/scripts/demo_query_patterns.py --demo-only
```

Expected output:
```
======================================================================
VERTICAL-001 Demo: Query Patterns
======================================================================

PostgreSQL Configuration:
  Host:     192.168.86.200:5436
  Database: omninode_bridge
  User:     postgres

[INFO] Connecting to PostgreSQL...
[OK] Connected

Database contains N total patterns (M demo patterns)

Querying patterns (demo patterns only)...

Found 1 patterns:

[1] abc123def456...
    Domain:      general
    Pattern:     Demo pattern: Always validate input before...
    Confidence:  50.0%
    Status:      candidate
    Recurrence:  1 times
    Quality:     50.0%
    Days seen:   1
    Sessions:    1 unique
    First seen:  2026-02-02 ...
    Last seen:   2026-02-02 ...

----------------------------------------------------------------------
Summary:
  Total patterns:     1
  Avg confidence:     50.0%
  Domains:            general(1)

======================================================================
Demo step 3/3 complete: Patterns retrieved from PostgreSQL
...
```

### Step 4: Stop Consumer

In Terminal T1, press `Ctrl+C`:
```
^C
[INFO] Interrupted by user

[SUMMARY] Events processed: 1
[SUMMARY] Patterns stored:  1

[OK] Connections closed
```

---

## Validation Checklist

| Criterion | Expected | Check |
|-----------|----------|-------|
| Event emitted to Kafka | "Event emitted successfully" | [ ] |
| Consumer receives within 5s | "[INSERT] Pattern: abc123..." | [ ] |
| Pattern in PostgreSQL | Query returns pattern with signature_hash | [ ] |
| Full cycle < 30s | From emit to query | [ ] |

---

## Troubleshooting

### Consumer doesn't receive events

1. **Check topic exists**:
   ```bash
   source .env
   kcat -L -b $KAFKA_BOOTSTRAP_SERVERS | grep claude-hook-event
   ```

2. **Check consumer group offset**:
   ```bash
   source .env
   kcat -b $KAFKA_BOOTSTRAP_SERVERS -L | grep demo-vertical
   ```

3. **Reset consumer offset** (if needed):
   ```bash
   # Delete and recreate consumer group
   python plugins/onex/scripts/demo_consume_store.py
   # Then run emit again
   ```

### Database connection fails

1. **Verify connectivity**:
   ```bash
   source .env
   psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -c "SELECT 1"
   ```

2. **Check password**:
   ```bash
   source .env
   echo $POSTGRES_PASSWORD
   # Should not be empty
   ```

3. **Check table exists**:
   ```bash
   source .env
   psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE \
     -c "\d learned_patterns"
   ```

### Kafka connection fails

1. **Verify broker**:
   ```bash
   source .env
   kcat -b $KAFKA_BOOTSTRAP_SERVERS -L
   ```

2. **Check network**:
   ```bash
   source .env
   nc -zv $POSTGRES_HOST 29092
   ```

3. **Verify /etc/hosts** (if using hostname):
   ```bash
   grep omninode-bridge-redpanda /etc/hosts
   ```

---

## Advanced Usage

### Custom prompt

```bash
python plugins/onex/scripts/demo_emit_hook.py \
  --prompt "Always write tests before implementing features"
```

### Filter by domain

```bash
python plugins/onex/scripts/demo_query_patterns.py --domain testing
```

### Single-batch consumer mode

```bash
# Process one batch and exit (for CI/CD)
python plugins/onex/scripts/demo_consume_store.py --once
```

---

## Clean Up

Remove demo patterns after testing:

```bash
source .env
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE \
  -c "DELETE FROM learned_patterns WHERE pattern_signature LIKE 'Demo pattern:%'"
```

---

## Next Steps

After validating the demo:

1. **OMN-1782/1783**: Replace direct SQL with contract-driven repository
2. **OMN-1779**: Wire ManifestInjector for proper context injection
3. **OMN-1xxx**: Add dashboard UI for pattern visualization

---

**End of Runbook**
