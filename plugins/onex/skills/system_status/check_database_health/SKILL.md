---
description: PostgreSQL database health via omninode-runtime HTTP health endpoint (OMN-10492)
---

# Check Database Health

Monitor PostgreSQL database health through the omninode-runtime health endpoint.

The Mac must never connect directly to Postgres via raw psql. The correct
data access path is: Mac → runtime health endpoint → Postgres.

## What It Checks

- Runtime health endpoint reachability (`/health`)
- HTTP response status and latency
- Response body from the runtime service

## How to Use

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/system_status/check_database_health/_lib/execute.py
```

Override the endpoint via env var:

```bash
OMNINODE_RUNTIME_HEALTH_URL=http://192.168.86.201:8085/health `# onex-allow-internal-ip` \
  python3 ${CLAUDE_PLUGIN_ROOT}/skills/system_status/check_database_health/_lib/execute.py
```

## Example Output

```json
{
  "timestamp": "2025-11-12T14:30:00Z",
  "status": "healthy",
  "probe_method": "runtime_health_endpoint",
  "database": {
    "status": "healthy",
    "response_time_ms": 12.4,
    "status_code": 200,
    "details": {"status": "ok"},
    "endpoint": "http://192.168.86.201:8085/health" // onex-allow-internal-ip
  }
}
```
<!-- onex-allow-internal-ip -->

## Exit Codes

- `0` - Runtime health endpoint returned HTTP 200
- `1` - Endpoint unreachable, timed out, or returned non-200
